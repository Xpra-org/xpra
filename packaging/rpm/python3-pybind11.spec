%global debug_package %{nil}
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

Name:    pybind11
Version: 2.13.6
Release: 2%{?dist}
Summary: Seamless operability between C++11 and Python
License: BSD-3-Clause
URL:	 https://github.com/pybind/pybind11
Source0: https://github.com/pybind/pybind11/archive/v%{version}/%{name}-%{version}.tar.gz
# Patch out header path
Patch1:  pybind11-2.10.1-hpath.patch
%description
pybind11

BuildRequires: make
BuildRequires: %{py3rpmname}-devel
BuildRequires: %{py3rpmname}-setuptools
BuildRequires: eigen3-devel
BuildRequires: gcc-c++
BuildRequires: cmake

%package devel
Summary:  Development headers for pybind11
# For dir ownership
Requires: cmake

%description devel
This package contains the development headers for pybind11.

%package -n     %{py3rpmname}-%{name}
Requires: %{name}-devel%{?_isa} = %{version}-%{release}
Summary:        python C++ interop

%description -n %{py3rpmname}-%{name}
pybind11 is a lightweight header-only library that exposes C++ types \
in Python and vice versa, mainly to create Python bindings of existing \
C++ code.

This package contains the Python 3 files.

%prep
%setup -q
%patch 1 -p1 -b .hpath

%build
mkdir %{py3rpmname}
%cmake -B %{py3rpmname} -DCMAKE_BUILD_TYPE=Debug -DPYTHON_EXECUTABLE=%{_bindir}/%{python3} -DPYBIND11_INSTALL=TRUE -DUSE_PYTHON_INCLUDE_DIR=FALSE -DPYBIND11_TEST=OFF
%make_build -C %{py3rpmname}
CFLAGS="$RPM_OPT_FLAGS" %{python3} setup.py build

%install
%make_install -C %{py3rpmname}
PYBIND11_USE_CMAKE=true %py3_install "--install-purelib" "%{python3_sitearch}"

%files devel
%license LICENSE
%doc README.rst
%{_includedir}/pybind11/
%{_datadir}/cmake/pybind11/
%{_bindir}/pybind11-config
%{_datadir}/pkgconfig/%{name}.pc

%files -n %{py3rpmname}-%{name}
%{python3_sitearch}/%{name}/
%{python3_sitearch}/%{name}-%{version}-py%{python3_version}.egg-info

%changelog
* Sat Jan 18 2025 Fedora Release Engineering <releng@fedoraproject.org> - 2.13.6-2
- Rebuilt for https://fedoraproject.org/wiki/Fedora_42_Mass_Rebuild
