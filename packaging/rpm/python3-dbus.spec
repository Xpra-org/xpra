%define _disable_source_fetch 0
%if "%{getenv:PYTHON3}" == ""
%global python3 python3
%global py3rpmname python3
%else
%global python3 %{getenv:PYTHON3}
%global py3rpmname %(echo %{python3} | sed 's/t$/-freethreading/')
%undefine __pythondist_requires
%undefine __python_requires
%define python3_sitelib %(%{python3} -Ic "from sysconfig import get_path; print(get_path('purelib').replace('/usr/local/', '/usr/'))" 2> /dev/null)
%define python3_sitearch %(%{python3} -Ic "from sysconfig import get_path; print(get_path('platlib').replace('/usr/local/', '/usr/'))" 2> /dev/null)
%endif
%define python3_version %(%{python3} -c 'import sys;vi=sys.version_info;print(f"{vi[0]}.{vi[1]}")' 2> /dev/null)

%global debug_package %{nil}

Summary: D-Bus Python3 Bindings
Name:    %{py3rpmname}-dbus
Version: 1.5.0
Release: 1%{?dist}

License: MIT
URL:     http://www.freedesktop.org/wiki/Software/DBusBindings/
Source0: https://files.pythonhosted.org/packages/source/d/dbus-python/dbus_python-%{version}.tar.gz
# dbus-python only builds with meson >= 0.60, newer than what el8 ships,
# so we run meson straight from its source tarball:
%define meson_version 1.12.1
Source1: https://files.pythonhosted.org/packages/source/m/meson/meson-%{meson_version}.tar.gz

Requires:      %{py3rpmname}
BuildRequires: gcc
BuildRequires: dbus-devel
BuildRequires: pkgconfig(glib-2.0)
BuildRequires: %{py3rpmname}-devel
BuildRequires: ninja-build


%description
D-Bus python bindings for use with %{python3} programs.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "ac94ce330879108e5d37105164cc14b595bdf9326d2ce4a5acad6c1ab2bf6476" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
sha256=`sha256sum %{SOURCE1} | awk '{print $1}'`
if [ "${sha256}" != "ab0a6ca09f8ef70c564c8241fb5a23957886a0b53fb58412b5e07eaf07dba743" ]; then
	echo "invalid checksum for %{SOURCE1}"
	exit 1
fi
%autosetup -p1 -n dbus_python-%{version} -a 1

%build
%set_build_flags
%{python3} meson-%{meson_version}/meson.py setup build \
	--prefix=%{_prefix} --libdir=%{_libdir} --buildtype=plain \
	-Dpython=%{python3} -Dtests=disabled -Ddoc=disabled
%{python3} meson-%{meson_version}/meson.py compile -C build

%install
DESTDIR=%{buildroot} %{python3} meson-%{meson_version}/meson.py install -C build --no-rebuild
%if "%{python3}" != "python3"
rm -fv %{buildroot}%{_includedir}/dbus-1.0/dbus/dbus-python.h
rm -fv %{buildroot}%{_libdir}/pkgconfig/dbus-python.pc
%endif


%files
%doc NEWS
%license COPYING
%{python3_sitearch}/dbus/
%{python3_sitearch}/_dbus_*
#only include the development files for the "main" python3 package:
%if "%{python3}" == "python3"
%{_includedir}/dbus-1.0/dbus/dbus-python.h
%{_libdir}/pkgconfig/dbus-python.pc
%endif

%changelog
* Thu Oct 15 2026 Antoine Martin <antoine@xpra.org> - 1.5.0-1
- new upstream release, build using meson (autotools support was removed)

* Mon Jun 08 2026 Antoine Martin <antoine@xpra.org> - 1.4.0-2
- fix build on RHEL8 with Python 3.12: automake's py-compile uses removed 'imp' module

* Fri May 08 2026 Antoine Martin <antoine@xpra.org> - 1.4.0-1
- new upstream release

* Mon Oct 02 2023 Antoine Martin <antoine@xpra.org> - 1.3.2-1
- new upstream release
