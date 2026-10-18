%define _disable_source_fetch 0
%define __python_requires %{nil}
%define __pythondist_requires %{nil}
Autoreq: 0
%global debug_package %{nil}

Name:           python3-platformdirs
Version:        2.4.0
Release:        1%{?dist}
Summary:        Platform-specific application directories for Python
Group:          Development/Languages
License:        MIT
URL:            https://github.com/platformdirs/platformdirs
Source0:        https://files.pythonhosted.org/packages/source/p/platformdirs/platformdirs-%{version}.tar.gz
BuildArch:      noarch
BuildRequires:  python3-devel python3-setuptools
Requires:       python3

%description
Platformdirs locates platform-specific directories for application data,
configuration, caches and logs. This version supports EL8's Python 3.6.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "367a5e80b3d04d2428ffa76d33f124cf11e8fff2acdaa9b43d545f5c7d661ef2" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n platformdirs-%{version}
# Supply the release version without requiring setuptools_scm on EL8.
sed -i 's/setup()/setup(version="%{version}")/' setup.py

%build
%{__python3} setup.py build

%install
rm -rf %{buildroot}
%{__python3} setup.py install -O1 --skip-build --root %{buildroot}

%clean
rm -rf %{buildroot}

%files
%license LICENSE.txt
%doc README.rst
%{python3_sitelib}/platformdirs/
%{python3_sitelib}/platformdirs-*.egg-info/

%changelog
* Sun Oct 18 2026 Antoine Martin <antoine@xpra.org> - 2.4.0-1
- package the Python 3.6 compatible dependency for EL8 pytools
- build with EL8's setuptools and verify the source checksum
