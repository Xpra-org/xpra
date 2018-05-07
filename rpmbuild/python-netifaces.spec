#
# rpm spec for netifaces
#
%{!?__python2: %global __python2 /usr/bin/python2}
%{!?python2_sitearch: %global python2_sitearch %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))")}

#this spec file is for both Fedora and CentOS
#only Fedora has Python3 at present:
%if 0%{?fedora}
%define with_python3 1
%endif


Summary: Getting network addresses from Python
Vendor: http://alastairs-place.net/netifaces/
Name: python2-netifaces
Version: 0.10.7
Release: 1%{?dist}
License: GPL3
Requires: python
Group: Networking
Packager: Antoine Martin <antoine@nagafix.co.uk>
URL: http://winswitch.org/
Source: netifaces-%{version}.tar.gz
BuildRoot: %{_tmppath}/%{name}-%{version}-root
BuildRequires: python-devel, python-setuptools
Provides: netifaces = %{version}-%{release}
Provides: python-netifaces = %{version}-%{release}
Obsoletes: netifaces
Obsoletes: python-netifaces
Conflicts: netifaces < %{version}
Conflicts: python-netifaces < %{version}

%description
Getting network addresses from Python

%if 0%{?with_python3}
%package -n python3-netifaces
Summary: Getting network addresses from Python
Group: Networking

%description -n python3-netifaces
Getting network addresses from Python3
%endif


%prep
%setup -q -n netifaces-%{version}

%if 0%{?with_python3}
rm -rf %{py3dir}
cp -a . %{py3dir}
%endif

%build
%{__python2} setup.py build

%if 0%{?with_python3}
pushd %{py3dir}
%{__python3} setup.py build
popd
%endif

%install
%{__python2} setup.py install --root %{buildroot}

%if 0%{?with_python3}
%{__python3} setup.py install --root %{buildroot}
%endif

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root)
%doc README.rst
%{python2_sitearch}/netifaces*

%if 0%{?with_python3}
%files -n python3-netifaces
%defattr(-,root,root)
%{python3_sitearch}/netifaces*
%endif


%changelog
* Tue May 08 2018 Antoine Martin <antoine@nagafix.co.uk> - 0.10.7-1
- new upstream release

* Mon Apr 02 2018 Antoine Martin <antoine@nagafix.co.uk> - 0.10.6-1
- new upstream release

* Sat Dec 17 2016 Antoine Martin <antoine@nagafix.co.uk> - 0.10.5-2
- force update with new dependencies

* Fri Aug 26 2016 Antoine Martin <antoine@nagafix.co.uk> - 0.10.5-1
- new upstream release

* Mon Aug 01 2016 Antoine Martin <antoine@nagafix.co.uk> - 0.10.4-6
- trying to get centos6 to behave

* Fri Jul 29 2016 Antoine Martin <antoine@nagafix.co.uk> - 0.10.4-5
- fix obsolete atom

* Sun Jul 17 2016 Antoine Martin <antoine@nagafix.co.uk> - 0.10.4-4
- rename and obsolete old python package name

* Wed Sep 17 2014 Antoine Martin <antoine@nagafix.co.uk> 0.10.4-3
- Add Python3 package

* Wed Aug 27 2014 Antoine Martin <antoine@nagafix.co.uk> 0.10.4-2
- Rebuild with obsoletes tag

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
