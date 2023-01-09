%define _disable_source_fetch 0
%global srcname setuptools

Name:           python2-%{srcname}
Version:        44.1.1
Release:        1%{?dist}
Summary:        The blessed package to manage your versions by scm tags
License:        MIT
URL:            http://pypi.python.org/pypi/%{srcname}
Source0:        https://files.pythonhosted.org/packages/b2/40/4e00501c204b457f10fe410da0c97537214b2265247bc9a5bc6edd55b9e4/%{srcname}-%{version}.zip
BuildArch:      noarch
BuildRequires:  python2-devel

%description
Setuptools_scm handles managing your python package versions in scm metadata.
It also handles file finders for the suppertes scms.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "c67aa55db532a0dadc4d2e20ba9961cbd3ccc84d544e9029699822542b5a476b" ]; then
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
%doc README.rst
%{python2_sitelib}/*
%{_bindir}/easy_install
%{_bindir}/easy_install-2.7

%changelog
* Mon Jan 09 2023 Antoine Martin <antoine@xpra.org> - 44.1.1-1
- package for xpra 3.1 builds
