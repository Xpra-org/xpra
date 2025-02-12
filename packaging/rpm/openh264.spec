%define _disable_source_fetch 0

Name:           openh264
Version:        2.6.0
Release:        1
Summary:        H.264 codec library
License:        BSD-2-Clause
URL:            https://www.openh264.org/
Source0:        https://github.com/cisco/openh264/archive/v%{version}/openh264-%{version}.tar.gz

BuildRequires:  gcc-c++
BuildRequires:  make
BuildRequires:  nasm

# Replace the stub package
Obsoletes:      noopenh264 < 1:0

%description
OpenH264 is a codec library which supports H.264 encoding and decoding. It is
suitable for use in real time applications such as WebRTC.


%package        devel
Summary:        Development files for %{name}
Requires:       %{name}%{?_isa} = %{version}-%{release}
# Replace the stub package
Obsoletes:      noopenh264-devel < 1:0

%description    devel
The %{name}-devel package contains libraries and header files for
developing applications that use %{name}.


%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "558544ad358283a7ab2930d69a9ceddf913f4a51ee9bf1bfb9e377322af81a69" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q

%build
# Update the makefile with our build options
# Must be done in %%build in order to pick up correct LDFLAGS.
sed -i -e 's|^CFLAGS_OPT=.*$|CFLAGS_OPT=%{optflags}|' Makefile
sed -i -e 's|^PREFIX=.*$|PREFIX=%{_prefix}|' Makefile
sed -i -e 's|^LIBDIR_NAME=.*$|LIBDIR_NAME=%{_lib}|' Makefile
sed -i -e 's|^SHAREDLIB_DIR=.*$|SHAREDLIB_DIR=%{_libdir}|' Makefile
sed -i -e '/^CFLAGS_OPT=/i LDFLAGS=%{__global_ldflags}' Makefile

make %{?_smp_mflags}


%install
%make_install

# Remove static libraries
rm $RPM_BUILD_ROOT%{_libdir}/*.a

%files
%license LICENSE
%doc README.md
%{_libdir}/libopenh264.so.8
%{_libdir}/libopenh264.so.%{version}

%files devel
%{_includedir}/wels/
%{_libdir}/libopenh264.so
%{_libdir}/pkgconfig/openh264.pc

%changelog
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
