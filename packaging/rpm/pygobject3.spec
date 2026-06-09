%define _disable_source_fetch 0
%global debug_package %{nil}

%if "%{getenv:PYTHON3}" == ""
%global python3 python3
%global py3rpmname python3
%define package_prefix %{nil}
%else
%global python3 %{getenv:PYTHON3}
%global py3rpmname python3
%global py3rpmname %(echo %{python3} | sed 's/t$/-freethreading/')
%define package_prefix %{py3rpmname}-
%undefine __pythondist_requires
%undefine __python_requires
%define python3_sitearch %(%{python3} -Ic "from sysconfig import get_path; print(get_path('platlib').replace('/usr/local/', '/usr/'))" 2> /dev/null)
%endif

%if 0%{?el8}
# el8 only ships GLib 2.56 / gobject-introspection 1.64, too old for pygobject
# 3.46+ (which needs GLib >= 2.64). Stay on the last 3.44 series; it also uses
# the older egg-info layout and installs the pure-python bits to sitelib (hence
# the separate -gobject-base-noarch subpackage below):
%define glib2_version                  2.56.0
%define gobject_introspection_version  1.56.0
%global pygobject_series               3.44
%global pygobject_archive_ext          tar.xz
%global pygobject_sha256               3c6805d1321be90cc32e648215a562430e0d3d6edcda8f4c5e7a9daffcad5710
%define pygobject_version              3.44.1
%else
# el9+ ships gobject-introspection 1.68: use pygobject's real minimum (1.64.0)
# instead of Fedora's shipped 1.81.0 so el9 can build the 3.50 series:
%define glib2_version                  2.64.0
%define gobject_introspection_version  1.64.0
%global pygobject_series               3.50
%global pygobject_archive_ext          tar.gz
%global pygobject_sha256               ece6b860aab77cb649fdfc6e88d8a83765e7a62f7ffd39a628d6e2a0d397a7ff
%define pygobject_version              3.50.2
%endif
%define pycairo_version                1.16.0
%define python3_version                3.8

Name:           pygobject3
Version:        %{pygobject_version}
Release:        1%{?dist}
Summary:        Python bindings for GObject Introspection

License:        LGPL-2.1-or-later
URL:            https://wiki.gnome.org/Projects/PyGObject
Source0:        https://download.gnome.org/sources/pygobject/%{pygobject_series}/pygobject-%{version}.%{pygobject_archive_ext}

BuildRequires:  pkgconfig(cairo-gobject)
BuildRequires:  pkgconfig(glib-2.0) >= %{glib2_version}
BuildRequires:  pkgconfig(gobject-introspection-1.0) >= %{gobject_introspection_version}
BuildRequires:  pkgconfig(libffi)
BuildRequires:  pkgconfig(py3cairo) >= %{pycairo_version}
BuildRequires:  meson
BuildRequires:  %{py3rpmname}-devel >= %{python3_version}
BuildRequires:  %{py3rpmname}-setuptools

%description
The %{name} package provides a convenient wrapper for the GObject library
for use in Python programs.

%package     -n %{py3rpmname}-gobject
Summary:        %{py3rpmname} bindings for GObject Introspection
Requires:       %{py3rpmname}-gobject-base%{?_isa} = %{version}-%{release}
# The cairo override module depends on this
Requires:       %{py3rpmname}-cairo%{?_isa} >= %{pycairo_version}

%description -n %{py3rpmname}-gobject
The %{python3}-gobject package provides a convenient wrapper for the GObject
library and and other libraries that are compatible with GObject Introspection,
for use in Python 3 programs.

%package     -n %{py3rpmname}-gobject-base
Summary:        Python 3 bindings for GObject Introspection base package
Requires:       gobject-introspection%{?_isa} >= %{gobject_introspection_version}
%if 0%{?el8}
Requires:       %{py3rpmname}-gobject-base-noarch = %{version}-%{release}
%endif
Requires:       %{py3rpmname}

%description -n %{py3rpmname}-gobject-base
This package provides the non-cairo specific bits of the GObject Introspection
library.

%if 0%{?el8}
%package     -n %{py3rpmname}-gobject-base-noarch
Summary:        Python 3 bindings for GObject Introspection base (not architecture dependent)
BuildArch:      noarch
Requires:       %{py3rpmname}-gobject-base = %{version}-%{release}
Requires:       %{py3rpmname}

%description -n %{py3rpmname}-gobject-base-noarch
This package provides the non-cairo specific bits of the GObject Introspection
library.
%endif

%package     -n %{py3rpmname}-gobject-devel
Summary:        Development files for embedding PyGObject introspection support
Requires:       %{py3rpmname}-gobject%{?_isa} = %{version}-%{release}
Requires:       gobject-introspection-devel%{?_isa}

%description -n %{py3rpmname}-gobject-devel
This package contains files required to embed PyGObject

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "%{pygobject_sha256}" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%autosetup -n pygobject-%{version} -p1

%build
%meson -Dpython=%{python3} -Dtests=false
%meson_build

%install
%meson_install


%files -n %{py3rpmname}-gobject
%{python3_sitearch}/gi/_gi_cairo*.so

%files -n %{py3rpmname}-gobject-base
%if 0%{?el8}
%{python3_sitearch}/gi
%{python3_sitearch}/PyGObject-*.egg-info
%else
%license COPYING
%doc NEWS
%dir %{python3_sitearch}/gi/
%{python3_sitearch}/gi/overrides/
%{python3_sitearch}/gi/repository/
%pycached %{python3_sitearch}/gi/*.py
%{python3_sitearch}/gi/_gi.*.so
%{python3_sitearch}/PyGObject-*.dist-info/
%{python3_sitearch}/pygtkcompat/
%endif

%if 0%{?el8}
%files -n %{py3rpmname}-gobject-base-noarch
%license COPYING
%doc NEWS
%dir %{python3_sitelib}/gi/
%{python3_sitelib}/gi/overrides/
%{python3_sitelib}/gi/repository/
%{python3_sitelib}/pygtkcompat/
%endif

%files -n %{py3rpmname}-gobject-devel
%dir %{_includedir}/pygobject-3.0/
%{_includedir}/pygobject-3.0/pygobject.h
%{_libdir}/pkgconfig/pygobject-3.0.pc

%changelog
* Tue Jun 09 2026 Antoine Martin <antoine@xpra.org> - 3.50.2-1
- el9+: use pygobject's real gobject-introspection minimum (1.64.0) instead of
  Fedora's shipped 1.81.0, which RHEL9 (gi 1.68) cannot satisfy
- el8: pin to 3.44.1 (last series that builds against GLib 2.56)

* Sat Sep 16 2023 Antoine Martin <antoine@xpra.org> - 3.44.1-2
- Fedora variant
