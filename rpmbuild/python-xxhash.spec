#
# spec file for package python-xxhash
#
# Copyright (c) 2016 Antoine Martin <antoine@devloop.org.uk>
#

# TODO: make RPM for xxhash and link against it...

#this spec file is for both Fedora and CentOS
#only Fedora has Python3 at present:
%if 0%{?fedora}%{?el8}
%define with_python3 1
%endif

%{!?__python2: %global __python2 python2}
%{!?__python3: %define __python3 python3}
%{!?python2_sitearch: %global python2_sitearch %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))")}
%{!?python3_sitearch: %global python3_sitearch %(%{__python3} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))")}


Name:           python2-xxhash
Version:        1.4.2
Release:        1%{?dist}
URL:            https://github.com/ifduyue/python-xxhash
Summary:        xxhash Bindings for Python
License:        BSD
Group:          Development/Languages/Python
Source:         https://files.pythonhosted.org/packages/7a/88/b7f2ce590944d6e879182ecf971f3f2562cd0db23b2de2f1d3110e4ec1b3/xxhash-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-build
%if 0%{?fedora}%{?el8}
BuildRequires:  python2-devel
BuildRequires:  python2-setuptools
%else
BuildRequires:  python-devel
BuildRequires:  python-setuptools
%endif
Provides:		python-xxhash

%description
This package provides Python2 bindings for the xxhash extremely fast hash algorithm.
https://github.com/Cyan4973/xxHash by Yann Collet.

%if 0%{?with_python3}
%package -n python3-xxhash
Summary:        xxhash Bindings for Python3
Group:          Development/Languages/Python

%description -n python3-xxhash
This package provides Python3 bindings for the xxhash extremely fast hash algorithm
https://github.com/Cyan4973/xxHash by Yann Collet.
%endif

%prep
%setup -q -n xxhash-%{version}
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
%{python2_sitearch}/xxhash*

%if 0%{?with_python3}
%files -n python3-xxhash
%defattr(-,root,root)
%{python3_sitearch}/xxhash*
%endif

%changelog
* Sun Oct 13 2019 Antoine Martin <antoine@nagafix.co.uk> - 1.4.2-1
- new upstream release

* Fri Oct 11 2019 Antoine Martin <antoine@nagafix.co.uk> - 1.4.1-1
- new upstream release

* Sun Aug 05 2018 Antoine Martin <antoine@nagafix.co.uk> - 1.2.0-1
- new upstream release

* Thu Mar 02 2017 Antoine Martin <antoine@nagafix.co.uk> - 1.0.1-1
- new upstream release

* Fri Feb 10 2017 Antoine Martin <antoine@nagafix.co.uk> - 0.6.3-1
- new upstream release

* Sat Aug 20 2016 Antoine Martin <antoine@nagafix.co.uk> - 0.6.1-1
- initial packaging
