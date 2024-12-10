# This file is part of Xpra.
# Copyright (C) 2010-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

%define version 3.1.9

%{!?with_python2: %define with_python2 1}
%{!?with_python3: %define with_python3 1}
%if 0%{?el9}
%define with_python2 0
%endif
%if 0%{?el7}
%define with_python3 0
%endif

%{!?__python2: %global __python2 python2}
%if %{with_python2}
%{!?python2_sitearch: %global python2_sitearch %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))")}
%endif
%if %{with_python3}
%{!?__python3: %define __python3 python3}
%{!?python3_sitearch: %global python3_sitearch %(%{__python3} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))")}
%endif

%define CFLAGS -O2
%define DEFAULT_BUILD_ARGS --with-Xdummy --without-enc_x265 --pkg-config-path=%{_libdir}/xpra/pkgconfig --rpath=%{_libdir}/xpra --without-cuda_rebuild

%{!?update_firewall: %define update_firewall 1}
%{!?run_tests: %define run_tests 0}
%{!?with_selinux: %define with_selinux 1}
#we only enable CUDA / NVENC with 64-bit builds:
%ifarch x86_64
%{!?with_cuda: %define with_cuda 1}
%else
%define with_cuda 0
%endif
%if 0%{?with_cuda}
%define build_args %{DEFAULT_BUILD_ARGS}
%else
%define build_args %{DEFAULT_BUILD_ARGS} --without-cuda_kernels --without-nvenc --without-nvfbc
%endif
%global selinux_variants mls targeted
%define selinux_modules cups_xpra xpra_socketactivation
%define Suggests Suggests
%define Recommends Recommends
#we never want to depend on proprietary nvidia bits,
#and we manage the codecs with a private library:
%global __requires_exclude ^(libnvjpeg|libnvidia-|libavcodec|libavformat|libavutil|libswscale|libx264).*\\.so.*$

# Python permits the !/usr/bin/python shebang for scripts that are cross
# compatible between python2 and python3, but Fedora 28 does not.  Fedora
# wants us to choose python3 for cross-compatible scripts.  Since we want
# to support python2 and python3 users, exclude our scripts from Fedora 28's
# RPM build check, so that we don't get a bunch of build warnings.
%global __brp_mangle_shebangs_exclude_from xpraforwarder|auth_dialog|xdg-open


# centos / rhel 7.2 onwards
%if 0%{?el7}
%define Suggests Requires
%define Recommends Requires
%define with_python3 0
%if "%{?dist}"==".el7_0"
echo CentOS 7.0 is no longer supported
exit 1
%endif
%if "%{?dist}"==".el7_1"
echo CentOS 7.1 is no longer supported
exit 1
%endif
%endif


Source0:			https://xpra.org/src/xpra-%{version}.tar.xz
Name:				xpra
Version:			%{version}
#grab the full revision number from the source archive's src_info.py file:
%define revision_no %(tar -OJxf %{SOURCE0} xpra-%{version}/xpra/src_info.py | grep -e "^REVISION=" | awk -F= '{print ".r"$2}' 2> /dev/null)
Release:			10%{revision_no}%{?dist}
Summary:			Xpra gives you "persistent remote applications" for X.
Group:				Networking
License:			GPLv2+ and BSD and LGPLv3+ and MIT
URL:				https://xpra.org/
Packager:			Antoine Martin <antoine@xpra.org>
Vendor:				https://xpra.org/
#rpm falls over itself if we try to make the top-level package noarch:
#BuildArch: noarch
BuildRoot:			%{_tmppath}/%{name}-%{version}-root
BuildRequires:		tar
BuildRequires:		grep
BuildRequires:		gawk
%if 0%{?el7}
Patch0:				centos7-oldsystemd.patch
Patch1:				selinux-nomap.patch
Patch2:				centos7-oldturbojpeg.patch
%endif
Requires:			xpra-html5
%if %{with_python3}
Requires:			python3-xpra-client = %{version}-%{release}
Requires:			python3-xpra-server = %{version}-%{release}
%if 0%{?fedora}
Requires:			python3-xpra-audio = %{version}-%{release}
%endif
%endif
%if 0%{?el7}
Requires:			python2-xpra-client = %{version}-%{release}
Requires:			python2-xpra-server = %{version}-%{release}
#no audio by default on centos7:
#Requires:			python2-xpra-audio = %{version}-%{release}
%endif
BuildRequires:		pam-devel
BuildRequires:		pkgconfig
BuildRequires:		gcc
%if 0%{?fedora}>=40
BuildRequires:		clang
%endif
BuildRequires:		gcc-c++
BuildRequires:		libxkbfile-devel
BuildRequires:		libXtst-devel
BuildRequires:		libXfixes-devel
BuildRequires:		libXcomposite-devel
BuildRequires:		libXdamage-devel
BuildRequires:		libXrandr-devel
BuildRequires:		libXext-devel
%if 0%{?el7}
BuildRequires:		libwebp-xpra-devel
BuildRequires:		libvpx-xpra-devel
%else
BuildRequires:		libwebp-devel
BuildRequires:		libvpx-devel
%endif
BuildRequires:		libyuv-devel
BuildRequires:		turbojpeg-devel
BuildRequires:		x264-xpra-devel
BuildRequires:		ffmpeg-xpra-devel
%description
Xpra gives you "persistent remote applications" for X. That is, unlike normal X applications, applications run with xpra are "persistent" -- you can run them remotely, and they don't die if your connection does. You can detach them, and reattach them later -- even from another computer -- with no loss of state. And unlike VNC or RDP, xpra is for remote applications, not remote desktops -- individual applications show up as individual windows on your screen, managed by your window manager. They're not trapped in a box.

So basically it's screen for remote X apps.

This metapackage installs both the python2 and python3 versions of xpra in full, including the python client, server and HTML5 client.


%package common
Summary:			Common files for xpra packages
Group:				Networking
BuildArch:			noarch
Requires(pre):		shadow-utils
Conflicts:			xpra < 2.1
Conflicts:			xpra-filesystem >= 6.0
%if 0%{?el7}
Requires:			redhat-lsb-core
%else
Recommends:			lsb_release
%endif
BuildRequires:		libfakeXinerama
BuildRequires:		which
%description common
This package contains the files which are shared between all the xpra packages.

%package common-client
Summary:			Common files for xpra client packages
Group:				Networking
BuildArch:			noarch
Requires:			xpra-common >= %{version}-%{release}
BuildRequires:		desktop-file-utils
Requires(post):		desktop-file-utils
Requires(postun):	desktop-file-utils
#without this, the system tray is unusable with gnome!
%if 0%{?el8}%{?el9}
Recommends:			gnome-shell-extension-topicons-plus
%endif
%description common-client
This package contains the files which are shared between all the xpra client packages.

%package common-server
Summary:			Common files for xpra server packages
Group:				Networking
BuildArch:			noarch
Requires:			xpra-common >= %{version}-%{release}
%if 0%{?fedora}
Suggests:			xmodmap
Suggests:			xrandr
Requires:			xrdb
%else
Requires:			xorg-x11-server-utils
%endif
Requires:			xorg-x11-drv-dummy
Requires:			xorg-x11-xauth
Requires:			selinux-policy
Requires(post):		openssl
Requires(post):		systemd-units
Requires(preun):	systemd-units
Requires(postun):	systemd-units
%{Recommends}:		which
%{Recommends}:		libfakeXinerama
%{Recommends}:		mesa-dri-drivers
%if ! 0%{?el7}
#allows the server to use software opengl:
%{Recommends}:		mesa-libOSMesa
%endif
%{Recommends}:		redhat-menus
%{Recommends}:		gnome-menus
%{Recommends}:		gnome-icon-theme
BuildRequires:		systemd-devel
BuildRequires:		checkpolicy
BuildRequires:		selinux-policy-devel
BuildRequires:		pam-devel
%if 0%{?run_tests}
BuildRequires:		dbus-x11
BuildRequires:		tigervnc
BuildRequires:		xorg-x11-server-Xvfb
BuildRequires:		xorg-x11-drv-dummy
%if 0%{?fedora}
BuildRequires:			xmodmap
BuildRequires:			xrandr
BuildRequires:			xrdb
%else
BuildRequires:			xorg-x11-server-utils
%endif
%endif
Requires(post):  	/usr/sbin/semodule, /usr/sbin/semanage, /sbin/restorecon, /sbin/fixfiles
Requires(postun):	/usr/sbin/semodule, /usr/sbin/semanage, /sbin/restorecon, /sbin/fixfiles
%description common-server
This package contains the files which are shared between all the xpra server packages.

%package html5
Summary:			Xpra HTML5 client
Group:				Networking
BuildArch:			noarch
Conflicts:			xpra < 2.1
%if ! 0%{?el7}
BuildRequires:		uglify-js
%endif
%if 0%{?fedora}
BuildRequires:		js-jquery
Requires:		js-jquery
%endif
%if 0%{?el7}%{?el8}%{?el9}
BuildRequires:		system-logos
%{Recommends}:          system-logos
%endif
%if 0%{?el8}%{?el9}
BuildRequires:		system-backgrounds
%{Recommends}:          system-backgrounds
%endif
%description html5
This package contains Xpra's HTML5 client.

%if %{with_python2}
%package -n python2-xpra
Summary:			python2 build of xpra
Group:				Networking
Requires:			python2
Requires:			xpra-common >= %{version}-%{release}
Requires:			python2-lz4
Requires:			python2-rencode
%if 0%{?el7}
Requires:			python-pillow
Requires:			libvpx-xpra
Requires:			libwebp-xpra
%else
Requires:			python2-pillow
Requires:			libvpx
Requires:			libwebp
Conflicts:			libvpx-xpra
Obsoletes:          		libvpx-xpra < 1.8
Conflicts:			libwebp-xpra
Obsoletes:          		libwebp-xpra < 1.8
%endif
Requires:			x264-xpra
Requires:			ffmpeg-xpra
Requires:			turbojpeg
Requires:			libyuv
%if 0%{?fedora}%{?el8}
Recommends:			python2-appindicator
Recommends:			python2-numpy
Recommends:			python2-paramiko
Recommends:			python2-dns
#Recommends:			python2-lzo
Recommends: 		        python2-kerberos
Recommends:         		python2-gssapi
#webcam:
%{Suggests}:			python2-opencv
Recommends:			python2-inotify
Recommends:			python2-avahi
Recommends:         		python2-ldap
Recommends:         		python2-ldap3
Recommends:			python2-dbus
%endif
%{Recommends}:			python2-netifaces
%{Suggests}:			python2-cryptography
BuildRequires:			python2-Cython
BuildRequires:			python2
BuildRequires:			pygtk2-devel
BuildRequires:			pygobject2-devel
%if 0%{?el7}
Requires:			numpy
%if 0%{?run_tests}
BuildRequires:			numpy
%endif
Requires:			dbus-python
BuildRequires:			python-setuptools
%else
BuildRequires:			python2-setuptools
%if 0%{?run_tests}
BuildRequires:			python2-numpy
%endif
%endif
%if 0%{?run_tests}
BuildRequires:			python2-pillow
BuildRequires:			python2-rencode
%endif
%description -n python2-xpra
This package contains the python2 common build of xpra.

%package -n python2-xpra-audio
Summary:			python2 build of xpra audio support
Group:				Networking
Requires:			python2-xpra = %{version}-%{release}
%if 0%{?fedora}
#EL7 requires 3rd party repos like "media.librelamp.com"
Requires:			python2-gstreamer1
Recommends:			gstreamer1-plugins-ugly
Recommends:			gstreamer1-plugins-ugly-free
%endif
Requires:			gstreamer1
Requires:			gstreamer1-plugins-base
Requires:			gstreamer1-plugins-good
%{Recommends}:		gstreamer1-plugin-timestamp
%{Recommends}:		pulseaudio
%{Recommends}:		pulseaudio-utils
%if 0%{?run_tests}
Requires:			python2-gstreamer1
BuildRequires:		gstreamer1
BuildRequires:		gstreamer1-plugins-good
BuildRequires:		pulseaudio
BuildRequires:		pulseaudio-utils
%endif
%description -n python2-xpra-audio
This package contains audio support for python2 builds of xpra.

%package -n python2-xpra-client
Summary:			python2 build of xpra client
Group:				Networking
Conflicts:			xpra < 2.1
Requires:			xpra-common-client >= %{version}-%{release}
Requires:			python2-xpra = %{version}-%{release}
Requires:			pygtk2
Requires:			python2-pyopengl
Requires:			pygtkglext
%{Recommends}:		python2-pyu2f
#no longer available in Fedora 30:
#BuildRequires:		python2-cups
%if 0%{?fedora}%{?el8}
Recommends:         python2-pyxdg
Recommends:			python2-xpra-audio
Recommends:			python2-cups
Suggests:			sshpass
%if 0%{?run_tests}
%if 0%{?fedora}
BuildRequires:		xclip
BuildRequires:		python2-pyxdg
%endif
%endif
%endif
%if 0%{?el7}
Requires:			python-cups
%endif
%description -n python2-xpra-client
This package contains the python2 xpra client.

%package -n python2-xpra-server
Summary:			python2 build of xpra server
Group:				Networking
Requires:			xpra-common-server >= %{version}-%{release}
Requires:			python2-xpra = %{version}-%{release}
Requires:			pygtk2
%{Recommends}:		cups-filters
%{Recommends}:		dbus-x11
%{Recommends}:		gtk2-immodule-xim
%if %{with_cuda}
%{Recommends}:		python2-pycuda
%{Recommends}:		python2-pynvml
%endif
%if 0%{?el7}
Requires:			python-cups
Requires:			python-setproctitle
%else
Recommends:			python2-xpra-audio
Recommends:			cups-pdf
Recommends:			python2-cups
Recommends:			python2-uinput
Recommends:			python2-setproctitle
%endif
BuildRequires:		python2-Cython
%description -n python2-xpra-server
This package contains the python2 xpra server.
%endif

#optional python3 packages:
%if %{with_python3}
%package -n python3-xpra
Summary:			Xpra gives you "persistent remote applications" for X. Python3 build.
Group:				Networking
Requires:			xpra-common = %{version}-%{release}
Requires:			python3
Requires:			python3-lz4
Requires:			python3-pillow
Requires:			python3-rencode
Requires:			python3-numpy
Requires:			libyuv
Requires:			libvpx
Requires:			turbojpeg
Conflicts:			libvpx-xpra
Obsoletes:			libvpx-xpra < 1.8
Conflicts:			libwebp-xpra
Obsoletes:			libwebp-xpra < 1.8
Requires:			x264-xpra
Requires:			ffmpeg-xpra
Requires:			python3-cryptography
Requires:			python3-gobject
Recommends:			python3-inotify
Recommends:			python3-netifaces
Recommends:			python3-dbus
Recommends:			python3-avahi
Recommends:			python3-dns
Recommends:			python3-paramiko
#Recommends:			python3-lzo
Recommends:         python3-kerberos
Recommends:         python3-gssapi
Recommends:         python3-ldap
Recommends:         python3-ldap3
Recommends:         python3-brotli
#Suggests:           python3-cpuinfo
Requires:			libwebp
BuildRequires:		python3
BuildRequires:		python3-devel
BuildRequires:		python3-Cython
BuildRequires:		python3-gobject
BuildRequires:		pygobject3-devel
BuildRequires:		python3-cairo-devel
BuildRequires:		x264-xpra-devel
BuildRequires:		ffmpeg-xpra-devel
BuildRequires:		gtk3-devel
BuildRequires:		gobject-introspection-devel
%if 0%{?run_tests}
BuildRequires:		python3-cryptography
BuildRequires:		python3-rencode
BuildRequires:		python3-numpy
BuildRequires:		python3-pillow
%endif
%description -n python3-xpra
This package contains the python3 build of xpra.

%package -n python3-xpra-audio
Summary:			python3 build of xpra audio support
Group:				Networking
Requires:			python3-xpra = %{version}-%{release}
Requires:			python3-gstreamer1
Requires:			gstreamer1
Requires:			gstreamer1-plugins-base
Requires:			gstreamer1-plugins-good
Recommends:			gstreamer1-plugin-timestamp
Recommends:			gstreamer1-plugins-ugly
Recommends:			gstreamer1-plugins-ugly-free
Recommends:			pulseaudio
Recommends:			pulseaudio-utils
%if 0%{?run_tests}
Requires:			python3-gstreamer1
BuildRequires:		gstreamer1
BuildRequires:		gstreamer1-plugins-good
BuildRequires:		pulseaudio
BuildRequires:		pulseaudio-utils
%endif
%description -n python3-xpra-audio
This package contains audio support for python2 builds of xpra.

%package -n python3-xpra-client
Summary:			python3 build of xpra client
Group:				Networking
Requires:			xpra-common-client = %{version}-%{release}
Requires:			python3-xpra = %{version}-%{release}
Requires:           		python3-cairo
BuildRequires:		python3-pyxdg
BuildRequires:		python3-cups
Recommends:			python3-xpra-audio
Recommends:			python3-cups
Recommends:			python3-pyopengl
Recommends:			python3-pyu2f
Recommends:			python3-xdg
#without this, the system tray is unusable!
%if 0%{?el8}%{?el9}
Recommends:			gnome-shell-extension-topicons-plus
%endif
%if 0%{?fedora}
Recommends:			libappindicator-gtk3
%endif
Suggests:			sshpass
%if 0%{?run_tests}
%if 0%{?fedora}
BuildRequires:		xclip
%endif
%endif
%description -n python3-xpra-client
This package contains the python3 xpra client.

%package -n python3-xpra-server
Summary:			python3 build of xpra server
Group:				Networking
Requires:			xpra-common-server = %{version}-%{release}
Requires:			python3-xpra = %{version}-%{release}
Recommends:			cups-filters
Recommends:			cups-pdf
Recommends:			python3-cups
Recommends:			dbus-x11
Recommends:			gtk3-immodule-xim
Recommends:			python3-setproctitle
Recommends:			librsvg2
%if %{with_cuda}
Recommends:			python3-pynvml
Recommends:			python3-pycuda
%endif
BuildRequires:		gcc
BuildRequires:		gcc-c++
BuildRequires:		python3-Cython
#once the server is fully ported over to python3:
#Recommends:		python3-uinput
%description -n python3-xpra-server
This package contains the python3 xpra server.
%endif


%prep
#sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
#if [ "${sha256}" != "ffff" ]; then
#	echo "invalid checksum for %{SOURCE0}"
#	exit 1
#fi
rm -rf $RPM_BUILD_DIR/xpra-%{version}-python2 $RPM_BUILD_DIR/xpra-%{version}
xzcat $RPM_SOURCE_DIR/xpra-%{version}.tar.xz | tar -xf -
pushd $RPM_BUILD_DIR/xpra-%{version}
%if 0%{?el7}
#remove some systemd configuration options:
%patch -P 0 -p1
%patch -P 1 -p1
#missing definitions in turbojpeg headers:
%patch -P 2 -p1
%endif

popd
mv $RPM_BUILD_DIR/xpra-%{version} $RPM_BUILD_DIR/xpra-%{version}-python2
%if %{with_python3}
rm -rf $RPM_BUILD_DIR/xpra-%{version}-python3 $RPM_BUILD_DIR/xpra-%{version}
xzcat $RPM_SOURCE_DIR/xpra-%{version}.tar.xz | tar -xf -
mv $RPM_BUILD_DIR/xpra-%{version} $RPM_BUILD_DIR/xpra-%{version}-python3
%endif


%if !0%{?el7}
%debug_package
%endif


%build
%if %{with_python3}
pushd xpra-%{version}-python3
rm -rf build install
# set pkg_config_path for xpra video libs:
CFLAGS="%{CFLAGS}" LDFLAGS="%{?LDFLAGS} -Wl,--as-needed" %{__python3} setup.py build \
%if ! %{with_python2}
	--without-html5 --without-printing --without-cuda_kernels \
%endif
	%{build_args}
popd
%endif

pushd xpra-%{version}-python2
%if %{with_python2}
rm -rf build install
# set pkg_config_path for xpra video libs
CFLAGS="%{CFLAGS}" LDFLAGS="%{?LDFLAGS} -Wl,--as-needed" %{__python2} setup.py build \
	%{build_args}
%endif
%if 0%{?with_selinux}
for mod in %{selinux_modules}
do
	pushd selinux/${mod}
	for selinuxvariant in %{selinux_variants}
	do
	  make NAME=${selinuxvariant} -f /usr/share/selinux/devel/Makefile
	  mv ${mod}.pp ${mod}.pp.${selinuxvariant}
	  make NAME=${selinuxvariant} -f /usr/share/selinux/devel/Makefile clean
	done
	popd
done
%endif
popd


%install
rm -rf $RPM_BUILD_ROOT
pushd xpra-%{version}-python2
%if %{with_python2}
%{__python2} setup.py install \
	%{build_args} \
	--prefix /usr --skip-build --root %{buildroot}
#fix permissions on shared objects
find %{buildroot}%{python2_sitearch}/xpra -name '*.so' -exec chmod 0755 {} \;
#remove the tests, not meant to be installed in the first place
rm -fr ${RPM_BUILD_ROOT}/%{python2_sitearch}/unittests
%endif
%if 0%{?with_selinux}
for mod in %{selinux_modules}
do
	for selinuxvariant in %{selinux_variants}
	do
	  install -d %{buildroot}%{_datadir}/selinux/${selinuxvariant}
	  install -p -m 644 selinux/${mod}/${mod}.pp.${selinuxvariant} \
	    %{buildroot}%{_datadir}/selinux/${selinuxvariant}/${mod}.pp
	done
done
%endif
popd

%if %{with_python3}
pushd xpra-%{version}-python3
%{__python3} setup.py install \
	%{build_args} \
%if %{with_python2}
	--without-html5 --without-printing --without-cuda_kernels \
%endif
	--prefix /usr --skip-build --root %{buildroot}
popd
#fix permissions on shared objects
find %{buildroot}%{python3_sitearch}/xpra -name '*.so' -exec chmod 0755 {} \;
#remove the tests, not meant to be installed in the first place
rm -fr ${RPM_BUILD_ROOT}/%{python3_sitearch}/unittests
sed -i "s+/usr/bin/python2+/usr/bin/python3+g" ${RPM_BUILD_ROOT}/usr/bin/*xpra*
%else
sed -i "s+/usr/bin/python3+/usr/bin/python2+g" ${RPM_BUILD_ROOT}/usr/bin/*xpra*
%endif

# Ensure none of the .js files are executeable
find %{buildroot}%{_datadir}/xpra/www/js -name '*.js' -exec chmod 0644 {} \;


%clean
rm -rf $RPM_BUILD_ROOT

%files

%files html5
%defattr(-,root,root)
%{_datadir}/xpra/www
%{_datadir}/xpra/http-headers

%files common
%defattr(-,root,root)
%{_bindir}/xpra*
%{_datadir}/xpra/README
%{_datadir}/xpra/COPYING
%{_datadir}/xpra/icons
%{_datadir}/xpra/*.wav
%{_datadir}/xpra/cuda
%{_datadir}/man/man1/xpra*
%{_datadir}/metainfo/xpra.appdata.xml
%{_datadir}/icons/xpra.png
%{_datadir}/icons/xpra-mdns.png
%{_datadir}/icons/xpra-shadow.png
%dir %{_sysconfdir}/xpra
%config %{_sysconfdir}/xpra/xpra.conf
%config %{_sysconfdir}/xpra/conf.d/05_features.conf
%config %{_sysconfdir}/xpra/conf.d/10_network.conf
%config %{_sysconfdir}/xpra/conf.d/12_ssl.conf
%config %{_sysconfdir}/xpra/conf.d/15_file_transfers.conf
%config %{_sysconfdir}/xpra/conf.d/16_printing.conf
%config %{_sysconfdir}/xpra/conf.d/20_sound.conf
%config %{_sysconfdir}/xpra/conf.d/30_picture.conf
%config %{_sysconfdir}/xpra/conf.d/35_webcam.conf

%files common-client
%config %{_sysconfdir}/xpra/conf.d/40_client.conf
%config %{_sysconfdir}/xpra/conf.d/42_client_keyboard.conf
%{_datadir}/applications/xpra-launcher.desktop
%{_datadir}/applications/xpra-gui.desktop
%{_datadir}/applications/xpra.desktop
%{_datadir}/mime/packages/application-x-xpraconfig.xml

%files common-server
%{_sysconfdir}/dbus-1/system.d/xpra.conf
%{_bindir}/xpra_udev_product_version
/lib/systemd/system/xpra.service
/lib/systemd/system/xpra.socket
%{_prefix}/lib/cups/backend/xpraforwarder
%{_prefix}/lib/udev/rules.d/71-xpra-virtual-pointer.rules
%{_datadir}/xpra/content-type
%{_datadir}/xpra/content-categories
%{_datadir}/applications/xpra-shadow.desktop
%{_libexecdir}/xpra/xdg-open
%{_libexecdir}/xpra/gnome-open
%{_libexecdir}/xpra/gvfs-open
%{_libexecdir}/xpra/auth_dialog
%config(noreplace) %{_sysconfdir}/sysconfig/xpra
%config %{_prefix}/lib/tmpfiles.d/xpra.conf
%config %{_prefix}/lib/sysusers.d/xpra.conf
%config %{_sysconfdir}/pam.d/xpra
%config(noreplace) %{_sysconfdir}/X11/xorg.conf.d/90-xpra-virtual.conf
%config(noreplace) %{_sysconfdir}/xpra/xorg.conf
%config(noreplace) %{_sysconfdir}/xpra/xorg-uinput.conf
%if %{with_cuda}
%config(noreplace) %{_sysconfdir}/xpra/cuda.conf
%config(noreplace) %{_sysconfdir}/xpra/*.keys
%endif
%config %{_sysconfdir}/xpra/conf.d/50_server_network.conf
%config %{_sysconfdir}/xpra/conf.d/55_server_x11.conf
%config %{_sysconfdir}/xpra/conf.d/60_server.conf
%config %{_sysconfdir}/xpra/conf.d/65_proxy.conf
%if 0%{?with_selinux}
%{_datadir}/selinux/*/*.pp
%endif

%if %{with_python2}
%files -n python2-xpra
%{python2_sitearch}/xpra/buffers
%{python2_sitearch}/xpra/clipboard
%{python2_sitearch}/xpra/notifications
%{python2_sitearch}/xpra/codecs
%{python2_sitearch}/xpra/dbus
%{python2_sitearch}/xpra/gtk_common
%{python2_sitearch}/xpra/keyboard
%{python2_sitearch}/xpra/net
%{python2_sitearch}/xpra/platform
%{python2_sitearch}/xpra/scripts
%{python2_sitearch}/xpra/x11
%{python2_sitearch}/xpra/monotonic_time.so
%{python2_sitearch}/xpra/rectangle.so
%{python2_sitearch}/xpra/*.py*
%{python2_sitearch}/xpra-*.egg-info

%files -n python2-xpra-audio
%{python2_sitearch}/xpra/sound

%files -n python2-xpra-client
%{python2_sitearch}/xpra/client

%files -n python2-xpra-server
%{python2_sitearch}/xpra/server
%endif

%if %{with_python3}
%files -n python3-xpra
%{python3_sitearch}/xpra/__pycache__
%{python3_sitearch}/xpra/buffers
%{python3_sitearch}/xpra/clipboard
%{python3_sitearch}/xpra/notifications
%{python3_sitearch}/xpra/codecs
%{python3_sitearch}/xpra/dbus
%{python3_sitearch}/xpra/gtk_common
%{python3_sitearch}/xpra/keyboard
%{python3_sitearch}/xpra/net
%{python3_sitearch}/xpra/platform
%{python3_sitearch}/xpra/scripts
%{python3_sitearch}/xpra/sound
%{python3_sitearch}/xpra/x11
%{python3_sitearch}/xpra/monotonic_time.*.so
%{python3_sitearch}/xpra/rectangle.*.so
%{python3_sitearch}/xpra/*.py*
%{python3_sitearch}/xpra-*.egg-info

%files -n python3-xpra-audio
%{python3_sitearch}/xpra/sound

%files -n python3-xpra-client
%{python3_sitearch}/xpra/client

%files -n python3-xpra-server
%{python3_sitearch}/xpra/server
%endif

%check
/usr/bin/desktop-file-validate %{buildroot}%{_datadir}/applications/xpra-launcher.desktop
/usr/bin/desktop-file-validate %{buildroot}%{_datadir}/applications/xpra-gui.desktop
/usr/bin/desktop-file-validate %{buildroot}%{_datadir}/applications/xpra-shadow.desktop
/usr/bin/desktop-file-validate %{buildroot}%{_datadir}/applications/xpra.desktop

%if 0%{?debug_tests}
export XPRA_UTIL_DEBUG=1
export XPRA_TEST_DEBUG=1
%endif

%if 0%{?run_tests}
pushd xpra-%{version}-python2/unittests
#we don't have python2-cryptography, so can't run the tests:
rm -fr unit/net/crypto_test.py unit/client/mixins/webcam_test.py
PYTHONPATH="%{buildroot}%{python2_sitearch}:." PATH="`pwd`/../scripts/:$PATH" XPRA_COMMAND="%{__python2} `pwd`/../scripts/xpra" XPRA_CONF_DIR="`pwd`/../etc/xpra" %{__python2} ./unit/run.py
popd

%if 0%{?with_python3}
pushd xpra-%{version}-python3/unittests
rm -fr unit/client unit/server/*server*py unit/client/mixins/webcam_test.py
PYTHONPATH="%{buildroot}%{python3_sitearch}:." PATH="%{__python3} `pwd`/../scripts/:$PATH" XPRA_COMMAND="`pwd`/../scripts/xpra" XPRA_CONF_DIR="`pwd`/../etc/xpra" %{__python3} ./unit/run.py
popd
%endif
%endif


%post common-server
%if ! 0%{?el7}
%tmpfiles_create xpra.conf
#fedora can use sysusers.d instead
%sysusers_create xpra.conf
%else
getent group xpra > /dev/null || groupadd -r xpra
%endif
if [ ! -e "/etc/xpra/ssl-cert.pem" ]; then
	umask=`umask`
	umask 077
	openssl req -new -newkey rsa:4096 -days 3650 -nodes -x509 \
		-subj "/C=US/ST=Denial/L=Springfield/O=Dis/CN=localhost" \
		-keyout "/etc/xpra/key.pem" -out "/etc/xpra/cert.pem" 2> /dev/null
	cat "/etc/xpra/key.pem" "/etc/xpra/cert.pem" > "/etc/xpra/ssl-cert.pem"
	umask $umask
	chmod 644 /etc/xpra/cert.pem
fi
%if 0%{update_firewall}
ZONE=`firewall-offline-cmd --get-default-zone 2> /dev/null`
if [ ! -z "${ZONE}" ]; then
	set +e
	firewall-cmd --zone=${ZONE} --list-ports | grep "14500/tcp" >> /dev/null 2>&1
	if [ $? != "0" ]; then
		firewall-cmd --zone=${ZONE} --add-port=14500/tcp --permanent >> /dev/null 2>&1
		if [ $? == "0" ]; then
			firewall-cmd --reload | grep -v "^success"
		else
			firewall-offline-cmd --add-port=14500/tcp | grep -v "^success"
		fi
	fi
	set -e
fi
%endif
/bin/chmod 700 /usr/lib/cups/backend/xpraforwarder
%if 0%{?with_selinux}
for mod in %{selinux_modules}
do
	for selinuxvariant in %{selinux_variants}
	do
	  /usr/sbin/semodule -s ${selinuxvariant} -i \
	    %{_datadir}/selinux/${selinuxvariant}/${mod}.pp &> /dev/null || :
	done
done
semanage port -a -t xpra_port_t -p tcp 14500 2>&1 | grep -v "already defined" || :
restorecon -R /etc/xpra /usr/lib/systemd/system/xpra* /usr/bin/xpra* || :
restorecon -R /run/xpra* /run/user/*/xpra 2> /dev/null || :
restorecon -R /usr/lib/cups/backend/xpraforwarder || :
%endif
/bin/systemctl daemon-reload >/dev/null 2>&1 || :
if [ $1 -eq 1 ]; then
	/bin/systemctl enable xpra.socket >/dev/null 2>&1 || :
	/bin/systemctl start xpra.socket >/dev/null 2>&1 || :
else
	/bin/systemctl daemon-reload >/dev/null 2>&1 || :
	/bin/systemctl restart xpra.socket >/dev/null 2>&1 || :
fi
if [ -e "/bin/udevadm" ]; then
	udevadm control --reload-rules && udevadm trigger || :
fi
#reload dbus to get our new policy:
systemctl reload dbus

%post common-client
/usr/bin/update-mime-database &> /dev/null || :
/usr/bin/update-desktop-database &> /dev/null || :
/bin/touch --no-create %{_datadir}/icons/hicolor &>/dev/null || :

%preun common-server
if [ $1 -eq 0 ] ; then
	/bin/systemctl daemon-reload >/dev/null 2>&1 || :
	/bin/systemctl disable xpra.service > /dev/null 2>&1 || :
	/bin/systemctl disable xpra.socket > /dev/null 2>&1 || :
	/bin/systemctl stop xpra.service > /dev/null 2>&1 || :
	/bin/systemctl stop xpra.socket > /dev/null 2>&1 || :
fi

%postun common-server
/bin/systemctl daemon-reload >/dev/null 2>&1 || :
%if 0%{update_firewall}
if [ $1 -eq 0 ]; then
	ZONE=`firewall-offline-cmd --get-default-zone 2> /dev/null`
	if [ ! -z "${ZONE}" ]; then
		set +e
		firewall-cmd --zone=${ZONE} --remove-port=14500/tcp --permanent >> /dev/null 2>&1
		if [ $? == "0" ]; then
			firewall-cmd --reload | grep -v "^success"
		else
			firewall-offline-cmd --add-port=14500/tcp | grep -v "^success"
		fi
		set -e
	fi
fi
%endif
%if 0%{?with_selinux}
if [ $1 -eq 0 ] ; then
	semanage port -d -p tcp 14500
	for mod in %{selinux_modules}
	do
		for selinuxvariant in %{selinux_variants}
		do
			/usr/sbin/semodule -s ${selinuxvariant} -r ${mod} &> /dev/null || :
		done
	done
fi
%endif

%postun common-client
/usr/bin/update-mime-database &> /dev/null || :
/usr/bin/update-desktop-database &> /dev/null || :
if [ $1 -eq 0 ] ; then
	/bin/touch --no-create %{_datadir}/icons/hicolor &>/dev/null
	/usr/bin/gtk-update-icon-cache %{_datadir}/icons/hicolor &>/dev/null || :
fi

%posttrans common
/usr/bin/gtk-update-icon-cache %{_datadir}/icons/hicolor &>/dev/null || :


%changelog
* Tue Dec 10 2024 Antoine Martin <antoine@xpra.org> 3.1.9-10.1xpra1
- build and packaging:
     libyuv 0.1878.20231004
     packaging updates for CentOS7: libyuv, skip pycuda
     python-netifaces missing gcc build dependency
     remove outdated numpy packaging workaround on MS Windows
     ffmpeg v7 compatibility for decoder and swscale, skip encoder
     remove ffmpeg encoder from MS Windows and MacOS builds
     never bundle any Qt components
     match `comtypes` module changes
     support build arguments specified using an environment variable
     support new repository build script target file
     cffi packaging workaround for MacOS
     produce an SBOM file on MS Windows
     use arch specific pkg-config for cuda, if found
     pynvml 12.560.30
     pyuinput 1.0.1
     require clang to build the CUDA kernels, instead of GCC >= 14
     missing SVG loader on MS Windows
     pixbuf loaders cache not populated
     initial arm64 build support for MS Windows
- encodings:
     avoid slow modules (ie: csc_cython)
     stick to the same video scaling setting longer, avoid big swings
     handle decoding of padded frames
     quality and speed can be used with all generic encodings
     clamp vrefresh to a useful range
     quality and speed disabled when encoding set to 'auto'
     support newer versions of python-pillow
     10 bit per channel issues
- major:
     protect against potential buffer overflows
     MS Windows printing crash
     system tray cleanup crash
     automatic port assignment error
     raise AES key derivation limits
     missing start menu
     try harder to find the matching key, using the keyval, key name - lowercase if needed, use default modifiers if that's all we have
     only preserve keycodes for native X11 clients
     context errors with sync-xvfb switch
     print all pages on MS Windows
     errors when the connection is closed whilst we process it
     OpenGL scroll paints, scaling arctifacts
     clipboard INCR transfers stop
     show border on XShape windows
     audio failures with 'auto' sink
     metadata ignored
     system tray errors on displays without compositing
     ignore framerate when parsing vfb resolutions
     expose all clipboard targets
     authentication aborted due to encryption not detected
     error redirection failures should not propagate
     xpra top failures on some platforms (ie: MS Windows)
     xpra top corrupted output
     vsock connection errors
- minor and cosmetic fixes:
     MS Windows setup script syntax errors
     proxy servers should respond to `id` requests
     encoding speed and quality menus not sticking
     map missing modifiers using defaults
     don't assume that zlib is available
     handle invalid dbus-launch command options
     try to prevent all ATK warnings
     prevent ssl header from messing up the log
     try to handle missing python pillow slightly more gracefully
     log opengl probe command
     confusing X11 display message
     avoid X11 client message format warnings
     use correct type for numlock modifier
     handle missing python-pillow more gracefully

* Fri Jul 12 2024 Antoine Martin <antoine@xpra.org> 3.1.8-10.1xpra1
- major:
     better compatibility with python2 servers
     missed clipboard synchronization events
     try to cleanup OpenGL context more correctly
     content type guess mismatch due to types
     crashes on clipboard backend cleanup
     bug report hangs when closing
     missing cairo dependency for non-OpenGL renderer
     honour `ssh` switch when re-connecting
     MS Windows pdfium compatibility
     preserve the same interpreter with systemd-run wrapping
     ignore keyboard layouts without a valid X11 name
     mDNS sessions not grouped in mdns sessions gui tool
- build and packaging:
     CentOS 7 uses a vendored name for lsb_release
     CentOS 7 build fix
     libvpx 1.14.1, libwebp 1.4.0
     Cython 3.x warnings, exception value warnings
     Debian build scripts need `wget` for the outdated python packages workarounds
     missing crypto libraries in MacOS builds
     build CUDA kernels with clang instead of gcc 14+
     bundle openssh.cnf with MS Windows builds
- encodings:
     ensure NV12 encoded streams are decoded the same as YUV420P
     ignore alpha channel when requested
     tolerate video dimensions rounded down to nearest multiple of 2
     smarter auto refresh encoding selection
     include color range metadata in h264 stream
     handle full range colorspace conversion
     mmap overwrite race condition
- minor and cosmetic fixes:
     connection errors with RFB mode and http socket upgrades
     support scaling specifed as a percentage
     shadow servers: missing attributes should raise a AttributeError
     vpx: set the correct (unused) pixel format constant
     unused import, typos
     build `modifications` attribute is a number
     case insensitive window role matching
     `konsole` is a text application
     missing constant
     downgrade unavoidable Wayland keyboard warning
     stricter default and return types
     decode usernames on MS Windows
     don't enable `sync-xvfb` without cairo
     we have a test suite
     warn that paramiko is unmaintained

* Sun Mar 17 2024 Antoine Martin <antoine@xpra.org> 3.1.7-10.1xpra1
- major fixes:
     windows misplaced on screen, moving unexpectedly
     windows wm-state synchronization issue
     window geometry not updated or preserved
     window model setup delays
     lossy, downscaled or subsampled text screen updates
     X11 properties clash
     http socket upgrades for slow requests
     size constraint calculation for max size
     workaround paramiko error with some agent keys
     `run_scaled` and `attach=yes` errors in virtual envs
     XImage pixel buffers are read-only
     python buffers wrongly allowing writes
     use TLS ssl protocol constant if available
     proxy draw passthrough stripping of unused alpha channels
     client exit with password dialog (MS Windows and MacOS)
     incorrect `mmap` availability check, better forward compatibility
     MS Windows system tray initial icon may be lost
     MS Windows tools not waiting for user input to close
     ensure no subprocess will wait for user input
     `xpra top` client failures recording backtraces
     `xpra top` hanging on start
     choose the best colorspace conversion module
     faster video YUV to RGB for non-OpenGL rendering
     x11 properties forwarding not handled
- clipboard:
     honour client specified order of clipboard preferred targets
     try harder to handle unexpected clipboard data formats
     allow 'text/html' clipboard transfers
- OpenGL:
     numpy race condition in OpenGL initialization
     OpenGL probe error messages
- system tray:
     appindicator system tray not shown
     shadow servers system tray missing, errors showing 'about' information
     try harder to find an icon to use
- build, packaging and platforms:
     MS Windows 'Light' builds
     better compatibility with "Windows Kits" locations
     remove generated file from VCS
     make it easier to build DEBs
     pycuda 2020.1 patch for compatibility between RHEL 8 and newer CUDA SDKs
     build CUDA kernels with clang
     missing `lsb_release` soft dependency in RPMs
     always build python rencode and python lz4 for RHEL 9
     newer libyuv snapshot
     explicit failure with Python 3.13 and newer
     clang compilation warnings
     install Cython via pip for DEB builds
     Cython compilation warnings
     Cython 0.29.37.1 / 3.0.9
     ffmpeg 6.1.1
     libvpx 1.14.0
     syntax errors in generated build info file
     nvfbc compilation warnings
     don't expand environment variables in config files
     force include xxhash and brotli libraries in MacOS builds
     close log files to avoid warnings on MS Windows
     bundle `pynvml` with the full MS Windows builds
     force `zeroconf` into the MS Windows bundle
     missing console title on MS Windows
     broken MS Windows EXE tools: missing function, use wrappers to setup environment
- minor:
     builtin ssh server connection errors when display is specified
     ssh upgrade errors when unavailable
     blacklist some more greedy clipboard applications
     rfb cleanup errors
     better rencode compatibility for XSettings
     codec self test error handler bug
     make it easier to load and test a single codec
     proxy instances signal handlers not firing
     handle missing stderr more gracefully
- cosmetic:
     don't try to set an invalid keymap
     prevent missing video options from spamming the logs
     ignore options from newer config files
     notification errors during shutdown
     don't query 'linux_distribution' on MacOS or MS Windows
     avoid potential mmap checks side-effects
     avoid mDNS errors, log message instead
     Python 3.12 SyntaxWarning
     don't try to print a display size we don't have
     gst-plugin-scanner packaging for MacOS
     deprecation warnings, unused imports
     consistency: accept more iterables
     make it possible to silence DPI warning notifications

* Mon Nov 27 2023 Antoine Martin <antoine@xpra.org> 3.1.6-10.1xpra1
- major fixes:
    some `scroll` screen updates not flushed
    crashes with newer versions of GI / GTK
    pipe and process leak with signal watcher
    RandR must re-use an existing mode if it exists
    honour all 'start' options with remote starts
- build, packaging and platforms:
    library updates: ffmpeg 6.1, python2 dbus 1.2.18, python3 pycuda 2023.1 (2022.1 for python2), pbr 6.0, pyxdg 0.28, pynvml 12.535.133, libwebp 1.3.2, libvpx 1.13.1, pyopengl 3.1.7 (3.1.6 for RHEL7), cython 3.0.6 and 0.29.36, dummy driver 0.4.1
    cx_Freeze packaging workarounds for python2 MS Windows builds
    ensure `freetype2`, `cairo` and `certifi` are bundled in
    python 3.12 compatibility
    automatic RPM release numbers
    support RPM downgrades from newer versions
    drop support for Fedora versions older than 37
    missing DEB pkgconf dependency
    Cython 3.x and 0.29.x compatibility
    remove support for Debian Stretch
    rely on distro DEB packages for python-opengl, python-lz4, rencode, xserver-xorg-video-dummy
    build with Cython 3.x for Python 3 on Debian
    more reliable ARCH detection
    don't enable dbus module on MacOS or MS Windows
    don't use `XDG_RUNTIME_DIR` on MacOS
    `named-pipe` warnings
- network:
    ssh upgrades flag not disabled on import error
    try harder to locate the start of websocket data
    try to close sockets cleanly on exit and on errors
    honour clipboard size limits
    shortcut out if not binding to any local sockets
    dpi values must be rounded to integers
    rencodeplus capability validation
- trays and notifications:
    avoid None value errors with MS Windows native notifier
    prefer native system trays to Gtk's StatusIcon, except on X11
    MacOS tray menu errors
    missing system tray on MS Windows after explorer.exe restart
    missing or disabled tray menus with `AppIndicator` backend
- compatibility:
    honour `opengl=force`
    webcam forwarding geometry
    compatibility with a wider range of Python Pillow versions
    better detection of Wayland vs X11 sessions
    force X11 backend for PyOpenGL
    only enable compression after the handshake
    partial compatibility with v6 clients and servers: encryption, mmap, encodings, dpi
    never expose None values, our custom types or `numpy` types in `info` packet data or notifications
    X11 OpenGL context manager inconsistency
    remove outdated ogg latency fix warning
    workaround NVENC deprecated presets
    log clipboard backend failures
    distribution detection fallback code path was broken
- cosmetic:
    cleaner client output
    pyobjc warnings
    bump large packet size to silence Java warnings
    `ffmpeg`'s `register_all` was called twice unnecessarily
    use attribute alias if available (cleanup code path)
    errors in `GREMEDY` OpenGL debugging
    formatting errors in verbose / x11 debug mode
    `RFB` error when rejecting protocol versions
    explicitly return a failure value from the ldap authentication module
    no-prefix coloured output with more text subcommands
    use integer division for counters
    window filter invalid parsing
    more RandR mode debug details
    unused code and variables removed
    valid linter warnings
    `proxy-video-encoders` is a valid command line option
    changelog formatting and bogus dates

* Thu Jun 15 2023 Antoine Martin <antoine@xpra.org> 3.1.5-10.1xpra1
- build, packaging and platforms:
    MacOS arm64 builds
    MacOS builds fail early outside `jhbuild` shell, clean `.cpp` files
    MacOS bundle numpy for PyOpenGL
    fix building libyuv on RHEL 7
    avoid spec file patch warnings with newer rpm build tools, CentOS7
    compilation warnings with Python2
    Python3 str vs bytes error in client
    silence Python cryptography 'openssl legacy' error
    ignore more files generated by build tools
    package mistyped in exclusion list
    DEB Python3 builds missing correct shebang
    DEB build occasional permission errors
    remove invalid DEB dependency on `python-minimal`
    workaround exotic x264 library version strings
    compatibility with the latest cx_Freeze
    runtime errors with CUDA-free builds on MS Windows
    more setuptools workarounds
    strip Cython html files
    Cython 0.29.35
    PyOpenGL 3.1.7
    Python2 PyOpenGL 3.1.6, Python3 PyOpenGL 3.1.7
    xorg-x11-drv-dummy 0.4.1
- major fixes:
    GLib memory allocator crash
    fix missing system tray with 'AyatanaAppIndicator3' vs 'AppIndicator3'
    don't use Gtk.StatusIcon on Wayland, it doesn't work
    clients without keymaps
    clients without desktops attributes
    only allow logging tweaks via env vars for non-root users
    always format the log record
    match client desktop geometry and skip DPI warnings
    potential unflushed X11 errors could crash GTK
    stricter validation of `xdg` menu data
    handle mode `xdg` library loading errors
    unwanted lost-focus events
    only use synthetic unfocus events when needed
    focus not synchronized properly
    sessions gui crashing when exiting using a key shortcut on MS Windows
    handle invalid 'use-display' option more gracefully
    Python2 builds cannot use 'rencodeplus'
    MacOS OpenGL race condition causing blank windows
- network:
    html5 client v5 compatibility regression with python2 builds
    protocol was not flushing on close
    IPv6 parsing
    handle paramiko ssh config parsing errors more gracefully: `CanonicalizeHostname`
    404 handler was missing!
- encodings:
    handle mixed case encoding names correctly (ie: `png/P`)
    honour 8-bit encodings
    handle RGBA icon data
    disable `delta` encoding - which caused some visual corruption
- cosmetic:
    spurious DPI warnings
    handle malformed display names better
    make it possible to disable `sha1`
    avoid errors if `md5` has already been removed
    parsing of X11 window names in clipboard information helper function
    avoid 404 errors in server log when newer html5 client versions are used
    don't flood the screen with `mmap` debugging
    initialize server fully so errors don't cause more cleanup errors
    window event handler logging error
    server can run without stderr
    not yet used command parsing functionality not working as intended
    MacOS GUI diagnostic tool standalone runtime failure

* Sun Mar 05 2023 Antoine Martin <antoine@xpra.org> 3.1.4-10.1xpra1
- major fixes:
    correctly wait for worker threads to terminate
    workaround new broken python3-uinput packages on Fedora
    more robust version parsing
    missing X11 error context in XI2 input bindings
    clipboard errors on Microsoft Windows (regression in 3.1.3)
    timestamp clamping code could swallow X11 client messages
    add `capability` authentication module
    match display size exactly with RandR 1.6
- keyboard:
    xkb rules name parsing error with Python 3
    avoid errors when there is no keyboard config
    fallback keycode mapping errors
- build, packaging and platforms:
    support the latest version of gtk-mac-bundler
    pyobjc libffi crash workarounds
    Cython 3.0.0b1 compatibility
    ffmpeg v6 compatibility
    support for RHEL 9.x and clones
    missing systray dependency on Debian and Ubuntu
    build only python3-xpra DEBs for newer distributions
    DEBs switched to pybuild
    build errors with latest Python
    MS Windows `unregister` class reliably
    MS Windows errors building the C++ modules
    use symlinks for CUDA path on MS Windows
    use standardized paths for new repo build scripts
    missing checksums and dependencies for some RPM spec files
    Python2 compatibility fixes
    make it possible to override build options on MacOS
- network:
    add rencodeplus
    better compatibility with newer versions: emulate the `command` Posix command
    handle version generic requests
    websocket fixes: python2 compatibility, error handler
    proxy should not try to recompress strings
    IPv6 parsing errors
    support newer versions of python-cryptography
    silence OpenSSL3 + pycryptography legacy warning
    workaround for missing paramiko dependency on python3-invoke (ie: Fedora)
    safer paramiko lookup functions
    ldap 'username_format' option can be set using an environment variable
- cosmetic:
    more helpful connection failure messages
    handle config file parsing errors more gracefully
    free wrapper explicitly to avoid warnings in webp decoder
    errors in xsettings watcher
    avoid errors deleting the temporary print file
    MacOS doesn't have an `XDG_RUNTIME_DIR`
    catch missing python-dbus earlier
    avoid errors when python-xdg is not installed
    don't assume the peer is 32-bit when unspecified
- encodings:
    only enable an encoding if we have an encoder for it
    avoid video for small sizes
    honour `XPRA_ALPHA` environment variable in client
    validate x264 encoder dimensions to prevent potential crashes
    fix transparency saturation: use premultiplied alpha with pillow and webp
    numpy import race condition
    expose `IDR` frame type in NVENC

* Sun Jun 26 2022 Antoine Martin <antoine@xpra.org> 3.1.3-10.1xpra1
- major fixes:
    GDK crash when updating parked windows geometry
    always free X11 images safely
    MS Windows clients mishandling some window hints (ie: Firefox)
    connection errors when non-user-interactive clients are connected
    filenames with special characters when opened remotely
    missing notifications due to icon parsing errors
    handling of packet parsing errors
    bencoder error when cuda info is missing
    missing auto-refresh
    'Content-Security-Policy' fixes and workarounds for Safari, xpra-html5 v6
    keyboard mapping not honouring the more specific keymap definition
    honour system prefix when loading xkb keymaps
    launcher gui initialization error on Wayland
    audio and webcam not starting with some packet encoders
- build and packaging:
    build using CUDA 11.7 by default, compile as C++11
    clean target left some generated files behind
    dependency updates
    MacOS new package signing key
    ffmpeg 5.0 compatibility
    library updates: Cython, pynvml, etc
    workarounds for latest Cython with GCC 4
    support almalinux, rocklylinux and oraclelinux 8 build targets
    aarch64 builds
    content type updates: `unityhub` is a browser, `ffplay` is video
- minor bugs and tweaks:
    clipboard errors with MS Windows clients and UTF8 data
    server errors on encoding change (ie: client tray menu)
    store and send client properties as strings
    configurable ping timeout delay
    make it possible to run the client without some cython extensions
    'xpra showsetting' subcommand errors
    always expose the server socket location
    make socket querying code more resilient
    potential race conditions with xpra info requests
- cosmetic:
    more understandable error message when ssh fails to connect
    during shutdown, ignore errors trying to set nodelay / cork
    clipboard error messages when there is no client handling it
    avoid warnings triggered by Pillow v9
    show disabled menu entries in MacOS menus with GTK3 builds
    codec loader output was ignoring standard log output format
    silence spurious authentication modules warnings
    always log the full backtrace for client connection errors
    use the correct license short names
    nvml version query error
    misc logging tweaks and fixes
- encodings:
    disable vaapi with the ffmpeg encoder (crashy)
    handle grayscale png images with transparency
    workaround for missing video mode client metadata
    don't send empty alpha channel
    never delay screen updates unless we have a video region
    jpeg decoder generated invalid picture metadata

* Tue Oct 19 2021 Antoine Martin <antoine@xpra.org> 3.1.2-10.1xpra1
- encoding errors with vpx
- fix pkg-info build command
- packaging workarounds for Ubuntu Impish
- fixup missing import in backport
- minor RPM build fixes
- rebuild with small fixes

* Thu Oct 07 2021 Antoine Martin <antoine@xpra.org> 3.1.1-10.1xpra1
- critical bugs:
    fix crashes during printer enumeration on MS Windows
    fix crashes when starting audio forwarding via the command line
    disable crashy ffmpeg codecs with 32-bit builds
    rencode DoS (MacOS and MS Windows binary builds)
    missing key events
- server stalls:
    don't load menu data from the main thread
    don't query the list of printers from the main thread
- build, packaging and platform fixes:
    Python 3.10 support
    default to using CUDA 11.4
    don't try to build NVENC against newer glibc headers (CUDA bug)
    support NVidia Ampere cards natively
    compatibility with experimental version of ffmpeg (GBRP9LE)
    more reliable git branch detection
    Linux distribution detection bug with Python 3 versions
    remove unnecessary runtime dependency on distutils
    clipboard support with python2 servers started from a Wayland environment
    corrupted cursors on MS Windows
    make it possible to bundle webcam support on MS Windows (still disabled by default)
    updated GStreamer dependencies
    the Debian package name we have to recommend is 'dnspython'
    generic / common RPM packages should not depend on Python 3
    use the correct /etc/default path for service configuration
    MacOS updates for GTK3 3.24.30: patches, dependencies
    MacOS packaging of the latest Python pillow with webp support
    add missing C++ files to source snapshots
    fixup some compatibility issues in previous backports
    clean generated Cython files (some pyd filenames have changed)
    use the versioned python interpreter for sourcing files (fix error on CentOS 8)
    locate libfakeXinerama more reliably (at build time)
    missing vpx support on CentOS 7.x
    libwebp 1.2.1
    pynvml 11.470.66
    patched rencode - override the buggy version from EPEL
    arm64 build and packaging tweaks
- network:
    handle mmap client setup errors correctly
    mmap unix group lookup API
    support improved packet encoders
    use the correct exit code for encryption problems
    http script errors
    session 'name' server control command error
    use cryptographically secure random values with AES
    prevent DoS using unreasonably large number of key stretching iterations
    menu errors when there are active VNC connections
    stricter validation of raw packet indexes
    better compatibility with packet encoders (start menu, clipboard)
    reply with 404 if we don't find any data to send
    correctly parse ssh remote command output
    MacOS and MS Windows shadow servers missing the default TCP socket (port 14500)
- authentication:
    stricter validation of challenge digest
    honour the `socket-dirs` option in authentication modules
    fallback to the current user if the one specified is invalid
- encodings:
    correctly paint OpenGL scaled jpeg YUV screen updates
    error in 'void' paint handler (normally unused)
    sha1 data integrity checksum values
    re-enable non-fatal ffmpeg logging outside suppressed code blocks
    vpx encoder uninitialized variable undefined behaviour
    restrict the number of NVENC errors tagged as transient
    don't use AV sync for 'text', 'desktop' and 'picture' content types
- window geometry:
    errors with StackMode requests
    size hints not being honoured in some rare cases
- misc fixes:
    notifications should not override the exit code
    stop processing info requests when the server is exiting
    increase the maximum size of Xdummy resolutions (uses more memory)
    retry if we fail to load the list of windows the first time (seamless servers)
    missing notifications when failing to load the icon
    fix default values shown with 'xpra --help'
    try harder to exit the server cleanly (kill xvfb and dbus later)
    honour the force-replace-wm flag when upgrading
    some modifiers may not have matching key names (ie: VNC clients)
    don't expose xdg desktop entries that don't have a command to run
    smooth scrolling with GTK3 clients
    documentation, debugging, logging tweaks and fixes
    u2f tool error
    prefer https for links to the xpra.org website
    fix saving icons with gi bindings (Python 3)
    make it easier to run in a prefixed installation
    cursor regression with Python 2 builds
- proxy fixes:
    preserve audio packets chunking (avoids an HTML5 client bug)
    avoid potential race conditions with video encoder re-framing
    try harder to find a usable session directory to use
- audio fixes:
    ensure we always stop the 'new-stream' notification process
    remove aac codec flag causing compatibility errors
    fix sink test tool command line usage
- 'top' client:
    server errors when 'top' clients are connected
    handle unicode window names correctly
    threading fixes (screen corruption)
    latency shown as always zero
- html5:
    less strict content security policy
    ensure the 'set-initial-position' attribute is initialized
    avoid sending window attributes set to 'None'
    fix lz4 with AES incompatibility
    log the reason when closing
    don't start a new session again when re-connecting
    don't try to re-connect when the server is shutting down
    re-connected session would lose its connection quickly
    keyboard layout mapping from browser language
    window snapping to the edge, wrong offset
    avoid triggering server side errors on OR windows

* Mon May 24 2021 Antoine Martin <antoine@xpra.org> 3.1-10.1xpra1
- critical fixes:
    proxy deadlock, subprocess leak, socket errors
    proxy start and display handling errors
    proxy disconnections under heavy load
    'scroll' detection bugs
    attach failures with remote start
    windows not getting focus
    unnecessary screen update latency
    crash / corruption in the webp encoder
    crash caused by resizing large SVG icons
    crash caused by notifications
    screen resizing with invalid DPI values
    audio silence detection with DEB packages
- screen update fixes:
    cairo rendering artifacts
    lossy screen updates when 'scroll' encoding is used
    video subregion detection error
    wayland client geometry repaint
    recover speed more quickly
    expire delayed regions on schedule
    mmap does not need refreshing
- misc fixes:
    concurrency runtime errors
    window resize counter was invalid / ignored
    cuda error handling
    xdg menu loading failures
    'encoding' control command
    invalid default value for $XDG_DATA_DIRS
    parsing of peercred options
    spurious errors if file transfers are disabled
    validation of display numbers
    sessions started by the proxy miss $HOME and $USER
    tray menu clipboard errors
    environment variables not honoured via xpra launcher
    URL forwarding errors with Python 3 clients
    dangerous default argument corruption
    honour XPRA_NOMD5 in window border code
    warning message format under VirtualBox on MS Windows
    honour the XPRA_XDG_EXPORT_ICONS environment variable
    ensure passwords are not logged using 'auth' debug logging
    xdg-open stdout / stderr formatting
- build, packaging, platform and test fixes:
    compilation errors with newer GCC versions, CentOS 7
    missing build dependencies
    split Python 2 vs 3 packages
    support Python 3.9
    printing diagnostic script errors with Python 3
    updated supported distributions
    updated build and runtime dependencies
    MacOS Big Sur compatibility
    SELinux policy tweaks
    ignore 'bell' audio device
    never pollute /root/.xpra or /root/.config/
    point to the correct systemd service configuration file path
    remove hard dependency on 'gnome-shell'
    invalid permissions on some scripts and data files
    update packging to get version information from git
    OpenBSD build fix
- MS Windows fixes:
    test errors due to low precision clock
    clipboard cleanup errors
    bubble notifications not showing up
    missing / transparent icons in the system tray
    overflow errors accessing window handles
    use an up to date PDFium library
    non-ascii key lookup with shadow servers
    client sub-layout detection
    client handling of 'Control' key combinations
- keyboard fixes:
    key symbol lookup
    invalid key modifier detection
    stuck keys
    mismapped key groups
- network fixes:
    handling of jittery connections
    silence mdns warnings
    socket creation errors with missing directories
    failures to enable packet compression
    connection errors when a non-ui client is already connected
    try harder not to leave 'xpra _proxy' zombies behind
    ssh connection errors with proxycommand or proxyhost port numbers
    ensure some packets are not delayed unnecessarily
    file transfers with non-ascii filenames
    automatically shrink large SVG icons
- HTML5 client:
    sends audio 'stop' before it is allowed to do so
    can specify the display to connect to
    show complete disconnection message
- enhancements and changes:
    allow exit-with-children with any start-child argument
    nvjpeg encoder
    latest 'xpra top' client
    updated window class mappings
    support smooth scrolling - ie: touchpads
    faster server startup
    increase default refresh rate
    honour initial window position hint
    'source-start' now handles executables that print the new environment
    drop Python 2 / GTK 2 builds on MS Windows
    add new common screen resolutions for Xdummy
    add 'map' and 'unmap' control commands
    debug logging tweaks, remove confusing messages
    the socket type can be specified with systemd socket activation
    stop supporting legacy salt digest modes
    always verify SSL hostname

* Thu Aug 20 2020 Antoine Martin <antoine@xpra.org> 3.0.12-10xpra1
- fix NVENC encoder (profile errors, cleanup race condition)
- fix unmanaged X11 message call which could cause GTK to crash when it fails
- fix 'sync-xvfb' option: setup error, non-standard bit depth support
- fix missing system tray on Ubuntu 18.04
- fix workspace spurious warnings on 64-bit X11 systems
- fix event handler with 64-bit MS Windows builds
- fix named-pipe server clash
- fix error handing in MS Windows printer query API
- switch to Xvfb on Debian and Ubuntu
- workaround more pyxdg bugs
- ignore plink packaging errors with 32-bit MS Windows builds
- disable swscale on 32-bit MS Windows builds (prevent crashes)
- tabs mixed with spaces (potential for bug)
- add missing DEB dependency

* Fri Aug 07 2020 Antoine Martin <antoine@xpra.org> 3.0.11-10xpra1
- fix encryption option overzealously enforced on all socket types
- fix network layer compression errors that can cause connections to drop
- fix printing errors with some shell character encodings
- fix NVENC h264 stream compatibility with HTML5 client
- fix windows not getting focused when clicking on title bar (HTML5)
- fix suspend / resume errors with tray windows
- fix Python2 / GTK2 compatibility regression from 3.0.10
- fix tray geometry errors
- fix minimum video scaling not being honoured via heuristics
- fix clipboard data sometimes going missing when ownership changes
- fix error in main thread verifier (fortunately, never fired)
- fix python-pillow packaging conflicts on CentOS / RHEL 7
- fix memory contents of the swscale pixel format object
- fix csc_swscale converter getting recycled every time
- fix division by zero errors during window cleanup
- fix detection of named-pipe creation errors
- fix MS Windows shadow server errors with 'bind=auto'
- fix MS Windows servers slow to handle connections with mDNS enabled
- fix sshfp support on MacOS (was missing dns python module)
- fix MacOS errors with some subcommands (ie: 'list')
- fix notification widget wrongly stealing input focus
- fix support for building with CUDA 11.0
- fix unshrinkable session-info window
- fix window resizing errors when non-GUI clients are also connected
- avoid ever using b-frames for text content
- silence unhelpful gtk warnings on MacOS
- avoid opengl warning with wayland
- discard invalid clipboard requests early
- workaround for older versions of python-cryptography
- use 'text' mode for 'geany' (fixes lossy screen updates)
- ensure all toolbox windows set a correct and readable window title
- convert invalid map events to warnings (no scary crash reports)
- also update mdns records when the session name changes
- make it possible to specify the path used for saving video streams / frames

* Thu Jun 04 2020 Antoine Martin <antoine@xpra.org> 3.0.10-10xpra3
- fix X11 server key symbol lookup via Xkb
- fix encryption not honoured with TCP sockets upgraded to WebSocket
- fix window corruption with 'scroll' encoder
- fix desktop-scaling changes from the system tray
- fix clipboard synchronization problems caused by clipit
- fix packaging with newer versions of py2app (MacOS)
- fix logging spam in start-new-command dialog
- fix building from source on archlinux
- fix swapped red and blue colours channels in win32 systray
- fix error parsing invalid config files
- fix missing content-type for some windows
- fix server crash on exit on some Linux distributions
- fix 'xpra send-file' to use absolute file paths
- fix format of attributes given to glXChooseVisual
- fix crashes in OpenGL context setup on X11
- fix race condition in window statistics
- fix server errors when non-interactive clients are connected
- fix option parsing errors causing html5 client connection failures
- fix python-lz4 packaging on MS Windows (Python2 builds)
- html5 fixes:
    missing desktop background
    client errors painting rgb32 data with a padded rowstride
    clipboard wrongly clearing data on failures
    compatibility issues with Internet Explorer
    missing transparency for windows in focus
    no windows focused after close
    connection errors caused by spurious packets
    error in invalid packet handler
    AES encryption connections
    connection errors with AES and lz4 (disable lz4 for now)
    packet error with very small paint packets
    'insecure passwords' option shown in the wrong cases
    handle window iconification messages
    update version in about page
- fix connection errors with 'None' values in bencoder (ie: html5)
- fix connection errors with websocket connections and AES encryption
- fix duplicate clipboard token sent from MS Windows servers
- fix window initialization errors causing server startup failures
- cleaner exit path: destroy all of our windows properly
- add workaround for wine applications (disabled by default)
- add 'terminator' to the 'text' application hint
- validate webp image dimensions for transparency encoding
- workaround bugs in pyxdg / menu configuration
- try harder to strip all temporary build prefixes
- remove invalid extra strings from mdns service name
- change DLL search order to prevent conflict (MS Windows)
- MacOS: update to Python 2.7.18 for python2 builds
- don't recommend installing Apple's 'bonjour' on MS Windows (not needed)
- MS Windows build setup update: install python-lzo using pacman

* Wed Apr 15 2020 Antoine Martin <antoine@xpra.org> 3.0.9-10xpra3
- rebuild with python2 fixup

* Tue Apr 14 2020 Antoine Martin <antoine@xpra.org> 3.0.9-10xpra2
- fix HTML5 client XSS
- fix focus issues
- fix server hangs and unpainted windows due to invalid dimensions
- fix window icons and cursors visual corruption or crashes
- fix unbearably slow screen updates when vrefresh value is invalid
- fix client OpenGL crashes with remote starts (run probe first)
- fix keypad regression (AltGr changes, again)
- fix MS Windows shadow servers
- fix race condition collecting latency data for session info
- fix missing pycuda dependency for nvenc on MS Windows
- fix missing signatures on MS Windows EXE and MSI builds
- fix scoring of NVENC codec (should be used ahead of sofware encoders)
- fix start menu updates getting lost
- fix OpenGL diagnostic messages getting cut off
- fix change of encoding from the system tray
- fix quality and speed changes from the system tray
- fix clipboard and popup menu problems with Eclipse
- fix name of shadow server process on MS Windows, used in log file names
- fix audio query subprocess with MS shadow servers
- fix unlikely race condition in speaker forwarding shutdown sequence
- fix desktop-fullscreen=yes automatic scaling
- fix missing bug report data due to uninitialized X11 bindings
- fix bug report error if we cannot grab a screenshot (ie: Wayland)
- fix error saving binary data with python3 builds of the bug report tool
- fix errors querying the display under Wayland
- hide scary stacktraces when shutting down ssh proxy commands
- if we have an ssh password we can use, try that first
- blacklist VirtualBox's SVGA3D OpenGL driver (fixes black windows)
- don't use webp with image dimensions beyond its limits
- use regular X11 system tray with i3
- hide confusing named-pipe prefix in empty output on MS Windows
- HTML5 fixes: invalid IMG tag, reserved keyword, language detection, draw debugging, etc
- don't try to read /proc if not on Posix
- support more versions of Visual Studio when compiling CUDA kernels
- use a more specific python3 interpreter version
- update application content-type mappings
- remove out of date information from man page
- MacOS: openssl 1.1.1f

* Wed Apr 01 2020 Antoine Martin <antoine@xpra.org> 3.0.8-2xpra1
- rebuilt with ssh run-xpra script fix

* Tue Mar 31 2020 Antoine Martin <antoine@xpra.org> 3.0.8-1xpra1
- fix handling of dpi command line switch (correctly this time?)
- fix bug report window not getting focus on MacOS
- fix spurious ssh key warnings with newer versions of paramiko
- fix AltGr mode with non-X11 clients, layout-group changes
- fix rare unexpected client exit on MS Windows
- fix MS Windows clipboard:
    update failures
    convert CRLF line endings
- Clipboard:
    fix selection not shown as active in menus (MS Windows and MacOS)
    fix spurious warnings when sharing a session
    fix clipboard reset with python2 builds
    selection translation for outbound data
    support client applications that don't use TARGETS (ie: Motif)
    reject invalid targets
- fix 'xpra upgrade' wrongly updating non-xpra displays
- fix logging error in client geometry debugging output
- fix pulseaudio start command with Ubuntu Xenial
- fix spurious de-iconifications
- fix handling of server control commands with python3 clients
- fix UDP backport bug sending control packets
- fix vfb getting killed on upgrade failure
- fix proxy server cleanup: force forwarders to terminate
- fix session info errors during client exit
- fix printer cleanup errors with invalid UTF8 printer names
- fix transient-for popup window workaround
- fix missing libyuv csc module on MacOS
- fix unicode errors saving xpra runner shell script with python3
- try to prevent conflicts with Fedora's packages
- better detection of Wayland environments
- use python3 (if installed) by default on Ubuntu Xenial
- don't use Xdummy on arm, too slow
- don't show 'Download' button that we can't honour
- show all pressed keys according to X11 server in 'xpra info'
- try harder not to use video for tiny areas

* Thu Mar 12 2020 Antoine Martin <antoine@xpra.org> 3.0.7-1xpra1
- fix avcodec2 race condition crash
- fix errors when re-initializing windows (ie: toggling OpenGL on or off)
- fix deiconification error when there are system trays forwarded
- fix missing alpha channel when some windows are first shown
- fix systemd-run errors: verify it does work before trying to use it
- fix debug builds compilation error on MS Windows
- fix server crashes on SIGINT: shutdown cleanly
- fix proxy server client connection setup error hanlder
- fix file authentication handler using a default password filename
- fix directshow errors on local mingw installations
- fix opengl properties missing from server hello packet
- fix HTML5 sound-control errors when speaker forwarding is disabled
- fix HTML5 "Terminate" options wrongly enabled in "Connect" mode
- fix clipboard sharing with the MacOS shadow server
- fix MS Windows clipboard access denied errors
- fix X11 clipboard error handling: continue processing
- fix unit tests failures (clipboard, etc)
- fix bug report clipboard copy and screnshots
- fix clipboard timeouts when a client disconnects
- fix mdns cleanup done twice on server exit, causing errors
- fix malformed XSettings due to invalid color data format
- fix FreeBSD builds
- fix MS Windows packaging missing a codec DLL, Plink DLL
- fix HMAC hashes exposed, keep only valid options
- fix 'showconfig' output for boolean values set to 'auto'
- fix parsing of client display information in legacy format
- fix validation of size-hints
- fix cursor saving debug code with GTK3
- fix keyboard layout group not getting reset on client exit
- fix some empty keyboard layout group strings parsed as non-empty
- fix keyboard-sync mode not being honoured by servers
- fix keyboard raw mode
- fix missing 'perispomeni' key mapping with Python 2 servers
- add missing debug logging to keyboard mapping
- more reliable lookup of keycodes when translating (non-X11 clients)
- add missing dependency for printer forwarding on Debian
- packaging for Ubuntu Focal Fossa
- skip bundling some external test modules with binary installers
- more correct code for locating the 'Downloads' folder on MS Windows
- avoid spurious background worker warnings on exit
- make unavoidable comtypes error less scary
- add 'libreoffice' to the text mode whitelist
- library updates: Python 3.8.2, etc
- packaging workarounds for setuptools breakage

* Sat Feb 08 2020 Antoine Martin <antoine@xpra.org> 3.0.6-1xpra2
- fix 'User' not honoured in ssh_config
- fix X11 server initiate move-resize
- prettier format for new connection information
- Debian packaging: prefer python3 installations

* Wed Feb 05 2020 Antoine Martin <antoine@xpra.org> 3.0.6-1xpra1
- fix UDP with Python3
- fix key mapping issues with non-X11 clients and non-US layouts
- fix notification logging errors during shutdown
- fix window stacking order with html5 client and override redirect windows
- fix png/P and png/L decoding
- fix very slow startup on Debian due to missing libfakeXinerama
- fix display scaling notification warning
- fix errors generating the tray title string
- fix missing webp modules in 'clean' build target
- fix some special characters with HTML5 client
- fix initiate-moveresize with multiple clients
- fix keyboard layout detection with MS Windows 10 clients
- fix control commands argument error handling
- fix unit tests
- fix window repaint issues: system tray, Python 2 non-opengl window spinners
- fix server errors during client connection cleanup
- fix spacebar and other characters with tablet input devices (ie: mobile browsers)
- fix unhelpful backtraces when client application windows are lost
- fix MS Windows packaging workarounds for TK
- fix for crashes on X11 displays lacking RandR support
- fix handling of non 24/32-bit png window icons
- man page connection string fixes
- disable cpuinfo module - known to cause problems on various platforms
- ignore error and continue when loading version information from invalid builds
- remove executable file permissions on files uploaded to the server
- blacklist 'Intel(R) UHD Graphics 620'
- use correct location for appdata.xml
- use Debian location for systemd service config file
- ensure emacs, gvim and xxdiff always use 'text' mode
- re-enable pulseaudio memfd (was wrongly disabled in v3.0.0)
- remove remnants of GTK2 dependencies from non-GTK2 components
- add missing entry to path information tool

* Tue Jan 07 2020 Antoine Martin <antoine@xpra.org> 3.0.5-1xpra1
- fix missing undecorated opengl windows on win32 with GTK3 (correct fix)
- fix fake Xinerama errors with unicode monitor names
- fix av-sync backport for python2 servers
- fix errors when the dbus submodule is not installed
- fix RFB server key handling
- fix exit code for unsupported sockets
- fix tray title with openssh and plink SSH backends
- fix crashes on win32 shadow exit
- fix 'xpra upgrade'
- fix focus problems with OR windows
- fix wrong client info shown in 'xpra top'
- fix 'xpra top' error that scrambled the output, flickering
- fix X11 keyboard query against secondary screens
- skip trying to load X11 components on non-X11 platforms
- allow F11 through to the browser to make it easier to go fullscreen
- prevent sshfp dns errors from causing ssh connection failures
- obscure passwords from log files
- remove duplicated attribute from xpra info
- remove unused loggers
- expose av-sync and webcam client capabilities
- better wayland mode detection
- add more missing files to MANIFEST
- add v4l2 codec files to clean target
- add logging to gtk display cleanup

* Thu Dec 19 2019 Antoine Martin <antoine@xpra.org> 3.0.4-1xpra1
- fix missing undecorated windows on win32
- fix av-sync
- fix X11 property synchronization error due to race condition
- fix XI2 bindings not loading
- fix ssh upgrades wrongly claimed as supported when paramiko is not installed
- fix 'wireless' network device detection on Linux
- fix 'Sound Buffer' graph
- fix errors caused by window title error handler
- fix missing 'Packet Encoders' and 'Packet Compressors' with python3 clients
- relax RPM dependencies to allow different versions to be installed simultaneously
- add missing files to MANIFEST
- distinguish certificate verification errors from other ssl errors

* Tue Dec 10 2019 Antoine Martin <antoine@xpra.org> 3.0.3-1xpra1
- fix clipboard synchronization with HTML5 client
- fix window repaints with GTK3
- fix GDK scaling causing window painting issues (force off)
- fix slow repaint with OpenGL and combined updates (ie: scrolling)
- fix missing video screen updates with 32-bit browsers: disable video
- fix for X11 applications requesting invalid clipboard targets
- fix "xpra top" errors when the terminal window is too small
- fix blank xpra dialog windows when closed then shown again (ie: server commands)
- fix compilation on non-i386 32-bit platforms
- fix platform query errors causing command failures
- fix Python2 builds: ignore GTK2 deprecation warnings
- fix X11 property synchronization with Python2 builds
- fix XSetClassHint call with Python 3
- fix window move + resize shortcut
- fix ssh proxy options not preserved when loading session files
- fix focus of dialogs with MacOS clients (ie: SSH dialogs)
- fix error and missing refresh after changing quality or speed settings
- fix NVENC error when pynvml is not installed
- fix NVENC temporary failure retry code path
- fix SSH start for shadow and start-desktop subcommands from MacOS
- fix fullscreen / maximized windows on MacOS
- fix bogus screen dimensions with GTK3 on MacOS
- fix client launcher helper script on MacOS
- fix window resizing with OpenGL on MacOS
- fix DPI value from the command line with desktop-scaling
- fix typo in man page
- fix errors with some odd Python3 builds (subprocess.getoutput)
- fix cursor packets missing encoding attribute
- fix dangling symlink in html5 client Fedora RPM package
- fix notification error handling the speaker forwarding error message
- fix incorrect and unhelpful message on connection error
- fix openssl crypto DLL errors during MS Windows installation
- prevent conflict with Fedora downstream packaging of xpra
- make it possible to disable colourspace synchronization
- show mdns status in xpra info
- MacOS library updates (many, including Python 3.8.0)
- support CUDA 10.2
- disable CSD on MS Windows (GTK3 CSD bug workaround)
- re-enable OpenGL on MS Windows (was GTK3 bug)

* Tue Nov 05 2019 Antoine Martin <antoine@xpra.org> 3.0.2-1
- fix clipboard synchronization issue with MS Windows clients properly
- fix Pillow 6.x compatibility with MS Windows packaging
- fix null bytes in X11 error text properly
- fix Python 3 servers wrongly re-sending the 'screen' attribute
- fix remote logging failures with some message formats
- fix lost screen updates
- fix GTK scaling causing window geometry issues
- fix HTML5 clipboard data sent from polling events
- fix CUDA device logging with multiple devices
- fix 32-bit build errors on xxhash
- fix RPM jpeg and libyuv dependencies
- fix OpenGL window not refreshing with Python 3
- fix OpenGL context held for too long
- fix SSH connection errors when 'port' is specified in the ssh config
- fix faac and faad2 security issues in MS Windows and MacOS builds
- fix window size hints misapplied with GTK3 on MS Windows and Wayland
- disable OpenGL acceleration on old Intel chipsets
- disable OpenGL acceleration with GTK3 builds on MS Windows (for now, pending bug)
- show python interpreter version on about dialog
- re-instante ancient popup window workaround (was disabled by mistake)
- don't use av-synchronization for text and picture content types
- workaround Fedora packaging causing gratuitious conflicts

* Wed Oct 23 2019 Antoine Martin <antoine@xpra.org> 3.0.1-2
- correct clipboard fix

* Tue Oct 22 2019 Antoine Martin <antoine@xpra.org> 3.0.1-1
- fix clipboard synchronization failures with MS Windows clients
- fix window cleanup errors preventing a clean exit
- fix launcher error if sharing flag is unset
- fix window states wrongly getting reset
- fix SSH password dialog lockups on MS Windows
- fix authentication module errors (multifile, python3)
- fix radio buttons on start server dialog (python3)
- fix error in encoding selection fallback (python3)
- fix logging error in cups printing backend (python3)
- fix null bytes in X11 error text (notifications errors)
- fix keyboard debug logging error
- fix error querying X11 properties under pure wayland client
- fix unresponsive appindicator system tray
- fix GDK window scaling setting wrongly propagated to the server
- fix compilation on Ubuntu Eoan Ermine
- fix file download failures on MS Windows due to invalid characters
- fix handling of file download errors
- fix Debian bin path warnings
- fix error handling in 'xpra top'
- fix pyobjc API compatibility in OpenGL transparency shim
- fix out of date PKG OS version requirements
- fix PKG compatibility with MacOS 10.15 Catalina
- fix window border color parsing failures causing errors
- fix OpenGL window paint errors with some drivers
- make it easier to launch test tools
- update Python to 3.7.5 on MacOS
- bump revision to override broken Fedora packaging
- show Python version in MacOS packages
- re-enable tooltips on MS Windows
- update to xxhash 0.7.2
- consistent use of quotes in endpoint logging

* Sat Sep 21 2019 Antoine Martin <antoine@xpra.org> 3.0-1
- Python 3 port complete, now the default: #1571, #2195
- much nicer HTML5 client user interface: #2269
- Window handling:
- smoother window resizing: #478 (OpenGL)
- honouring gravity: #2217
- lock them in readonly mode: #2137
- xpra top subcommand: #2348
- faster startup:
- #2347 faster client startup
- #2341 faster server startup
- OpenGL:
- more reliable driver probing: #2204
- cursor paint support: #1497
- transparency on MacOS: #1794
- Encoding:
- lossless window scrolling: #1320
- scrolling acceleration for non-OpenGL backends: #2295
- harden image parsing: #2279
- workaround slow video encoder initialization (ie: NVENC) using replacement frames: #2048
- avoid loading codecs we don't need: #2344
- skip some CUDA devices, speedup enumeration: #2415
- Clipboard:
- new native clipboard implementations for all platforms: #812
- HTML5 asynchronous clipboard: #1844
- HTML5 support for copying images: #2312 (with watermarking)
- brotli compression for text data: #2289
- Authentication:
- modular client authentication handlers: #1796
- mysql authentication module: #2287
- generic SQL authentication module: #2288
- Network:
- client listen mode: #1022
- retry to connect until it succeeds or times out: #2346
- mdns TXT attributes updated at runtime: #2187
- zeroconf fixes: #2317
- drop pybonjour: #2297
- paramiko honours IdentityFile: #2282, handles SIGINT better: #2378
- proxy server fixes for ssl and ssh sockets: #2399, remove spurious options: #2193
- proxy ping and timeouts: #2408
- proxy dynamic authentication: #2261
- Automated Testing:
- test HTML5 client: #2231
- many new mixin tests: #1773 (and bugs found)
- start-new-commands is now enabled by default: #2278, and the UI allows free text: #2221
- basic support for native GTK wayland client: #2243
- forward custom X11 properties: #2311
- xpra launcher visual feedback during connection: #1421, sharing option: #2115
- "Window" menu on MacOS: #1808

* Tue Mar 19 2019 Antoine Martin <antoine@xpra.org> 2.5-1
- Python 3 port mostly complete, including packaging for Debian
- pixel compression and bandwidth management:
- better recovery from network congestion
- distinguish refresh from normal updates
- better tuning for mmap connections
- heuristics improvements
- use video encoders more aggressively
- prevent too many delayed frames with x264
- better video region detection with opengl content
- better automatic tuning for client applications
- based on application categories
- application supplied hints
- application window encoding hints
- using environment variables and disabling video
- HTML5 client improvements
- Client improvements:
- make it easier to start new commands, provide start menu
- probe OpenGL in a subprocess to detect and workaround driver crashes
- use appindicator if available
- Packaging:
- merge xpra and its dependencies into the ​MSYS2 repository
- ship fewer files in MS Windows installers
- partial support for parallel installation of 32-bit and 64-bit version on MS Windows
- MacOS library updates
- CentOS 7: libyuv and turbojpeg
- Windows Services for Linux (WSL) support
- Fedora 30 and Ubuntu Disco support
- Ubuntu HWE compatibility (manual steps required due to upstream bug)
- Server improvements:
- start command on last client exit
- honour minimum window size
- Python 3
- upgrade-desktop subcommand
- Network layer:
- less copying
- use our own websocket layer
- make it easier to install mdns on MS Windows
- make mmap group configurable
- TCP CORK support on Linux
- SSH transport:
- support .ssh/config with paramiko backend
- connecting via ssh proxy hosts
- SSHFP with paramiko:
- clipboard: restrict clipboard data transfers size
- audio: support wasapi on MS Windows
- code cleanups, etc

* Sat Oct 13 2018 Antoine Martin <antoine@xpra.org> 2.4-1
- SSH client integration (paramiko)
- builtin server support for TCP socket upgrades to SSH (paramiko)
- automatic TCP port allocation
- expose desktop-sessions as VNC via mdns
- add zeroconf backend
- register more URL schemes
- window content type heuristics configuration
- use content type it to better tune automatic encoding selection
- automatic video scaling
- bandwidth-limit management in video encoders
- HTML5 client mpeg1 and h264 decoding
- HTML5 client support for forwarding of URL open requests
- HTML5 client Internet Explorer 11 compatibility
- HTML5 client toolbar improvements
- HTML5 fullscreen mode support
- limit video dimensions to cap CPU and bandwidth usage
- keyboard layout handling fixes
- better memory management and resource usage
- new default GUI welcome screen
- desktop file for starting shadow servers more easily
- clipboard synchronization with multiple clients
- use notifications bubbles for more important events
- workarounds for running under Wayland with GTK3
- modal windows enabled by default
- support xdg base directory specification and socket file time
- improved python3 support (still client only)
- multi-window shadow servers on MacOS and MS Windows
- buildbot upgrade
- more reliable unit tests
- fixes and workarounds for Java client applications
- locally authenticated users can shutdown proxy servers
- restrict potential privileged information leakage
- enhanced per-client window filtering
- remove extra pixel copy in opengl enabled client
- clip pointer events to the actual window content size
- new platforms: Ubuntu Cosmic, Fedora 29

* Tue May 08 2018 Antoine Martin <antoine@xpra.org> 2.3-1
- stackable authentication modules
- tcp wrappers authentication module
- gss, kerberos, ldap and u2f authentication modules
- request access to the session
- pulseaudio server per session to prevent audio leaking
- better network bandwidth utilization and congestion management
- faster encoding and decoding: YUV for webp and jpeg, encoder hints, better vsync
- notifications actions forwarding, custom icons, expose warnings
- upload notification and management
- shadow servers multi window mode
- tighter client OS integratioin
- client window positioning and multi-screen support
- unique application icon used as tray icon
- multi stop or attach
- control start commands
- forward signals sent to windows client side
- forward requests to open URLs or files on the server side
- html5 client improvements: top bar, debugging, etc
- custom http headers, support content security policy
- python3 port improvements
- bug fixes: settings synchronization, macos keyboard mapping, etc
- packaging: switch back to ffmpeg system libraries, support GTK3 on macos
- structural improvements: refactoring, fewer synchronized X11 calls, etc


* Mon Dec 11 2017 Antoine Martin <antoine@xpra.org> 2.2-1
- support RFB clients (ie: VNC) with bind-rfb or rfb-upgrade options
- UDP transport (experimental) with bind-udp and udp://host:port URLs
- TCP sockets can be upgrade to Websockets and / or SSL, RFB
- multiple bind options for all socket types supported: tcp, ssl, ws, wss, udp, rfb
- bandwidth-limit option, support for very low bandwidth connections
- detect network performance characteristics
- "xpra sessions" browser tool for both mDNS and local sessions
- support arbitrary resolutions with Xvfb (not with Xdummy yet)
- new OpenGL backends, with support for GTK3 on most platforms
- window transparency on MS Windows
- optimized webp encoding, supported in HTML5 client
- uinput virtual pointer device for supporting fine grained scrolling
- connection strings now support the standard URI format protocol://host:port/
- rencode is now used by default for the initial packet
- skip sending audio packets when inactive
- improved support for non-us keyboard layouts with non-X11 clients
- better modifier key support on Mac OS
- clipboard support with GTK3
- displayfd command line option
- cosmetic system tray menu layout changes
- dbus service for the system wide proxy server (stub)
- move mmap file to $XDG_RUNTIME_DIR (where applicable)
- password prompt dialog in client
- fixed memory leaks

* Mon Jul 24 2017 Antoine Martin <antoine@xpra.org> 2.1-1
- improve system wide proxy server, logind support on, socket activation
- new authentication modules: peercred, sqlite
- split packages for RPM, MS Windows and Mac OS
- digitally signed MS Windows installers
- HTML5 client improvements:
   file upload support
   better non-us keyboard and language support
   safe HMAC authentication over HTTP, re-connection etc
   more complete window management, (pre-)compression (zlib, brotli)
   mobile on-screen keyboard
   audio forwarding for IE
   remote drag and drop support
- better Multicast DNS support, with a GUI launcher
- improved image depth / deep color handling
- desktop mode can now be resized easily
- any window can be made fullscreen (Shift+F11 to trigger)
- Python3 GTK3 client is now usable
- shutdown the server from the tray menu
- terminate child commands on server shutdown
- macos library updates: #1501, support for virtual desktops
- NVENC SDK version 8 and HEVC support
- Nvidia capture SDK support for fast shadow servers
- shadow servers improvements: show shadow pointer in opengl client
- structural improvements and important bug fixes


* Fri Mar 17 2017 Antoine Martin <antoine@xpra.org> 2.0-1
- dropped support for outdated OS and libraries (long list)
- 64-bit builds for MS Windows and MacOSX
- MS Windows MSYS2 based build system with fully up to date libraries
- MS Windows full support for named-pipe connections
- MS Windows and MacOSX support for mmap transfers
- more configurable mmap options to support KVM's ivshmem
- faster HTML5 client, now packaged separately (RPM only)
- clipboard synchronization support for the HTML5 client
- faster window scrolling detection, bandwidth savings
- support more screen bit depths: 8, 16, 24, 30 and 32
- support 10-bit per pixel rendering with the OpenGL client backend
- improved keyboard mapping support when sharing sessions
- faster native turbojpeg codec
- OpenGL enabled by default on more chipsets, with better driver sanity checks
- better handling of tablet input devices (multiple platforms and HTML5 client)
- synchronize Xkb layout group
- support stronger HMAC authentication digest modes
- unit tests are now executed automatically on more platforms
- fix python-lz4 0.9.0 API breakage
- fix html5 visual corruption with scroll paint packets


* Tue Dec 06 2016 Antoine Martin <antoine@xpra.org> 1.0-1
- SSL socket support
- IANA assigned default port 14500 (so specifying the TCP port is now optional)
- include a system-wide proxy server service on our default port, using system authentication
- MS Windows users can start a shadow server from the start menu, which is also accessible via http
- list all local network sessions exposed via mdns using xpra list-mdns
- the proxy servers can start new sessions on demand
- much faster websocket / http server for the HTML5 client, with SSL support
- much improved HTML client, including support for native video decoding
- VNC-like desktop support: "xpra start-desktop"
- pointer grabs using Shift+Menu, keyboard grabs using Control+Menu
- window scrolling detection for much faster compression
- server-side support for 10-bit colours
- better automatic encoding selection and video tuning, support H264 b-frames
- file transfer improvements
- SSH password input support on all platforms in launcher
- client applications can trigger window move and resize with MS Windows and Mac OS X clients
- geometry handling improvements, multi-monitor, fullscreen
- drag and drop support between application windows
- colour management synchronisation (and DPI, workspace, etc)
- the configuration file is now split into multiple logical parts, see /etc/xpra/conf.d
- more configuration options for printers
- clipboard direction restrictions
- webcam improvements: better framerate, device selection menu
- audio codec improvements, new codecs, mpeg audio
- reliable video support for all Debian and Ubuntu versions via private ffmpeg libraries
- use XDG_RUNTIME_DIR if possible, move more files to /run (sockets, log file)
- build and packaging improvements: minify during build: rpm "python2", netbsd v4l
- selinux policy for printing
- Mac OS X PKG installer now sets up ".xpra" file and "xpra:" URL associations
- Mac OS X remote shadow start support (though not all versions are supported)


* Mon Apr 18 2016 Antoine Martin <antoine@xpra.org> 0.17.0-1
- GStreamer 1.6.x on MS Windows and OSX
- opus is now the default sound codec
- microphone and speaker forwarding no longer cause sound loops
- new sound container formats: matroska, gdp
- much improved shadow servers, especially for OSX and MS Windows
- use newer Plink SSH with Windows Vista onwards
- OSX PKG installer, with file association
- libyuv codec for faster colourspace conversion
- NVENC v6, HEVC hardware encoding
- xvid mpeg4 codec
- shadow servers now expose a tray icon and menu
- improved tablet input device support on MS Windows
- improved window geometry handling
- OSX dock clicks now restore existing windows
- OSX clipboard synchronization menu
- new encryption backend: python-cryptography, hardware accelerated AES
- the dbus server can now be started automatically
- support for using /var/run on Linux and multiple sockets
- support for AF_VSOCK virtual networking
- broadcast sessions via mDNS on MS Windows and OSX
- window geometry fixes
- window close event is now configurable, automatically disconnects
- webcam forwarding (limited scope)
- SELinux policy improvements (still incomplete)
- new event based start commands: after connection / on connection
- split file authentication module
- debug logging and message improvements

* Wed Dec 16 2015 Antoine Martin <antoine@xpra.org> 0.16.0-1
- remove more legacy code, cleanups, etc
- switch to GStreamer 1.x on most platforms
- mostly gapless audio playback
- audio-video synchronization
- zero copy memoryview buffers (Python 2.7 and later), safer read-only buffers
- improved vp9 support
- handling of very high client resolutions (8k and above)
- more reliable window positioning and geometry
- enable OpenGL accelerated rendering by default on all platforms
- add more sanity checks to codecs and csc modules
- network and protocol improvements: safety checks, threading
- encryption improvements: support TCP only encryption, PKCS#7 padding
- improved printer forwarding
- improved DPI and anti-alias synchronization and handling
- better multi-monitor support
- support for screen capture tools (disabled by default)
- automatic desktop scaling to save bandwidth and CPU (upscale on client)
- support remote SSH start without specifying a display
- support multiple socket directories
- lz4 faster modes with automatic speed tuning
- server file upload from system tray
- new subcommand: "xpra showconfig"
- option to select a specific clibpoard to synchronize with (MS Windows only)
- faster OpenGL screen updates: group screen updates
- dbus server for easier runtime control
- replace calls to setxkbmap with native X11 API
- XShm for override-redirect windows and shadow servers
- faster X11 shadow servers
- XShape forwarding for X11 clients
- improved logging and debugging tools, fault injection
- more robust error handling and recovery from client errors
- NVENC support for MS Windows shadow servers

* Tue Apr 28 2015 Antoine Martin <antoine@xpra.org> 0.15.0-1
- printer forwarding
- functional HTML5 client
- add session idle timeout switch
- add html command line switch for easily setting up an HTML5 xpra server
- dropped support for Python 2.5 and older, allowing many code cleanups and improvements
- include manual in html format with MS Windows and OSX builds
- add option to control socket permissions (easier setup of containers)
- client log output forwarding to the server
- fixed workarea coordinates detection for MS Windows clients
- improved video region detection and handling
- more complete support for window states (keep above, below, sticky, etc..) and general window manager responsabilities
- allow environment variables passed to children to be specified in the config files
- faster reformatting of window pixels before compression stage
- support multiple delta regions and expire them (better compression)
- allow new child commands to be started on the fly, also from the client's system tray (disabled by default)
- detect mismatch between some codecs and their shared library dependencies
- NVENC SDK support for versions 4 and 5, YUV444 and lossless mode
- libvpx support for vp9 lossless mode, much improved performance tuning
- add support for child commands that do not interfere with "exit-with-children"
- add scaling command line and config file switch for controlling automatic scaling aggressiveness
- sound processing is now done in a separate process (lower latency, and more reliable)
- add more control over sound command line options, so sound can start disabled and still be turned on manually later
- add command line option for selecting the sound source (pulseaudio, alsa, etc)
- show sound bandwidth usage
- better window icon forwarding, especially for non X11 clients
- optimized OpenGL rendering for X11 clients
- handle screen update storms better
- window group-leader support on MS Windows (correct window grouping in the task bar)
- GTK3 port improvements (still work in progress)
- added unit tests which are run automatically during packaging
- more detailed information in xpra info (cursor, CPU, connection, etc)
- more detailed bug report information
- more minimal MS Windows and OSX builds

* Thu Aug 14 2014 Antoine Martin <antoine@xpra.org> 0.14.0-1
- support for lzo compression
- support for choosing the compressors enabled (lz4, lzo, zlib)
- support for choosing the packet encoders enabled (bencode, rencode, yaml)
- support for choosing the video decoders enabled
- built in bug report tool, capable of collecting debug information
- automatic display selection using Xorg "-displayfd"
- better video region support, increased quality for non-video regions
- more reliable exit and cleanup code, hooks and notifications
- prevent SSH timeouts on login password or passphrase input
- automatic launch the correct tool on MS Windows
- OSX: may use the Application Services folder for a global configuration
- removed python-webm, we now use the native cython codec only
- OpenCL: warn when AMD icd is present (causes problems with signals)
- better avahi mDNS error reporting
- better clipboard compression support
- better packet level network tuning
- support for input methods
- xpra info cleanups and improvments (show children, more versions, etc)
- integrated keyboard layout detection on *nix
- upgrade and shadow now ignore start child
- improved automatic encoding selection, also faster
- keyboard layout selection via system tray on *nix
- more Cython compile time optimizations
- some focus issues fixed

* Wed Aug 13 2014 Antoine Martin <antoine@xpra.org> 0.13.9-1
- fix clipboard on OSX
- fix remote ssh start with start-child issues
- use secure "compare_digest" if available
- fix crashes in codec cleanup
- fix video encoding fallback code
- fix fakeXinerama setup wrongly skipped in some cases
- fix connection failures with large screens and uncompressed RGB
- fix Ubuntu trustyi Xvfb configuration
- fix clipboard errors with no data
- fix opencl platform initialization errors

* Wed Aug 06 2014 Antoine Martin <antoine@xpra.org> 0.13.8-1
- fix server early exit when pulseaudio terminates
- fix SELinux static codec library label (make it persistent)
- fix missed auto-refresh when batching
- fix disabled clipboard packets coming through
- fix cleaner client connection shutdown sequence and exit code
- fix resource leak on connection error
- fix potential bug in fallback encoding selection
- fix deadlock on worker race it was meant to prevent
- fix remote ssh server start timeout
- fix avahi double free on exit
- fix png and jpeg painting via gdk pixbuf (when PIL is missing)
- fix webp refresh loops
- honour lz4-off environment variable
- fix proxy handling of raw RGB data for large screen sizes
- fix potential error from missing data in client packets

* Thu Jul 10 2014 Antoine Martin <antoine@xpra.org> 0.13.7-3
- fix x11 server pixmap memory leak
- fix speed and quality values range (1 to 100)
- fix nvenc device allocation errors
- fix unnecessary refreshes with nvenc
- fix "initenv" compatibility with older servers
- don't start child when upgrading or shadowing

* Tue Jun 17 2014 Antoine Martin <antoine@xpra.org> 0.13.6-3
- fix compatibility older versions of pygtk (centos5)
- fix compatibility with python 2.4 (centos5)
- fix AltGr workaround with win32 clients
- fix some missing keys with 'fr' keyboard layout (win32)
- fix installation on systems without python-glib (centos5)
- fix Xorg version detection for Fedora rawhide

* Sat Jun 14 2014 Antoine Martin <antoine@xpra.org> 0.13.5-3
- re-fix opengl compatibility

* Fri Jun 13 2014 Antoine Martin <antoine@xpra.org> 0.13.5-1
- fix use correct dimensions when evaluating video
- fix invalid latency statistics recording
- fix auto-refresh wrongly cancelled
- fix connection via nested ssh commands
- fix statically linked builds of swscale codec
- fix system tray icons when upgrading server
- fix opengl compatibility with older libraries
- fix ssh connection with shells not starting in home directory
- fix keyboard layout change forwarding

* Tue Jun 10 2014 Antoine Martin <antoine@xpra.org> 0.13.4-1
- fix numeric keypad period key mapping on some non-us keyboards
- fix client launcher GUI on OSX
- fix remote ssh start with clean user account
- fix remote shadow start with automatic display selection
- fix avoid scaling during resize
- fix changes of speed and quality via xpra control (make it stick)
- fix xpra info global batch statistics
- fix focus issue with some applications
- fix batch delay use

* Sun Jun 01 2014 Antoine Martin <antoine@xpra.org> 0.13.3-1
- fix xpra upgrade
- fix xpra control error handling
- fix window refresh on inactive workspace
- fix slow cursor updates
- fix error in rgb strict mode
- add missing x11 server type information

* Sun Jun 01 2014 Antoine Martin <antoine@xpra.org> 0.13.2-1
- fix painting of forwarded tray
- fix initial window workspace
- fix launcher with debug option in config file
- fix compilation of x265 encoder
- fix infinite recursion in cython csc module
- don't include sound utilities when building without sound

* Wed May 28 2014 Antoine Martin <antoine@xpra.org> 0.13.1-1
- honour lossless encodings
- fix avcodec2 build for Debian jessie and sid
- fix pam authentication module
- fix proxy server launched without a display
- fix xpra info data format (wrong prefix)
- fix transparency with png/L mode
- fix loss of transparency when toggling OpenGL
- fix re-stride code for compatibility with ancient clients
- fix timer reference leak causing some warnings

* Thu May 22 2014 Antoine Martin <antoine@xpra.org> 0.13.0-1
- Python3 / GTK3 client support
- NVENC module included in binary builds
- support for enhanced dummy driver with DPI option
- better build system with features auto-detection
- removed unsupported CUDA csc module
- improved buffer support
- faster webp encoder
- improved automatic encoding selection
- support running MS Windows installer under wine
- support for window opacity forwarding
- fix password mode in launcher
- edge resistance for automatic image downscaling
- increased default memory allocation of the dummy driver
- more detailed version information and tools
- stricter handling of server supplied values

* Fri May 16 2014 Antoine Martin <antoine@xpra.org> 0.12.6-1
- fix invalid pixel buffer size causing encoding failures
- fix auto-refresh infinite loop, and honour refresh quality
- fix sound sink with older versions of GStreamer plugins
- fix Qt applications crashes caused by a newline in xsettings..
- fix error with graphics drivers only supporting OpenGL 2.x only
- fix OpenGL crash on OSX with the Intel driver (now blacklisted)
- fix global menu entry text on OSX
- fix error in cairo backing cleanup
- fix RGB pixel data buffer size (re-stride as needed)
- avoid buggy swscale 2.1.0 on Ubuntu

* Sat May 03 2014 Antoine Martin <antoine@xpra.org> 0.12.5-1
- fix error when clients supply invalid screen dimensions
- fix MS Windows build without ffmpeg
- fix cairo backing alternative
- fix keyboard and sound test tools initialization and cleanup
- fix gcc version test used for enabling sanitizer build options
- fix exception handling in client when called from the launcher
- fix libav dependencies for Debian and Ubuntu builds

* Wed Apr 23 2014 Antoine Martin <antoine@xpra.org> 0.12.4-1
- fix xpra shadow subcommand
- fix xpra shadow keyboard mapping support for non-posix clients
- avoid Xorg dummy warning in log

* Wed Apr 09 2014 Antoine Martin <antoine@xpra.org> 0.12.3-1
- fix mispostioned windows
- fix quickly disappearing windows (often menus)
- fix server errors when closing windows
- fix NVENC server initialization crash with driver version mismatch
- fix rare invalid memory read with XShm
- fix webp decoder leak
- fix memory leak on client disconnection
- fix focus errors if windows disappear
- fix mmap errors on window close
- fix incorrect x264 encoder speed reported via "xpra info"
- fix potential use of mmap as an invalid fallback for video encoding
- fix logging errors in debug mode
- fix timer expired warning

* Sun Mar 30 2014 Antoine Martin <antoine@xpra.org> 0.12.2-1
- fix switching to RGB encoding via client tray
- fix remote server start via SSH
- fix workspace change detection causing slow screen updates

* Thu Mar 27 2014 Antoine Martin <antoine@xpra.org> 0.12.1-1
- fix 32-bit server timestamps
- fix client PNG handling on installations without PIL / Pillow

* Sun Mar 23 2014 Antoine Martin <antoine@xpra.org> 0.12.1-1
- NVENC support for YUV444 mode, support for automatic bitrate tuning
- NVENC and CUDA load balancing for multiple cards
- proxy encoding: ability to encode on proxy server
- fix fullscreen on multiple monitors via fakeXinerama
- OpenGL rendering improvements (for transparent windows, etc)
- support window grabs (drop down menus, etc)
- support specifying the SSH port number more easily
- enabled TCP_NODELAY socket option by default (lower latency)
- add ability to easily select video encoders and csc modules
- add local unix domain socket support to proxy server instances
- add "xpra control" commands to control encoding speed and quality
- improved handling of window resizing
- improved compatibility with command line tools (xdotool, wmctrl)
- ensure windows on other workspaces do not waste bandwidth
- ensure iconified windows do not waste bandwidth
- ensure maximized and fullscreen windows are prioritised
- ensure we reset xsettings when client disconnects
- better bandwidth utilization of jittery connections
- faster network code (larger receive buffers)
- better automatic encoding selection for smaller regions
- improved command line options (add ability to enable options which are disabled in the config file)
- trimmed all the ugly PyOpenGL warnings on startup
- much improved logging and debugging tools
- make it easier to distinguish xpra windows from local windows (border command line option)
- improved build system: smaller and more correct build output (much smaller OSX images)
- automatically stop remote shadow servers when client disconnects

* Tue Mar 18 2014 Antoine Martin <antoine@xpra.org> 0.11.6-1
- correct fix for system tray forwarding

* Tue Mar 18 2014 Antoine Martin <antoine@xpra.org> 0.11.5-1
- fix "xpra info" with bencoder
- ensure we re-sanitize window size hints when they change
- workaround applications with nonsensical size hints (ie: handbrake)
- fix 32-bit painting with GTK pixbuf loader (when PIL is not installed or disabled)
- fix system tray forwarding geometry issues
- fix workspace restore
- fix compilation warning
- remove spurious cursor warnings

* Sat Mar 01 2014 Antoine Martin <antoine@xpra.org> 0.11.4-1
- fix NVENC GPU memory leak
- fix video compatibility with ancient clients
- fix vpx decoding in ffmpeg decoders
- fix transparent system tray image with RGB encoding
- fix client crashes with system tray forwarding
- fix webp codec loader error handler

* Fri Feb 14 2014 Antoine Martin <antoine@xpra.org> 0.11.3-1
- fix compatibility with ancient versions of GTK
- fix crashes with malformed socket names
- fix server builds without client modules
- honour mdns flag set in config file
- blacklist VMware OpenGL driver which causes client crashes
- ensure all "control" subcommands run in UI thread

* Wed Jan 29 2014 Antoine Martin <antoine@xpra.org> 0.11.2-1
- fix Cython 0.20 compatibility
- fix OpenGL pixel upload alignment code
- fix xpra command line help page tokens
- fix compatibility with old versions of the python glib library

* Fri Jan 24 2014 Antoine Martin <antoine@xpra.org> 0.11.1-1
- fix compatibility with old/unsupported servers
- fix shadow mode
- fix paint issue with transparent tooltips on OSX and MS Windows
- fix pixel format typo in OpenGL logging

* Mon Jan 20 2014 Antoine Martin <antoine@xpra.org> 0.11.0-1
- NVENC hardware h264 encoding acceleration
- OpenCL and CUDA colourspace conversion acceleration
- proxy server mode for serving multiple sessions through one port
- support for sharing a TCP port with a web server
- server control command for modifying settings at runtime
- server exit command, which leaves Xvfb running
- publish session via mDNS
- OSX client two way clipboard support
- support for transparency with OpenGL window rendering
- support for transparency with 8-bit PNG modes
- support for more authentication mechanisms
- support remote shadow start via ssh
- support faster lz4 compression
- faster bencoder, rewritten in Cython
- builtin fallback colourspace conversion module
- real time frame latency graphs
- improved system tray forwarding support and native integration
- removed most of the Cython/C code duplication
- stricter and safer value parsing
- more detailed status information via UI and "xpra info"
- experimental HTML5 client
- drop non xpra clients with a more friendly response

* Tue Jan 14 2014 Antoine Martin <antoine@xpra.org> 0.10.12-1
- fix missing auto-refresh with lossy colourspace conversion
- fix spurious warning from Nvidia OpenGL driver
- fix OpenGL client crash with some drivers (ie: VirtualBox)
- fix crash in bencoder caused by empty data to encode
- fix ffmpeg2 h264 decoding (ie: Fedora 20+)
- big warnings about webp leaking memory
- generated debuginfo RPMs

* Tue Jan 07 2014 Antoine Martin <antoine@xpra.org> 0.10.11-1
- fix popup windows focus issue
- fix "xpra upgrade" subcommand
- fix server backtrace in error handler
- restore server target information in tray tooltip
- fix bencoder error with no-windows switch (missing encoding)
- add support for RGBX pixel format required by some clients
- avoid ffmpeg "data is not aligned" warning on client

* Wed Dec 04 2013 Antoine Martin <antoine@xpra.org> 0.10.10-1
- fix focus regression
- fix MS Windows clipboard copy including null byte
- fix h264 decoding with old versions of avcodec
- fix potential invalid read past the end of the buffer
- fix static vpx build arguments
- fix RGB modes exposed for transparent windows
- fix crash on clipboard loops: detect and disable clipboard
- support for ffmpeg version 2.x
- support for video encoding of windows bigger than 4k
- support video encoders that re-start the stream
- fix crash in decoding error path
- forward compatibility with namespace changes
- forward compatibility with the new generic encoding names

* Tue Nov 05 2013 Antoine Martin <antoine@xpra.org> 0.10.9-1
- fix h264 decoding of padded images
- fix plain RGB encoding with very old clients
- fix "xpra info" error when old clients are connected
- remove warning when "help" is specified as encoding

* Tue Oct 22 2013 Antoine Martin <antoine@xpra.org> 0.10.8-1
- fix misapplied patch breaking all windows with transparency

* Tue Oct 22 2013 Antoine Martin <antoine@xpra.org> 0.10.7-1
- fix client crash on Linux with AMD cards and fglrx driver
- fix missing WM_CLASS on X11 clients
- fix "xpra info" on shadow servers
- add usable 1366x768 dummy resolution

* Tue Oct 15 2013 Antoine Martin <antoine@xpra.org> 0.10.6-1
- fix window titles reverting to "unknown host"
- fix tray forwarding bug causing client disconnections
- replace previous rencode fix with warning

* Thu Oct 10 2013 Antoine Martin <antoine@xpra.org> 0.10.5-1
- fix client time out when the initial connection fails
- fix shadow mode
- fix connection failures when some system information is missing
- fix client disconnection requests
- fix encryption cipher error messages
- fix client errors when some features are disabled
- fix potential rencode bug with unhandled data types
- error out if the client requests authentication and none is available

* Tue Sep 10 2013 Antoine Martin <antoine@xpra.org> 0.10.4-2
- fix modifier key handling (was more noticeable with MS Windows clients)
- fix auto-refresh

* Fri Sep 06 2013 Antoine Martin <antoine@xpra.org> 0.10.3-2
- fix transient windows with no parent
- fix metadata updates handling (maximize, etc)

* Thu Aug 29 2013 Antoine Martin <antoine@xpra.org> 0.10.2-2
- fix connection error with unicode user name
- fix vpx compilation warning
- fix python 2.4 compatibility
- fix handling of scaling attribute via environment override
- build fix: ensure all builds include source information


* Tue Aug 20 2013 Antoine Martin <antoine@xpra.org> 0.10.1-1
- fix avcodec buffer pointer errors on some 32-bit Linux
- fix invalid time convertion
- fix OpenGL scaling with fractions
- compilation fix for some newer versions of libav
- honour scaling at high quality settings
- add ability to disable transparency via environment variable
- silence PyOpenGL warnings we can do nothing about
- fix CentOS 6.3 packaging dependencies

* Tue Aug 13 2013 Antoine Martin <antoine@xpra.org> 0.10.0-3
- performance: X11 shared memory (XShm) pixels transfers
- performance: zero-copy window pixels to picture encoders
- performance: zero copy decoded pixels to window (but not with OpenGL..)
- performance: multi-threaded x264 encoding and decoding
- support for speed tuning (latency vs bandwidth) with more encodings (png, jpeg, rgb)
- support for grayscale and palette based png encoding
- support for window and tray transparency
- support webp lossless
- support x264's "ultrafast" preset
- support forwarding of group-leader application window information
- prevent slow encoding from creating backlogs
- OpenGL accelerated client rendering enabled by default wherever supported
- register as a generic URL handler
- fullscreen toggle support
- stricter Cython code
- better handling of sound buffering and overruns
- experimental support for a Qt based client
- support for different window layouts with custom widgets
- don't try to synchronize with clipboards that do not exist (for shadow servers mostly)
- refactoring: move features and components to sub-modules
- refactoring: split X11 bindings from pure gtk code
- refactoring: codecs split encoding and decoding side
- refactoring: move more common code to utility classes
- refactoring: remove direct dependency on gobject in many places
- refactoring: platform code better separated
- refactoring: move wimpiggy inside xpra, delete parti
- export and expose more version information (x264/vpx/webp/PIL, OpenGL..)
- export compiler information with build (Cython, C compiler, etc)
- export much more debugging information about system state and statistics
- simplify non-UI subcommands and their packets, also use rencode ("xpra info", "xpra version", etc)

* Mon Jul 29 2013 Antoine Martin <antoine@xpra.org> 0.9.8-1
- fix client workarea size change detection (again)
- fix crashes handling info requests
- fix server hangs due to sound cleanup deadlock
- use lockless window video decoder cleanup (much faster)
- speedup server startup when no XAUTHORITY file exists yet

* Tue Jul 16 2013 Antoine Martin <antoine@xpra.org> 0.9.7-1
- fix error in sound cleanup code
- fix network threads accounting
- fix missing window icons
- fix client availibility of remote session start feature

* Sun Jun 30 2013 Antoine Martin <antoine@xpra.org> 0.9.6-1
- fix lost clicks on some popup menus (mostly with MS Windows clients)
- fix client workarea size change detection
- fix reading of unique "machine-id" on posix
- fix window reference leak for windows we fail to manage
- fix compatibility with pillow (PIL fork)
- fix session-info window graphs jumping (smoother motion)
- fix webp loading code for non-Linux posix systems
- fix window group-leader attribute setting
- fix man page indentation
- fix variable test vs use (correctness only)

* Thu Jun 06 2013 Antoine Martin <antoine@xpra.org> 0.9.5-1
- fix auto-refresh: don't refresh unnecessarily
- fix wrong initial timeout when ssh takes a long time to connect
- fix client monitor/resolution size change detection
- fix attributes reported to clients when encoding overrides are used
- Gentoo ebuild uses virtual to allow one to choose pillow or PIL

* Mon May 27 2013 Antoine Martin <antoine@xpra.org> 0.9.4-1
- revert cursor scaling fix which broke other applications
- fix auto refresh mis-firing
- fix type (atom) of the X11 visual property we expose

* Mon May 20 2013 Antoine Martin <antoine@xpra.org> 0.9.3-1
- fix clipboard for *nix clients
- fix selection timestamp parsing
- fix crash due to logging code location
- fix pixel area request dimensions for lossless edges
- fix advertized tray visual property
- fix cursors are too small with some applications
- fix crash when low level debug code is enabled
- reset cursors when disabling cursor forwarding
- workaround invalid window size hints

* Mon May 13 2013 Antoine Martin <antoine@xpra.org> 0.9.2-1
- fix double error when loading build information (missing about dialog)
- fix and simplify build "clean" subcommand
- fix OpenGL rendering alignment for padded rowstrides case
- fix potential double error when tray initialization fails
- fix window static properties usage

* Wed May 08 2013 Antoine Martin <antoine@xpra.org> 0.9.1-1
- honour initial client window's requested position
- fix for hidden appindicator
- fix string formatting error in non-cython fallback math code
- fix error if ping packets fail from the start
- fix for windows without a valid window-type (ie: shadows)
- fix OpenGL missing required feature detection (and add debug)
- add required CentOS RPM libXfont dependency
- tag our /etc configuration files in RPM spec file

* Thu Apr 25 2013 Antoine Martin <antoine@xpra.org> 0.9.0-1
- fix focus problems with old Xvfb display servers
- fix RPM SELinux labelling of static codec builds (CentOS)
- fix CentOS 5.x compatibility
- fix Python 2.4 and 2.5 compatibility (many)
- fix failed server upgrades killing the virtual display
- fix screenshot command with "OR" windows
- fix support "OR" windows that move and resize
- IPv6 server support
- support for many more audio codecs: flac, opus, wavpack, wav, speex
- support starting remote sessions with "xpra start"
- support for Xdummy with CentOS 6.4 onwards
- add --log-file command line option
- add clipboard regex string filtering
- add clipboard transfer in progress animation via system tray
- detect broken/slow connections and temporarily grey out windows
- reduce regular packet header sizes using numeric lookup tables
- allow more options in xpra config and launcher files
- safer test for windows to ignore (window IDs starts at 1 again)
- expose more version and statistical data via xpra info
- improved OpenGL client rendering (still disabled by default)
- upgrade to rencode 1.0.2

* Thu Mar 07 2013 Antoine Martin <antoine@xpra.org> 0.8.8-1
- fix server deadlock on dead connections
- fix compatibility with older versions of Python
- fix sound capture script usage via command line
- fix screen number preserve code
- fix error in logs in shadow mode

* Wed Feb 27 2013 Antoine Martin <antoine@xpra.org> 0.8.7-1
- fix x264 crash with older versions of libav
- fix 32-bit builds breakage introduce by python2.4 fix in 0.8.6
- fix missing sound forwarding when using the GUI launcher
- fix microphone forwarding errors
- fix client window properties store
- fix first workspace not preserved and other workspace issues

* Fri Feb 22 2013 Antoine Martin <antoine@xpra.org> 0.8.6-1
- fix python2.4 compatibility in icon grabbing code
- fix exit message location

* Sun Feb 17 2013 Antoine Martin <antoine@xpra.org> 0.8.5-1
- fix server crash with transient windows

* Wed Feb 13 2013 Antoine Martin <antoine@xpra.org> 0.8.4-1
- fix hello packet encoding bug
- fix colours in launcher and session-info windows

* Tue Feb 12 2013 Antoine Martin <antoine@xpra.org> 0.8.3-1
- Python 2.4 compatiblity fixes (CentOS 5.x)
- fix static builds of vpx and x264

* Sun Feb 10 2013 Antoine Martin <antoine@xpra.org> 0.8.2-1
- fix libav uninitialized structure crash
- fix warning on installations without sound libraries
- fix warning when pulseaudio utils are not installed
- fix delta compression race
- fix the return of some ghost windows
- stop pulseaudio on exit, warn if it fails to start
- re-enable system tray forwarding
- remove spurious "too many receivers" warnings

* Mon Feb 04 2013 Antoine Martin <antoine@xpra.org> 0.8.1-1
- fix server daemonize on some platforms
- fix server SSH support on platforms with old versions of glib
- fix "xpra upgrade" closing applications
- fix detection of almost-lossless frames with x264
- fix starting of a duplicate pulseaudio server on upgrade
- fix compatibility with older versions of pulseaudio (pactl)
- fix session-info window when a tray is being forwarded
- remove warning on builds with limited encoding support
- disable tray forwarding by default as it causes problems with some apps
- rename "Quality" to "Min Quality" in tray menu
- fix rpm packaging: remove unusable modules

* Thu Jan 31 2013 Antoine Martin <antoine@xpra.org> 0.8.0-9
- fix modal windows support
- fix default mouse cursor: now uses the client's default cursor
- fix short lived windows: avoid doing unnecessary work, avoid re-registering handlers
- fix limit the number of raw packets per client to prevent DoS via memory exhaustion
- fix authentication: ensure salt is per connection
- fix for ubuntu global application menus
- fix proxy handling of deadly signals
- fix pixel queue size calculations used for performance tuning decisions
- edge resistance for colourspace conversion level changes to prevent yoyo effect
- more aggressive picture quality tuning
- better CPU utilization
- new command line options and tray menu to trade latency for bandwidth
- x264 disable unecessary I-frames and avoid IDR frames
- performance and latency optimizations in critical sections
- avoid server loops: prevent the client from connecting to itself
- group windows according to the remote application they belong to
- sound forwarding (initial code, high latency)
- faster and more reliable client and server exit (from signal or otherwise)
- "xpra shadow" mode to clone an existing X11 display (compositors not supported yet)
- support for delta pixels mode (most useful for shadow mode)
- avoid warnings and X11 errors with the screenshot command
- better mouse cursor support: send cursors by name so their size matches the client's settings
- mitigate bandwidth eating cursor change storms: introduce simple cursor update batching
- support system tray icon forwarding (limited)
- preserve window workspace
- AES packet encryption for TCP mode (without key secure exchange for now)
- launcher entry box for username in SSH mode
- launcher improvements: highlight the password field if needed, prevent warnings, etc
- better window manager specification compatibility (for broken applications or toolkits)
- use lossless encoders more aggressively when possible
- new x264 tuning options: profiles to use and thresholds
- better detection of dead server sockets: retry and remove them if needed
- improved session information dialog and graphs
- more detailed hierarchical per-window details via "xpra info"
- send window icons in dedicated compressed packet (smaller new-window packets, faster)
- detect overly large main packets
- partial/initial Java/AWT keyboard support


* Mon Oct 08 2012 Antoine Martin <antoine@xpra.org> 0.7.0-1
- fix "AltGr" key handling with MS Windows clients (and others)
- fix crash with x264 encoding
- fix crash with fast disappearing tooltip windows
- avoid storing password in a file when using the launcher (except on MS Windows)
- many latency fixes and improvements: lower latency, better line congestion handling, etc
- lower client latency: decompress pictures in a dedicated thread (including rgb24+zlib)
- better launcher command feedback
- better automatic compression heuristics
- support for Xdummy on platforms with only a suid binary installed
- support for 'webp' lossy picture encoding (better and faster than jpeg)
- support fixed picture quality with x264, webp and jpeg (via command line and tray menu)
- support for multiple "start-child" options in config files or command line
- more reliable auto-refresh
- performance optimizations: caching results, avoid unnecessary video encoder re-initialization
- faster re-connection (skip keyboard re-configuration)
- better isolation of the virtual display process and child processes
- show performance statistics graphs on session info dialog (click to save)
- start with compression enabled, even for initial packet
- show more version and client information in logs and via "xpra info"
- client launcher improvements: prevent logging conflict, add version info
- large source layout cleanup, compilation warnings fixed

* Fri Oct 05 2012 Antoine Martin <antoine@xpra.org> 0.6.4-1
- fix bencoder to properly handle dicts with non-string keys
- fix swscale bug with windows that are too small by switch encoding
- fix locking of video encoder resizing leading to missing video frames
- fix crash with compression turned off: fix unicode encoding
- fix lack of locking sometimes causing errors with "xpra info"
- fix password file handling: exceptions and ignore carriage returns
- prevent races during setup and cleanup of network connections
- take shortcut if there is nothing to send

* Thu Sep 27 2012 Antoine Martin <antoine@xpra.org> 0.6.3-1
- fix memory leak in server after client disconnection
- fix launcher: clear socket timeout once connected and add missing options
- fix potential bug in network code (prevent disconnection)
- enable auto-refresh by default since we now use a lossy encoder by default

* Tue Sep 25 2012 Antoine Martin <antoine@xpra.org> 0.6.2-1
- fix missing key frames with x264/vpx: always reset the video encoder when we skip some frames (forces a new key frame)
- fix server crash on invalid keycodes (zero or negative)
- fix latency: isolate per-window latency statistics from each other
- fix latency: ensure we never record zero or even negative decode time
- fix refresh: server error was causing refresh requests to be ignored
- fix window options handling: using it for more than one value would fail
- fix video encoder/windows dimensions mismatch causing missing key frames
- fix damage options merge code (options were being squashed)
- ensure that small lossless regions do not cancel the auto-refresh timer
- restore protocol main packet compression and single chunk sending
- drop unnecessary OpenGL dependencies from some deb/rpm packages

* Fri Sep 14 2012 Antoine Martin <antoine@xpra.org> 0.6.1-1
- fix compress clipboard data (previous fix was ineffectual)

* Sat Sep 08 2012 Antoine Martin <antoine@xpra.org> 0.6.0-1
- fix launcher: don't block the UI whilst connecting, and use a lower timeout, fix icon lookup on *nix
- fix clipboard contents too big (was causing connection drops): try to compress them and just drop them if they are still too big
- x264 or vpx are now the default encodings (if available)
- compress rgb24 pixel data with zlib from the damage thread (rather than later in the network layer)
- better build environment detection
- experimental multi-user support (see --enable-sharing)
- better, more accurate "xpra info" statistics (per encoding, etc)
- tidy up main source directory
- simplify video encoders/decoders setup and cleanup code
- remove 'nogil' switch (as 'nogil' is much faster)
- test all socket types with automated tests

* Sat Sep 08 2012 Antoine Martin <antoine@xpra.org> 0.5.4-1
- fix man page typo
- fix non bash login shell compatibility
- fix xpra screenshot argument parsing error handling
- fix video encoding mismatch when switching encoding
- fix ssh mode on OpenBSD

* Wed Sep 05 2012 Antoine Martin <antoine@xpra.org> 0.5.3-1
- zlib compatibility fix: use chunked decompression when supported (newer versions)

* Wed Aug 29 2012 Antoine Martin <antoine@xpra.org> 0.5.2-1
- fix xpra launcher icon lookup on *nix
- fix big clipboard packets causing disconnection: just drop them instead
- fix zlib compression in raw packet mode: ensure we always flush the buffer for each chunk
- force disconnection after irrecoverable network parsing error
- fix window refresh: do not skip all windows after a hidden one!

* Mon Aug 27 2012 Antoine Martin <antoine@xpra.org> 0.5.1-6
- fix xpra_launcher
- build against rpmfusion repository, with build fix for Fedora 16

* Sat Aug 25 2012 Antoine Martin <antoine@xpra.org> 0.5.1-1
- fix DPI issue with Xdummy: set virtual screen to 96dpi by default
- avoid looping forever doing maths on 'infinity' value
- fix incomplete cloning of attributes causing default values to be used for batch configuration
- damage data queue batch factor was being calculated but not used
- ensure we update the data we use for calculations (was always using zero value)
- ensure "send_bell" is initialized before use
- add missing path string in warning message
- fix test code compatibility with older xpra versions
- statistics shown for 'damage_packet_queue_pixels' were incorrect

* Mon Aug 20 2012 Antoine Martin <antoine@xpra.org> 0.5.0-1
- new packet encoder written in C (much faster and data is now smaller too)
- read provided /etc/xpra/xpra.conf and user's own ~/.xpra/xpra.conf
- support Xdummy out of the box on platforms with recent enough versions of Xorg (and not installed suid)
- pass dpi to server and allow clients to specify dpi on the command line
- fix xsettings endianness problems
- fix clipboard tokens sent twice on start
- new command line options and UI to disable notifications forwarding, cursors and bell
- x264: adapt colourspace conversion, encoding speed and picture quality according to link and encoding/decoding performance
- automatically change video encoding: handle small region updates (ie: blinking cursor or spinner) without doing a full video frame refresh
- fairer window batching calculations, better performance over low latency links and bandwidth constrained links
- lower tcp socket connection timeout (10 seconds)
- better compression of cursor data
- log date and time with messages, better log messages (ie: "Ignoring ClientMessage..")
- send more client and server version information (python, gtk, etc)
- build cleanups: let distutils clean take care of removing all generated .c files
- code cleanups: move all win32 specific headers to win32 tree, fix vpx compilation warnings, whitespace, etc
- removed old "--no-randr" option
- drop compatibility with versions older than 0.3: we now assume the "raw_packets" feature is supported

* Mon Jul 23 2012 Antoine Martin <antoine@xpra.org> 0.4.0-1
- fix client application resizing its own window
- fix window dimensions hints not applied
- fix memleak in x264 cleanup code
- fix xpra command exit code (more complete fix)
- fix latency bottleneck in processing of damage requests
- fix free uninitialized pointers in video decoder initialization error codepath
- fix x264 related crash when resizing windows to one pixel width or height
- fix accounting of client decode time: ignore figure in case of decoding error
- fix subversion build information detection on MS Windows
- fix some binary packages which were missing some menu icons
- restore keyboard compatiblity code for MS Windows and OSX clients
- use padded buffers to prevent colourspace conversion from reading random memory
- release Python's GIL during vpx and x264 compression and colourspace conversion
- better UI launcher: UI improvements, detect encodings, fix standalone/win32 usage, minimize window once the client has started
- "xpra stop" disconnects all potential clients cleanly before exiting
- use memory aligned buffer for better performance with x264
- avoid vpx/x264 overhead for very small damage regions
- detect dead connection with ping packets: disconnect if echo not received
- force a full refresh when the encoding is changed
- more dynamic framerate performance adjustments, based on more metrics
- new menu option to toggle keyboard sync at runtime
- vpx/x264 runtime imports: detect broken installations and warn, but ignore when the codec is simply not installed
- enable environment debugging for damage batching via "XPRA_DEBUG_LATENCY" env variable
- simplify build by using setup file to generate all constants
- text clients now ignore packets they are not meant to handle
- removed compression menu since the default is good enough
- "xpra info" reports all build version information
- report server pygtk/gtk versions and show them on session info dialog and "xpra info"
- ignore dependency issues during sdist/clean phase of build
- record more statistics (mostly latency) in test reports
- documentation and logging added to code, moved test code out of main packages
- include distribution name in RPM version/filename
- CentOS 6 RPMs now depends on libvpx rather than a statically linked library
- CentOS static ffmpeg build with memalign for better performance
- no longer bundle parti window manager

* Tue Jul 10 2012 Antoine Martin <antoine@xpra.org> 0.3.3-1
- do not try to free the empty x264/vpx buffers after a decompression failure
- fix xpra command exit code (zero) when no error occurred
- fix Xvfb deadlock on shutdown
- fix wrongly removing unix domain socket on startup failure
- fix wrongly killing Xvfb on startup failure
- fix race in network code and meta data packets
- ensure clients use raw_packets if the server supports it (fixes 'gibberish' compressed packet errors)
- fix screen resolution reported by the server
- fix maximum packet size check wrongly dropping valid connections
- honour the --no-tray command line argument
- detect Xvfb startup failures and avoid taking over other displays
- don't record invalid placeholder value for "server latency"
- fix missing "damage-sequence" packet for sequence zero
- fix window focus with some Tk based application (ie: git gui)
- prevent large clipboard packets from causing the connection to drop
- fix for connection with older clients and server without raw packet support and rgb24 encoding
- high latency fix: reduce batch delay when screen updates slow down
- non-US keyboard layout fix
- correctly calculate min_batch_delay shown in statistics via "xpra info"
- require x264-libs for x264 support on Fedora

* Wed Jun 06 2012 Antoine Martin <antoine@xpra.org> 0.3.2-1
- fix missing 'a' key using OS X clients
- fix debian packaging for xpra_launcher
- fix unicode decoding problems in window title
- fix latency issue

* Tue May 29 2012 Antoine Martin <antoine@xpra.org> 0.3.1-1
- fix DoS in network connections setup code
- fix for non-ascii characters in source file
- log remote IP or socket address
- more graceful disconnection of invalid clients
- updates to the man page and xpra command help page
- support running the automated tests against older versions
- "xpra info" to report the number of clients connected
- use xpra's own icon for its own windows (about and info dialogs)

* Sun May 20 2012 Antoine Martin <antoine@xpra.org> 0.3.0-1
- zero-copy network code, per packet compression
- fix race causing DoS in threaded network protocol setup
- fix vpx encoder memory leak
- fix vpx/x264 decoding: recover from frame failures
- fix small per-window memory leak in server
- per-window update batching auto-tuning, which is fairer
- windows update batching now takes into account the number of pixels rather than just the number of regions to update
- support --socket-dir option over ssh
- IPv6 support using the syntax: ssh/::ffff:192.168.1.100/10 or tcp/::ffff:192.168.1.100/10000
- all commands now return a non-zero exit code in case of failure
- new "xpra info" command to report server statistics
- prettify some of the logging and error messages
- avoid doing most of the keyboard setup code when clients are in read-only mode
- automated regression and performance tests
- remove compatibility code for versions older than 0.1

* Fri Apr 20 2012 Antoine Martin <antoine@xpra.org> 0.2.1-1
- x264 and vpx video encoding support
- gtk3 and python 3 partial support (client only - no keyboard support)
- detect missing X11 server extensions and exit with error
- X11 vfb servers no longer listens on a TCP port
- clipboard fixes for Qt/KDE applications
- option for clients not to supply any keyboard mapping data (the server will no longer complain)
- show more system version information in session information dialog
- hide window decorations for openoffice splash screen (workaround)

* Wed Mar 21 2012 Antoine Martin <antoine@xpra.org> 0.1.0-1
- security: strict filtering of packet handlers until connection authenticated
- prevent DoS: limit number of concurrent connections attempting login (20)
- prevent DoS: limit initial packet size (memory exhaustion: 32KB)
- mmap: options to place sockets in /tmp and share mmap area across users via unix groups
- remove large amount of compatiblity code for older versions
- fix for Mac OS X clients sending hexadecimal keysyms
- fix for clipboard sharing and some applications (ie: Qt)
- notifications systems with dbus: re-connect if needed
- notifications: try not to interfere with existing notification services
- mmap: check for protected file access and ignore rather than error out (oops)
- clipboard: handle empty data rather than timing out
- spurious warnings: remove many harmless stacktraces/error messages
- detect and discard broken windows with invalid atoms, avoids vfb + xpra crash
- unpress keys all keys on start (if any)
- fix screen size check: also check vertical size is sufficient
- fix for invisible 0 by 0 windows: restore a minimum size
- fix for window dimensions causing enless resizing or missing window contents
- toggle cursors, bell and notifications by telling the server not to bother sending them, saves bandwidth
- build/deploy: don't modify file in source tree, generate it at build time only
- add missing GPL2 license file to show in about dialog
- Python 2.5: workarounds to restore support
- turn off compression over local connections (when mmap is enabled)
- clients can specify maximum refresh rate and screen update batching options

* Wed Feb 08 2012 Antoine Martin <antoine@xpra.org> 0.0.7.36-1
- fix clipboard bug which was causing Java applications to crash
- ensure we always properly disconnect previous client when new connection is accepted
- avoid warnings with Java applications, focus errors, etc

* Wed Feb 01 2012 Antoine Martin <antoine@xpra.org> 0.0.7.35-1
- ssh password input fix
- ability to take screenshots ("xpra screenshot")
- report server version ("xpra version")
- slave windows (drop down menus, etc) now move with their parent window
- show more session statistics: damage regions per second
- posix clients no longer interfere with the GTK/X11 main loop
- ignore missing properties when they are changed, and report correct source of the problem
- code style cleanups and improvements

* Thu Jan 19 2012 Antoine Martin <antoine@xpra.org> 0.0.7.34-1
- security: restrict access to run-xpra script (chmod)
- security: cursor data sent to the client was too big (exposing server memory)
- fix thread leak - properly this time, SIGUSR1 now dumps all threads
- off-by-one keyboard mapping error could cause modifiers to be lost
- pure python/cython method for finding modifier mappings (faster and more reliable)
- retry socket read/write after temporary error EINTR
- avoid warnings when asked to refresh windows which are now hidden
- auto-refresh was using an incorrect window size
- logging formatting fixes (only shown with logging on)
- hide picture encoding menu when mmap in use (since it is then ignored)

* Fri Jan 13 2012 Antoine Martin <antoine@xpra.org> 0.0.7.33-1
- readonly command line option
- correctly stop all network related threads on disconnection
- faster pixel data transfers for large areas
- fix auto-refresh jpeg quality
- fix potential exhaustion of mmap area
- fix potential race in packet compression setup code
- keyboard: better modifiers detection, synchronization of capslock and numlock
- keyboard: support all modifiers correctly with and without keyboard-sync option

* Wed Dec 28 2011 Antoine Martin <antoine@xpra.org> 0.0.7.32-1
- bug fix: disconnection could leave the server (and X11 server) in a broken state due to threaded UI calls
- bug fix: don't remove window focus when just any connection is lost, only when the real client goes away
- bug fix: initial windows should get focus (partial fix)
- support key repeat latency workaround without needing raw keycodes (OS X and MS Windows)
- command line switch to enable client side key repeat: "--no-keyboard-sync" (for high latency/jitter links)
- session info dialog: shows realtime connection and server details
- menu entry in system tray to raise all managed windows
- key mappings: try harder to unpress all keys before setting the new keymap
- key mappings: try to reset modifier keys as well as regular keys
- key mappings: apply keymap using Cython code rather than execing xmodmap
- key mappings: fire change callbacks only once when all the work is done
- use dbus for tray notifications if available, prefered to pynotify
- show full version information in about dialog

* Mon Nov 28 2011 Antoine Martin <antoine@xpra.org> 0.0.7.31-1
- threaded server for much lower latency
- fast memory mapped transfers for local connections
- adaptive damage batching, fixes window refresh
- xpra "detach" command
- fixed system tray for Ubuntu clients
- fixed maximized windows on Ubuntu clients

* Tue Nov 01 2011 Antoine Martin <antoine@xpra.org> 0.0.7.30-1
- fix for update batching causing screen corruption
- fix AttributeError jpegquality: make PIL (aka python-imaging) truly optional
- fix for jitter compensation code being a little bit too trigger-happy

* Wed Oct 26 2011 Antoine Martin <antoine@xpra.org> 0.0.7.29-2
- fix partial packets on boundary causing connection to drop (properly this time)

* Tue Oct 25 2011 Antoine Martin <antoine@xpra.org> 0.0.7.29-1
- fix partial packets on boundary causing connection to drop
- improve disconnection diagnostic messages
- scale cursor down to the client's default size
- better handling of right click on system tray icon
- posix: detect when there is no DISPLAY and error out
- support ubuntu's appindicator (yet another system tray implementation)
- remove harmless warnings about missing properties on startup

* Tue Oct 18 2011 Antoine Martin <antoine@xpra.org> 0.0.7.28-2
- fix password mode - oops

* Tue Oct 18 2011 Antoine Martin <antoine@xpra.org> 0.0.7.28-1
- much more efficient and backwards compatible network code, prevents a CPU bottleneck on the client
- forwarding of system notifications, system bell and custom cursors
- system tray menu to make it easier to change settings and disconnect
- automatically resize Xdummy to match the client's screen size whenever it changes
- PNG image compression support
- JPEG and PNG compression are now optional, only available if the Python Imaging Library is installed
- scale window icons before sending if they are too big
- fixed keyboard mapping for OSX and MS Windows clients
- compensate for line jitter causing keys to repeat
- fixed cython warnings, unused variables, etc

* Thu Sep 22 2011 Antoine Martin <antoine@xpra.org> 0.0.7.27-1
- compatibility fix for python 2.4 (remove "with" statement)
- slow down updates from windows that refresh continuously

* Tue Sep 20 2011 Antoine Martin <antoine@xpra.org> 0.0.7.26-1
- minor changes to support the Android client (work in progress)
- allow keyboard shortcuts to be specified, default is meta+shift+F4 to quit (disconnects client)
- clear modifiers when applying new keymaps to prevent timeouts
- reduce context switching in the network read loop code
- try harder to close connections cleanly
- removed some unused code, fixed some old test code

* Wed Aug 31 2011 Antoine Martin <antoine@xpra.org> 0.0.7.25-1
- Use xmodmap to grab the exact keymap, this should ensure all keys are mapped correctly
- Reset modifiers whenever we gain or lose focus, or when the keymap changes

* Mon Aug 15 2011 Antoine Martin <antoine@xpra.org> 0.0.7.24-1
- Use raw keycodes whenever possible, should fix keymapping issues for all Unix-like clients
- Keyboard fixes for AltGr and special keys for non Unix-like clients

* Wed Jul 27 2011 Antoine Martin <antoine@xpra.org> 0.0.7.23-2
- More keymap fixes..

* Wed Jul 20 2011 Antoine Martin <antoine@xpra.org> 0.0.7.23-1
- Try to use setxkbmap before xkbcomp to setup the matching keyboard layout
- Handle keyval level (shifted keys) explicitly, should fix missing key mappings
- More generic option for setting window titles
- Exit if the server dies

* Thu Jun 02 2011 Antoine Martin <antoine@xpra.org> 0.0.7.22-1
- minor fixes: jpeg, man page, etc

* Fri May 20 2011 Antoine Martin <antoine@xpra.org> 0.0.7.21-1
- ability to bind to an existing display with --use-display
- --xvfb now specifies the full command used. The default is unchanged
- --auto-refresh-delay does automatic refresh of idle displays in a lossless fashion

* Wed May 04 2011 Antoine Martin <antoine@xpra.org> 0.0.7.20-1
- more reliable fix for keyboard mapping issues

* Mon Apr 25 2011 Antoine Martin <antoine@xpra.org> 0.0.7.19-1
- xrandr support when running against Xdummy, screen resizes on demand
- fixes for keyboard mapping issues: multiple keycodes for the same key

* Mon Apr 4 2011 Antoine Martin <antoine@xpra.org> 0.0.7.18-2
- Fix for older distros (like CentOS) with old versions of pycairo

* Mon Mar 28 2011 Antoine Martin <antoine@xpra.org> 0.0.7.18-1
- Fix jpeg compression on MS Windows
- Add ability to disable clipboard code
- Updated man page

* Wed Jan 19 2011 Antoine Martin <antoine@xpra.org> 0.0.7.17-1
- Honour the pulseaudio flag on client

* Wed Aug 25 2010 Antoine Martin <antoine@xpra.org> 0.0.7.16-1
- Merged upstream changes.

* Thu Jul 01 2010 Antoine Martin <antoine@xpra.org> 0.0.7.15-1
- Add option to disable Pulseaudio forwarding as this can be a real network hog.
- Use logging rather than print statements.

* Tue May 04 2010 Antoine Martin <antoine@xpra.org> 0.0.7.13-1
- Ignore minor version differences in the future (must bump to 0.0.8 to cause incompatibility error)

* Tue Apr 13 2010 Antoine Martin <antoine@xpra.org> 0.0.7.12-1
- bump screen resolution

* Mon Jan 11 2010 Antoine Martin <antoine@xpra.org> 0.0.7.11-1
- first rpm spec file

###
### eof
###
