# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

%define _disable_source_fetch 0
%if "%{getenv:PYTHON3}" == ""
%global python3 python3
%global py3rpmname python3
%else
%global python3 %{getenv:PYTHON3}
%global py3rpmname %(echo %{python3} | sed 's/t$/-freethreading/')
%undefine __pythondist_requires
%undefine __python_requires
%define python3_sitelib %(%{python3} -Ic "from sysconfig import get_path; print(get_path('purelib').replace('/usr/local/', '/usr/'))" 2> /dev/null)
%define python3_sitearch %(%{python3} -Ic "from sysconfig import get_path; print(get_path('platlib').replace('/usr/local/', '/usr/'))" 2> /dev/null)
%endif

#this is a pure python package so debug is meaningless here:
%define debug_package %{nil}

Name:           %{py3rpmname}-fido2
Version:        2.1.1
Release:        1
URL:            https://github.com/Yubico/python-fido2
Summary:        For communicating with a FIDO device over USB as well as verifying attestation and assertion signatures.
License:        BSD
Group:          Development/Libraries/Python
Source0:		https://files.pythonhosted.org/packages/source/f/fido2/fido2-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-build
Requires:       %{py3rpmname}
Requires:       libfido2
BuildRequires:  %{py3rpmname}-devel
BuildRequires:  %{py3rpmname}-pip
BuildRequires:  %{py3rpmname}-setuptools
BuildRequires:  %{py3rpmname}-wheel
BuildRequires:  libfido2-devel

%description
Provides library functionality for communicating with a FIDO device over USB as well as verifying attestation and assertion signatures.
This library aims to support the FIDO U2F and FIDO 2 protocols for communicating with a USB authenticator via the Client-to-Authenticator Protocol (CTAP 1 and 2).

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "f1379f845870cc7fc64c7f07323c3ce41e8c96c37054e79e0acd5630b3fec5ac" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n fido2-%{version}
# fido2 uses poetry-core as build backend; patch to setuptools so we don't
# need a specific poetry-core version and can build fully offline:
sed -i \
    -e 's|requires = \["poetry-core"\]|requires = ["setuptools","wheel"]|' \
    -e 's|build-backend = "poetry.core.masonry.api"|build-backend = "setuptools.build_meta"|' \
    -e 's|, *email *= *"[^"]*"||g' \
    -e '/^readme *=/d' \
    pyproject.toml

%build
%{python3} -m pip wheel . --no-deps --no-build-isolation

%install
rm -rf %{buildroot}
%{python3} -m pip install . --no-deps --no-build-isolation --root %{buildroot}

%clean
rm -rf %{buildroot}

%files
%defattr(-,root,root)
%{python3_sitelib}/fido2/
%{python3_sitelib}/fido2-%{version}*

%changelog
* Mon Apr 06 2026 Antoine Martin <antoine@xpra.org> - 2.1.1-1
- initial packaging for xpra
