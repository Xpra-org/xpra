%{!?python_sitelib: %define python_sitelib %(%{__python} -c "from distutils.sysconfig import get_python_lib; print get_python_lib()")}
%if 0%{?rhel} && 0%{?rhel} <= 6
%{!?__python2: %global __python2 /usr/bin/python2}
%endif

#this spec file is for both Fedora and CentOS
#only Fedora has Python3 at present:
%if 0%{?fedora}
%define with_python3 1
%endif

%global VERSION 3.1.0

Name:           PyOpenGL
Version:        %{VERSION}final
Release:        2%{?dist}
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


%if 0%{?with_python3}
%package -n python3-PyOpenGL
Summary:    Python3 bindings for OpenGL

%description -n python3-PyOpenGL
PyOpenGL is the cross platform Python binding to OpenGL and related APIs. It
includes support for OpenGL v1.1, GLU, GLUT v3.7, GLE 3 and WGL 4. It also
includes support for dozens of extensions (where supported in the underlying
implementation).

%package -n python3-PyOpenGL-Tk
Summary:        %{name} OpenGL Tk widget
Group:          System Environment/Libraries
Requires:       %{name} = %{VERSION}-%{release}, tkinter

%description -n python3-PyOpenGL-Tk
%{name} Togl (Tk OpenGL widget) 1.6 support.
%endif


%prep
%setup -q -n %{name}-%{VERSION}

%build
%{__python2} setup.py build

%if 0%{?with_python3}
rm -rf %{py3dir}
cp -a . %{py3dir}
%endif

%install
rm -rf $RPM_BUILD_ROOT
%{__python2} setup.py install -O1 --skip-build --root="$RPM_BUILD_ROOT" \
  --prefix="%{_prefix}"
%if 0%{?with_python3}
pushd %{py3dir}
%{__python3} setup.py install -O1 --skip-build --root %{buildroot}
popd
%endif


%clean
rm -rf $RPM_BUILD_ROOT


%files
%defattr(-,root,root,-)
%{python_sitelib}/*OpenGL*
%exclude %{python_sitelib}/OpenGL/Tk

%files Tk
%defattr(-,root,root,-)
%{python_sitelib}/OpenGL/Tk

%if 0%{?with_python3}
%files -n python3-PyOpenGL
%defattr(-,root,root,-)
%{python3_sitelib}/*OpenGL*
%exclude %{python3_sitelib}/OpenGL/Tk

%files -n python3-PyOpenGL-Tk
%defattr(-,root,root,-)
%{python3_sitelib}/OpenGL/Tk
%endif


%changelog
* Wed Sep 17 2014 Antoine Martin <antoine@nagafix.co.uk> - 3.1.0final-2
- Add Python3 package

* Fri Sep 05 2014 Antoine Martin <antoine@devloop.org.uk> 3.1.0final-1
- Fix version string to prevent upgrade to older beta version

* Fri Aug 08 2014 Antoine Martin <antoine@devloop.org.uk> 3.1.0
- Initial packaging for xpra
