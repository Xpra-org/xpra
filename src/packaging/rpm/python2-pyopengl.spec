# Remove private provides from .so files in the python_sitearch directory
%global __provides_exclude_from ^%{python2_sitearch}/.*\\.so$
%{!?__python2: %define __python2 python2}
%{!?python2_sitearch: %global python2_sitearch %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))")}
%{!?python2_sitelib: %global python2_sitelib %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib())")}
%{!?python2_version: %global python2_version %(%{__python2} -c "import sys; sys.stdout.write(sys.version[:3])")}
%define _disable_source_fetch 0

#this spec file is for both Fedora and CentOS
%global srcname PyOpenGL

Name:           python2-pyopengl
Release:        1xpra1%{?dist}
Summary:        Python bindings for OpenGL
License:        BSD
URL:            http://pyopengl.sourceforge.net/
%if 0%{?el7}
Version:        3.1.6
Source0:        https://files.pythonhosted.org/packages/5b/01/f8fd986bc7f456f1a925ee0239f0391838ade92cdb6e5b674ffb8b86cfd6/PyOpenGL-%{version}.tar.gz
Source1:        https://files.pythonhosted.org/packages/8e/47/64aa665af0f7d0c2f6c4a865c1d521c3697504da971366d4dea12ce8b339/PyOpenGL-accelerate-%{version}.tar.gz
%else
Version:        3.1.7
Source0:        https://files.pythonhosted.org/packages/72/b6/970868d44b619292f1f54501923c69c9bd0ab1d2d44cf02590eac2706f4f/PyOpenGL-%{version}.tar.gz
Source1:        https://files.pythonhosted.org/packages/93/09/d08b3d07dbd88258276496a47273778f330f5ccf8390cb21b16b29d660de/PyOpenGL-accelerate-%{version}.tar.gz
%endif

Requires:       freeglut
Obsoletes:      python-pyopengl < %{version}-%{release}
Provides:       python-pyopengl = %{version}-%{release}
Obsoletes:      pyopengl < %{version}-%{release}
Provides:       pyopengl = %{version}-%{release}
Conflicts:		pyopengl < %{version}-%{release}
Obsoletes:      PyOpenGL < %{version}-%{release}
Provides:       PyOpenGL = %{version}-%{release}
Conflicts:		PyOpenGL < %{version}-%{release}
#Fedora broke our xpra repository :(
Obsoletes:      PyOpenGL-accelerate < %{version}-%{release}
Provides:       PyOpenGL-accelerate = %{version}-%{release}
Conflicts:		PyOpenGL-accelerate < %{version}-%{release}

BuildRequires:  gcc
%if 0%{?fedora}%{?el8}
%global __provides_exclude_from ^(%{python2_sitearch})/.*\\.so$
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

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
%if 0%{?el7}
if [ "${sha256}" != "8ea6c8773927eda7405bffc6f5bb93be81569a7b05c8cac50cd94e969dce5e27" ]; then
%else
if [ "${sha256}" != "eef31a3888e6984fd4d8e6c9961b184c9813ca82604d37fe3da80eb000a76c86" ]; then
%endif
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
sha256=`sha256sum %{SOURCE1} | awk '{print $1}'`
%if 0%{?el7}
if [ "${sha256}" != "ad8a300256eca25228261de16f741e51a30f34f1e1b1cf68359f5c62dbcdcdc3" ]; then
%else
if [ "${sha256}" != "2b123621273a939f7fd2ec227541e399f9b5d4e815d69ae0bdb1b6c70a293680" ]; then
%endif
	echo "invalid checksum for %{SOURCE1}"
	exit 1
fi
%setup -q -c -n %{srcname}-%{version} -T -a0 -a1
rm %{srcname}-%{version}/OpenGL/EGL/debug.py
rm %{srcname}-%{version}/tests/osdemo.py


%build
for dir in %{srcname}-%{version} %{srcname}-accelerate-%{version} ; do
    pushd $dir
	%{__python2} setup.py build
    popd
done


%install
for dir in %{srcname}-%{version} %{srcname}-accelerate-%{version} ; do
    pushd $dir
	%{__python2} setup.py install -O1 --skip-build --root %{buildroot}
    popd
done

# Fix up perms on compiled object files
find %{buildroot}%{python2_sitearch}/OpenGL_accelerate/ -name *.so -exec chmod 755 '{}' \;

%files
%{python2_sitelib}/%{srcname}-%{version}-py%{python2_version}.egg-info
%{python2_sitelib}/OpenGL/
%exclude %{python2_sitelib}/OpenGL/Tk
%{python2_sitearch}/OpenGL_accelerate/
%{python2_sitearch}/%{srcname}_accelerate-%{version}-py%{python2_version}.egg-info/

%files -n python2-pyopengl-tk
%{python2_sitelib}/OpenGL/Tk

%changelog
%if !0%{?el7}
* Thu Jun 08 2023 Antoine Martin <antoine@xpra.org> - 3.1.7-1xpra1
- new upstream release
%endif

* Mon Jan 09 2023 Antoine Martin <antoine@xpra.org> - 3.1.6-1xpra1
- new upstream release

* Wed Jan 22 2020 Antoine Martin <antoine@xpra.org> - 3.1.5-1xpra1
- new upstream release

* Wed Dec 04 2019 Antoine Martin <antoine@xpra.org> - 3.1.4-1xpra1
- new upstream release

* Mon Nov 25 2019 Antoine Martin <antoine@xpra.org> - 3.1.3rc1-1xpra1
- new upstream pre-release

* Tue Jul 03 2018 Antoine Martin <antoine@xpra.org> - 3.1.1a1-10xpra1
- try harder to prevent rpm db conflicts

* Thu Dec 07 2017 Antoine Martin <antoine@xpra.org> - 3.1.1a1-9xpra1
- remove opensuse bitrot

* Thu Jul 13 2017 Antoine Martin <antoine@xpra.org> - 3.1.1a1-4.2xpra4
- also obsolete / provide "python-opengl" package name

* Tue Jan 10 2017 Antoine Martin <antoine@xpra.org> - 3.1.1a1-4.1xpra4
- also use "python2-opengl" package name on CentOS

* Fri Aug 05 2016 Antoine Martin <antoine@xpra.org> - 3.1.1a1-4.1xpra3
- Fedora 23 does not have the python2 renamed packages yet
- only opensuse calls numpy python-numpy

* Mon Aug 01 2016 Antoine Martin <antoine@xpra.org> - 3.1.1a1-4.1xpra2
- and again

* Mon Aug 01 2016 Antoine Martin <antoine@xpra.org> - 3.1.1a1-4.xpra2
- Try harder to force centos to behave, override more versions too

* Thu Jul 28 2016 Antoine Martin <antoine@xpra.org> - 3.1.1a1-4.xpra1
- Try to ensure this updates the Fedora upstream package

* Mon Jul 18 2016 Antoine Martin <antoine@xpra.org> - 3.1.1a1r2-1
- Fix upgrade path for PyOpenGL_accelerate

* Sat Nov 28 2015 Antoine Martin <antoine@xpra.org> 3.1.1a1r1-1
- Force bump to ensure this supercedes the previous "final" builds

* Fri Nov 13 2015 Antoine Martin <antoine@xpra.org> 3.1.1a1-2
- Force rebuild with version lockstep change

* Sun Jul 12 2015 Antoine Martin <antoine@xpra.org> 3.1.1a1-1
- Force rebuild to workaround breakage caused by Fedora packaging differences
- Use new alpha build (no issues found so far)

* Wed Sep 17 2014 Antoine Martin <antoine@xpra.org> - 3.1.0final-3
- fixed Tk package dependencies

* Wed Sep 17 2014 Antoine Martin <antoine@xpra.org> - 3.1.0final-2
- Add Python3 package

* Fri Sep 05 2014 Antoine Martin <antoine@xpra.org> 3.1.0final-1
- Fix version string to prevent upgrade to older beta version

* Fri Aug 08 2014 Antoine Martin <antoine@xpra.org> 3.1.0-1
- Initial packaging for xpra
