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

%global debug_package %{nil}

Summary: D-Bus Python3 Bindings
Name:    %{python3}-dbus
Version: 1.3.2
Release: 2%{?dist}

License: MIT
URL:     http://www.freedesktop.org/wiki/Software/DBusBindings/
Source0: https://files.pythonhosted.org/packages/c1/d3/6be85a9c772d6ebba0cc3ab37390dd6620006dcced758667e0217fb13307/dbus-python-%{version}.tar.gz

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
PYTHON="%{python3}" autoreconf -vif

%build
export DBUS_PYTHON_USE_AUTOTOOLS=1
%set_build_flags
%{python3} ./setup.py build
# %configure PYTHON="%{__python3}"
make

%install
%{python3} ./setup.py install --prefix=%{buildroot}/usr

# unpackaged files
rm -fv  ${buildroot}%{python3_sitearch}/*.la
rm -rfv ${buildroot}%{_datadir}/doc/dbus-python/

%files
%doc NEWS
%license COPYING
%{python3_sitearch}/dbus*

%changelog
* Mon Oct 02 2023 Antoine Martin <antoine@xpra.org> - 1.3.2-1
- new upstream release
