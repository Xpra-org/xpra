# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

%define _disable_source_fetch 0
%if "%{getenv:PYTHON3}" == ""
%if 0%{?fedora}
echo this must be built for the not default python3
exit
%endif
%global python3 python3
%global py3rpmname python3
%else
%global python3 %{getenv:PYTHON3}
%global py3rpmname %(echo %{python3} | sed 's/t$/-freethreading/')
%undefine __pythondist_requires
%undefine __python_requires
%define python3_sitelib %(%{python3} -Ic "from sysconfig import get_path; print(get_path('purelib').replace('/usr/local/', '/usr/'))" 2> /dev/null)
%endif

%global pypi_name packaging
Name:           %{py3rpmname}-%{pypi_name}
Version:        26.2
Release:        1%{?dist}
Summary:        Core utilities for Python packages
License:        ASL 2.0 or BSD
URL:            https://github.com/pypa/packaging
Source0:        https://files.pythonhosted.org/packages/source/p/%{pypi_name}/%{pypi_name}-%{version}.tar.gz
BuildArch:      noarch
Requires:       %{py3rpmname}
BuildRequires:  %{py3rpmname}-devel
BuildRequires:  %{py3rpmname}-pip
BuildRequires:  %{py3rpmname}-setuptools
BuildRequires:  %{py3rpmname}-wheel


%description -n %{py3rpmname}-%{pypi_name}
Reusable core utilities for various Python Packaging interoperability
specifications: version handling, specifiers, markers, requirements, tags,
and utilities.

It is used at build time by setuptools / wheel: the bdist_wheel command does
"from packaging import tags", so this package must be available before any
wheel is built for the matching python interpreter.


%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "ff452ff5a3e828ce110190feff1178bb1f2ea2281fa2075aadb987c2fb221661" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%autosetup -n %{pypi_name}-%{version}
# packaging uses the flit_core build backend, which is not packaged for the
# alternative python interpreters we build against - patch it to setuptools so
# we can build fully offline (as we do for python3-fido2):
sed -i \
    -e 's|^requires = \[.*flit_core.*\]|requires = ["setuptools","wheel"]|' \
    -e 's|^build-backend = "flit_core.buildapi"|build-backend = "setuptools.build_meta"|' \
    -e 's|^dynamic = \["version"\]|version = "%{version}"|' \
    pyproject.toml
# centos9's / el8's old setuptools cannot parse the PEP 639 SPDX license string,
# convert it to the legacy table form which both old and new setuptools accept:
sed -i 's|^license = "Apache-2.0 OR BSD-2-Clause"$|license = {text = "Apache-2.0 OR BSD-2-Clause"}|' pyproject.toml
# packaging uses a src/ layout - tell setuptools where to find the package:
cat >> pyproject.toml <<EOF

[tool.setuptools.packages.find]
where = ["src"]
EOF


%build
%{python3} -m pip wheel . --no-deps --no-build-isolation


%install
%{python3} -m pip install . --no-deps --no-build-isolation --root %{buildroot}


%files -n %{py3rpmname}-%{pypi_name}
%license LICENSE.APACHE LICENSE.BSD
%doc README.rst
%{python3_sitelib}/%{pypi_name}/
%{python3_sitelib}/%{pypi_name}-%{version}.dist-info/


%changelog
* Tue Jun 09 2026 Antoine Martin <antoine@xpra.org> - 26.2-1
- initial packaging for xpra (split out of python3-wheel)
