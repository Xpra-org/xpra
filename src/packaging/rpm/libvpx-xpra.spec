%define _disable_source_fetch 0

Name:	     libvpx-xpra
Version:     1.9.0
Release:     1%{?dist}
Summary:     vpx library for xpra

Group:       Applications/Multimedia
License:     BSD
URL:	     http://www.webmproject.org/code/
Source0:     https://github.com/webmproject/libvpx/archive/v%{version}/libvpx-%{version}.tar.gz
BuildRoot:   %(mktemp -ud %{_tmppath}/%{name}-%{version}-%{release}-XXXXXX)

BuildRequires:	yasm
BuildRequires:	gcc
BuildRequires:	gcc-c++
BuildRequires:	make
#Requires:

%description
vpx library for xpra


%package devel
Summary: Development files for the vpx library
Group: Development/libraries
Requires: %{name} = %{version}
Requires: pkgconfig

%description devel
This package contains the development files for %{name}.


%global debug_package %{nil}


%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "d279c10e4b9316bf11a570ba16c3d55791e1ad6faa4404c67422eb631782c80a" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%if 0%{?el8}%{?fedora}
echo "Fedora and RHEL8 should use system packages"
exit 1
%endif
%setup -q -n libvpx-%{version}


%build
./configure \
    --prefix="%{_prefix}" \
    --libdir="%{_libdir}/xpra" \
    --as=yasm \
    --enable-pic \
%if 0%{?el6}
    --disable-libyuv \
%endif
%if 0%{?el6}%{?el7}
    --disable-unit-tests \
%endif
    --disable-install-docs \
    --disable-install-bins \
    --enable-shared \
    --enable-vp8 \
    --enable-vp9 \
    --enable-realtime-only \
    --enable-runtime-cpu-detect

make %{?_smp_mflags}


%install
rm -rf %{buildroot}
make install DESTDIR=%{buildroot}

# dirty hack because configure does not provide includedir flag
mkdir %{buildroot}/%{_includedir}/xpra
mv %{buildroot}/%{_includedir}/vpx %{buildroot}/%{_includedir}/xpra
sed -i 's,/include,/include/xpra,' %{buildroot}/%{_libdir}/xpra/pkgconfig/vpx.pc

%clean
rm -rf %{buildroot}


%files
%defattr(-,root,root,-)
%doc AUTHORS CHANGELOG PATENTS README
%{_libdir}/xpra/libvpx.so.*

%files devel
%defattr(-,root,root,-)
%{_includedir}/xpra/vpx/
%{_libdir}/xpra/libvpx.a
%{_libdir}/xpra/libvpx.so
%{_libdir}/xpra/pkgconfig/vpx.pc


%changelog
* Thu Oct 15 2020 Antoine Martin <antoine@xpra.org> 1.9.0-1
- new upstream release

* Mon Feb 03 2020 Antoine Martin <antoine@xpra.org> 1.8.2-1
- new upstream release

* Fri Jul 19 2019 Antoine Martin <antoine@xpra.org> 1.8.1-1
- new upstream release

* Mon Feb 05 2018 Antoine Martin <antoine@xpra.org> 1.8.0-1
- new upstream release

* Sat Jan 27 2018 Antoine Martin <antoine@xpra.org> 1.7.0-1
- new upstream release

* Tue Jan 24 2017 Antoine Martin <antoine@xpra.org> 1.6.1-1
- new upstream release

* Sun Jul 24 2016 Antoine Martin <antoine@xpra.org> 1.6.0-1
- new upstream release

* Fri Nov 13 2015 Antoine Martin <antoine@xpra.org> 1.5.0-1
- new upstream release

* Sat Apr 04 2015 Antoine Martin <antoine@xpra.org> 1.4.0-1
- new upstream release

* Mon Jul 14 2014 Matthew Gyurgyik <pyther@pyther.net>
- initial package
