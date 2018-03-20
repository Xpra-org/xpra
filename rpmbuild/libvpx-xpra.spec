Name:	     libvpx-xpra
Version:     1.7.0
Release:     1%{?dist}
Summary:     vpx library for xpra

Group:       Applications/Multimedia
License:     BSD
URL:	     http://www.webmproject.org/code/
Source0:     http://downloads.webmproject.org/releases/webm/libvpx-%{version}.tar.gz
BuildRoot:   %(mktemp -ud %{_tmppath}/%{name}-%{version}-%{release}-XXXXXX)

BuildRequires:	yasm
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


%prep
%setup -q -n libvpx-%{version}


%build
./configure \
    --prefix="%{_prefix}" \
    --libdir="%{_libdir}/xpra" \
    --enable-pic \
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
* Sat Jan 27 2017 Antoine Martin <antoine@devloop.org.uk> 1.7.0-1
- new upstream release

* Tue Jan 24 2017 Antoine Martin <antoine@devloop.org.uk> 1.6.1-1
- new upstream release

* Sun Jul 24 2016 Antoine Martin <antoine@devloop.org.uk> 1.6.0-1
- new upstream release

* Fri Nov 13 2015 Antoine Martin <antoine@devloop.org.uk> 1.5.0-1
- new upstream release

* Sat Apr 04 2015 Antoine Martin <antoine@devloop.org.uk> 1.4.0-1
- new upstream release

* Mon Jul 14 2014 Matthew Gyurgyik <pyther@pyther.net>
- initial package
