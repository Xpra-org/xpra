#
# spec file for package python-lz4
#
# Copyright (c) 2013-2017
#

#this spec file is for both Fedora and CentOS
#only Fedora has Python3 at present:
%if 0%{?fedora}
%define with_python3 1
%endif

%{!?__python2: %global __python2 python2}
%{!?__python3: %define __python3 python3}
%{!?python2_sitearch: %global python2_sitearch %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))")}
%{!?python3_sitearch: %global python3_sitearch %(%{__python3} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))")}


Name:           python2-lz4
Version:        0.10.0
Release:        1%{?dist}
URL:            https://github.com/python-lz4/python-lz4
Summary:        LZ4 Bindings for Python
License:        GPLv2+
Group:          Development/Languages/Python
Source:         https://pypi.python.org/packages/1b/69/6c106a77a804f08938487a9bf45a9771209f487c9dadea8ea819c1555e35/lz4-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-build
BuildRequires:  python-devel
BuildRequires:  python-setuptools
%if 0%{?suse_version}==0
BuildRequires:  lz4-devel
%endif
Requires: 		lz4
Provides:		python-lz4
Obsoletes:      python-lz4 < 0.8.2-3
Conflicts:		python-lz4 < 0.8.2-3
Patch0:         lz4-skip-nose-vs-sphinx-mess.patch

%description
This package provides Python2 bindings for the lz4 compression library
http://code.google.com/p/lz4/ by Yann Collet.

%if 0%{?with_python3}
%package -n python3-lz4
Summary:        LZ4 Bindings for Python3
Group:          Development/Languages/Python

%description -n python3-lz4
This package provides Python3 bindings for the lz4 compression library
http://code.google.com/p/lz4/ by Yann Collet.
%endif

%prep
%setup -q -n lz4-%{version}
#only needed on centos (a fairly brutal solution):
%if 0%{?fedora:1}
#should work... until things get out of sync again
%else
%patch0 -p1
%endif

%if 0%{?with_python3}
rm -rf %{py3dir}
cp -a . %{py3dir}
%endif

%build
export CFLAGS="%{optflags}"
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
rm -rf %{buildroot}

%files
%defattr(-,root,root,-)
%doc README.rst
%{python2_sitearch}/lz4*

%if 0%{?with_python3}
%files -n python3-lz4
%defattr(-,root,root)
%{python3_sitearch}/lz4*
%endif

%changelog
* Sat Jun 11 2017 Antoine Martin <antoine@nagafix.co.uk> - 0.10.0-1
- New upstream release

* Sun May 14 2017 Antoine Martin <antoine@nagafix.co.uk> - 0.9.1-1
- New upstream release

* Mon Mar 13 2017 Antoine Martin <antoine@nagafix.co.uk> - 0.9.0-1
- New upstream release

* Sat Dec 24 2016 Antoine Martin <antoine@nagafix.co.uk> - 0.8.2-3
- conflict with old package name

* Mon Jul 18 2016 Antoine Martin <antoine@nagafix.co.uk> - 0.8.2-2
- new package name, obsolete the old one

* Fri Jun 17 2016 Antoine Martin <antoine@nagafix.co.uk> - 0.8.2-1
- New upstream release

* Fri Apr 29 2016 Antoine Martin <antoine@nagafix.co.uk> - 0.8.1-1
- New upstream release

* Thu Jan 07 2016 Antoine Martin <antoine@nagafix.co.uk> - 0.8.0.rc2-1
- Merge "release the GIL" patch

* Mon Jul 13 2015 Antoine Martin <antoine@nagafix.co.uk> - 0.8.0.rc1-1
- Pre-release testing

* Sat Jun 27 2015 Antoine Martin <antoine@nagafix.co.uk> - 0.7.0-2
- Add version information to package

* Wed Sep 17 2014 Antoine Martin <antoine@nagafix.co.uk> - 0.7.0-1
- Add Python3 package

* Mon Jul 07 2014 Antoine Martin <antoine@devloop.org.uk> - 0.7.0-0
- New upstream release

* Fri Mar 21 2014 Antoine Martin <antoine@devloop.org.uk> - 0.6.1-0
- New upstream release

* Wed Jan 15 2014 Antoine Martin <antoine@devloop.org.uk> - 0.6.0-1.0
- Fix version in specfile
- build debuginfo packages

* Sun Dec 8 2013 Stephen Gauthier <sgauthier@spikes.com> - 0.6.0-0
- First version for Fedora Extras
