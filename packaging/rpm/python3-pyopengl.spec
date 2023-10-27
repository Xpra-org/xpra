# Remove private provides from .so files in the python_sitearch directory
%global __provides_exclude_from ^%{python3_sitearch}/.*\\.so$

%define _disable_source_fetch 0
%if "%{getenv:PYTHON3}" == ""
%global python3 python3
%else
%global python3 %{getenv:PYTHON3}
%undefine __pythondist_requires
%undefine __python_requires
%define python3_sitelib %(%{python3} -Ic "from sysconfig import get_path; print(get_path('purelib').replace('/usr/local/', '/usr/'))" 2> /dev/null)
%define python3_sitearch %(%{python3} -Ic "from sysconfig import get_path; print(get_path('platlib').replace('/usr/local/', '/usr/'))" 2> /dev/null)
%endif

%global debug_package %{nil}

#this spec file is for both Fedora and CentOS
%global srcname PyOpenGL

Name:           %{python3}-pyopengl
Version:        3.1.7
Release:        2%{?dist}
Summary:        Python 3 bindings for OpenGL
License:        BSD
URL:            http://pyopengl.sourceforge.net/
Source0:        https://files.pythonhosted.org/packages/72/b6/970868d44b619292f1f54501923c69c9bd0ab1d2d44cf02590eac2706f4f/%{srcname}-%{version}.tar.gz
Source1:        https://files.pythonhosted.org/packages/93/09/d08b3d07dbd88258276496a47273778f330f5ccf8390cb21b16b29d660de/%{srcname}-accelerate-%{version}.tar.gz
Patch0:         pyopengl-egl-open-warning.patch

BuildRequires:  %{python3}-devel
BuildRequires:  %{python3}-setuptools
BuildRequires:  %{python3}-numpy
Requires:       freeglut
Requires:       %{python3}-numpy
Obsoletes:      %{python3}-PyOpenGL < 3.1.5
Obsoletes:      %{python3}-PyOpenGL-accelerate < 3.1.5
Provides:       %{python3}-PyOpenGL = %{version}-%{release}
Provides:       %{python3}-PyOpenGL-accelerate = %{version}-%{release}

%description
PyOpenGL is the cross platform Python binding to OpenGL and related APIs. It
includes support for OpenGL v1.1, GLU, GLUT v3.7, GLE 3 and WGL 4. It also
includes support for dozens of extensions (where supported in the underlying
implementation).

PyOpenGL is inter-operable with a large number of external GUI libraries
for Python including (Tkinter, wxPython, FxPy, PyGame, and Qt).


%package -n     %{python3}-pyopengl-tk
Summary:        %{srcname} Python 3.x Tk widget
BuildArch:      noarch
Requires:       %{python3}-pyopengl = %{version}-%{release}
Requires:       %{python3}-tkinter
# These can be removed in Fedora 27
Obsoletes:      %{python3}-PyOpenGL-Tk < 3.1.2
Provides:       %{python3}-PyOpenGL-Tk = %{version}-%{release}

%description -n %{python3}-pyopengl-tk
%{srcname} Togl (Tk OpenGL widget) 1.6 support for Python 3.x.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "eef31a3888e6984fd4d8e6c9961b184c9813ca82604d37fe3da80eb000a76c86" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
sha256=`sha256sum %{SOURCE1} | awk '{print $1}'`
if [ "${sha256}" != "2b123621273a939f7fd2ec227541e399f9b5d4e815d69ae0bdb1b6c70a293680" ]; then
	echo "invalid checksum for %{SOURCE1}"
	exit 1
fi
%setup -q -c -n %{srcname}-%{version} -T -a0 -a1
cd %{srcname}-%{version}
%patch -p1 -P 0


%build
for dir in %{srcname}-%{version} %{srcname}-accelerate-%{version} ; do
    pushd $dir
	%{python3} setup.py build
    popd
done


%install
for dir in %{srcname}-%{version} %{srcname}-accelerate-%{version} ; do
    pushd $dir
	%{python3} setup.py install -O1 --skip-build --root %{buildroot}
    popd
done

# Fix up perms on compiled object files
find %{buildroot}%{python3_sitearch}/OpenGL_accelerate/ -name *.so -exec chmod 755 '{}' \;

# Remove shebangs - note that weirdly these files have a space between
# the #! and the /, so this sed recipe is not the usual one
pushd %{buildroot}%{python3_sitelib}/OpenGL/arrays
sed -i -e '/^#! \//, 1d' buffers.py _buffers.py
popd
rm -fr %{buildroot}%{python3_sitearch}/UNKNOWN-*.egg-info


%files
%license %{srcname}-%{version}/license.txt
%{python3_sitelib}/%{srcname}-%{version}-py*.egg-info
%{python3_sitelib}/OpenGL/
%exclude %{python3_sitelib}/OpenGL/Tk
%{python3_sitearch}/OpenGL_accelerate/
%{python3_sitearch}/%{srcname}_accelerate-%{version}-py*.egg-info/


%files -n %{python3}-pyopengl-tk
%{python3_sitelib}/OpenGL/Tk


%changelog
* Fri Oct 27 2023 Antoine Martin <antoine@xpra.org> - 3.1.7-2
- add patch to silence egl file open warning

* Mon Oct 02 2023 Antoine Martin <antoine@xpra.org> - 3.1.7-1
- new upstream release
- remove 'xpra' package suffix

* Wed Feb 17 2021 Antoine Martin <antoine@xpra.org> - 3.1.5-1xpra2
- verify source checksum

* Wed Jan 22 2020 Antoine Martin <antoine@xpra.org> - 3.1.5-1xpra1
- new upstream release

* Wed Dec 04 2019 Antoine Martin <antoine@xpra.org> - 3.1.4-1xpra1
- new upstream release

* Mon Nov 25 2019 Antoine Martin <antoine@xpra.org> - 3.1.3rc1-1xpra1
- new upstream pre-release

* Wed Sep 18 2019 Antoine Martin <antoine@xpra.org> - 3.1.1a1-10xpra2
- remove python2 support

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
