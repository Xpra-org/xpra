%define _disable_source_fetch 0
%define _build_id_links none
%define commit 5db6aa6cab1b146e07b60cc1736a01f21da01154
%global debug_package %{nil}

Name:	     x264-xpra
Version:     20210301
Release:     1%{?dist}
Summary:     x264 library for xpra
Group:       Applications/Multimedia
License:     GPL
URL:	     http://www.videolan.org/developers/x264.html
Source0:     https://github.com/mirror/x264/archive/%{commit}.zip
BuildRoot:   %(mktemp -ud %{_tmppath}/%{name}-%{version}-%{release}-XXXXXX)
AutoReq:     0
AutoProv:    0

BuildRequires:	nasm
BuildRequires:	gcc
BuildRequires:	make
BuildRequires:	perl-Digest-MD5

%description
x264 library for xpra

%package devel
Summary: Development files for the x264 library
Group: Development/libraries
Requires: %{name} = %{version}
Requires: pkgconfig
Requires: x264-xpra = %{version}
AutoReq:     0
AutoProv:    0

%description devel
This package contains the development files for %{name}.


%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "f3795b0b428e1b329305b2c19eb244e3e911231023f5bb8456dcb705a74d9545" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n x264-%{commit}


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
rm -f %{buildroot}/usr/share/bash-completion/completions/x264
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
* Mon Mar 01 2021 Antoine Martin <antoine@xpra.org> - 20210301-1
- remove legacy CentOS 7 switches
- build from github mirror snapshot
- add missing dependency

* Wed Feb 17 2021 Antoine Martin <antoine@xpra.org> - 20210110-2
- verify source checksum

* Sun Jan 10 2021 Antoine Martin <antoine@xpra.org> - 20210110-1
- use a newer snapshot from git
