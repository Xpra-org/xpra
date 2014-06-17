Name:	  libwebp	
Version:  0.4.0
Release:  1%{?dist}
Summary:  WebP library and conversion tools

Group:          Applications/Multimedia
License:	BSD
URL:		https://developers.google.com/speed/webp/
Source0:	https://webp.googlecode.com/files/libwebp-%{version}.tar.gz
BuildRoot:	%(mktemp -ud %{_tmppath}/%{name}-%{version}-%{release}-XXXXXX)

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
%setup -q


%build
./configure \
    --prefix="%{_prefix}" \
    --libdir="%{_libdir}" \
    --enable-pic \
    --enable-shared \
    --enable-static \

make %{?_smp_mflags}


%install
rm -rf %{buildroot}
make install DESTDIR=%{buildroot}


%clean
rm -rf %{buildroot}


%files
%defattr(-,root,root,-)
%doc AUTHORS COPYING PATENTS README
%{_bindir}/cwebp
%{_bindir}/dwebp
%{_libdir}/libwebp.so.*
%{_datadir}/man/man1/cwebp.1.gz
%{_datadir}/man/man1/dwebp.1.gz

%files devel
%defattr(-,root,root,-)
%{_includedir}/webp/
%{_libdir}/libwebp.a
%{_libdir}/libwebp.la
%{_libdir}/libwebp.so
%{_libdir}/pkgconfig/libwebp.pc


%changelog

