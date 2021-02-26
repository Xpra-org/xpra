Name: pycairo
Version: 1.16.3
Release: 6%{?dist}
Summary: Python bindings for the cairo library

License: MPLv1.1 or LGPLv2
URL: http://cairographics.org/pycairo
Source0: https://github.com/pygobject/pycairo/releases/download/v%{version}/pycairo-%{version}.tar.gz

BuildRequires: cairo-devel
BuildRequires: pkgconfig
BuildRequires: python3-devel
BuildRequires: python3-pytest

%define _disable_source_fetch 0

%description
Python bindings for the cairo library.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "5bb321e5d4f8b3a51f56fc6a35c143f1b72ce0d748b43d8b623596e8215f01f7" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi 
%setup -q

%package -n python3-cairo
Summary: Python 3 bindings for the cairo library
%{?python_provide:%python_provide python3-cairo}

%description -n python3-cairo
Python 3 bindings for the cairo library.

%package -n python3-cairo-devel
Summary: Libraries and headers for py3cairo
Requires: python3-cairo%{?_isa} = %{version}-%{release}
Requires: python3-devel

%description -n python3-cairo-devel
This package contains files required to build wrappers for cairo add-on
libraries so that they interoperate with py3cairo.

%prep
%setup -q

%build
%py3_build

%install
%py3_install

%check
%{__python3} setup.py test

%files -n python3-cairo
%license COPYING*
%{python3_sitearch}/cairo/
%{python3_sitearch}/pycairo*.egg-info

%files -n python3-cairo-devel
%dir %{_includedir}/pycairo
%{_includedir}/pycairo/py3cairo.h
%{_libdir}/pkgconfig/py3cairo.pc

%changelog
* Fri Feb 26 2021 Antoine Martin <totaam@gmail.com> - 1.16.3-6
- forced to rebuild since the CentOS repositories don't carry python3-cairo-devel
