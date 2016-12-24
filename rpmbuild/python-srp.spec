#
# spec file for package python-srp
#
# Copyright (c) 2015
#

#this spec file is for both Fedora and CentOS
#only Fedora has Python3 at present:
%if 0%{?fedora}
%define with_python3 0
%endif

%{!?__python2: %global __python2 python2}
%{!?__python3: %define __python3 python3}
%{!?python2_sitearch: %global python2_sitearch %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))")}
%{!?python3_sitearch: %global python3_sitearch %(%{__python3} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))")}


Name:           python2-srp
Version:        1.0.5
Release:        2%{?dist}
URL:            http://pythonhosted.org/srp/
Summary:        Secure Remote Password for python
License:        MIT
Group:          Development/Languages/Python
Source:         https://pypi.python.org/packages/source/s/srp/srp-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-build
BuildRequires:  python-devel
BuildRequires:  openssl-devel
BuildRequires:  python-setuptools
Requires:       openssl
Provides:       python-srp
Obsoletes:      python-srp
Conflicts:      python-srp
Patch0:         python-srp-py3k.patch

%description
This package provides an implementation of the Secure Remote Password protocol (SRP).

%if 0%{?with_python3}
%package -n python3-srp
Summary:        Secure Remote Password for Python3
Group:          Development/Languages/Python

%description -n python3-srp
This package provides a Python 3 implementation of the Secure Remote Password protocol (SRP).
%endif

%prep
%setup -q -n srp-%{version}

%if 0%{?with_python3}
rm -rf %{py3dir}
cp -a . %{py3dir}
pushd %{py3dir}
%patch0 -p1
popd
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
%{python2_sitearch}/srp*

%if 0%{?with_python3}
%files -n python3-srp
%defattr(-,root,root)
%{python3_sitearch}/srp*
%endif

%changelog
* Sat Dec 24 2016 Antoine Martin <antoine@devloop.org.uk> - 1.0.5-2
- try harder to supersede the old package name

* Sun Jul 17 2016 Antoine Martin <antoine@nagafix.co.uk> - 1.0.5-1
- rename and obsolete old python package name

* Thu Jan 07 2016 Antoine Martin <antoine@nagafix.co.uk> - 1.0.5-0
- Initial packaging
