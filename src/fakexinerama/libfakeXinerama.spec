#
# spec file for libfakeXinerama
#
# Copyright (c) 2014 Antoine Martin <antoine@devloop.org.uk>
#

Name:           libfakeXinerama
Version:        0.1.0
Release:        2%{?dist}
Url:            https://www.xpra.org/trac/wiki/FakeXinerama
Summary:        Fake Xinerama library for exposing virtual screens to X11 client applications
License:        MIT
Group:          System Environment/Libraries
Source:         http://xpra.org/src/libfakeXinerama-%{version}.tar.bz2
BuildRoot:      %{_tmppath}/%{name}-%{version}-build

BuildRequires:  gcc, libXinerama-devel, libX11-devel, glibc-headers

%description
This package provides a fake Xinerama library which can be used
to return pre-defined screen layout information to X11 client applications
which use the Xinerama extension.


%prep
%setup -q

# % debug_package

%build
gcc -O2 -Wall fakeXinerama.c -fPIC -o libfakeXinerama.so.1.0 -shared
ln -sf libfakeXinerama.so.1.0 libfakeXinerama.so.1

%install
mkdir -p %{buildroot}%{_libdir}
install -p libfakeXinerama.so.* %{buildroot}%{_libdir}/
#cp -p mycommand %{buildroot}%{_bindir}/

%clean
rm -rf %{buildroot}

%files
%defattr(-,root,root,-)
%doc README.TXT
%{_libdir}/libfakeXinerama.so.1*

%changelog
* Sat Feb 01 2014 Antoine Martin <antoine@devloop.org.uk - 0.1.0-1.0
- First version
