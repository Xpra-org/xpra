%{!?python_sitelib: %define python_sitelib %(%{__python} -c "from distutils.sysconfig import get_python_lib; print get_python_lib()")}

Name:           PyOpenGL
Version:        3.1.0
Release:        1%{?dist}
Summary:        Python bindings for OpenGL
License:        BSD
Group:          System Environment/Libraries
URL:            http://pyopengl.sourceforge.net/
Source0:        http://downloads.sourceforge.net/pyopengl/%{name}-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)
BuildRequires:  python-devel python-setuptools-devel
BuildArch:      noarch
Requires:       numpy python-setuptools freeglut
# in some other repositories this is named python-opengl
Provides:       python-opengl = %{version}-%{release}
Obsoletes:      python-opengl < %{version}-%{release}

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
Requires:       %{name} = %{version}-%{release}, tkinter

%description Tk
%{name} Togl (Tk OpenGL widget) 1.6 support.

%prep
%setup -q -n %{name}-%{version}

%build
%{__python} setup.py build


%install
rm -rf $RPM_BUILD_ROOT
%{__python} setup.py install -O1 --skip-build --root="$RPM_BUILD_ROOT" \
  --prefix="%{_prefix}"
#chmod -x $RPM_BUILD_ROOT%{python_sitelib}/%{name}-%{version}-py?.?.egg-info


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
* Fri Aug 08 2014 Antoine Martin <antoine@devloop.org.uk> 3.1.0
- Initial packaging for xpra
