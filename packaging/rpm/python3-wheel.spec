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

%global pypi_name wheel
Name:           %{py3rpmname}-%{pypi_name}
Release:        4%{?dist}
Version:        0.47.0
Source0:        https://files.pythonhosted.org/packages/source/w/%{pypi_name}/%{pypi_name}-%{version}.tar.gz
Summary:        Built-package format for Python
Requires:       %{py3rpmname}
BuildRequires:  %{py3rpmname}-devel
BuildRequires:  %{py3rpmname}-setuptools
License:        MIT
URL:            https://github.com/pypa/wheel
BuildArch:      noarch


%description -n %{py3rpmname}-%{pypi_name}
Wheel is the reference implementation of the Python wheel packaging standard,
as defined in PEP 427.

It has two different roles:

 1. A setuptools extension for building wheels that provides the bdist_wheel
    setuptools command.
 2. A command line tool for working with wheel files.


%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "cc72bd1009ba0cf63922e28f94d9d83b920aa2bb28f798a31d0691b02fa3c9b3" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%autosetup -n %{pypi_name}-%{version} -p1
# centos9's old setuptools cannot parse the PEP 639 SPDX license string,
# convert it to the legacy table form which both old and new setuptools accept:
sed -i 's/^license = "MIT"$/license = {text = "MIT"}/' pyproject.toml


%build
%{python3} ./setup.py build


%install
PYTHONPATH="%{buildroot}%{python3_sitelib}" %{python3} ./setup.py install --prefix %{buildroot}/usr
# we don't want that unusable egg directory
mv %{buildroot}%{python3_sitelib}/%{pypi_name}*egg/%{pypi_name} %{buildroot}%{python3_sitelib}/ || true
rm -fr %{buildroot}%{python3_sitelib}/%{pypi_name}*egg
# setuptools may pull in 'packaging' as a build-time dependency and drop it as
# a standalone egg - we don't ship it here (it is built separately, see
# python3-packaging.spec):
rm -fr %{buildroot}%{python3_sitelib}/packaging*egg
# various files we don't care about,
# that may get generated on some build variants:
rm -fr %{buildroot}%{python3_sitelib}/__pycache__
rm -f %{buildroot}%{python3_sitelib}/easy-install.pth
rm -f %{buildroot}%{python3_sitelib}/site.py
rm -fr %{buildroot}%{python3_sitelib}/%{pypi_name}-*.egg-info
# setuptools and / or pkg_resources generate an unusable mess,
# so use this wrapper instead:
mkdir -p %{buildroot}%{_bindir} >& /dev/null
echo "#!/usr/bin/python%{python3_version}" > %{buildroot}%{_bindir}/%{pypi_name}
echo "from wheel.__main__ import main" >> %{buildroot}%{_bindir}/%{pypi_name}
echo "main()" >> %{buildroot}%{_bindir}/%{pypi_name}
%if "%{python3}" != "python3"
mv %{buildroot}%{_bindir}/%{pypi_name} %{buildroot}%{_bindir}/%{pypi_name}-%{python3_version}
%endif

%files -n %{py3rpmname}-%{pypi_name}
%license LICENSE.txt
%doc README.rst
%{_bindir}/%{pypi_name}*
%{python3_sitelib}/%{pypi_name}/


%changelog
* Tue Jun 09 2026 Antoine Martin <antoine@xpra.org> - 0.47.0-4
- build 'packaging' as a separate package (python3-packaging) instead of bundling it
- drop stale bundled(packaging) Provides and ASL/BSD license clause: wheel does not
  vendor 'packaging', it imports the top-level package

* Mon Jun 08 2026 Antoine Martin <antoine@xpra.org> - 0.47.0-3
- ship 'packaging' on el8 (required by wheel at runtime, no separate package there)

* Mon Jun 08 2026 Antoine Martin <antoine@xpra.org> - 0.47.0-2
- convert PEP 639 SPDX license string to legacy table form for centos9's old setuptools

* Fri May 08 2026 Antoine Martin <antoine@xpra.org> - 0.47.0-1
- new upstream release

* Mon Jan 06 2025 Antoine Martin <antoine@xpra.org> - 0.45.1-2
- new upstream release

* Thu Apr 25 2024 Antoine Martin <antoine@xpra.org> - 0.43.0-1
- new upstream release

* Sun Nov 19 2023 Antoine Martin <antoine@xpra.org> - 0.41.3-2
- get rid of unusable egg directory

* Sun Nov 12 2023 Antoine Martin <antoine@xpra.org> - 0.41.3-1
- new upstream release

* Mon Oct 02 2023 Antoine Martin <antoine@xpra.org> - 0.41.2-1
- new upstream release
