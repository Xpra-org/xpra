Name:	     libwebp-xpra
Version:     0.5.0
Release:     1%{?dist}
Summary:     WebP library and conversion tools for xpra

Group:       Applications/Multimedia
License:     BSD
URL:	     https://developers.google.com/speed/webp/
Source0:     https://webp.googlecode.com/files/libwebp-%{version}.tar.gz
BuildRoot:   %(mktemp -ud %{_tmppath}/%{name}-%{version}-%{release}-XXXXXX)

#BuildRequires:	yasm
#Requires:	

%description
WebP library and conversion tools

%package devel
Summary: Development files for the webp library
Group: Development/libraries
Requires: %{name} = %{version}
Requires: pkgconfig

%description devel
This package contains the files required to develop programs that will encode
WebP images.

%prep
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

%files devel
%defattr(-,root,root,-)
%{_includedir}/xpra/webp/
%{_libdir}/xpra/libwebp.a
%{_libdir}/xpra/libwebp.la
%{_libdir}/xpra/libwebp.so
%{_libdir}/xpra/pkgconfig/libwebp.pc


%changelog
* Sun Dec 27 2015 Antoine Martin <antoine@devloop.org.uk> 0.5.0-1
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
