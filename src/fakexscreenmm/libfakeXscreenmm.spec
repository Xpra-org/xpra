#
# spec file for libfakeXscreenmm
#
# Copyright (c) 2014 Antoine Martin <antoine@devloop.org.uk>
#

Name:           libfakeXscreenmm
Version:        0.1.0
Release:        1%{?dist}
Url:            https://www.xpra.org/trac/wiki/FakeXscreenmm
Summary:        Library for overriding the virtual screens dimensions exposed to X11 client applications
License:        MIT
Group:          System Environment/Libraries
Source:         http://xpra.org/src/libfakeXscreenmm-%{version}.tar.bz2
BuildRoot:      %{_tmppath}/%{name}-%{version}-build

BuildRequires:  gcc, libX11-devel, glibc-headers

%description
This package provides a library which can be used via LD_PRELOAD
to return different screen dimension information to X11 client applications.


%prep
%setup -q

%build
gcc -O2 -Wall fakeXscreenmm.c -fPIC -o libfakeXscreenmm.so.1.0 -shared

%install
mkdir -p %{buildroot}%{_libdir}
install -p libfakeXscreenmm.so.* %{buildroot}%{_libdir}/
ln -sf libfakeXscreenmm.so.1.0 %{buildroot}%{_libdir}/libfakeXscreenmm.so.1

%clean
rm -rf %{buildroot}

%files
%defattr(-,root,root,-)
%doc README.TXT
%{_libdir}/libfakeXscreenmm.so.1*

%post -p /sbin/ldconfig

%postun -p /sbin/ldconfig

%changelog
* Mon Feb 03 2014 Antoine Martin <antoine@devloop.org.uk - 0.1.0-1.0
- First version
