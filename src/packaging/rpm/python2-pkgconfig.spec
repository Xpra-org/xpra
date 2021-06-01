%{!?__python2: %global __python2 python2}
%{!?python2_sitelib: %global python2_sitelib %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print get_python_lib()")}
%define _disable_source_fetch 0
%global srcname pkgconfig

Name:           python2-%{srcname}
Version:        1.5.2
Release:        1%{?dist}
Summary:        A Python interface to the pkg-config command line tool
License:        MIT
URL:            https://github.com/matze/%{srcname}
Source0:        https://files.pythonhosted.org/packages/ae/61/5a76ead90f9a62212c231b05231031e750f24e4dd2401d8c7f3f0527821b/%{srcname}-%{version}.tar.gz
BuildArch:      noarch
BuildRequires:  python2-devel
BuildRequires:  python2-setuptools

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
if [ "${sha256}" != "38d612488f0633755a2e7a8acab6c01d20d63dbc31af75e2a9ac98a6f638ca94" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%autosetup -n %{srcname}-%{version}
# Strip shebang
find -type f -name '*.py' -exec sed -i -e '1{\@^#!/usr/bin/env python@d}' {} ';'

%build
%{__python2} setup.py build

%install
%{__python2} setup.py install --root %{buildroot}

%check
#%{__python2} setup.py test

%files
%license LICENSE
%doc README.rst
%{python2_sitelib}/%{srcname}*

%changelog
* Wed May 26 2021 Antoine Martin <antoine@xpra.org> - 1.5.2-1
- package for xpra 3.1 builds
