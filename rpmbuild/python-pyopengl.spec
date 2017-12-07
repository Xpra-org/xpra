# Remove private provides from .so files in the python_sitearch directory
%global __provides_exclude_from ^%{python_sitearch}/.*\\.so$
%{!?__python2: %define __python2 python2}
%{!?python2_sitearch: %global python2_sitearch %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))")}
%{!?python2_sitelib: %global python2_sitelib %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib())")}
%{!?python2_version: %global python2_version %(%{__python2} -c "import sys; sys.stdout.write(sys.version[:3])")}

#this spec file is for both Fedora and CentOS
%global srcname PyOpenGL

Name:           python2-pyopengl
Version:        3.1.1a1
Release:        9xpra1%{?dist}
Summary:        Python bindings for OpenGL
License:        BSD
URL:            http://pyopengl.sourceforge.net/
Source0:        https://pypi.python.org/packages/source/P/%{srcname}/%{srcname}-%{version}.tar.gz
Source1:        https://pypi.python.org/packages/source/P/%{srcname}-accelerate/%{srcname}-accelerate-%{version}.tar.gz

Requires:       freeglut
Obsoletes:      python-pyopengl < 3.1.2
Provides:       python-pyopengl = %{version}-%{release}
Obsoletes:      pyopengl < 3.1.2
Provides:       pyopengl = %{version}-%{release}
Conflicts:		pyopengl
Obsoletes:      PyOpenGL < 3.1.2
Provides:       PyOpenGL = %{version}-%{release}
Conflicts:		PyOpenGL
#Fedora broke our xpra repository :(
Obsoletes:      PyOpenGL-accelerate < 3.1.2
Provides:       PyOpenGL-accelerate = %{version}-%{release}
Conflicts:		PyOpenGL-accelerate

%if 0%{?fedora}
%define with_python3 1
Requires:       python2-numpy
BuildRequires:  python2-setuptools
BuildRequires:  python2-devel
%else
Requires:       numpy
BuildRequires:  python-setuptools
BuildRequires:  python-devel
%endif

%description
PyOpenGL is the cross platform Python binding to OpenGL and related APIs. It
includes support for OpenGL v1.1, GLU, GLUT v3.7, GLE 3 and WGL 4. It also
includes support for dozens of extensions (where supported in the underlying
implementation).

PyOpenGL is inter-operable with a large number of external GUI libraries
for Python including (Tkinter, wxPython, FxPy, PyGame, and Qt).


%if 0%{?with_python3}
%package -n     python3-pyopengl
Summary:        Python 3 bindings for OpenGL
BuildRequires:  python3-devel
BuildRequires:  python3-setuptools
BuildRequires:  python3-numpy
Requires:       freeglut
Requires:       python3-numpy
Obsoletes:      python3-PyOpenGL < 3.1.2
Obsoletes:      python3-PyOpenGL-accelerate < 3.1.2
Provides:       python3-PyOpenGL = %{version}-%{release}
Provides:       python3-PyOpenGL-accelerate = %{version}-%{release}

%description -n python3-pyopengl
PyOpenGL is the cross platform Python binding to OpenGL and related APIs. It
includes support for OpenGL v1.1, GLU, GLUT v3.7, GLE 3 and WGL 4. It also
includes support for dozens of extensions (where supported in the underlying
implementation).

PyOpenGL is inter-operable with a large number of external GUI libraries
for Python including (Tkinter, wxPython, FxPy, PyGame, and Qt).
%endif


%package -n     python2-pyopengl-tk
Summary:        %{srcname} Python 2.x Tk widget
BuildArch:      noarch
Requires:       python2-pyopengl = %{version}-%{release}
Requires:       tkinter
Obsoletes:      PyOpenGL-Tk < 3.1.2
Provides:       PyOpenGL-Tk = %{version}-%{release}
Obsoletes:      python-pyopengl-tk < 3.1.2
Provides:       python-pyopengl-tk = %{version}-%{release}

%description -n python2-pyopengl-tk
%{srcname} Togl (Tk OpenGL widget) 1.6 support for Python 2.x.


%if 0%{?with_python3}
%package -n     python3-pyopengl-tk
Summary:        %{srcname} Python 3.x Tk widget
BuildArch:      noarch
Requires:       python3-pyopengl = %{version}-%{release}
Requires:       python3-tkinter
# These can be removed in Fedora 27
Obsoletes:      python3-PyOpenGL-Tk < 3.1.2
Provides:       python3-PyOpenGL-Tk = %{version}-%{release}

%description -n python3-pyopengl-tk
%{srcname} Togl (Tk OpenGL widget) 1.6 support for Python 3.x.
%endif

%prep
%setup -q -c -n %{srcname}-%{version} -T -a0 -a1


%build
for dir in %{srcname}-%{version} %{srcname}-accelerate-%{version} ; do
    pushd $dir
	%{__python2} setup.py build
	%if 0%{?with_python3}
	%{__python3} setup.py build
    %endif
    popd
done


%install
for dir in %{srcname}-%{version} %{srcname}-accelerate-%{version} ; do
    pushd $dir
	%{__python2} setup.py install -O1 --skip-build --root %{buildroot}
	%if 0%{?with_python3}
	%{__python3} setup.py install -O1 --skip-build --root %{buildroot}
    %endif
    popd
done

# Fix up perms on compiled object files
find %{buildroot}%{python2_sitearch}/OpenGL_accelerate/ -name *.so -exec chmod 755 '{}' \;
%if 0%{?with_python3}
find %{buildroot}%{python3_sitearch}/OpenGL_accelerate/ -name *.so -exec chmod 755 '{}' \;

# Remove shebangs - note that weirdly these files have a space between
# the #! and the /, so this sed recipe is not the usual one
pushd %{buildroot}%{python2_sitelib}/OpenGL/arrays
sed -i -e '/^#! \//, 1d' buffers.py _buffers.py
popd

pushd %{buildroot}%{python3_sitelib}/OpenGL/arrays
sed -i -e '/^#! \//, 1d' buffers.py _buffers.py
popd
%endif


%files
%{python2_sitelib}/%{srcname}-%{version}-py%{python2_version}.egg-info
%{python2_sitelib}/OpenGL/
%exclude %{python2_sitelib}/OpenGL/Tk
%{python2_sitearch}/OpenGL_accelerate/
%{python2_sitearch}/%{srcname}_accelerate-%{version}-py%{python2_version}.egg-info/

%if 0%{?with_python3}
%files -n python3-pyopengl
%license %{srcname}-%{version}/license.txt
%{python3_sitelib}/%{srcname}-%{version}-py%{python3_version}.egg-info
%{python3_sitelib}/OpenGL/
%exclude %{python3_sitelib}/OpenGL/Tk
%{python3_sitearch}/OpenGL_accelerate/
%{python3_sitearch}/%{srcname}_accelerate-%{version}-py%{python3_version}.egg-info/
%endif


%files -n python2-pyopengl-tk
%{python2_sitelib}/OpenGL/Tk

%if 0%{?with_python3}
%files -n python3-pyopengl-tk
%{python3_sitelib}/OpenGL/Tk
%endif


%changelog
* Thu Dec 07 2017 Antoine Martin <antoine@devloop.org.uk> - 3.1.1a1-9xpra1
- remove opensuse bitrot

* Thu Jul 13 2017 Antoine Martin <antoine@devloop.org.uk> - 3.1.1a1-4.2xpra4
- also obsolete / provide "python-opengl" package name

* Tue Jan 10 2017 Antoine Martin <antoine@devloop.org.uk> - 3.1.1a1-4.1xpra4
- also use "python2-opengl" package name on CentOS

* Fri Aug 05 2016 Antoine Martin <antoine@devloop.org.uk> - 3.1.1a1-4.1xpra3
- Fedora 23 does not have the python2 renamed packages yet
- only opensuse calls numpy python-numpy

* Mon Aug 01 2016 Antoine Martin <antoine@devloop.org.uk> - 3.1.1a1-4.1xpra2
- and again

* Mon Aug 01 2016 Antoine Martin <antoine@devloop.org.uk> - 3.1.1a1-4.xpra2
- Try harder to force centos to behave, override more versions too

* Thu Jul 28 2016 Antoine Martin <antoine@devloop.org.uk> - 3.1.1a1-4.xpra1
- Try to ensure this updates the Fedora upstream package

* Mon Jul 18 2016 Antoine Martin <antoine@devloop.org.uk> - 3.1.1a1r2-1
- Fix upgrade path for PyOpenGL_accelerate

* Sat Nov 28 2015 Antoine Martin <antoine@nagafix.co.uk> 3.1.1a1r1-1
- Force bump to ensure this supercedes the previous "final" builds

* Fri Nov 13 2015 Antoine Martin <antoine@nagafix.co.uk> 3.1.1a1-2
- Force rebuild with version lockstep change

* Sun Jul 12 2015 Antoine Martin <antoine@nagafix.co.uk> 3.1.1a1-1
- Force rebuild to workaround breakage caused by Fedora packaging differences
- Use new alpha build (no issues found so far)

* Wed Sep 17 2014 Antoine Martin <antoine@nagafix.co.uk> - 3.1.0final-3
- fixed Tk package dependencies

* Wed Sep 17 2014 Antoine Martin <antoine@nagafix.co.uk> - 3.1.0final-2
- Add Python3 package

* Fri Sep 05 2014 Antoine Martin <antoine@devloop.org.uk> 3.1.0final-1
- Fix version string to prevent upgrade to older beta version

* Fri Aug 08 2014 Antoine Martin <antoine@devloop.org.uk> 3.1.0-1
- Initial packaging for xpra
