%{!?python_sitelib: %global python_sitelib %(%{__python} -c "from distutils.sysconfig import get_python_lib; print get_python_lib()")}
%{!?python_sitearch: %global python_sitearch %(%{__python} -c "from distutils.sysconfig import get_python_lib; print get_python_lib(1)")}

%define pygtk2 pygtk2
%if 0%{?suse_version}
%define pygtk2 python-gtk
%endif


Name:           pygtkglext
Version:        1.1.0
Release:        16%{?dist}
Summary:        Python bindings for GtkGLExt
License:        LGPLv2+
Group:          System Environment/Libraries
URL:            http://www.k-3d.org/gtkglext/Main_Page
Source:         http://downloads.sourceforge.net/gtkglext/%{name}-%{version}.tar.bz2
BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)
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
Requires:       pkgconfig pygtk2-devel

%description    devel
The %{name}-devel package contains libraries and header files for
developing applications that use %{name}.


%prep
%setup -q
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
* Sat Jun 07 2014 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 1.1.0-16
- Rebuilt for https://fedoraproject.org/wiki/Fedora_21_Mass_Rebuild

* Sun Aug 04 2013 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 1.1.0-15
- Rebuilt for https://fedoraproject.org/wiki/Fedora_20_Mass_Rebuild

* Thu Feb 14 2013 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 1.1.0-14
- Rebuilt for https://fedoraproject.org/wiki/Fedora_19_Mass_Rebuild

* Sat Jul 21 2012 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 1.1.0-13
- Rebuilt for https://fedoraproject.org/wiki/Fedora_18_Mass_Rebuild

* Sat Jan 14 2012 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 1.1.0-12
- Rebuilt for https://fedoraproject.org/wiki/Fedora_17_Mass_Rebuild

* Tue Dec 06 2011 Adam Jackson <ajax@redhat.com> - 1.1.0-11
- Rebuild for new libpng

* Tue Feb 08 2011 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 1.1.0-10
- Rebuilt for https://fedoraproject.org/wiki/Fedora_15_Mass_Rebuild

* Wed Jul 21 2010 David Malcolm <dmalcolm@redhat.com> - 1.1.0-9
- Rebuilt for https://fedoraproject.org/wiki/Features/Python_2.7/MassRebuild

* Thu Jan  7 2010 Hans de Goede <hdegoede@redhat.com> 1.1.0-8
- Change python_foo macros to use %%global as the new rpm will break
  using %%define here, see:
  https://www.redhat.com/archives/fedora-devel-list/2010-January/msg00093.html

* Sun Jul 26 2009 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 1.1.0-7
- Rebuilt for https://fedoraproject.org/wiki/Fedora_12_Mass_Rebuild

* Thu Feb 26 2009 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 1.1.0-6
- Rebuilt for https://fedoraproject.org/wiki/Fedora_11_Mass_Rebuild

* Sat Nov 29 2008 Ignacio Vazquez-Abrams <ivazqueznet+rpm@gmail.com> - 1.1.0-5
- Rebuild for Python 2.6

* Tue Feb 19 2008 Fedora Release Engineering <rel-eng@fedoraproject.org> - 1.1.0-4
- Autorebuild for GCC 4.3

* Wed Aug 15 2007 Hans de Goede <j.w.r.degoede@hhs.nl> 1.1.0-3
- Update License tag for new Licensing Guidelines compliance

* Thu Mar 29 2007 Hans de Goede <j.w.r.degoede@hhs.nl> 1.1.0-2
- Various specfile improvements (bz 234122)

* Sat Mar 24 2007 Hans de Goede <j.w.r.degoede@hhs.nl> 1.1.0-1
- Initial Fedora Extras package
