%global python2dir %{_builddir}/python2-%{name}-%{version}-%{release}
%define _disable_source_fetch 0

Summary: D-Bus Python2 Bindings
Name:    python2-dbus
Version: 1.2.18
Release: 1%{?dist}

License: MIT
URL:     http://www.freedesktop.org/wiki/Software/DBusBindings/
Source0: https://files.pythonhosted.org/packages/b1/5c/ccfc167485806c1936f7d3ba97db6c448d0089c5746ba105b6eb22dba60e/dbus-python-%{version}.tar.gz

# borrow centos7 patch to use sitearch properly
#Patch0: 0001-Move-python-modules-to-architecture-specific-directo.patch

BuildRequires: make
BuildRequires: dbus-devel
BuildRequires: dbus-glib-devel
BuildRequires: python2-devel
BuildRequires: python2-setuptools
# autoreconf and friends
BuildRequires: autoconf-archive automake libtool
%if 0%{?el7}
Provides: python-dbus = %{version}-%{release}
%endif
Provides: dbus-python = %{version}-%{release}
Provides: dbus-python%{?_isa} = %{version}-%{release}
Obsoletes: dbus-python < %{version}-%{release}


%description
D-Bus python bindings for use with python programs.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "92bdd1e68b45596c833307a5ff4b217ee6929a1502f5341bae28fd120acf7260" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%autosetup -p1 -n dbus-python-%{version}

# For new arches (aarch64/ppc64le), and patch0
autoreconf -vif

%build
%py2_build
%configure PYTHON="%{__python2}"
%make_build

%install
%py2_install

# unpackaged files
rm -fv  $RPM_BUILD_ROOT%{python2_sitearch}/*.la
rm -rfv $RPM_BUILD_ROOT%{_datadir}/doc/dbus-python/

%files
%doc NEWS
%license COPYING
%{python2_sitearch}/*.so
%{python2_sitearch}/dbus/
%{python2_sitearch}/dbus_python*egg-info

%changelog
* Sat Nov 11 2023 Antoine Martin <antoine@xpra.org> - 1.2.18-1
- new upstream release

* Sat Jun 12 2021 Antoine Martin <antoine@xpra.org> - 1.2.16-2
- centos8 python2

* Sat Sep 28 2019 Antoine Martin <antoine@xpra.org> - 1.2.16-1
- centos8 python2

* Sat Sep 28 2019 Antoine Martin <antoine@xpra.org> - 1.2.8-1
- centos8 python2
