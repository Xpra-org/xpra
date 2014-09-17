#
# spec file for package python-lz4
#
# Copyright (c) 2013-2014
#

#this spec file is for both Fedora and CentOS
#only Fedora has Python3 at present:
%if 0%{?fedora}
%define with_python3 1
%endif

%if 0%{?rhel} && 0%{?rhel} <= 6
%{!?__python2: %global __python2 /usr/bin/python2}
%{!?python2_sitearch: %global python2_sitearch %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))")}
%endif

Name:           python-lz4
Version:        0.7.0
Release:        0%{?dist}
URL:            https://github.com/steeve/python-lz4
Summary:        LZ4 Bindings for Python
License:        GPLv2+
Group:          Development/Languages/Python
Source:         https://pypi.python.org/packages/source/l/lz4/lz4-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-build
BuildRequires:  python-devel
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

#FIXME: this is fugly
%if %(egrep -q 'Fedora release 2|CentOS Linux release 7|RedHat Linux release 7' /etc/redhat-release && echo 0 || echo 1)
%debug_package
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
