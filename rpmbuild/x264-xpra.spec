%define _build_id_links none

Name:	     x264-xpra
Version:     20210110
%if 0%{?beta} < 1
Release:     1%{?dist}
%else
Release:     0%{?dist}
%endif
Summary:     x264 library for xpra

Group:       Applications/Multimedia
License:     GPL
URL:	     http://www.videolan.org/developers/x264.html
Source0:     http://download.videolan.org/pub/x264/snapshots/x264-snapshot-%{version}-d198931a-stable.tar.bz2
BuildRoot:   %(mktemp -ud %{_tmppath}/%{name}-%{version}-%{release}-XXXXXX)
AutoProv:    0

BuildRequires:	yasm


%if 0%{?fedora}%{?el8}
%global debug_package %{nil}
%endif

%if 0%{?fedora} || 0%{?rhel} >= 7
BuildRequires: perl-Digest-MD5
%endif

%description
x264 library for xpra

%package devel
Summary: Development files for the x264 library
Group: Development/libraries
Requires: %{name} = %{version}
Requires: pkgconfig
Requires: x264-xpra = %{version}
AutoReq:  0

%description devel
This package contains the development files for %{name}.


%prep
%setup -q -n x264-stable


%build
./configure \
    --prefix="%{_prefix}" \
    --libdir="%{_libdir}/xpra" \
    --includedir="%{_includedir}/xpra" \
    --bit-depth=all \
    --enable-shared \
    --enable-static

make %{?_smp_mflags}


%install
rm -rf %{buildroot}
make install DESTDIR=%{buildroot}

# remove executable and bash completion:
rm %{buildroot}/usr/share/bash-completion/completions/x264
rm %{buildroot}/usr/bin/x264

%post -p /sbin/ldconfig
%postun -p /sbin/ldconfig

%clean
rm -rf %{buildroot}

%files
%defattr(644,root,root,0755)
%doc AUTHORS COPYING*
%{_libdir}/xpra/libx264.so.*

%files devel
%defattr(644,root,root,0755)
%{_includedir}/xpra/x264.h
%{_includedir}/xpra/x264_config.h
%{_libdir}/xpra/libx264.a
%{_libdir}/xpra/libx264.so
%{_libdir}/xpra/pkgconfig/x264.pc

%changelog
* Sun Jan 10 2021 Antoine Martin <antoine@xpra.org> 20210110-1
- use a newer snapshot from git
