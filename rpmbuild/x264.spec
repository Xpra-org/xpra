Name:	  x264		
Version:  20140612
Release:  1%{?dist}
Summary:  Library for encoding and decoding H264/AVC video streams	

Group:          Applications/Multimedia
License:	GPL
URL:		http://www.videolan.org/developers/x264.html
Source0:	http://download.videolan.org/pub/x264/snapshots/x264-snapshot-%{version}-2245-stable.tar.bz2
BuildRoot:	%(mktemp -ud %{_tmppath}/%{name}-%{version}-%{release}-XXXXXX)

Requires:       %{name}-libs = %{version}-%{release}
BuildRequires:	yasm

%if 0%{?fedora}
BuildRequires: perl-Digest-MD5
%endif

%description
x264 is a free library for encoding H264/AVC video streams, written from
scratch.

This package contains the frontend.

%package libs
Summary: Library for encoding H264/AVC video streams
Group: Development/Libraries

%description libs
x264 is a free library for encoding H264/AVC video streams, written from
scratch.

%package devel
Summary: Development files for the x264 library
Group: Development/libraries
Requires: %{name} = %{version}
Requires: pkgconfig

%description devel
x264 is a free library for encoding H264/AVC video streams, written from
scratch.

This package contains the development files.

%prep
%setup -q -n x264-snapshot-%{version}-2245-stable


%build
./configure \
    --prefix="%{_prefix}" \
    --libdir="%{_libdir}" \
    --enable-shared \
    --enable-static \

make %{?_smp_mflags}


%install
rm -rf %{buildroot}
make install DESTDIR=%{buildroot}

%post -p /sbin/ldconfig
%postun -p /sbin/ldconfig

%clean
rm -rf %{buildroot}


%files
%defattr(644,root,root,0755)
%doc AUTHORS COPYING*
%{_bindir}/x264

%files libs
%defattr(644,root,root,0755)
%{_libdir}/libx264.so.*

%files devel
%defattr(644,root,root,0755)
%{_includedir}/x264.h
%{_includedir}/x264_config.h
%{_libdir}/libx264.a
%{_libdir}/libx264.so
%{_libdir}/pkgconfig/x264.pc

%changelog

