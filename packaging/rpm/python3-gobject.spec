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

%define glib2_version                  2.64.0
%define gobject_introspection_version  1.81.0
%define pycairo_version                1.16.0
%define python3_version                3.8

Name:           python3-gobject
Version:        3.55.3
Release:        1%{?dist}
Summary:        Python bindings for GObject Introspection

License:        LGPL-2.1-or-later
URL:            https://wiki.gnome.org/Projects/PyGObject
Source0:        https://download.gnome.org/sources/pygobject/3.55/pygobject-%{version}.tar.gz

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
Requires:       %{py3rpmname}

%description -n %{py3rpmname}-gobject-base
This package provides the non-cairo specific bits of the GObject Introspection
library.

%package     -n python3-gobject-devel
Summary:        Development files for embedding PyGObject introspection support
Requires:       gobject-introspection-devel%{?_isa}

%description -n python3-gobject-devel
This package contains files required to embed PyGObject

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "14f52750312bd689dde3a75e968849e3e16c4a0803f1c7734dffb00a1c847af9" ]; then
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
%license COPYING
%doc NEWS
%dir %{python3_sitearch}/gi/
%{python3_sitearch}/gi/overrides/
%{python3_sitearch}/gi/repository/
%pycached %{python3_sitearch}/gi/*.py
%{python3_sitearch}/gi/_gi.*.so
%{python3_sitearch}/PyGObject-*.dist-info/

%files -n python3-gobject-devel
%dir %{_includedir}/pygobject-3.0/
%{_includedir}/pygobject-3.0/pygobject.h
%{_includedir}/pygobject-3.0/pygobject-types.h
%{_libdir}/pkgconfig/pygobject-3.0.pc

%changelog
* Sat Sep 16 2023 Antoine Martin <antoine@xpra.org> - 3.44.1-2
- Fedora variant
