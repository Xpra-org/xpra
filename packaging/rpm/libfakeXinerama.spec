#
# spec file for libfakeXinerama
#
# Copyright (c) 2014-2021 Antoine Martin <antoine@xpra.org>
#

%define _disable_source_fetch 0

Name:           libfakeXinerama
Version:        0.1.0
Release:        4%{?dist}
URL:            https://www.xpra.org/trac/wiki/FakeXinerama
Summary:        Fake Xinerama library for exposing virtual screens to X11 client applications
License:        MIT
Group:          System Environment/Libraries
Source0:        https://xpra.org/src/libfakeXinerama-%{version}.tar.bz2
BuildRoot:      %{_tmppath}/%{name}-%{version}-build

BuildRequires:  gcc
BuildRequires:  make
BuildRequires:  libXinerama-devel
BuildRequires:  libX11-devel
%if 0%{?suse_version}
BuildRequires:  linux-glibc-devel
%else
BuildRequires:  glibc-headers
%endif

%description
This package provides a fake Xinerama library which can be used
to return pre-defined screen layout information to X11 client applications
which use the Xinerama extension.

%global debug_package %{nil}

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "7d368575973024e851a6a91392dba39edb47dfd20ad5c0c65a560935b544ab3f" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi 
%setup -q

%build
gcc -O2 -Wall fakeXinerama.c -fPIC -o libfakeXinerama.so.1.0 -shared

%install
mkdir -p %{buildroot}%{_libdir}
install -p libfakeXinerama.so.* %{buildroot}%{_libdir}/
ln -sf libfakeXinerama.so.1.0 %{buildroot}%{_libdir}/libfakeXinerama.so.1

%clean
rm -rf %{buildroot}

%files
%defattr(-,root,root,-)
%doc README.TXT
%{_libdir}/libfakeXinerama.so.1*

%post -p /sbin/ldconfig

%postun -p /sbin/ldconfig

%changelog
* Wed Feb 17 2021 Antoine Martin <antoine@xpra.org> 0.1.0-4
- verify source checksum

* Mon Feb 03 2014 Antoine Martin <antoine@xpra.org> - 0.1.0-3.0
- First version
