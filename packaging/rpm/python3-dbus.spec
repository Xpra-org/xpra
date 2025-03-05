%define _disable_source_fetch 0
%if "%{getenv:PYTHON3}" == ""
%global python3 python3
%else
%global python3 %{getenv:PYTHON3}
%undefine __pythondist_requires
%undefine __python_requires
%define python3_sitelib %(%{python3} -Ic "from sysconfig import get_path; print(get_path('purelib').replace('/usr/local/', '/usr/'))" 2> /dev/null)
%define python3_sitearch %(%{python3} -Ic "from sysconfig import get_path; print(get_path('platlib').replace('/usr/local/', '/usr/'))" 2> /dev/null)
%endif
%define python3_version %(%{python3} -c 'import sys;vi=sys.version_info;print(f"{vi[0]}.{vi[1]}")' 2> /dev/null)

%global debug_package %{nil}

Summary: D-Bus Python3 Bindings
Name:    %{python3}-dbus
Version: 1.3.2
Release: 2%{?dist}

License: MIT
URL:     http://www.freedesktop.org/wiki/Software/DBusBindings/
Source0: https://files.pythonhosted.org/packages/source/d/dbus-python/dbus-python-%{version}.tar.gz

Requires:      %{python3}
BuildRequires: dbus-devel
BuildRequires: dbus-glib-devel
BuildRequires: %{python3}-devel
BuildRequires: %{python3}-setuptools
BuildRequires: %{python3}-wheel
BuildRequires: autoconf-archive
BuildRequires: automake
BuildRequires: libtool


%description
D-Bus python bindings for use with %{python3} programs.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "ad67819308618b5069537be237f8e68ca1c7fcc95ee4a121fe6845b1418248f8" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%autosetup -p1 -n dbus-python-%{version}

%build
%set_build_flags
export DBUS_PYTHON_USE_AUTOTOOLS=1
export PYTHON="%{python3}"
export PYTHON_VERSION="%{python3_version}"
%configure PYTHON="%{python3}"
make

%install
export PYTHON="%{python3}"
%make_install

# unpackaged files
rm -fv %{buildroot}%{python3_sitearch}/*.la
rm -rfv %{buildroot}%{_datadir}/doc/dbus-python/
%if "%{python3}" != "python3"
rm -fv %{buildroot}%{_includedir}/dbus-1.0/dbus/dbus-python.h
rm -fv %{buildroot}%{_libdir}/pkgconfig/dbus-python.pc
%endif


%files
%doc NEWS
%license COPYING
%{python3_sitelib}/dbus*
%{python3_sitearch}/_dbus_*
#only include the development files for the "main" python3 package:
%if "%{python3}" == "python3"
%{_includedir}/dbus-1.0/dbus/dbus-python.h
%{_libdir}/pkgconfig/dbus-python.pc
%endif

%changelog
* Mon Oct 02 2023 Antoine Martin <antoine@xpra.org> - 1.3.2-1
- new upstream release
