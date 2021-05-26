# spec file for package python-lz4
%{!?__python2: %global __python2 python2}
%{!?python2_sitearch: %global python2_sitearch %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))")}
%define _disable_source_fetch 0

Name:           python2-lz4
Version:        2.2.1
Release:        2
URL:            https://github.com/python-lz4/python-lz4
Summary:        LZ4 Bindings for Python
License:        GPLv2+
Group:          Development/Languages/Python
Source:         https://files.pythonhosted.org/packages/98/52/94bb31d416e52c3c9cc432e26b7a30b4b5a3c853e81df2906ce4bbc59437/lz4-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-build
BuildRequires:  python2-devel
BuildRequires:  python2-setuptools
BuildRequires:  python2-setuptools_scm
BuildRequires:  python2-pkgconfig
Requires: 		lz4
Provides:		python-lz4 = %{version}-%{release}
Obsoletes:      python-lz4 < %{version}-%{release}
Conflicts:		python-lz4 < %{version}-%{release}

%description
This package provides Python2 bindings for the lz4 compression library
http://code.google.com/p/lz4/ by Yann Collet.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "b666e2d04648f656b6af7d863bc7e50bd72bc00c5c569f89ead010c29c5facb4" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n lz4-%{version}
#only needed on centos (a fairly brutal solution):

%build
export CFLAGS="%{optflags}"
%{__python2} setup.py build

%install
%{__python2} setup.py install --root %{buildroot}

%clean
rm -rf %{buildroot}

%files
%defattr(-,root,root,-)
%doc README.rst
%{python2_sitearch}/lz4*

%changelog
* Thu Sep 26 2019 Antoine Martin <antoine@xpra.org> - 2.2.1-2
- remove old dependency

* Mon Sep 16 2019 Antoine Martin <antoine@xpra.org> - 2.2.1-1
- New upstream release

* Thu Jan 10 2019 Antoine Martin <antoine@xpra.org> - 2.1.6-1
- New upstream release

* Sun Nov 04 2018 Antoine Martin <antoine@xpra.org> - 2.1.2-1
- New upstream release

* Sun Jul 08 2018 Antoine Martin <antoine@xpra.org> - 2.0.2-1
- New upstream release

* Tue Jul 03 2018 Antoine Martin <antoine@xpra.org> - 2.0.1-2
- try harder to prevent rpm db conflicts

* Mon Jul 02 2018 Antoine Martin <antoine@xpra.org> - 2.0.1-1
- New upstream release

* Fri May 11 2018 Antoine Martin <antoine@xpra.org> - 1.10-1
- New upstream release

* Tue Apr 03 2018 Antoine Martin <antoine@xpra.org> - 0.21.6-2.xpra1
- Force upgrade of broken Fedora 28 package, which is missing the new python "deprecation" dependency

* Mon Feb 05 2018 Antoine Martin <antoine@xpra.org> - 0.21.6-1
- New upstream release

* Thu Feb 01 2018 Antoine Martin <antoine@xpra.org> - 0.19.2-1
- New upstream release

* Mon Jan 22 2018 Antoine Martin <antoine@xpra.org> - 0.19.1-1
- New upstream release

* Mon Jan 01 2018 Antoine Martin <antoine@xpra.org> - 0.18.1-1
- New upstream release

* Mon Dec 25 2017 Antoine Martin <antoine@xpra.org> - 0.14.0-1
- New upstream release

* Fri Dec 22 2017 Antoine Martin <antoine@xpra.org> - 0.13.0-1
- New upstream release

* Tue Nov 21 2017 Antoine Martin <antoine@xpra.org> - 0.11.1-1
- New upstream release

* Sun Jul 02 2017 Antoine Martin <antoine@xpra.org> - 0.10.1-1
- New upstream release

* Sat Jun 10 2017 Antoine Martin <antoine@xpra.org> - 0.10.0-1
- New upstream release

* Sun May 14 2017 Antoine Martin <antoine@xpra.org> - 0.9.1-1
- New upstream release

* Mon Mar 13 2017 Antoine Martin <antoine@xpra.org> - 0.9.0-1
- New upstream release

* Sat Dec 24 2016 Antoine Martin <antoine@xpra.org> - 0.8.2-3
- conflict with old package name

* Mon Jul 18 2016 Antoine Martin <antoine@xpra.org> - 0.8.2-2
- new package name, obsolete the old one

* Fri Jun 17 2016 Antoine Martin <antoine@xpra.org> - 0.8.2-1
- New upstream release

* Fri Apr 29 2016 Antoine Martin <antoine@xpra.org> - 0.8.1-1
- New upstream release

* Thu Jan 07 2016 Antoine Martin <antoine@xpra.org> - 0.8.0.rc2-1
- Merge "release the GIL" patch

* Mon Jul 13 2015 Antoine Martin <antoine@xpra.org> - 0.8.0.rc1-1
- Pre-release testing

* Sat Jun 27 2015 Antoine Martin <antoine@xpra.org> - 0.7.0-2
- Add version information to package

* Wed Sep 17 2014 Antoine Martin <antoine@xpra.org> - 0.7.0-1
- Add Python3 package

* Mon Jul 07 2014 Antoine Martin <antoine@xpra.org> - 0.7.0-0
- New upstream release

* Fri Mar 21 2014 Antoine Martin <antoine@xpra.org> - 0.6.1-0
- New upstream release

* Wed Jan 15 2014 Antoine Martin <antoine@xpra.org> - 0.6.0-1.0
- Fix version in specfile
- build debuginfo packages

* Sun Dec 8 2013 Stephen Gauthier <sgauthier@spikes.com> - 0.6.0-0
- First version for Fedora Extras
