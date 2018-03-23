# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

%{!?__python2: %global __python2 python2}
%{!?__python3: %define __python3 python3}
%{!?python2_sitearch: %global python2_sitearch %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))")}
%{!?python3_sitearch: %global python3_sitearch %(%{__python3} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))")}

#this is a pure python package so debug is meaningless here:
%define debug_package %{nil}

Name:           python2-pyu2f
Version:        0.1.2
Release:        1
URL:            https://github.com/google/pyu2f
Summary:        Python based U2F host library for Linux
License:        BSD
Group:          Development/Libraries/Python
Source:        	https://pypi.python.org/packages/5e/84/12044502227f40ed51e40997bf1a86e07504a0cf0fcc3bdefccc78ce93aa/pyu2f-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-build
Provides:       python-pynvml

%description
pyu2f provides functionality for interacting with a U2F device over USB.

%if 0%{?fedora}
%package -n python3-pyu2f
Summary:        Python3 based U2F host library for Linux
License:        BSD
Group:          Development/Libraries/Python

%description -n python3-pyu2f
pyu2f provides functionality for interacting with a U2F device over USB.
%endif

%prep
%setup -q -n pyu2f-0.1.2

%build
%{__python2} ./setup.py build
%if 0%{?fedora}
rm -fr %{py3dir}
cp -r . %{py3dir}
pushd %{py3dir}
%{__python3} ./setup.py build
popd
%endif

%install
%{__python2} ./setup.py install --prefix=%{_prefix} --root=%{buildroot}
%if 0%{?fedora}
pushd %{py3dir}
%{__python3} ./setup.py install --prefix=%{_prefix} --root=%{buildroot}
popd
%endif

%clean
rm -rf %{buildroot}

%files
%defattr(-,root,root)
%{python2_sitelib}/pyu2f/*
%{python2_sitelib}/pyu2f-%{version}-py2*.egg-info/*

%if 0%{?fedora}
%files -n python3-pyu2f
%defattr(-,root,root)
%{python3_sitelib}/pyu2f/*
%{python3_sitelib}/pyu2f-%{version}-py3*.egg-info/*
%endif

%changelog
* Sat Mar 24 2018 Antoine Martin <antoine@devloop.org.uk> - 0.1.2
- initial packaging for xpra
