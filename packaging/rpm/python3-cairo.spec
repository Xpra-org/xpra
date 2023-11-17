%define _disable_source_fetch 0
%if "%{getenv:PYTHON3}" == ""
%global python3 python3
%define package_prefix %{nil}
%else
%global python3 %{getenv:PYTHON3}
%define __python3 /usr/bin/%{python3}
%define package_prefix %{python3}-
%undefine __pythondist_requires
%undefine __python_requires
%endif
%define python3_sitearch %(%{python3} -Ic "from sysconfig import get_path; print(get_path('platlib').replace('/usr/local/', '/usr/'))" 2> /dev/null)

Name: pycairo
Version: 1.23.0
Release: 3%{?dist}
Summary: Python bindings for the cairo library

License: LGPL-2.1-only OR MPL-1.1
URL: https://www.cairographics.org/pycairo
Source0: https://github.com/pygobject/pycairo/releases/download/v%{version}/pycairo-%{version}.tar.gz

BuildRequires: gcc
BuildRequires: pkgconfig(cairo)
BuildRequires: %{python3}-devel
BuildRequires: %{python3}-setuptools

%description
Python bindings for the cairo library.

%package -n %{python3}-cairo
Summary: Python 3 bindings for the cairo library
Requires: %{python3}

%description -n %{python3}-cairo
Python 3 bindings for the cairo library.

%package -n python3-cairo-devel
Summary: Libraries and headers for py3cairo
Requires: %{python3}-cairo%{?_isa} = %{version}-%{release}
Requires: %{python3}-devel

%description -n python3-cairo-devel
This package contains files required to build wrappers for cairo add-on
libraries so that they interoperate with py3cairo.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "9b61ac818723adc04367301317eb2e814a83522f07bbd1f409af0dada463c44c" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%autosetup -p1

%build
%py3_build

%install
%py3_install

%files -n %{python3}-cairo
%license COPYING*
%doc README.rst
%{python3_sitearch}/cairo/
%{python3_sitearch}/pycairo*.egg-info

%files -n python3-cairo-devel
%dir %{_includedir}/pycairo
%{_includedir}/pycairo/py3cairo.h
%{_libdir}/pkgconfig/py3cairo.pc

%changelog
* Sat Sep 16 2023 Antoine Martin <antoine@xpra.org> - 1.23.0-3
- bump release no to test updated dependencies

* Fri Jan 20 2023 Fedora Release Engineering <releng@fedoraproject.org> - 1.23.0-2
- Rebuilt for https://fedoraproject.org/wiki/Fedora_38_Mass_Rebuild
