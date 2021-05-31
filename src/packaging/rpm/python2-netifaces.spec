%{!?__python2: %global __python2 /usr/bin/python2}
%{!?python2_sitearch: %global python2_sitearch %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))")}
%define _disable_source_fetch 0

Summary:	Getting network addresses from Python
Vendor:		http://alastairs-place.net/netifaces/
Name:		python2-netifaces
Version:	0.10.9
Release:	1%{?dist}
License:	GPL3
Group:		Networking
Packager:	Antoine Martin <antoine@xpra.org>
URL:		http://xpra.org/
Source:		https://files.pythonhosted.org/packages/0d/18/fd6e9c71a35b67a73160ec80a49da63d1eed2d2055054cc2995714949132/netifaces-%{version}.tar.gz
BuildRoot:	%{_tmppath}/%{name}-%{version}-root
Requires:	python2
BuildRequires: python2-devel
BuildRequires: python2-setuptools
%if 0%{el7}
Provides:	netifaces = %{version}-%{release}
Provides:	python-netifaces = %{version}-%{release}
Obsoletes:	netifaces
Obsoletes:	python-netifaces
Conflicts:	netifaces < %{version}
Conflicts:	python-netifaces < %{version}
%endif

%description
Getting network addresses from Python

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "2dee9ffdd16292878336a58d04a20f0ffe95555465fee7c9bd23b3490ef2abf3" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n netifaces-%{version}

%build
%{__python2} setup.py build

%install
%{__python2} setup.py install --root %{buildroot}

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root)
%doc README.rst
%{python2_sitearch}/netifaces*

%changelog
* Fri Jan 11 2019 Antoine Martin <antoine@xpra.org> - 0.10.9-1
- new upstream release

* Tue Nov 13 2018 Antoine Martin <antoine@xpra.org> - 0.10.7-2
- force rebuild

* Tue May 08 2018 Antoine Martin <antoine@xpra.org> - 0.10.7-1
- new upstream release

* Mon Apr 02 2018 Antoine Martin <antoine@xpra.org> - 0.10.6-1
- new upstream release

* Sat Dec 17 2016 Antoine Martin <antoine@xpra.org> - 0.10.5-2
- force update with new dependencies

* Fri Aug 26 2016 Antoine Martin <antoine@xpra.org> - 0.10.5-1
- new upstream release

* Mon Aug 01 2016 Antoine Martin <antoine@xpra.org> - 0.10.4-6
- trying to get centos6 to behave

* Fri Jul 29 2016 Antoine Martin <antoine@xpra.org> - 0.10.4-5
- fix obsolete atom

* Sun Jul 17 2016 Antoine Martin <antoine@xpra.org> - 0.10.4-4
- rename and obsolete old python package name

* Wed Sep 17 2014 Antoine Martin <antoine@xpra.org> 0.10.4-3
- Add Python3 package

* Wed Aug 27 2014 Antoine Martin <antoine@xpra.org> 0.10.4-2
- Rebuild with obsoletes tag

* Thu Feb 23 2012 Antoine Martin <antoine@xpra.org> 0.10.4-1
- Updated to 0.10.4

* Thu Feb 23 2012 Antoine Martin <antoine@xpra.org> 0.8.0-1
- Fixed bit-rot in the ioctl() code path
- Fixed a problem with setup.py that might manifest itself if the config.cache file was manually edited
- Fixed the ioctl() code path to cope with systems that have sa_len
- Removed empty 'addr' entries for interfaces that don't provide any addresses
- Added a version property to the module that you can test at runtime
- Added address_families dictionary to allow code to look up the symbolic name corresponding to a given numeric address family code

* Sun Nov 14 2010 Antoine Martin <antoine@xpra.org> 0.5.0-2
- Rebuilt with new, simplified specfile

* Sat May 01 2010 Antoine Martin <antoine@xpra.org> 0.5.0-1
- First attempt at making RPMs
