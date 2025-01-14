# This file is part of Xpra.
# Copyright (C) 2010-2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#we manage the scripts for multiple python versions,
#so don't mangle the shebangs:
%undefine __brp_mangle_shebangs
%undefine __pythondist_requires
%undefine __python_requires
#and don't add dependencies we don't need:
AutoReqProv: no
autoreq: no
autoprov: no
%global __requires_exclude ^(libnvjpeg|libnvidia-).*\\.so.*$
%global __requires_exclude %__requires_exclude|^/usr/bin/python.*$

#on RHEL, there is only one python>=3.10 build at present,
#so this package can use the canonical name 'xpra',
#but on Fedora, we only use the main package for the default python3
%global python3 python3
%global package_prefix xpra

%if "%{getenv:PYTHON3}" != ""
%global python3 %{getenv:PYTHON3}
%if 0%{?fedora}
%global package_prefix %{python3}-xpra
%endif
%define python3_sitelib %(%{python3} -Ic "from sysconfig import get_path; print(get_path('purelib').replace('/usr/local/', '/usr/'))" 2> /dev/null)
%define python3_sitearch %(%{python3} -Ic "from sysconfig import get_path; print(get_path('platlib').replace('/usr/local/', '/usr/'))" 2> /dev/null)
%endif

%define qt6 0
%define CFLAGS -O2
%define DEFAULT_BUILD_ARGS --with-Xdummy --without-Xdummy_wrapper --without-evdi --without-cuda_rebuild
%if 0%{?fedora}>=39
%global debug_package %{nil}
%endif
%if 0%{?fedora}
%define qt6 1
%define DEFAULT_BUILD_ARGS --with-Xdummy --without-Xdummy_wrapper --without-evdi --without-cuda_rebuild --with-qt6_client
%endif
%if 0%{?el10}
%define qt6 1
%global debug_package %{nil}
%define DEFAULT_BUILD_ARGS --without-evdi --without-cuda_rebuild --with-qt6_client --without-docs
%endif

%global gnome_shell_extension input-source-manager@xpra_org

%{!?nthreads: %global nthreads %(nproc)}
%{!?update_firewall: %define update_firewall 1}
%{!?run_tests: %define run_tests 0}
%{!?with_selinux: %define with_selinux 1}
%global selinux_variants mls targeted
%define selinux_modules cups_xpra xpra_socketactivation

%ifarch aarch64 riscv5
%{!?nthreads: %global nthreads 1}
%endif

Name:				%{package_prefix}
Version:			6.2.3
Summary:			Xpra gives you "persistent remote applications" for X.
Group:				Networking
License:			GPLv2+ and BSD and LGPLv3+ and MIT
URL:				https://xpra.org/
Packager:			Antoine Martin <antoine@xpra.org>
Vendor:				https://xpra.org/
Source:				https://xpra.org/src/xpra-%{version}.tar.xz
#grab the full revision number from the source archive's src_info.py file:
%define revision_no %(tar -OJxf %{SOURCE0} xpra-%{version}/xpra/src_info.py | sed 's/ //g' | grep -e "^REVISION=" | awk -F= '{print ".r"$2}' 2> /dev/null)
%define cuda_arch %(arch)
%{!?nvidia_codecs: %define nvidia_codecs %(pkg-config --exists cuda || pkg-config --exists cuda-%{cuda_arch} && echo 1)}
#Fedora 38+ cannot build the cuda kernels:
%if 0%{?fedora}>=38
%if 0%{nvidia_codecs}
%define fatbin %(tar -Jtf %{SOURCE0} xpra-%{version}/fs/share/xpra/cuda | grep .fatbin | wc -l 2> /dev/null)
#we can only include cuda if we have pre-built fatbin kernels:
%if 0%{fatbin}==0
%define nvidia_codecs 0
%endif
%endif
%endif
%if 0%{?nvidia_codecs}
%define build_args %{DEFAULT_BUILD_ARGS}
%else
%define build_args %{DEFAULT_BUILD_ARGS} --without-nvidia
%endif

Release:			10%{revision_no}%{?dist}
#rpm falls over itself if we try to make the top-level package noarch:
#BuildArch: noarch
BuildRoot:			%{_tmppath}/%{package_prefix}-%{version}-root
BuildRequires:		tar
BuildRequires:		grep
BuildRequires:		gawk
BuildRequires:		gcc
%if 0%{?fedora}>=40
BuildRequires:		clang
%endif
BuildRequires:		gcc-c++
BuildRequires:		%{python3}-cython
BuildRequires:		pkgconfig
BuildRequires:		%{python3}-setuptools
BuildRequires:		coreutils
Requires:			xpra-html5 >= 5
Requires:			xpra-filesystem >= 5
Requires:			%{package_prefix}-common = %{version}-%{release}
Requires:			%{package_prefix}-codecs = %{version}-%{release}
Recommends:			%{package_prefix}-codecs-extra = %{version}-%{release}
Recommends:			%{package_prefix}-codecs-nvidia = %{version}-%{release}
Recommends:			%{package_prefix}-x11 = %{version}-%{release}
Requires:			%{package_prefix}-client = %{version}-%{release}
Requires:			%{package_prefix}-client-gtk3 = %{version}-%{release}
Requires:			%{package_prefix}-server = %{version}-%{release}
Recommends:			%{package_prefix}-audio = %{version}-%{release}
Suggests:           %{package_prefix}-client-qt6 = %{version}-%{release}
Conflicts:			python3-xpra < 6
Obsoletes:			python3-xpra < 6
%if "%{package_prefix}"!="xpra"
Provides:           xpra = %{version}-%{release}
%endif
%description
Xpra gives you "persistent remote applications" for X. That is, unlike normal X applications, applications run with xpra are "persistent" -- you can run them remotely, and they don't die if your connection does. You can detach them, and reattach them later -- even from another computer -- with no loss of state. And unlike VNC or RDP, xpra is for remote applications, not remote desktops -- individual applications show up as individual windows on your screen, managed by your window manager. They're not trapped in a box.

So basically it's screen for remote X apps.

This metapackage installs the %{python3} build of xpra in full,
including the python client, server and HTML5 client.


%package -n xpra-filesystem
Summary:			Common filesystem files for all xpra packages
BuildArch:          noarch
Requires(post):     coreutils
%if 0%{?fedora}
#installs selinux policy:
Requires(post):		policycoreutils
Requires(preun):    policycoreutils
%endif
Conflicts:			xpra < 6
Conflicts:			python3-xpra < 6
%description -n xpra-filesystem
This package contains the files (mostly configuration files and top level scripts)
which are shared between all installations of xpra.
This package is independent of the python version used.


%package -n %{package_prefix}-common
Summary:			Common files for xpra packages
Group:				Networking
Requires(pre):		shadow-utils
Conflicts:			xpra < 6
Obsoletes:			xpra-common-client < 6
Obsoletes:			xpra-common-server < 6
%if ! 0%{?el10}
BuildRequires:		pandoc
%endif
BuildRequires:		which
Requires:			%{python3}
Requires:			%{python3}-gobject
Recommends:         xpra-filesystem >= 5
Recommends:         lsb_release
Recommends:			%{python3}-pillow
Recommends:			%{python3}-cryptography
Recommends:			%{python3}-netifaces
Recommends:			%{python3}-dbus
Recommends:			%{python3}-dns
Recommends:			%{python3}-paramiko
Suggests:			%{python3}-kerberos
Suggests:			%{python3}-gssapi
Suggests:			%{python3}-ldap
Suggests:			%{python3}-ldap3
Suggests:           %{python3}-cpuinfo
Recommends:			%{python3}-aioquic
%if 0%{?el9}%{?el10}
Recommends:			%{python3}-avahi
%endif
%if 0%{?fedora}
Recommends:			%{python3}-zeroconf
%endif
BuildRequires:		pkgconfig(liblz4)
Requires:			lz4-libs
BuildRequires:		xxhash-devel
Requires:			xxhash-libs
BuildRequires:		pkgconfig(libbrotlidec)
BuildRequires:		pkgconfig(libbrotlienc)
Recommends:			brotli
%if ! 0%{?el10}
BuildRequires:		pkgconfig(libqrencode)
%endif
Recommends:			qrencode
BuildRequires:		%{python3}-gobject
BuildRequires:		pkgconfig(pygobject-3.0)
BuildRequires:		pkgconfig(py3cairo)
BuildRequires:		pkgconfig(gtk+-3.0)
BuildRequires:		pkgconfig(gobject-introspection-1.0)
%if 0%{?run_tests}
BuildRequires:		%{python3}-cryptography
BuildRequires:		%{python3}-numpy
%endif
%description -n %{package_prefix}-common
This package contains the files which are shared between the xpra client and server packages.


%package -n %{package_prefix}-codecs
Summary:			Picture and video codecs for xpra clients and servers.
Suggests:			%{package_prefix}-codecs-extra
Suggests:			%{package_prefix}-codecs-nvidia
Requires:			%{package_prefix}-common = %{version}-%{release}
Requires:			%{python3}-pillow
BuildRequires:		pkgconfig(libdrm)
Requires:			libdrm
BuildRequires:		pkgconfig(vpx)
Requires:			libvpx
Obsoletes:          libvpx-xpra < 1.8
BuildRequires:		pkgconfig(libwebp)
Requires:			libwebp
BuildRequires:		pkgconfig(libturbojpeg)
Requires:			turbojpeg
BuildRequires:		pkgconfig(libyuv)
Requires:			libyuv
%ifnarch %{riscv}
BuildRequires:		pkgconfig(openh264)
Requires:			openh264
%endif
%if 0%{?fedora}
BuildRequires:		pkgconfig(spng)
BuildRequires:		zlib-devel
Requires:			libspng
%endif
#not available yet:
#BuildRequires:		libevdi-devel
#Requires:			libevdi
#this is a downstream package - it should not be installed:
Conflicts:			xpra-codecs-freeworld
%description -n %{package_prefix}-codecs
This package contains extra picture and video codecs used by xpra clients and servers.


%package -n %{package_prefix}-codecs-extras
Summary:			Extra picture and video codecs for xpra clients and servers.
Requires:			%{package_prefix}-codecs = %{version}-%{release}
%if ! 0%{?el10}
%ifnarch riscv64
Recommends:			x264
BuildRequires:		pkgconfig(x264)
Requires:			libavif
BuildRequires:		pkgconfig(libavif)
%endif
%endif
#for gstreamer video encoder and decoder:
Recommends:			gstreamer1
Recommends:			python3-gstreamer1
#appsrc, videoconvert:
Recommends:			gstreamer1-plugins-base
#vaapi:
Recommends:			gstreamer1-vaapi
#strangely conflicts with 'mesa-va-drivers' instead of replacing it:
Suggests:			mesa-va-drivers-freeworld
#x264:
Recommends:			gstreamer1-plugins-ugly
#av1:
Recommends:			gstreamer1-plugins-bad-free-extras
#pipewire:
Recommends:			pipewire-gstreamer
%description -n %{package_prefix}-codecs-extras
This package contains extra picture and video codecs used by xpra clients and servers.
These codecs may have patent or licensing issues.


%if 0%{?nvidia_codecs}
%package -n %{package_prefix}-codecs-nvidia
Summary:			Picture and video codecs that rely on NVidia GPUs and CUDA.
BuildRequires:		cuda
Requires:			%{package_prefix}-codecs = %{version}-%{release}
Requires:			%{python3}-pycuda
Recommends:			%{python3}-pynvml
%description -n %{package_prefix}-codecs-nvidia
This package contains the picture and video codecs that rely on NVidia GPUs and CUDA,
this is used by both xpra clients and servers.
%endif


%package -n %{package_prefix}-audio
Summary:			%{python3} build of xpra audio support
Conflicts:			python3-xpra-audio < 6
Obsoletes:			python3-xpra-audio < 6
Requires:			%{package_prefix}-common = %{version}-%{release}
Requires:			gstreamer1
Requires:			gstreamer1-plugins-base
Requires:			gstreamer1-plugins-good
Recommends:			gstreamer1-plugin-timestamp
Recommends:			gstreamer1-plugins-bad
Recommends:			gstreamer1-plugins-ugly
Recommends:			gstreamer1-plugins-ugly-free
Recommends:			pulseaudio
Recommends:			pulseaudio-module-x11
Recommends:			pulseaudio-utils
%if 0%{?run_tests}
BuildRequires:		gstreamer1
BuildRequires:		gstreamer1-plugins-good
BuildRequires:		pulseaudio
BuildRequires:		pulseaudio-utils
%endif
%description -n %{package_prefix}-audio
This package contains audio support for xpra.


%package -n %{package_prefix}-client
Summary:			xpra client
Conflicts:			python3-xpra-client < 6
Obsoletes:			python3-xpra-client < 6
Requires:			%{package_prefix}-common = %{version}-%{release}
BuildRequires:		desktop-file-utils
Requires(post):		desktop-file-utils
Requires(postun):   shared-mime-info
Requires(postun):	desktop-file-utils
Recommends:			%{python3}-cups
Recommends:		    %{python3}-pysocks
Recommends:         NetworkManager-libnm
Suggests:			sshpass
%description -n %{package_prefix}-client
This package contains the xpra client.


%package -n %{package_prefix}-client-gtk3
Summary:			GTK3 xpra client
Requires:			%{package_prefix}-client = %{version}-%{release}
Requires:			gtk3
Requires:           %{python3}-cairo
Requires(post):     coreutils
Requires(postun):   gtk-update-icon-cache
Requires(posttrans): gtk-update-icon-cache
Recommends:			%{package_prefix}-codecs = %{version}-%{release}
Recommends:			%{package_prefix}-x11 = %{version}-%{release}
Recommends:			pinentry
Recommends:			%{package_prefix}-audio
Recommends:			%{python3}-pyopengl
Recommends:			%{python3}-pyu2f
Recommends:         %{python3}-psutil
Suggests:			sshpass
Suggests:           %{package_prefix}-client-gnome
%if 0%{?run_tests}
%if 0%{?fedora}
BuildRequires:		xclip
%endif
%endif
%description -n%{package_prefix}-client-gtk3
This package contains the GTK3 xpra client.


%if %{qt6}
%package -n %{package_prefix}-client-qt6
Summary:			Experimental xpra Qt6 client
Requires:			%{package_prefix}-client = %{version}-%{release}
Requires:			%{python3}-pyqt6
%description -n%{package_prefix}-client-qt6
This package contains an experimental client using the Qt6 toolkit.
%endif


%package -n %{package_prefix}-client-gnome
Summary:			Gnome integration for the xpra client
Requires:			%{package_prefix}-client-gtk3 = %{version}-%{release}
%if 0%{?el8}
# sadly removed from Fedora and RHEL9
Requires:			gnome-shell-extension-topicons-plus
Requires(post):     gnome-shell
%else
Requires:			gnome-shell-extension-appindicator
Requires(post):		gnome-shell-extension-common
%endif
%description -n%{package_prefix}-client-gnome
This package installs the GNOME Shell extensions
that can help in restoring the system tray functionality.
It also includes the %{gnome_shell_extension} extension which
is required for querying and activating keyboard input sources.


%package -n %{package_prefix}-x11
Summary:			X11 bindings
BuildRequires:		pkgconfig(xkbfile)
BuildRequires:		pkgconfig(xtst)
BuildRequires:		pkgconfig(xcomposite)
BuildRequires:		pkgconfig(xdamage)
BuildRequires:		pkgconfig(xres)
BuildRequires:		pkgconfig(xfixes)
BuildRequires:		pkgconfig(xrandr)
Requires:			%{package_prefix}-common = %{version}-%{release}
Requires:			libxkbfile
Requires:			libXtst
Requires:			libXcomposite
Requires:			libXdamage
Requires:			libXres
Requires:			libXfixes
Requires:			libXrandr
Requires:			gtk3
%if 0%{?fedora}
Suggests:			xmodmap
Suggests:			xrandr
Recommends:			xrdb
%else
%if ! 0%{?el10}
Requires:			xorg-x11-server-utils
%endif
%endif
%if 0%{?el10}
Requires:			weston
Requires:			xorg-x11-server-Xwayland
%else
Requires:			xorg-x11-drv-dummy
%endif
Requires:			xorg-x11-xauth
Recommends:			xterm
Recommends:			mesa-dri-drivers
Recommends:         %{python3}-lxml
%description -n %{package_prefix}-x11
This package contains the x11 bindings


%package -n %{package_prefix}-server
Summary:			xpra server
Conflicts:			python3-xpra-server < 6
Obsoletes:			python3-xpra-server < 6
Requires:			%{package_prefix}-common = %{version}-%{release}
Requires:			gtk3
Recommends:			%{package_prefix}-x11 = %{version}-%{release}
Recommends:			%{package_prefix}-client = %{version}-%{release}
Recommends:			%{package_prefix}-codecs = %{version}-%{release}
Recommends:			%{package_prefix}-codecs-extra = %{version}-%{release}
Recommends:			%{package_prefix}-codecs-nvidia = %{version}-%{release}
Recommends:			cups-filters
Recommends:			cups-pdf
Recommends:			%{python3}-cups
Recommends:			dbus-x11
Recommends:			gtk3-immodule-xim
Recommends:			%{python3}-setproctitle
Recommends:			librsvg2
Recommends:			ibus
Recommends:			%{python3}-pyxdg
Recommends:         %{python3}-watchdog
Recommends:			xdg-menu
Suggests:			tcp_wrappers-libs
Suggests:			%{python3}-ldap3
Suggests:			%{python3}-ldap
Suggests:			%{python3}-oauthlib
%if 0%{?fedora}%{?el10}
# looks like they forgot to expose the pkgconfig?
BuildRequires:		procps-ng-devel
%else
BuildRequires:		pkgconfig(libprocps)
%endif
# unfortunately, there are no python prefixed cups packages:
%if "%{python3}"=="python3"
BuildRequires:		%{python3}-cups
%endif
BuildRequires:		pkgconfig(libsystemd)
BuildRequires:		checkpolicy
BuildRequires:		selinux-policy-devel
BuildRequires:		pam-devel
%if ! 0%{?el10}
#for detecting the path to the Xorg binary (not the wrapper):
BuildRequires:		xorg-x11-server-Xorg
%endif
Requires:			selinux-policy
Requires(post):		openssl
%if 0%{update_firewall}
Requires(post):		firewalld
%endif
Requires(post):		systemd
Requires(post):		systemd-units
Requires(preun):	systemd-units
Requires(postun):	systemd-units
Recommends:			redhat-menus
Recommends:			gnome-menus
Recommends:			gnome-icon-theme
#allows the server to use software opengl:
Recommends:			mesa-libOSMesa
%if 0%{?run_tests}
BuildRequires:		dbus-x11
BuildRequires:		dbus-tools
BuildRequires:		tigervnc
BuildRequires:		xorg-x11-server-Xvfb
BuildRequires:		xorg-x11-drv-dummy
BuildRequires:		%{python3}-pyxdg
%endif
Requires(post):		/usr/sbin/semodule, /usr/sbin/semanage, /sbin/restorecon, /sbin/fixfiles
Requires(postun):	/usr/sbin/semodule, /usr/sbin/semanage, /sbin/restorecon, /sbin/fixfiles
%description -n %{package_prefix}-server
This package contains the xpra server.


%prep
#sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
#if [ "${sha256}" != "ffff" ]; then
#	echo "invalid checksum for %{SOURCE0}"
#	exit 1
#fi
rm -rf $RPM_BUILD_DIR/xpra-%{version}
xzcat $RPM_SOURCE_DIR/xpra-%{version}.tar.xz | tar -xf -

%debug_package


%build
pushd xpra-%{version}
rm -rf build install
# set pkg_config_path for xpra video libs:
export BUILD_TYPE="RPM"
CFLAGS="%{CFLAGS}" LDFLAGS="%{?LDFLAGS} -Wl,--as-needed" %{python3} setup.py build \
	-j %{nthreads} \
	%{build_args} \
	--without-printing --without-cuda_kernels

%if 0%{?with_selinux}
for mod in %{selinux_modules}
do
	pushd fs/share/selinux/${mod}
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
pushd xpra-%{version}
export BUILD_TYPE="RPM"
%{python3} setup.py install \
	%{build_args} \
	--prefix /usr --skip-build --root %{buildroot}
%if 0%{?fedora}
#on Fedora, we can have multiple python builds:
%if "%{python3}"!="python3"
#the 'xpra' script should always use the default python interpreter,
#use a prefixed copy for other python3 builds:
cp %{buildroot}/usr/bin/xpra %{buildroot}/usr/bin/%{package_prefix}
%endif
#make sure the shebang is the canonical one,
#no matter which python3 was used for building the package:
sed -i '1s=^#!/usr/bin/\(python\|env python\)[0-9.]*=#!/usr/bin/env python3=' %{buildroot}/usr/bin/xpra
sed -i '1s=^#!/usr/bin/\(python\|env python\)[0-9.]*=#!/usr/bin/env python3=' %{buildroot}/usr/bin/xpra_launcher
%endif
%if 0%{?with_selinux}
for mod in %{selinux_modules}
do
	for selinuxvariant in %{selinux_variants}
	do
	  install -d %{buildroot}%{_datadir}/selinux/${selinuxvariant}
	  install -p -m 644 fs/share/selinux/${mod}/${mod}.pp.${selinuxvariant} \
	    %{buildroot}%{_datadir}/selinux/${selinuxvariant}/${mod}.pp
	done
done
%endif
popd

#fix permissions on shared objects
find %{buildroot}%{python3_sitearch}/xpra -name '*.so' -exec chmod 0755 {} \;

#remove the tests, not meant to be installed in the first place
#(but I can't get distutils to play nice: I want them built, not installed)
rm -fr ${RPM_BUILD_ROOT}/%{python3_sitearch}/unittests
rm -fr ${RPM_BUILD_ROOT}%{python3_sitearch}/UNKNOWN-*.egg-info


%clean
rm -rf $RPM_BUILD_ROOT

%files
#meta package

%files -n %{package_prefix}-client-gnome
%{_datadir}/gnome-shell/extensions/%{gnome_shell_extension}/COPYING
%{_datadir}/gnome-shell/extensions/%{gnome_shell_extension}/README.md
%{_datadir}/gnome-shell/extensions/%{gnome_shell_extension}/extension.js
%{_datadir}/gnome-shell/extensions/%{gnome_shell_extension}/metadata.json

%files -n xpra-filesystem
%defattr(-,root,root)
%{_bindir}/xpra*
%{_bindir}/run_scaled*
%{_prefix}/lib/cups/backend/xpraforwarder
%if ! 0%{?el10}
%{_docdir}/xpra
%endif
%{_datadir}/xpra/README.md
%{_datadir}/xpra/COPYING
%{_datadir}/xpra/icons
%{_datadir}/xpra/images
%{_datadir}/xpra/*.wav
%{_datadir}/man/man1/xpra*.1*
%{_datadir}/man/man1/run_scaled.1*
%{_datadir}/metainfo/xpra.appdata.xml
%{_datadir}/icons/xpra.png
%{_datadir}/icons/xpra-mdns.png
%{_datadir}/icons/xpra-shadow.png
%dir %{_sysconfdir}/xpra
%config(noreplace) %{_sysconfdir}/sysconfig/xpra
%config %{_prefix}/lib/tmpfiles.d/xpra.conf
%config %{_prefix}/lib/sysusers.d/xpra.conf
%config %{_sysconfdir}/pam.d/xpra
# the xpra config:
%config %{_sysconfdir}/xpra/xpra.conf
%config %{_sysconfdir}/xpra/conf.d/05_features.conf
%config %{_sysconfdir}/xpra/conf.d/10_network.conf
%config %{_sysconfdir}/xpra/conf.d/12_ssl.conf
%config %{_sysconfdir}/xpra/conf.d/15_file_transfers.conf
%config %{_sysconfdir}/xpra/conf.d/16_printing.conf
%config %{_sysconfdir}/xpra/conf.d/20_audio.conf
%config %{_sysconfdir}/xpra/conf.d/30_picture.conf
%config %{_sysconfdir}/xpra/conf.d/35_webcam.conf
%config %{_sysconfdir}/xpra/conf.d/40_client.conf
%config %{_sysconfdir}/xpra/conf.d/42_client_keyboard.conf
%config %{_sysconfdir}/xpra/conf.d/50_server_network.conf
%config %{_sysconfdir}/xpra/conf.d/55_server_x11.conf
%config %{_sysconfdir}/xpra/conf.d/60_server.conf
%config %{_sysconfdir}/xpra/conf.d/65_proxy.conf
%if 0%{?nvidia_codecs}
%config(noreplace) %{_sysconfdir}/xpra/cuda.conf
%config(noreplace) %{_sysconfdir}/xpra/*.keys
%endif
%config(noreplace) %{_sysconfdir}/X11/xorg.conf.d/90-xpra-virtual.conf
%config(noreplace) %{_sysconfdir}/xpra/xorg.conf
%config(noreplace) %{_sysconfdir}/xpra/xorg-uinput.conf
%config %{_sysconfdir}/xpra/content-type/*
%config %{_sysconfdir}/xpra/content-categories/*
%config %{_sysconfdir}/xpra/content-parent/*
%config %{_sysconfdir}/xpra/http-headers/*
%if 0%{?with_selinux}
%{_datadir}/selinux/*/*.pp
%endif

%files -n %{package_prefix}-common
%if 0%{?fedora}
%if "%{python3}"!="python3"
%{_bindir}/%{package_prefix}
%endif
%endif
%{python3_sitearch}/xpra/buffers/
%{python3_sitearch}/xpra/clipboard/
%{python3_sitearch}/xpra/gstreamer/
%{python3_sitearch}/xpra/notifications/
%{python3_sitearch}/xpra/codecs/argb/
%{python3_sitearch}/xpra/codecs/pillow/
%{python3_sitearch}/xpra/util/
%pycached %{python3_sitearch}/xpra/*.py
%pycached %{python3_sitearch}/xpra/codecs/__init__.py
%pycached %{python3_sitearch}/xpra/codecs/checks.py
%pycached %{python3_sitearch}/xpra/codecs/constants.py
%pycached %{python3_sitearch}/xpra/codecs/debug.py
%pycached %{python3_sitearch}/xpra/codecs/icon_util.py
%pycached %{python3_sitearch}/xpra/codecs/image.py
%pycached %{python3_sitearch}/xpra/codecs/loader.py
%pycached %{python3_sitearch}/xpra/codecs/rgb_transform.py
%pycached %{python3_sitearch}/xpra/codecs/video.py
%{python3_sitearch}/xpra/dbus/
%{python3_sitearch}/xpra/gtk/
%{python3_sitearch}/xpra/keyboard/
%{python3_sitearch}/xpra/net/
%{python3_sitearch}/xpra/opengl/
%{python3_sitearch}/xpra/platform/
%{python3_sitearch}/xpra/scripts/
%{python3_sitearch}/xpra-*.egg-info

%files -n %{package_prefix}-x11
%{python3_sitearch}/xpra/x11/

%files -n %{package_prefix}-codecs
%{python3_sitearch}/xpra/codecs/csc_cython
%{python3_sitearch}/xpra/codecs/drm
#/xpra/codecs/evdi
%{python3_sitearch}/xpra/codecs/jpeg
%{python3_sitearch}/xpra/codecs/libyuv
%{python3_sitearch}/xpra/codecs/v4l2
%{python3_sitearch}/xpra/codecs/vpx
%{python3_sitearch}/xpra/codecs/webp
%ifnarch %{riscv}
%{python3_sitearch}/xpra/codecs/openh264
%endif
%if 0%{?fedora}
%{python3_sitearch}/xpra/codecs/spng
%endif

%files -n %{package_prefix}-codecs-extras
%ifnarch %{riscv}
%if ! 0%{?el10}
%{python3_sitearch}/xpra/codecs/x26?
%{python3_sitearch}/xpra/codecs/avif
%endif
%endif
%{python3_sitearch}/xpra/codecs/gstreamer

%if 0%{?nvidia_codecs}
%files -n %{package_prefix}-codecs-nvidia
%{_datadir}/xpra/cuda
%{python3_sitearch}/xpra/codecs/nvidia
%endif

%files -n %{package_prefix}-audio
%{python3_sitearch}/xpra/audio/

%files -n %{package_prefix}-client
%{python3_sitearch}/xpra/client/auth/
%{python3_sitearch}/xpra/client/base/
%pycached %{python3_sitearch}/xpra/client/__init__.py

%if %{qt6}
%files -n %{package_prefix}-client-qt6
%{python3_sitearch}/xpra/client/qt6/
%endif

%files -n %{package_prefix}-client-gtk3
%{python3_sitearch}/xpra/client/gui/
%{python3_sitearch}/xpra/client/gtk3/
%{python3_sitearch}/xpra/client/mixins/
%{_libexecdir}/xpra/xpra_signal_listener
%{_datadir}/applications/xpra-launcher.desktop
%{_datadir}/applications/xpra-gui.desktop
%{_datadir}/applications/xpra.desktop
%{_datadir}/mime/packages/application-x-xpraconfig.xml
%{_datadir}/xpra/autostart.desktop

%files -n %{package_prefix}-server
%{python3_sitearch}/xpra/server
%{python3_sitearch}/xpra/codecs/proxy
%{_sysconfdir}/dbus-1/system.d/xpra.conf
/lib/systemd/system/xpra.service
/lib/systemd/system/xpra.socket
%{_prefix}/lib/udev/rules.d/71-xpra-virtual-pointer.rules
%{_datadir}/xpra/css
%{_datadir}/applications/xpra-shadow.desktop
%{_libexecdir}/xpra/xdg-open
%{_libexecdir}/xpra/gnome-open
%{_libexecdir}/xpra/gvfs-open
%{_libexecdir}/xpra/auth_dialog
%{_libexecdir}/xpra/xpra*

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
pushd xpra-%{version}
XPRA_BIN_DIR="`pwd`/fs/bin/"
XPRA_COMMAND="${XPRA_BIN_DIR}/xpra"
XPRA_CONF_DIR="`pwd`/fs/etc/xpra"
pushd tests/unittests
PYTHONPATH="%{python3_sitearch}:%{buildroot}%{python3_sitearch}:`pwd`" \
PATH="${XPRA_BIN_DIR}:$PATH" \
XPRA_COMMAND="${XPRA_COMMAND}" \
XPRA_CONF_DIR="${XPRA_CONF_DIR}" \
XPRA_TEST_COVERAGE=0 \
GDK_BACKEND=x11 \
%{python3} ./unit/run.py
popd
popd
%endif


%post -n xpra-filesystem
/bin/chmod 700 /usr/lib/cups/backend/xpraforwarder
%if 0%{?with_selinux}
restorecon -R /usr/lib/cups/backend/xpraforwarder || :
%endif
%tmpfiles_create xpra.conf
%sysusers_create xpra.conf
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
%endif

%post -n %{package_prefix}-server
%{python3} /usr/bin/xpra setup-ssl > /dev/null
%if 0%{update_firewall}
ZONE=`firewall-offline-cmd --get-default-zone 2> /dev/null`
if [ ! -z "${ZONE}" ]; then
	set +e
	firewall-cmd --zone=${ZONE}	--list-ports | grep "14500/tcp" >> /dev/null 2>&1
	if [ $? != "0" ]; then
		firewall-cmd --zone=${ZONE} --add-port=14500/tcp --permanent >> /dev/null 2>&1
		if [ $? == "0" ]; then
			firewall-cmd --reload | grep -v "^success"
		else
			firewall-offline-cmd --add-port=14500/tcp | grep -v "^success"
		fi
	fi
	firewall-cmd --zone=${ZONE}	--list-ports | grep "14500/udp" >> /dev/null 2>&1
	if [ $? != "0" ]; then
		firewall-cmd --zone=${ZONE} --add-port=14500/udp --permanent >> /dev/null 2>&1
		if [ $? == "0" ]; then
			firewall-cmd --reload | grep -v "^success"
		else
			firewall-offline-cmd --add-port=14500/udp | grep -v "^success"
		fi
	fi
	set -e
fi
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

%preun -n %{package_prefix}-server
if [ $1 -eq 0 ] ; then
	/bin/systemctl daemon-reload >/dev/null 2>&1 || :
	/bin/systemctl disable xpra.service > /dev/null 2>&1 || :
	/bin/systemctl disable xpra.socket > /dev/null 2>&1 || :
	/bin/systemctl stop xpra.service > /dev/null 2>&1 || :
	/bin/systemctl stop xpra.socket > /dev/null 2>&1 || :
fi

%postun -n %{package_prefix}-server
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

%preun -n xpra-filesystem
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

%post -n %{package_prefix}-client
/usr/bin/update-mime-database &> /dev/null || :

%postun -n %{package_prefix}-client
/usr/bin/update-mime-database &> /dev/null || :

%post -n %{package_prefix}-client-gtk3
/usr/bin/update-desktop-database &> /dev/null || :
/bin/touch --no-create %{_datadir}/icons/hicolor &>/dev/null || :

%post -n %{package_prefix}-client-gnome
#try to enable it for active users:
for uid in `ls /run/user/`; do
    if [ "$uid" == "0" ]; then
        continue
    fi
    BUS="/run/user/$uid/bus"
    if [ -S "${BUS}" ]; then
%if 0%{?el8}
sudo -i -u "#$uid" DBUS_SESSION_BUS_ADDRESS="unix:path=$BUS" gnome-shell-extension-tool -e TopIcons@phocean.net  &>/dev/null || :
sudo -i -u "#$uid" DBUS_SESSION_BUS_ADDRESS="unix:path=$BUS" gnome-shell-extension-tool -e %{gnome_shell_extension}  &>/dev/null || :
%else
sudo -i -u "#$uid" DBUS_SESSION_BUS_ADDRESS="unix:path=$BUS" gnome-extensions enable appindicatorsupport@rgcjonas.gmail.com  &>/dev/null || :
sudo -i -u "#$uid" DBUS_SESSION_BUS_ADDRESS="unix:path=$BUS" gnome-extensions enable %{gnome_shell_extension}  &>/dev/null || :
%endif
    fi
done

%posttrans -n %{package_prefix}-client-gtk3
/usr/bin/gtk-update-icon-cache %{_datadir}/icons/hicolor &>/dev/null || :

%postun -n %{package_prefix}-client-gtk3
/usr/bin/update-desktop-database &> /dev/null || :
if [ $1 -eq 0 ] ; then
	/bin/touch --no-create %{_datadir}/icons/hicolor &>/dev/null
	/usr/bin/gtk-update-icon-cache %{_datadir}/icons/hicolor &>/dev/null || :
fi


%changelog
* Tue Jan 14 2025 Antoine Martin <antoine@xpra.org> 6.2.3-10
- Platforms, build and packaging:
   pillow 11.1.0
   `exe` installer standalone step
   handle diverging RHEL clone packaging behaviour
   move default package list for newer build script default
   invalid refresh rate detected on some MS Windows configurations
   normalize smooth scroll wheel values on macos
- RHEL 10 builds:
   package Qt6 client
   use `weston` + `Xwayland` as xvfb on RHEL 10
   provide wrapper script for `weston` + `Xwayland`
   replace `noopenh264` with `openh264`
   `AlmaLinux` `10-kitten` package list
   `CentOS` `stream10` package list
- Major:
   Network Manager API errors in some environments
   websocket connection loss with some proxies sending empty payloads
   handle broken `pyopengl-accelerate` installations more gracefully
   keyboard layout group regression
- Encodings:
   batch delay increase compounded
   avoid damage storms: switch to full frames earlier
- Clipboard:
   always claim the clipboard selection when updated
   always update the peer when the owner changes
   remote clipboard option not honoured on some platorms
   allow all clipboards by default
- Desktop mode:
   better compatibility with some window managers when resizing
   handle fixed size desktops correctly
- Minor:
   toolbox examples do not run on some platforms
   `configure` tool incorrectly saves some options
   hide 'configure shadow server' on light builds
   typo in `nvjpeg` encoder / decoder build switches
   `libexec` scripts installed twice
   icon glob lookup mismatch
   division by zero on MS Windows
   update keyboard layout mapping for `ku` and `ir`
   avoid lowering quality for `text` content type, avoid scaling and subsampling
   avoid potential logging loop
   close splash screen on server start error
- Cosmetic:
   `openh264` license tag
   remove outdated Wayland clipboard warning
   typo
   strict mode type mismatch
   incorrect compression debug logging
   incorrect damage elapsed time in debug logging

* Tue Dec 10 2024 Antoine Martin <antoine@xpra.org> 6.2.2-10
- Platforms, build and packaging:
   MSYS2 aarch64 build fix and prefix detection
   RPM support for per arch pkgconfig
   missing SVG loader on MS Windows
   loaders cache not populated on MS Windows
   `install-repo` file permission on Debian
   record which repository is targeted
   `libproxy` support for MS Windows clients
   `PyOpenGL 3.1.8` + force upgrade
   missing MacOS AES library
   support providing build arguments using environment
   syntax errors in the MS Windows build setup script
   `openh264` 2.5.0
   `python-pillow` 11.0.0
   require `clang++` for building CUDA kernels on some Debian distributions + fixup
   `install-dev` to honour Xdummy flag
- SBOM:
   SBOM support on MS Windows
   record for CUDA
   record 'Light' builds
   export to JSON
   record pip packages
- Encodings:
   honour `openh264` maximum dimensions
   `rgb` errors at unusual bit depths
   10 bits per channel issues: use pillow, detect alpha channel correctly and encode it properly
- System Tray Menu:
   options disabled once 'auto' is selected
   speed tuning disabled
- Major:
   authentication options not honoured with some bind options
   disable workspace support on MS Windows to prevent crashes
   `start-gui` fails if no application is selected
   prevent padded image overflows
   `xpra top` corrupted output
   `vsock` connection errors
   printing errors on MS Windows
   use symlinks to prevent ssh agent forwarding setup errors
- Minor:
   clamp 'vrefresh' to a useful range
   `quic` connections are safe for authentication
- Cosmetic:
   add missing autentication modules to documentation
   add `pyopenssl` to dependencies documentation
   unnecessary import
   broken OpenGL drivers documentation link
   handle missing pillow more gracefully
   show full icondata error
   proxy error messages formatting

* Tue Oct 29 2024 Antoine Martin <antoine@xpra.org> 6.2.1-10
- System tray:
   paint errors with `mmap` mode
   distorted paints
- Major:
   OpenGL errors with MS Windows clients missing stderr
   keycode mapping for Wayland clients
   some windows not shown when there is a tray window being forwarded
   connection failures on some server platforms
- Minor:
   quality and speed options can be used with generic encodings
   check `pam_start` return value in `pam` authentication module
   `install-repo` support for Debian and Ubuntu derivatives
- Cosmetic:
   show which client backend values are acceptable
   log OpenGL probe errors
   date in changelog
   add Ubuntu `oracular` support to `install-repo` subcommand
   border color parsing deprecation warning

* Wed Oct 09 2024 Antoine Martin <antoine@xpra.org> 6.2-10
- Platforms, build and packaging:
   pycuda for Fedora 41
   move `opengl` module to top level
   re-enable cython csc module
- Fixes:
   AES padding
- Features:
   PoC PyQt6 client
   `minimal` command line switch
   option to completely disable all of GStreamer
   strongly enforce disabled subsystems
   watch for start menu file changes reliably, on all platforms
   improve transient and permanent hardware codec failures differently
   continue to remove GTK
   guess initial server display resolution
- Network:
   multi-processing proxy server with SSL
   more control commands for proxy instances
   inline more data in network packets
   SSL setup made easy

* Thu Jul 18 2024 Antoine Martin <antoine@xpra.org> 6.1-10
- Platforms, build and packaging:
   RHEL 10 builds
   make it easier to setup a development environment and to install the repositories
- Encodings:
   faster scaling of subsampled images without OpenGL
   zero-copy drawing without OpenGL
   scale YUV before converting to RGB
   full range video compression
   GPU checks from a containerized environment
   colorspace fixes
- Network:
   WebTransport server
   QUIC fast-open
- Features:
   handle display scaling correctly on more platforms
   use native file chooser on some platforms
   support custom window grouping
   optional username verification for authentication modules
   resize virtual display to a specific resolution only
   filter environment exposed to xvfb subcommand
- Cosmetic:
   many type hints added
   linter warnings fixed


* Thu Apr 25 2024 Antoine Martin <antoine@xpra.org> 6.0-10
- Platforms, build and packaging:
   require and take advantage of Python 3.10+
   cythonize everything and build test on git push
   workaround for distributions incompatible with CUDA
   add `xpra-client-gnome` package
   use the system provided xxHash library
   riscv64 builds
   PEP 517: pyproject.toml
- Features:
   OpenGL core profile
   `xpra configure` tool
   faster `mmap`
   make it easier to disable almost everything
   remove legacy compatibility
   try harder to locate the correct xauth file
   honour MacOS backing scale factor with OpenGL
   workspace support for MS Windows 10
   readonly memoryviews
- Network:
   abstract sockets
   wait for local server sockets to become available
   enable websocket upgrades without the html5 client
   update ssh agent to active user
   use libnm to access network information
   ssl auto upgrade
   honour `/etc/ssh/ssh_config`
   `xpra list-clients`
- Cosmetic:
   silence warnings: #4023, #2177, #3988, #4028
   easier call tracing
   PEP 8: code style
- Documentation:
   ivshmem
   subsystems
   authentication handlers
   record some SBOM data

* Sat Aug 19 2023 Antoine Martin <antoine@xpra.org> 5.0-10
- Major improvements:
   QUIC transport
   split packaging
   freedesktop screencast / remotedesktop
   ease of use: easier basic commands, open html5 client, disable all audio features
- Platforms, build and packaging:
   Python 3.12 installations
   replace Python2 builds
   LTS feature deprecation
   stricter type checks
   more MacOS workarounds
- Server:
   try harder to find a valid menu prefix
   exit with windows
   side buttons with MS Windows shadow servers
   mirror client monitor layout
   side buttons with MS Windows shadow servers
- Client:
   allow keyboard shortcuts in readonly mode
   show decoder statistics
   keyboard layout switching shortcut
   layout switching detection for MS Windows
   mirror mouse cursor when sharing
- Minor:
   generic exec authentication module
   audio `removesilence`
   make pulseaudio real-time and high-priority scheduling modes configurable
   use urrlib for parsing
   GTK removal progress
   documentation updates and fixes: broken links, typos
- Network:
   smaller handshake packet
   SSL auto-upgrade
   better IPv6
   new packet format
   ssh agent forwarding automatic switching when sharing
   use libnm to query network devices
   exclude more user data by default
- Encodings:
   use intra refresh
   `stream` encoding for desktop mode
   GStreamer codecs

* Sat Oct 01 2022 Antoine Martin <antoine@xpra.org> 4.4-10
- Platforms, build and packaging:
   Native LZ4 bindings
   Safer native brotli bindings
   Native qrencode bindings
   openSUSE build tweaks, Fedora 37, Oracle Linux / Rocky Linux / Alma Linux / CentOS Stream : 8 and 9
   Debian finally moved to `libexec`
   MS Windows taskbar integration
   SSH server support on MS Windows, including starting shadow sessions
- Server:
   Configurable vertical refresh rate
   Virtual Monitors
   Multi-monitor desktop mode
   Expand an existing desktop
   Exit with windows
   Full shadow keyboard mapping
   xwait subcommand
   guess content-type from parent pid
   cups print backend status report
   Override sockets on upgrade
   Allow additional options to X server invocation
   Control commands for modifying command environment and read only flag
   Start new commands via a proxy server's SSH listener
- Shadow server:
   Geometry restrictions
   Shadow specific applications
- Client:
   Automatic keyboard grabs
   Pointer confinement
   Faster window initial data
   Improved DPI detection on MS Windows
   Show all current keyboard shortcuts
   Preserve all options when reconnecting
   Option to accept SSL mismatched host permanently
   Forward all command line options
   Smooth scrolling options
   Per-window scaling - experimental
   Workaround Wayland startup hangs
- Security and authentication:
   Configurable information disclosure
   Keycloak authentication
   Capability based authentication
   Authentication for web server scripts
   OTP authentication
   Workaround paramiko `No existing session` error
- Encodings and latency:
   Option to cap picture quality
   Expose scaling quality
   NVJPEG decoder
   AVIF encoding
   selective `scroll` encoding detection
- Network:
   SOCKS proxy connection support
   SSH agent forwarding
   SSH workarounds for polluted stream premable
   proxy network performance improvement
- Misc:
   easier xpra subcommand invocation
- Refactoring and preparation for the next LTS release:
   Feature deprecation
   Remove "app menus" support
   Remove ancient complicated code
   Simplify the build file
   More robust info handlers
   Remove scary warnings
   f-strings

* Wed Dec 08 2021 Antoine Martin <antoine@xpra.org> 4.3-10
- Platforms, build and packaging:
   arm64 support #3291, including nvenc and nvjpeg: #3378
   non-system header builds (eg: conda): #3360
   fixed MacOS shadow start via ssh: #3343
   parallel builds: #3255
   don't ship too may pillow plugins: #3133
   easier access to documentation: #3015
   Python 3.10 buffer api compatibility: #3031
- Misc:
   make it easier to silence OpenGL validation warnings: #3380
   don't wait for printers: #3170
   make it easier to autostart: #3134
   'clean' subcommand: #3099
   flexible 'run_scaled' subcommand: #3303
   more flexible key shortcuts configuration: #3183
- Encodings and latency:
   significant latency and performance improvements: #3337
   spng decoder #3373 and encoder: #3374
   jpeg with transparency: #3367
   faster argb module: #3361
   faster nvjpeg module using CUDA, add transparency: #2984
   faster xshape scaling: #1226
   downscale jpeg and webp: #3333
   disable av-sync for applications without audio: #3351
   opaque region support: #3317
   show FPS on client window: #3311
   nvenc to use the same device context as nvjpeg: #3195
   nvenc disable unsupported presets: #3136
- Network:
   make it easier to use SSL: #3299
   support more AES modes: GCM, CFB and CTR, #3247
   forked rencodeplus encoder: #3229
- Server:
   shadow specific areas or monitors: #3320
   faster icon lookup: #3326
   don't trust _NET_WM_PID: #3251
   move all sessions to a sub-directory: #3217
   more reliable server cleanup: #3218
   better VNC support: #3256
   more seamless server upgrades: #541
   source /etc/profile: #3083
   switch input method to ibus: #2359

* Tue May 18 2021 Antoine Martin <antoine@xpra.org> 4.2-1
- use pinentry for password prompts and ssh prompts
- nvjpeg encoder
- gui for starting remote sessions
- new subcommands: `recover`, `displays`, `list-sessions`, `clean-displays`, `clean-sockets`
- many fixes:
   window initial position
   focus issues
   non-opengl paint corruption
   slow rendering on MacOS
   handle smooth scroll events with wayland clients
   always lossless screen updates for terminals
   clipboard timeout
   peercred auth options
- support multiple clients using mmap simultaneously with non-default file paths
- only synchronize xsettings with seamless servers
- automatic desktop scaling is now disabled
- workaround for gnome applications starting slowly (documentation)

* Sat Feb 27 2021 Antoine Martin <antoine@xpra.org> 4.1-1
- Overhauled container based build system
- Splash screen
- `run_scaled` utility script
- Client:
   header bar option for window control menu
   generate a qrcode to connect
   show all keyboard shortcuts
   progress bar for file transfers
   GTK cairo backend support for more native bit depths
   disable xpra's keyboard shortcuts from the system tray menu
   automatically include the server log in bug reports
- OpenGL client backend:
   render at fixed bit depths with the `pixel-depth` option
   support more bit depths
- Clipboard:
   MacOS support for images, more text formats, etc
   MS Windows support for images
   wayland clients
- Server:
   faster server startup
   `xpra list-windows` subcommand
   new window control commands: move / resize and map / unmap
   remote logging from server to client
   support window re-stacking
- `xpra top`:
   show pids, shortcuts
   more details in the list view
   show speed and quality
- Display:
   bumped maximum resolution beyond 8K
   set the initial resolution more easily using the 'resize-display' option
- Encoding:
   server side picture downscaling
   libva hardware accelerated encoding
   NVENC 30-bit accelerated encoding
   vpx 30-bit
   x264 30-bit
   faster 30-bit RGB subsampling
   scroll encoding now handled more generically
   black and white mode
- Network:
   IGD / UPNP
   SO_KEEPALIVE option
   clients can be queried and controlled using local sockets
   specify connection attributes using the connection string
   nested SSH tunnels
   websocket header modules
   specify the socket type with socket activation
   expose the packet flush flag
   `xpra shell` subcommand for interacting with processes in real time
   custom group sockets directory permissions and name
- Testing:
   better test coverage
   cleanup output

* Sun May 10 2020 Antoine Martin <antoine@xpra.org> 4.0-1
- Drop support for:
   Python 2, GTK2
   legacy versions (pre 1.0)
   weak authentication
- Network, per socket options:
   authentication and encryption
   ssl
   ssh
   bind options for client
- make it easier to send files from the server
- xpra toolbox subcommand
- xpra help subcommand
- xpra top new features
- faster startup
- signal handling fixes
- smoother window resizing
- refactoring and testing
   unit tests coverage and fixes
   completely skip loading unused features at runtime
   get rid of capabilities data after parsing it
   better module dependency separation
   don't convert to a string before we need it
- more useful window and tray title
- make it easier to source environment
- disable desktop animations in desktop mode
- automatic start-or-upgrade, automatic X11 display rescue
- support MS Windows OpenSSH server to start shadow
- more selective use of OpenGL acceleration in client
- expose server OpenGL capabilities
- cleaner HTML5 syntax

* Tue Mar 19 2019 Antoine Martin <antoine@xpra.org> 3.0-1
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
