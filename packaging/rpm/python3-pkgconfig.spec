%define _disable_source_fetch 0
%global srcname pkgconfig

Name:           python3-%{srcname}
Version:        1.5.5
Release:        1%{?dist}
Summary:        Python interface to the pkg-config command line tool
%{?python_provide:%python_provide python3-%{srcname}}

License:        MIT
URL:            https://github.com/matze/pkgconfig
Source:         %{pypi_source}

BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  python3-setuptools
Requires:       %{_bindir}/pkg-config


%description
pkgconfig is a Python module to interface with the pkg-config command line
tool and supports Python 2.6+.

It can be used to

* check if a package exists
* check if a package meets certain version requirements
* query CFLAGS and LDFLAGS
* parse the output to build extensions with setup.py

If pkg-config is not on the path, raises EnvironmentError.


%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "deb4163ef11f75b520d822d9505c1f462761b4309b1bb713d08689759ea8b899" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%autosetup -n %{srcname}-%{version}
# We need to keep egg-info as a directory
# https://github.com/sdispater/poetry/issues/866
sed -i -e s/distutils.core/setuptools/ setup.py


%build
%py3_build


%install
%py3_install


%files -n python3-%{srcname}
%license LICENSE
%doc README.rst
%{python3_sitelib}/%{srcname}-*.egg-info/
%{python3_sitelib}/%{srcname}/


%changelog
* Mon Mar 21 2022 Antoine Martin <antoine@xpra.org> - 1.5.5-1
- initial packaging for CentOS 8 based on the Fedora spec file
