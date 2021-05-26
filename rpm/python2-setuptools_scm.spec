%define _disable_source_fetch 0
%global srcname setuptools_scm

Name:           python2-%{srcname}
Version:        1.17.0
Release:        1%{?dist}
Summary:        The blessed package to manage your versions by scm tags
License:        MIT
URL:            http://pypi.python.org/pypi/%{srcname}
Source0:        https://files.pythonhosted.org/packages/a7/52/5f84da9ee2780682795550ddea20bec3e604a8a82600f4e5d3a6ca0bcbcd/%{srcname}-%{version}.tar.gz
BuildArch:      noarch
BuildRequires:  python2-devel
BuildRequires:  python2-setuptools

%description
Setuptools_scm handles managing your python package versions in scm metadata.
It also handles file finders for the suppertes scms.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "70a4cf5584e966ae92f54a764e6437af992ba42ac4bca7eb37cc5d02b98ec40a" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%autosetup -n %{srcname}-%{version}

%build
%{__python2} setup.py build

%install
%{__python2} setup.py install --root %{buildroot}

%files
%license LICENSE
%doc CHANGELOG.rst README.rst
%{python2_sitelib}/*

%changelog
* Wed May 26 2021 Antoine Martin <antoine@xpra.org> - 1.17.0-1
- package for xpra 3.1 builds
