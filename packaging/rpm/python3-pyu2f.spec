# This file is part of Xpra.
# Copyright (C) 2018-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

%define _disable_source_fetch 0
%if "%{getenv:PYTHON3}" == ""
%global python3 python3
%else
%global python3 %{getenv:PYTHON3}
%undefine __pythondist_requires
%undefine __python_requires
%define python3_sitelib %(%{python3} -Ic "from sysconfig import get_path; print(get_path('purelib').replace('/usr/local/', '/usr/'))" 2> /dev/null)
%define python3_sitearch %(%{python3} -Ic "from sysconfig import get_path; print(get_path('platlib').replace('/usr/local/', '/usr/'))" 2> /dev/null)
%endif

#this is a pure python package so debug is meaningless here:
%define debug_package %{nil}

Name:           %{python3}-pyu2f
Version:        0.1.5
Release:        3
URL:            https://github.com/google/pyu2f
Summary:        Python3 based U2F host library for Linux
License:        BSD
Group:          Development/Libraries/Python
Source0:		https://files.pythonhosted.org/packages/source/p/pyu2f/pyu2f-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-build
Requires:       %{python3}
BuildRequires:  %{python3}-devel

%description
pyu2f provides functionality for interacting with a U2F device over USB.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "a3caa3a11842fc7d5746376f37195e6af5f17c0a15737538bb1cebf656fb306b" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n pyu2f-0.1.5

%build
%{python3} ./setup.py build

%install
%{python3} ./setup.py install --prefix=%{_prefix} --root=%{buildroot}
rm -fr %{buildroot}%{python3_sitearch}/UNKNOWN-*.egg-info

%clean
rm -rf %{buildroot}

%files
%defattr(-,root,root)
%{python3_sitelib}/pyu2f/*
%{python3_sitelib}/pyu2f-%{version}-py3*.egg-info/*

%changelog
* Wed Feb 17 2021 Antoine Martin <antoine@xpra.org> - 0.1.5-3
- verify source checksum

* Wed Feb 17 2021 Antoine Martin <antoine@xpra.org> - 0.1.5-2
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
