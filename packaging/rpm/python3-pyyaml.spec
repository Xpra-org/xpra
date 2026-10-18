%define _disable_source_fetch 0
%if "%{getenv:PYTHON3}" == ""
%global python3 python3
%global py3rpmname python3
%else
%global python3 %{getenv:PYTHON3}
%global py3rpmname %(echo %{python3} | sed 's/t$/-freethreading/')
%undefine __pythondist_requires
%undefine __python_requires
%define python3_sitearch %(%{python3} -Ic "from sysconfig import get_path; print(get_path('platlib').replace('/usr/local/', '/usr/'))" 2> /dev/null)
%endif

Name:           %{py3rpmname}-pyyaml
Version:        6.0.3
Release:        1%{?dist}
Summary:        YAML parser and emitter for Python
Group:          Development/Languages
License:        MIT
URL:            https://pyyaml.org/
Source0:        https://files.pythonhosted.org/packages/source/p/pyyaml/pyyaml-%{version}.tar.gz
BuildRequires:  gcc
BuildRequires:  libyaml-devel
BuildRequires:  %{py3rpmname}-devel
BuildRequires:  %{py3rpmname}-setuptools
BuildRequires:  %{py3rpmname}-cython
Requires:       %{py3rpmname}
Provides:       %{py3rpmname}-PyYAML = %{version}-%{release}
Provides:       %{py3rpmname}-yaml = %{version}-%{release}

%description
PyYAML is a YAML parser and emitter for Python, with Unicode support,
standard YAML tags, and Python-specific tags for representing Python objects.
This package includes the LibYAML bindings for faster parsing and emitting.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "d76623373421df22fb4cf8817020cbb7ef15c725b9d5e45f17e189bfc384190f" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n pyyaml-%{version}

%build
CFLAGS="$RPM_OPT_FLAGS" %{python3} setup.py --with-libyaml build

%install
%{python3} setup.py --with-libyaml install -O1 --skip-build --root %{buildroot}

%check
PYTHONPATH=%{buildroot}%{python3_sitearch}:tests/legacy_tests %{python3} -c "import yaml, test_all; assert yaml.__with_libyaml__; assert test_all.main([])"

%files
%license LICENSE
%doc README.md CHANGES
%{python3_sitearch}/yaml/
%{python3_sitearch}/_yaml/
%{python3_sitearch}/PyYAML-%{version}-py*.egg-info

%changelog
* Sun Oct 18 2026 Antoine Martin <antoine@xpra.org> - 6.0.3-1
- initial packaging
