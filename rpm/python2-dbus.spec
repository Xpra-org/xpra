%global python2dir %{_builddir}/python2-%{name}-%{version}-%{release}

Summary: D-Bus Python2 Bindings
Name:    python2-dbus
Version: 1.2.8
Release: 1%{?dist}

License: MIT
URL:     http://www.freedesktop.org/wiki/Software/DBusBindings/
Source0: http://dbus.freedesktop.org/releases/dbus-python/dbus-python-%{version}.tar.gz
Source1: http://dbus.freedesktop.org/releases/dbus-python/dbus-python-%{version}.tar.gz.asc

# borrow centos7 patch to use sitearch properly
Patch0: 0001-Move-python-modules-to-architecture-specific-directo.patch

BuildRequires: dbus-devel
BuildRequires: dbus-glib-devel
BuildRequires: python2-docutils
BuildRequires: python2-devel
BuildRequires: python2dist(setuptools)
# autoreconf and friends
BuildRequires: autoconf-archive automake libtool
Provides: dbus-python = %{version}-%{release}
Provides: dbus-python%{?_isa} = %{version}-%{release}
Obsoletes: dbus-python < %{version}-%{release}


%description
D-Bus python bindings for use with python programs.

%prep
%autosetup -p1 -n dbus-python-%{version}

# For new arches (aarch64/ppc64le), and patch0
autoreconf -vif

%build
%set_build_flags
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
* Sat Sep 28 2019 Antoine Martin <antoine@xpra.org> - 1.2.8-1
- centos8 python2
