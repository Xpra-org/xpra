Name:	  libvpx	
Version:  1.3.0
Release:  1%{?dist}
Summary:  Library for encoding and decoding VP8/VP9 video streams	

Group:          Applications/Multimedia
License:	BSD
URL:		http://www.webmproject.org/code/
Source0:	https://webm.googlecode.com/files/libvpx-v%{version}.tar.bz2
BuildRoot:	%(mktemp -ud %{_tmppath}/%{name}-%{version}-%{release}-XXXXXX)

BuildRequires:	yasm
#Requires:	

%description
Utility and library for encoding VP8/VP9 video streams.


%package devel
Summary: Development files for the vpx library
Group: Development/libraries
Requires: %{name} = %{version}
Requires: pkgconfig

%description devel
This package contains the files required to develop programs that will encode
VP8/VP9 video streams.

%prep
%setup -q -n %{name}-v%{version}


%build
./configure \
    --prefix="%{_prefix}" \
    --libdir="%{_libdir}" \
    --enable-pic \
    --disable-install-docs \
    --enable-shared \
    --enable-static \
    --enable-vp8 \
    --enable-vp9 \
    --enable-realtime-only \
    --enable-runtime-cpu-detect \

make %{?_smp_mflags}


%install
rm -rf %{buildroot}
make install DESTDIR=%{buildroot}


%clean
rm -rf %{buildroot}


%files
%defattr(-,root,root,-)
%doc AUTHORS CHANGELOG PATENTS README
%{_bindir}/vp8_scalable_patterns
%{_bindir}/vp9_spatial_scalable_encoder
%{_bindir}/vpxdec
%{_bindir}/vpxenc
%{_libdir}/libvpx.so.*

%files devel
%defattr(-,root,root,-)
%{_includedir}/vpx/
%{_libdir}/libvpx.a
%{_libdir}/libvpx.so
%{_libdir}/pkgconfig/vpx.pc


%changelog

