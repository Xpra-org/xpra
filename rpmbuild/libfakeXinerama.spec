#
# spec file for libfakeXinerama
#
# Copyright (c) 2014 Antoine Martin <antoine@devloop.org.uk>
#

Name:           libfakeXinerama
Version:        0.1.0
Release:        3%{?dist}
Url:            https://www.xpra.org/trac/wiki/FakeXinerama
Summary:        Fake Xinerama library for exposing virtual screens to X11 client applications
License:        MIT
Group:          System Environment/Libraries
Source:         http://xpra.org/src/libfakeXinerama-%{version}.tar.bz2
BuildRoot:      %{_tmppath}/%{name}-%{version}-build

BuildRequires:  gcc
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


%prep
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
* Mon Feb 03 2014 Antoine Martin <antoine@devloop.org.uk> - 0.1.0-3.0
- First version
