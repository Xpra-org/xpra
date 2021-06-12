%global python2dir %{_builddir}/python2-%{name}-%{version}-%{release}
%define _disable_source_fetch 0

Summary: D-Bus Python2 Bindings
Name:    python2-dbus
Version: 1.2.16
Release: 2%{?dist}

License: MIT
URL:     http://www.freedesktop.org/wiki/Software/DBusBindings/
Source0: https://files.pythonhosted.org/packages/62/7e/d4fb56a1695fa65da0c8d3071855fa5408447b913c58c01933c2f81a269a/dbus-python-1.2.16.tar.gz

# borrow centos7 patch to use sitearch properly
Patch0: 0001-Move-python-modules-to-architecture-specific-directo.patch

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
if [ "${sha256}" != "11238f1d86c995d8aed2e22f04a1e3779f0d70e587caffeab4857f3c662ed5a4" ]; then
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
* Sat Jun 12 2021 Antoine Martin <antoine@xpra.org> - 1.2.16-2
- centos8 python2

* Sat Sep 28 2019 Antoine Martin <antoine@xpra.org> - 1.2.16-1
- centos8 python2

* Sat Sep 28 2019 Antoine Martin <antoine@xpra.org> - 1.2.8-1
- centos8 python2
