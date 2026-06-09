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
%define python3_version %(%{python3} -c 'import sys;vi=sys.version_info;print(f"{vi[0]}.{vi[1]}")' 2> /dev/null)

%global pypi_name pip
Name:           %{py3rpmname}-%{pypi_name}
Version:        26.1.2
Release:        1%{?dist}
Summary:        The PyPA recommended tool for installing Python packages
License:        MIT
URL:            https://github.com/pypa/pip
Source0:        https://files.pythonhosted.org/packages/source/p/%{pypi_name}/%{pypi_name}-%{version}.tar.gz
BuildArch:      noarch
Requires:       %{py3rpmname}
BuildRequires:  %{py3rpmname}-devel
BuildRequires:  %{py3rpmname}-setuptools
BuildRequires:  %{py3rpmname}-wheel


%description -n %{py3rpmname}-%{pypi_name}
pip is the package installer for Python. It is used here to build the other
python packages we ship for the alternative interpreter ("pip wheel" /
"pip install"), so it must be available before those are built.


%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "f49cd134c61cf2fd75e0ce2676db03e4054504a5a4986d00f8299ae632dc4605" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%autosetup -n %{pypi_name}-%{version}
# pip uses the flit_core build backend, which is not packaged for the
# alternative python interpreters we build against - patch it to setuptools so
# we can build fully offline (as we do for python3-fido2 / python3-packaging):
sed -i \
    -e 's|^requires = \[.*flit[-_]core.*\]|requires = ["setuptools","wheel"]|' \
    -e 's|^build-backend = "flit_core.buildapi"|build-backend = "setuptools.build_meta"|' \
    -e 's|^dynamic = \["version"\]|version = "%{version}"|' \
    pyproject.toml
# old setuptools (el8 / centos9) cannot parse the PEP 639 SPDX license string,
# convert it to the legacy table form and drop the PEP 639 license-files list:
sed -i 's|^license = "MIT"$|license = {text = "MIT"}|' pyproject.toml
sed -i '/^license-files = \[/,/^]/d' pyproject.toml
# pip uses a src/ layout and bundles non-python data files (certifi/cacert.pem,
# distlib launchers, vendored licenses, ...) - flit ships everything in the
# package tree automatically, but setuptools needs to be told where the package
# is and which data files to include:
cat >> pyproject.toml <<EOF

[tool.setuptools]
include-package-data = true

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
"*" = ["*.pem","*.typed","*.pyi","*.json","*.exe","*.txt","*.md","*.rst","*.js","LICENSE*","COPYING*"]
EOF
# register bdist_wheel explicitly: the setuptools we build for el8 (< 70.1) has
# no integrated bdist_wheel and our python3-wheel ships without entry points, so
# the command would otherwise be unavailable ("invalid command 'bdist_wheel'"):
cat > setup.py <<EOF
import setuptools
try:
    from setuptools.command.bdist_wheel import bdist_wheel
except ImportError:
    try:
        from wheel._bdist_wheel import bdist_wheel
    except ImportError:
        from wheel.bdist_wheel import bdist_wheel
setuptools.setup(cmdclass={"bdist_wheel": bdist_wheel})
EOF


%build
# build the wheel with setuptools directly (no pip is available for this
# interpreter yet - that is the whole point of this package):
%{python3} setup.py bdist_wheel -d dist


%install
# unpack the wheel built above with the in-tree pip (it only installs files and
# generates the launchers - it does not rebuild, so no build backend is needed):
PYTHONPATH=src %{python3} -m pip install dist/%{pypi_name}-%{version}-*.whl \
    --no-deps --ignore-installed --no-warn-script-location \
    --root %{buildroot} --prefix /usr
%if "%{python3}" != "python3"
# only ship the version-suffixed launcher for the alternative interpreter;
# the unversioned pip / pip3 would clash with the system python3-pip:
rm -f %{buildroot}%{_bindir}/pip %{buildroot}%{_bindir}/pip3
%endif


%files -n %{py3rpmname}-%{pypi_name}
%license LICENSE.txt
%doc README.rst
%{_bindir}/pip*
%{python3_sitelib}/%{pypi_name}/
%{python3_sitelib}/%{pypi_name}-%{version}.dist-info/


%changelog
* Tue Jun 09 2026 Antoine Martin <antoine@xpra.org> - 26.1.2-1
- initial packaging for xpra (build dependency for the alternative interpreters)
