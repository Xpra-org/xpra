%define _disable_source_fetch 0
%global _hardened_build 1

Name:           lz4
Version:        1.9.2
Release:        1%{?dist}
Summary:        Extremely fast compression algorithm

Group:          Applications/System
License:        GPLv2+ and BSD
URL:            https://code.google.com/p/lz4/
Source0:        https://github.com/%{name}/%{name}/archive/v%{version}.tar.gz

%if 0%{?rhel}
BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-buildroot
%endif

%description
LZ4 is an extremely fast loss-less compression algorithm, providing compression
speed at 400 MB/s per core, scalable with multi-core CPU. It also features
an extremely fast decoder, with speed in multiple GB/s per core, typically
reaching RAM speed limits on multi-core systems.

%package        devel
Summary:        Development library for lz4
Group:          Development/Libraries
License:        BSD
Requires:       %{name}%{?_isa} = %{version}-%{release}

%description    devel
This package contains the header(.h) and library(.so) files required to build
applications using liblz4 library.


%package        static
Summary:        Static library for lz4
Group:          Development/Libraries
License:        BSD

%description    static
LZ4 is an extremely fast loss-less compression algorithm. This package
contains static libraries for static linking of applications.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "658ba6191fa44c92280d4aa2c271b0f4fbc0e34d249578dd05e50e76d0e5efcc" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%if 0%{?el8}%{?fedora}
echo "Fedora and RHEL8 should use system packages"
exit 1
%endif
%setup -q -n %{name}-%{version}
echo '#!/bin/sh' > ./configure
chmod +x ./configure

%build
%configure
make


%install
%configure
%make_install LIBDIR=%{_libdir} PREFIX=/usr INSTALL="install -p"
#fix symlink not installed as a symlink:
rm %{buildroot}/usr/bin/lz4c
ln -sf lz4 %{buildroot}/usr/bin/lz4c
chmod -x %{buildroot}%{_includedir}/*.h


%post -p /sbin/ldconfig
%postun -p /sbin/ldconfig


%files
%doc programs/COPYING NEWS
%{_bindir}/lz4
%{_bindir}/lz4c
%{_bindir}/lz4cat
%{_bindir}/unlz4
%{_mandir}/man1/*lz4*
%{_libdir}/liblz4.so.1*


%files devel
%doc lib/LICENSE
%{_includedir}/*.h
%{_libdir}/liblz4.so
%{_libdir}/pkgconfig/liblz4.pc


%files static
%doc lib/LICENSE
%{_libdir}/liblz4.a


%changelog
* Wed Aug 21 2019 Antoine Martin <antoine@xpra.org> - 1.9.2-1
- new upstream release

* Wed Sep 12 2018 Antoine Martin <antoine@xpra.org> - 1.8.3-1
- new upstream release

* Tue Aug 21 2018 Antoine Martin <antoine@xpra.org> - 1.8.2-1
- new upstream release

* Mon Jan 22 2018 Antoine Martin <antoine@xpra.org> - 1.8.1.2-1
- new upstream release

* Sat Jan 13 2018 Antoine Martin <antoine@xpra.org> - 1.8.1-1
- new upstream release

* Thu Sep 14 2017 Antoine Martin <antoine@xpra.org> - 1.8.0-1
- new upstream release

* Mon Jan 16 2017 Antoine Martin <antoine@xpra.org> - 1.7.5-1
- new upstream release

* Wed Nov 23 2016 Antoine Martin <antoine@xpra.org> - 1.7.4-2
- PIE build fix

* Tue Nov 22 2016 Antoine Martin <antoine@xpra.org> - 1.7.4-1
- new upstream release

* Thu Nov 17 2016 Antoine Martin <antoine@xpra.org> - 1.7.3-1
- new upstream release
- new version naming scheme

* Sat Mar 12 2016 Antoine Martin <antoine@xpra.org> - r131-2
- use hardened build option

* Thu Dec 17 2015 Antoine Martin <antoine@xpra.org> - r131-1
- xpra packaging for CentOS
