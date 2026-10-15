%define _disable_source_fetch 0
%if "%{getenv:PYTHON3}" == ""
%global python3 python3
%define package_prefix %{nil}
%global py3rpmname python3
%else
%global python3 %{getenv:PYTHON3}
%define __python3 /usr/bin/%{python3}
%global py3rpmname %(echo %{python3} | sed 's/t$/-freethreading/')
%define package_prefix %{python3}-
%undefine __pythondist_requires
%undefine __python_requires
%endif
%define python3_sitearch %(%{python3} -Ic "from sysconfig import get_path; print(get_path('platlib').replace('/usr/local/', '/usr/'))" 2> /dev/null)

Name: pycairo
Version: 1.29.2
Release: 1%{?dist}
Summary: Python bindings for the cairo library

License: LGPL-2.1-only OR MPL-1.1
URL: https://www.cairographics.org/pycairo
Source0: https://github.com/pygobject/pycairo/releases/download/v%{version}/pycairo-%{version}.tar.gz
# pycairo needs meson >= 0.64, newer than what el8 / el9 ship,
# so we run meson straight from its source tarball:
%define meson_version 1.12.1
Source1: https://files.pythonhosted.org/packages/source/m/meson/meson-%{meson_version}.tar.gz

BuildRequires: gcc
BuildRequires: pkgconfig(cairo)
BuildRequires: %{py3rpmname}-devel
BuildRequires: ninja-build

%description
Python bindings for the cairo library.

%package -n %{py3rpmname}-cairo
Summary: Python 3 bindings for the cairo library
Requires: %{py3rpmname}

%description -n %{py3rpmname}-cairo
Python 3 bindings for the cairo library.

%package -n python3-cairo-devel
Summary: Libraries and headers for py3cairo
Requires: %{py3rpmname}-cairo%{?_isa} = %{version}-%{release}
Requires: %{py3rpmname}-devel

%description -n python3-cairo-devel
This package contains files required to build wrappers for cairo add-on
libraries so that they interoperate with py3cairo.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "3e69fff74fe64f5ba2dfa31f67c6bdf26413342574047437d2ac520d35e9a489" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
sha256=`sha256sum %{SOURCE1} | awk '{print $1}'`
if [ "${sha256}" != "ab0a6ca09f8ef70c564c8241fb5a23957886a0b53fb58412b5e07eaf07dba743" ]; then
	echo "invalid checksum for %{SOURCE1}"
	exit 1
fi
%autosetup -p1 -a 1

%build
%set_build_flags
%{python3} meson-%{meson_version}/meson.py setup build \
	--prefix=%{_prefix} --libdir=%{_libdir} --buildtype=plain \
	-Dpython=%{python3} -Dtests=false
%{python3} meson-%{meson_version}/meson.py compile -C build

%install
DESTDIR=%{buildroot} %{python3} meson-%{meson_version}/meson.py install -C build --no-rebuild

%files -n %{py3rpmname}-cairo
%license COPYING*
%doc README.rst
%{python3_sitearch}/cairo/
%{python3_sitearch}/pycairo*.dist-info

%files -n python3-cairo-devel
%dir %{_includedir}/pycairo
%{_includedir}/pycairo/py3cairo.h
%{_libdir}/pkgconfig/py3cairo.pc

%changelog
* Thu Oct 15 2026 Antoine Martin <antoine@xpra.org> - 1.29.2-1
- new upstream release, build using meson

* Sat Sep 16 2023 Antoine Martin <antoine@xpra.org> - 1.23.0-3
- bump release no to test updated dependencies

* Fri Jan 20 2023 Fedora Release Engineering <releng@fedoraproject.org> - 1.23.0-2
- Rebuilt for https://fedoraproject.org/wiki/Fedora_38_Mass_Rebuild
