%define _disable_source_fetch 0
%if "%{getenv:PYTHON3}" == ""
echo this must be built for the not default python3
exit
%global python3 python3
%else
%global python3 %{getenv:PYTHON3}
%undefine __pythondist_requires
%undefine __python_requires
%define python3_sitelib %(%{python3} -Ic "from sysconfig import get_path; print(get_path('purelib').replace('/usr/local/', '/usr/'))" 2> /dev/null)
%define python3_sitearch %(%{python3} -Ic "from sysconfig import get_path; print(get_path('platlib').replace('/usr/local/', '/usr/'))" 2> /dev/null)
%endif
%define python3_version %(%{python3} -c 'import sys;vi=sys.version_info;print(f"{vi[0]}.{vi[1]}")')

%global pypi_name wheel
Name:           %{python3}-%{pypi_name}
Version:        0.41.3
Release:        1%{?dist}
Source0:        https://files.pythonhosted.org/packages/fb/d0/0b4c18a0b85c20233b0c3bc33f792aefd7f12a5832b4da77419949ff6fd9/%{pypi_name}-%{version}.tar.gz
Summary:        Built-package format for Python
Provides:       bundled(python3dist(packaging)) = 20.9
BuildRequires:  %{python3}-devel
BuildRequires:  %{python3}-setuptools
License:        MIT and (ASL 2.0 or BSD)
URL:            https://github.com/pypa/wheel
BuildArch:      noarch


%description -n %{python3}-%{pypi_name}
Wheel is the reference implementation of the Python wheel packaging standard,
as defined in PEP 427.

It has two different roles:

 1. A setuptools extension for building wheels that provides the bdist_wheel
    setuptools command.
 2. A command line tool for working with wheel files.}


%prep
%autosetup -n %{pypi_name}-%{version} -p1


%build
%py3_build


%install
%{python3} ./setup.py install --prefix %{buildroot}/usr
mv %{buildroot}%{_bindir}/%{pypi_name} %{buildroot}%{_bindir}/%{pypi_name}-%{python3_version}

%files -n %{python3}-%{pypi_name}
%license LICENSE.txt
%doc README.rst
%{_bindir}/%{pypi_name}-%{python3_version}
%{python3_sitelib}/%{pypi_name}*/


%changelog
* Sun Nov 12 2023 Antoine Martin <antoine@xpra.org> - 0.41.3-1
- new upstream release

* Mon Oct 02 2023 Antoine Martin <antoine@xpra.org> - 0.41.2-1
- new upstream release
