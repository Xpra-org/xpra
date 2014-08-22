#
# rpm spec for netifaces
#



Summary: Getting network addresses from Python
Vendor: http://alastairs-place.net/netifaces/
Name: python-netifaces
Version: 0.10.4
Release: 1%{?dist}
License: GPL3
Requires: python
Group: Networking
Packager: Antoine Martin <antoine@nagafix.co.uk>
URL: http://winswitch.org/
Source: netifaces-%{version}.tar.gz
BuildRoot: %{_tmppath}/%{name}-%{version}-root
BuildRequires: python-devel, python-setuptools
Provides: netifaces


%description
Getting network addresses from Python


%changelog
* Thu Feb 23 2012 Antoine Martin <antoine@nagafix.co.uk> 0.10.4-1
- Updated to 0.10.4

* Thu Feb 23 2012 Antoine Martin <antoine@nagafix.co.uk> 0.8.0-1
- Fixed bit-rot in the ioctl() code path
- Fixed a problem with setup.py that might manifest itself if the config.cache file was manually edited
- Fixed the ioctl() code path to cope with systems that have sa_len
- Removed empty 'addr' entries for interfaces that don't provide any addresses
- Added a version property to the module that you can test at runtime
- Added address_families dictionary to allow code to look up the symbolic name corresponding to a given numeric address family code

* Sun Nov 14 2010 Antoine Martin <antoine@nagafix.co.uk> 0.5.0-2
- Rebuilt with new, simplified specfile

* Sat May 01 2010 Antoine Martin <antoine@nagafix.co.uk> 0.5.0-1
- First attempt at making RPMs


%prep
%setup -q -n netifaces-%{version}

%build
%{__python} setup.py build

%install
rm -rf $RPM_BUILD_ROOT
%{__python} setup.py install -O1 --prefix /usr --root %{buildroot}

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root)
%doc  README.rst
%{_libdir}/python*/site-packages/netifaces*

###
### eof
###
