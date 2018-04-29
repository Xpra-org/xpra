Name:	     libwebp-xpra
Version:     1.0.0
Release:     1%{?dist}
Summary:     WebP library and conversion tools for xpra

Group:       Applications/Multimedia
License:     BSD
URL:	     https://developers.google.com/speed/webp/
Source0:     http://downloads.webmproject.org/releases/webp/libwebp-%{version}.tar.gz
BuildRoot:   %(mktemp -ud %{_tmppath}/%{name}-%{version}-%{release}-XXXXXX)

BuildRequires: gcc
BuildRequires: autoconf
BuildRequires: automake
BuildRequires: libtool

%description
WebP library and conversion tools, private version for Xpra


%package devel
Summary: Development files for the webp library
Group: Development/libraries
Requires: %{name} = %{version}
Requires: pkgconfig

%description devel
This package contains the files required to develop programs that will encode
WebP images.

%prep
%if ! 0%{?el7}
echo "this package is only meant to be built for RHEL / CentOS 7.x"
exit 1
%endif
%setup -q -n libwebp-%{version}


%build
./configure \
    --prefix="%{_prefix}" \
    --libdir="%{_libdir}/xpra" \
    --includedir="%{_includedir}/xpra" \
    --enable-shared

make %{?_smp_mflags}


%install
rm -rf %{buildroot}
make install DESTDIR=%{buildroot}

rm -rf %{buildroot}/usr/bin
rm -rf %{buildroot}/usr/share


%clean
rm -rf %{buildroot}


%files
%defattr(-,root,root,-)
%doc AUTHORS COPYING PATENTS README
%{_libdir}/xpra/libwebp.so.*
%{_libdir}/xpra/libwebpdemux.so.*

%files devel
%defattr(-,root,root,-)
%{_includedir}/xpra/webp/
%{_libdir}/xpra/libwebp.a
%{_libdir}/xpra/libwebp.la
%{_libdir}/xpra/libwebp.so
%{_libdir}/xpra/libwebpdemux.a
%{_libdir}/xpra/libwebpdemux.la
%{_libdir}/xpra/libwebpdemux.so
%{_libdir}/xpra/pkgconfig/libwebp.pc
%{_libdir}/xpra/pkgconfig/libwebpdemux.pc


%changelog
* Mon Apr 30 2018 Antoine Martin <antoine@devloop.org.uk> 1.0.0-1
- new upstream release

* Wed Nov 29 2017 Antoine Martin <antoine@devloop.org.uk> 0.6.1-1
- new upstream release

* Wed Nov 22 2017 Antoine Martin <antoine@devloop.org.uk> 0.6.0-1
- new upstream release

* Fri Nov 13 2015 Antoine Martin <antoine@devloop.org.uk> 0.4.4-1
- new upstream release

* Tue Mar 31 2015 Antoine Martin <antoine@devloop.org.uk> 0.4.3-1
- new upstream release

* Sat Oct 25 2014 Antoine Martin <antoine@devloop.org.uk> 0.4.2-1
- new upstream release

* Mon Aug 18 2014 Antoine Martin <antoine@devloop.org.uk> 0.4.1-1
- Update to 0.4.1

* Thu Jul 31 2014 Antoine Martin <antoine@devloop.org.uk>
- configure doesn't support --enable-pic

* Mon Jul 14 2014 Matthew Gyurgyik <pyther@pyther.net>
- initial package
