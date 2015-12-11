%{!?python_sitelib: %global python_sitelib %(%{__python} -c "from distutils.sysconfig import get_python_lib; print get_python_lib()")}
%{!?python_sitearch: %global python_sitearch %(%{__python} -c "from distutils.sysconfig import get_python_lib; print get_python_lib(1)")}

%define pygtk2 pygtk2
%define pygtkglext pygtkglext
%if 0%{?suse_version}
%define pygtk2 python-gtk
%define pygtkglext python-gtkglext
%endif


Name:           %{pygtkglext}
Version:        1.1.0
Release:        16.xpra1%{?dist}
Summary:        Python bindings for GtkGLExt
License:        LGPLv2+
Group:          System Environment/Libraries
URL:            http://www.k-3d.org/gtkglext/Main_Page
Source:         http://downloads.sourceforge.net/gtkglext/pygtkglext-%{version}.tar.bz2
BuildRoot:      %{_tmppath}/pygtkglext-%{version}-%{release}-root-%(%{__id_u} -n)
BuildRequires:  gtkglext-devel
BuildRequires:  python-devel
BuildRequires:  %{pygtk2}-devel
Requires:       %{pygtk2}
Requires:       PyOpenGL
%if 0%{?suse_version}
Patch0:			pygtkgl-version.patch
Patch1:			pygtkgl-overrides.patch
Patch2:			pygtkgl-constants.patch
%endif

%description
Python bindings for GtkGLExt.


%package        devel
Summary:        Development files for %{name}
Group:          Development/Libraries
Requires:       %{name} = %{version}-%{release}
Requires:       pkgconfig
Requires:       %{pygtk2}-devel

%description    devel
The %{name}-devel package contains libraries and header files for
developing applications that use %{name}.


%prep
%setup -q -n pygtkglext-%{version}
iconv -f EUC-JP -t UTF8 AUTHORS > tmp
mv tmp AUTHORS
iconv -f EUC-JP -t UTF8 README > tmp
mv tmp README
%if 0%{?suse_version}
%patch0 -p1
%patch1 -p1
%patch2 -p1
%endif


%build
%configure
make %{?_smp_mflags}


%install
rm -rf $RPM_BUILD_ROOT
make install DESTDIR=$RPM_BUILD_ROOT INSTALL="%{__install} -p"
if [ %{python_sitelib} != %{python_sitearch} ]; then
  mv $RPM_BUILD_ROOT%{python_sitelib}/gtk-2.0/gtk/gdkgl/* \
     $RPM_BUILD_ROOT%{python_sitearch}/gtk-2.0/gtk/gdkgl
  mv $RPM_BUILD_ROOT%{python_sitelib}/gtk-2.0/gtk/gtkgl/* \
     $RPM_BUILD_ROOT%{python_sitearch}/gtk-2.0/gtk/gtkgl
fi
rm $RPM_BUILD_ROOT%{python_sitearch}/gtk-2.0/gtk/gdkgl/_gdkgl.la
rm $RPM_BUILD_ROOT%{python_sitearch}/gtk-2.0/gtk/gtkgl/_gtkgl.la

# this can be executed to run some basic tests (it has a main and shebang)
chmod +x $RPM_BUILD_ROOT%{python_sitearch}/gtk-2.0/gtk/gtkgl/apputils.py

# for %%doc
rm examples/Makefile*


%clean
rm -rf $RPM_BUILD_ROOT


%files
%defattr(-,root,root,-)
%doc AUTHORS ChangeLog COPYING COPYING.LIB README examples
%{python_sitearch}/gtk-2.0/gtk/gdkgl
%{python_sitearch}/gtk-2.0/gtk/gtkgl

%files devel
%defattr(-,root,root,-)
%{_libdir}/pkgconfig/*.pc
%{_datadir}/pygtk/2.0/defs/*


%changelog
* Thu Dec 03 2015 Antoine Martin <antoine@nagafix.co.uk> - 1.1.0-16.xpra1
- Added support for building on openSUSE
