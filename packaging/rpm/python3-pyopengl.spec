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
Version:        3.1.9
Release:        1%{?dist}
Summary:        Python 3 bindings for OpenGL
License:        BSD
URL:            http://pyopengl.sourceforge.net/
Source0:        https://files.pythonhosted.org/packages/source/p/pyopengl_accelerate/pyopengl_accelerate-%{version}.tar.gz
Source1:        https://files.pythonhosted.org/packages/source/p/pyopengl/pyopengl-%{version}.tar.gz
Patch0:         pyopengl-py3.13-nonumpy.patch

BuildRequires:	coreutils
BuildRequires:  %{python3}-devel
BuildRequires:  %{python3}-setuptools
BuildRequires:  %{python3}-cython
BuildRequires:  gcc
Requires:       %{python3}
Requires:       freeglut
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

%description -n %{python3}-pyopengl-tk
%{srcname} Togl (Tk OpenGL widget) 1.6 support for Python 3.x.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "85957c7c76975818ff759ec9243f9dc7091ef6f373ea37a2eb50c320fd9a86f3" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
sha256=`sha256sum %{SOURCE1} | awk '{print $1}'`
if [ "${sha256}" != "28ebd82c5f4491a418aeca9672dffb3adbe7d33b39eada4548a5b4e8c03f60c8" ]; then
	echo "invalid checksum for %{SOURCE1}"
	exit 1
fi
%setup -q -c -n %{srcname}-%{version} -T -a0 -a1
pushd pyopengl_accelerate-%{version}
%patch -p1 -P 0
popd


%build
NPROCS=${NPROCS:-`nproc`}
for srcdir in pyopengl-%{version} pyopengl_accelerate-%{version}; do
    pushd $srcdir
    %{python3} setup.py build -j ${NPROCS}
    popd
done


%install
for srcdir in pyopengl-%{version} pyopengl_accelerate-%{version}; do
    pushd $srcdir
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
%license pyopengl-%{version}/license.txt
%{python3_sitelib}/OpenGL/
%{python3_sitelib}/PyOpenGL*.egg-info
%exclude %{python3_sitelib}/OpenGL/Tk
%{python3_sitearch}/OpenGL_accelerate/
%{python3_sitearch}/PyOpenGL_accelerate*.egg-info


%files -n %{python3}-pyopengl-tk
%{python3_sitelib}/OpenGL/Tk


%changelog
* Mon Jan 27 2025 Antoine Martin <antoine@xpra.org> - 3.1.9-1
- new upstream release
- switch back to pypi

* Thu Dec 05 2024 Antoine Martin <antoine@xpra.org> - 3.1.8-2
- also patch accelerate version number

* Sat Nov 09 2024 Antoine Martin <antoine@xpra.org> - 3.1.8-1
- build new release from github archive, match merged layout

* Sat Aug 17 2024 Antoine Martin <antoine@xpra.org> - 3.1.7-8
- added cython dependency to re-generate the C bindings

* Tue Jul 02 2024 Antoine Martin <antoine@xpra.org> - 3.1.7-7
- add Python 3.12 patch for ctypes change

* Sat Jun 15 2024 Antoine Martin <antoine@xpra.org> - 3.1.7-6
- lower `numpy` to a suggestion, because xpra doesn't use numpy with pyopengl

* Sat Jun 15 2024 Antoine Martin <antoine@xpra.org> - 3.1.7-5
- don't require numpy, only recommend it
- apply no-numpy patch on Fedora 40+
- remove reference to outdated 'PyOpenGL-Tk'

* Sat Oct 28 2023 Antoine Martin <antoine@xpra.org> - 3.1.7-4
- bump release number to update the build from Fedora 39

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
