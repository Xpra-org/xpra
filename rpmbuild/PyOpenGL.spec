%{!?python_sitelib: %define python_sitelib %(%{__python} -c "from distutils.sysconfig import get_python_lib; print get_python_lib()")}

%global VERSION 3.1.0

Name:           PyOpenGL
Version:        %{VERSION}final
Release:        1%{?dist}
Summary:        Python bindings for OpenGL
License:        BSD
Group:          System Environment/Libraries
URL:            http://pyopengl.sourceforge.net/
Source0:        http://downloads.sourceforge.net/pyopengl/%{name}-%{VERSION}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{VERSION}-%{release}-root-%(%{__id_u} -n)
BuildRequires:  python-devel
#see: http://fedoraproject.org/wiki/Changes/Remove_Python-setuptools-devel
%if 0%{?fedora}
BuildRequires:  python-setuptools
%else
BuildRequires:  python-setuptools-devel
%endif
BuildArch:      noarch
Requires:       numpy python-setuptools freeglut
# in some other repositories this is named python-opengl
Provides:       python-opengl = %{VERSION}-%{release}
Obsoletes:      python-opengl < %{VERSION}-%{release}

%description
PyOpenGL is the cross platform Python binding to OpenGL and related APIs. It
includes support for OpenGL v1.1, GLU, GLUT v3.7, GLE 3 and WGL 4. It also
includes support for dozens of extensions (where supported in the underlying
implementation).

PyOpenGL is interoperable with a large number of external GUI libraries
for Python including (Tkinter, wxPython, FxPy, PyGame, and Qt).


%package Tk
Summary:        %{name} OpenGL Tk widget
Group:          System Environment/Libraries
Requires:       %{name} = %{VERSION}-%{release}, tkinter

%description Tk
%{name} Togl (Tk OpenGL widget) 1.6 support.

%prep
%setup -q -n %{name}-%{VERSION}

%build
%{__python} setup.py build


%install
rm -rf $RPM_BUILD_ROOT
%{__python} setup.py install -O1 --skip-build --root="$RPM_BUILD_ROOT" \
  --prefix="%{_prefix}"


%clean
rm -rf $RPM_BUILD_ROOT


%files
%defattr(-,root,root,-)
%{python_sitelib}/*OpenGL*
%exclude %{python_sitelib}/OpenGL/Tk

%files Tk
%defattr(-,root,root,-)
%{python_sitelib}/OpenGL/Tk


%changelog
* Fri Sep 05 2014 Antoine Martin <antoine@devloop.org.uk> 3.1.0final
- Fix version string to prevent upgrade to older beta version

* Fri Aug 08 2014 Antoine Martin <antoine@devloop.org.uk> 3.1.0
- Initial packaging for xpra
