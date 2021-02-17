# This file is part of Xpra.
# Copyright (C) 2018-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

%{!?__python3: %define __python3 python3}
%{!?python3_sitearch: %global python3_sitearch %(%{__python3} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))")}

#this is a pure python package so debug is meaningless here:
%define debug_package %{nil}

Name:           python3-pyu2f
Version:        0.1.5
Release:        2
URL:            https://github.com/google/pyu2f
Summary:        Python3 based U2F host library for Linux
License:        BSD
Group:          Development/Libraries/Python
Source:			https://files.pythonhosted.org/packages/29/b5/c1209e6cb77647bc2c9a6a1a953355720f34f3b006b725e303c70f3c0786/pyu2f-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-build
BuildRequires:  python3-devel

%description
pyu2f provides functionality for interacting with a U2F device over USB.

%prep
%setup -q -n pyu2f-0.1.5

%build
%{__python3} ./setup.py build

%install
%{__python3} ./setup.py install --prefix=%{_prefix} --root=%{buildroot}

%clean
rm -rf %{buildroot}

%files
%defattr(-,root,root)
%{python3_sitelib}/pyu2f/*
%{python3_sitelib}/pyu2f-%{version}-py3*.egg-info/*

%changelog
* Wed Feb 17 2020 Antoine Martin <antoine@xpra.org> - 0.1.5-2
- add missing python3-devel build dependency, was causing python3_sitelib macro to fail

* Sat Oct 31 2020 Antoine Martin <antoine@xpra.org> - 0.1.5-1
- new upstream release

* Thu Sep 26 2019 Antoine Martin <antoine@xpra.org> - 0.1.4-4
- drop support for python2

* Wed Sep 25 2019 Antoine Martin <antoine@xpra.org> - 0.1.4-3
- build for CentOS 8

* Thu Jun 28 2018 Antoine Martin <antoine@xpra.org> - 0.1.4-2
- fix provides tag

* Sat Mar 24 2018 Antoine Martin <antoine@xpra.org> - 0.1.4-1
- new upstream release

* Sat Mar 24 2018 Antoine Martin <antoine@xpra.org> - 0.1.2
- initial packaging for xpra
