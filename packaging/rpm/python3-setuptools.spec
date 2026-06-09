%global srcname setuptools
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
%endif

Name:           %{py3rpmname}-%{srcname}
Version:        82.0.1
Release:        1%{?dist}
Summary:        The blessed package to manage your versions by scm tags
License:        MIT
URL:            http://pypi.python.org/pypi/%{srcname}
Source0:        https://files.pythonhosted.org/packages/source/s/%{srcname}/%{srcname}-%{version}.tar.gz
BuildArch:      noarch
BuildRequires:  %{py3rpmname}-devel
Requires:       %{py3rpmname}

%description
Setuptools_scm handles managing your python package versions in scm metadata.
It also handles file finders for the suppertes scms.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "7d872682c5d01cfde07da7bccc7b65469d3dca203318515ada1de5eda35efbf9" ]; then
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
* Tue Jun 09 2026 Antoine Martin <antoine@xpra.org> - 82.0.1-1
- new upstream release (integrated bdist_wheel, vendored packaging)

* Tue Oct 17 2023 Antoine Martin <antoine@xpra.org> - 68.2.2-1
- new upstream release

* Fri Jul 28 2023 Antoine Martin <antoine@xpra.org> - 68.0.0-1
- package for xpra 6 builds
