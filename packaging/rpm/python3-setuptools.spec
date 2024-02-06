%global srcname setuptools
%define _disable_source_fetch 0
%if "%{getenv:PYTHON3}" == ""
%global python3 python3
%else
%global python3 %{getenv:PYTHON3}
%undefine __pythondist_requires
%undefine __python_requires
%define python3_sitelib %(%{python3} -Ic "from sysconfig import get_path; print(get_path('purelib').replace('/usr/local/', '/usr/'))" 2> /dev/null)
%endif

Name:           %{python3}-%{srcname}
Version:        68.2.2
Release:        1%{?dist}
Summary:        The blessed package to manage your versions by scm tags
License:        MIT
URL:            http://pypi.python.org/pypi/%{srcname}
Source0:        https://files.pythonhosted.org/packages/source/s/%{srcname}/%{srcname}-%{version}.tar.gz
BuildArch:      noarch
BuildRequires:  %{python3}-devel
Requires:       %{python3}

%description
Setuptools_scm handles managing your python package versions in scm metadata.
It also handles file finders for the suppertes scms.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "4ac1475276d2f1c48684874089fefcd83bd7162ddaafb81fac866ba0db282a87" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%autosetup -n %{srcname}-%{version}

%build
%{python3} setup.py build

%install
%{python3} setup.py install --root %{buildroot}

%files
%license LICENSE
%doc README.rst
%{python3_sitelib}/*

%changelog
* Tue Oct 17 2023 Antoine Martin <antoine@xpra.org> - 68.2.2-1
- new upstream release

* Fri Jul 28 2023 Antoine Martin <antoine@xpra.org> - 68.0.0-1
- package for xpra 6 builds
