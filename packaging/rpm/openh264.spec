%define _disable_source_fetch 0

# Build openh264 as a *private* library for Xpra: install it under a private
# library directory with a privately-named soname so that it can coexist with
# the distribution 'openh264' / 'noopenh264' packages instead of conflicting
# with, obsoleting or providing them.
# See https://github.com/Xpra-org/xpra/issues/4626
%global xpra_soname     libopenh264-xpra.so.8
%global xpra_libdir     %{_libdir}/xpra

Name:           xpra-openh264
Version:        2.6.0
Release:        2
Summary:        Private H.264 codec library for Xpra
License:        BSD-2-Clause
URL:            https://www.openh264.org/
Source0:        https://github.com/cisco/openh264/archive/v%{version}/openh264-%{version}.tar.gz

BuildRequires:  gcc-c++
BuildRequires:  make
BuildRequires:  nasm

%description
OpenH264 is a codec library which supports H.264 encoding and decoding. It is
suitable for use in real time applications such as WebRTC.

This is a private build for Xpra: the shared library is installed under
%{xpra_libdir} with a private soname (%{xpra_soname}) so that it neither
provides, conflicts with, nor obsoletes the distribution openh264 packages.


%package        devel
Summary:        Development files for %{name}
Requires:       %{name}%{?_isa} = %{version}-%{release}

%description    devel
The %{name}-devel package contains headers and pkg-config metadata for
building Xpra codec modules against the private openh264 build.


%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "558544ad358283a7ab2930d69a9ceddf913f4a51ee9bf1bfb9e377322af81a69" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi

%if 0%{?fedora}
echo "**********************************************************************"
echo "*** WARNING: the private 'xpra-openh264' package is for RHEL only. ***"
echo "*** Fedora should use the 'fedora-cisco-openh264' repo instead.    ***"
echo "*** Sleeping for 20 seconds so you can abort this build.           ***"
echo "**********************************************************************"
sleep 20
%endif

%setup -q -n openh264-%{version}

cat > %{name}.pc << EOF
libdir=%{xpra_libdir}
includedir=%{_includedir}/%{name}

Name: %{name}
Description: Private openh264 build for Xpra
Version: %{version}
Cflags: -I%{_includedir}/%{name}
Libs: -L%{xpra_libdir} -lopenh264-xpra -Wl,-rpath,%{xpra_libdir}
EOF


%build
# Update the makefile with our build options
# Must be done in %%build in order to pick up correct LDFLAGS.
sed -i -e 's|^CFLAGS_OPT=.*$|CFLAGS_OPT=%{optflags}|' Makefile
sed -i -e 's|^PREFIX=.*$|PREFIX=%{_prefix}|' Makefile
sed -i -e 's|^LIBDIR_NAME=.*$|LIBDIR_NAME=%{_lib}|' Makefile
sed -i -e 's|^SHAREDLIB_DIR=.*$|SHAREDLIB_DIR=%{_libdir}|' Makefile
sed -i -e '/^CFLAGS_OPT=/i LDFLAGS=%{__global_ldflags}' Makefile

# build with a private soname so the resulting library never collides with the
# distribution openh264 - this is what makes it safe to load alongside it:
make %{?_smp_mflags} SHLDFLAGS="-Wl,-soname,%{xpra_soname}"


%install
%make_install

# Remove static libraries
rm $RPM_BUILD_ROOT%{_libdir}/*.a

# Turn this into a private build: the shared object was already built with a
# private soname (see %%build); move it into the private library directory under
# that soname, add a matching development symlink, and relocate the headers
# under a private include directory. Everything that openh264 installed into the
# public locations is then removed, so this package provides nothing in the
# 'openh264' namespace.
mkdir -p $RPM_BUILD_ROOT%{xpra_libdir}
reallib=`find $RPM_BUILD_ROOT%{_libdir} -maxdepth 1 -type f -name 'libopenh264.so.*'`
mv "${reallib}" $RPM_BUILD_ROOT%{xpra_libdir}/%{xpra_soname}
ln -sf %{xpra_soname} $RPM_BUILD_ROOT%{xpra_libdir}/libopenh264-xpra.so
rm -f $RPM_BUILD_ROOT%{_libdir}/libopenh264.so*
rm -f $RPM_BUILD_ROOT%{_libdir}/pkgconfig/openh264.pc
mkdir -p $RPM_BUILD_ROOT%{_includedir}/%{name}
mv $RPM_BUILD_ROOT%{_includedir}/wels $RPM_BUILD_ROOT%{_includedir}/%{name}/
mkdir -p $RPM_BUILD_ROOT%{_libdir}/pkgconfig
cp -a %{name}.pc $RPM_BUILD_ROOT%{_libdir}/pkgconfig/


%files
%license LICENSE
%doc README.md
%dir %{xpra_libdir}
%{xpra_libdir}/%{xpra_soname}

%files devel
%{_includedir}/%{name}
%{xpra_libdir}/libopenh264-xpra.so
%{_libdir}/pkgconfig/%{name}.pc


%changelog
* Fri Jun 12 2026 Antoine Martin <antoine@xpra.org> - 2.6.0-2
- #4626 build as a private 'xpra-openh264' library so it can coexist with the
  distribution openh264 / noopenh264 packages
- install under a private library directory with a private soname (libopenh264-xpra.so.8)
- no longer provides, conflicts with or obsoletes 'noopenh264' / 'openh264'

* Wed Feb 12 2025 Antoine Martin <antoine@xpra.org> - 2.6.0-1
- new upstream release

* Thu Dec 26 2024 Antoine Martin <antoine@xpra.org> - 2.5.0-2
- replace 'noopenh264'

* Sat Nov 09 2024 Antoine Martin <antoine@xpra.org> - 2.5.0-1
- new upstream release

* Mon Feb 05 2024 Antoine Martin <antoine@xpra.org> - 2.4.1-1
- new upstream release

* Fri Nov 24 2023 Antoine Martin <antoine@xpra.org> - 2.4.0-1
- new upstream release

* Sun Sep 03 2023 Antoine Martin <antoine@xpra.org> - 2.3.1-2
- initial packaging for RHEL and clones
