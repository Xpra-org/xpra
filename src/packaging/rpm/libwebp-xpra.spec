%define _disable_source_fetch 0

Name:	     libwebp-xpra
Version:     1.2.1
Release:     1%{?dist}
Summary:     WebP library and conversion tools for xpra

Group:       Applications/Multimedia
License:     BSD
URL:	     https://developers.google.com/speed/webp/
Source0:     https://storage.googleapis.com/downloads.webmproject.org/releases/webp/libwebp-%{version}.tar.gz
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
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "808b98d2f5b84e9b27fdef6c5372dac769c3bda4502febbfa5031bd3c4d7d018" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
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
* Mon May 25 2020 Antoine Martin <antoine@xpra.org> 1.2.0-1
- new upstream release

* Tue Jan 14 2020 Antoine Martin <antoine@xpra.org> 1.1.0-1
- new upstream release

* Fri Jul 19 2019 Antoine Martin <antoine@xpra.org> 1.0.3-1
- new upstream release

* Wed Jan 23 2019 Antoine Martin <antoine@xpra.org> 1.0.2-1
- new upstream release

* Mon Nov 19 2018 Antoine Martin <antoine@xpra.org> 1.0.1-1
- new upstream release

* Mon Apr 30 2018 Antoine Martin <antoine@xpra.org> 1.0.0-1
- new upstream release

* Wed Nov 29 2017 Antoine Martin <antoine@xpra.org> 0.6.1-1
- new upstream release

* Wed Nov 22 2017 Antoine Martin <antoine@xpra.org> 0.6.0-1
- new upstream release

* Fri Nov 13 2015 Antoine Martin <antoine@xpra.org> 0.4.4-1
- new upstream release

* Tue Mar 31 2015 Antoine Martin <antoine@xpra.org> 0.4.3-1
- new upstream release

* Sat Oct 25 2014 Antoine Martin <antoine@xpra.org> 0.4.2-1
- new upstream release

* Mon Aug 18 2014 Antoine Martin <antoine@xpra.org> 0.4.1-1
- Update to 0.4.1

* Thu Jul 31 2014 Antoine Martin <antoine@xpra.org>
- configure doesn't support --enable-pic

* Mon Jul 14 2014 Matthew Gyurgyik <pyther@pyther.net>
- initial package
