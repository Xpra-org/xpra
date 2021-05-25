# Remove private provides from .so files in the python_sitearch directory
%global __provides_exclude_from ^%{python3_sitearch}/.*\\.so$

%define _disable_source_fetch 0
#this spec file is for both Fedora and CentOS
%global srcname PyOpenGL

Name:           python3-pyopengl
Version:        3.1.5
Release:        1xpra2%{?dist}
Summary:        Python 3 bindings for OpenGL
License:        BSD
URL:            http://pyopengl.sourceforge.net/
Source0:        https://files.pythonhosted.org/packages/b8/73/31c8177f3d236e9a5424f7267659c70ccea604dab0585bfcd55828397746/%{srcname}-%{version}.tar.gz
Source1:        https://files.pythonhosted.org/packages/a2/3c/f42a62b7784c04b20f8b88d6c8ad04f4f20b0767b721102418aad94d8389/%{srcname}-accelerate-%{version}.tar.gz

BuildRequires:  python3-devel
BuildRequires:  python3-setuptools
BuildRequires:  python3-numpy
Requires:       freeglut
Requires:       python3-numpy
Obsoletes:      python3-PyOpenGL < 3.1.2
Obsoletes:      python3-PyOpenGL-accelerate < 3.1.2
Provides:       python3-PyOpenGL = %{version}-%{release}
Provides:       python3-PyOpenGL-accelerate = %{version}-%{release}

%description
PyOpenGL is the cross platform Python binding to OpenGL and related APIs. It
includes support for OpenGL v1.1, GLU, GLUT v3.7, GLE 3 and WGL 4. It also
includes support for dozens of extensions (where supported in the underlying
implementation).

PyOpenGL is inter-operable with a large number of external GUI libraries
for Python including (Tkinter, wxPython, FxPy, PyGame, and Qt).


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

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "4107ba0d0390da5766a08c242cf0cf3404c377ed293c5f6d701e457c57ba3424" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
sha256=`sha256sum %{SOURCE1} | awk '{print $1}'`
if [ "${sha256}" != "12e5518b0216a478527c7ce5ddce623c3d0517adeb87226da767772e8b7f2f06" ]; then
	echo "invalid checksum for %{SOURCE1}"
	exit 1
fi
%setup -q -c -n %{srcname}-%{version} -T -a0 -a1


%build
for dir in %{srcname}-%{version} %{srcname}-accelerate-%{version} ; do
    pushd $dir
	%{__python3} setup.py build
    popd
done


%install
for dir in %{srcname}-%{version} %{srcname}-accelerate-%{version} ; do
    pushd $dir
	%{__python3} setup.py install -O1 --skip-build --root %{buildroot}
    popd
done

# Fix up perms on compiled object files
find %{buildroot}%{python3_sitearch}/OpenGL_accelerate/ -name *.so -exec chmod 755 '{}' \;

# Remove shebangs - note that weirdly these files have a space between
# the #! and the /, so this sed recipe is not the usual one
pushd %{buildroot}%{python3_sitelib}/OpenGL/arrays
sed -i -e '/^#! \//, 1d' buffers.py _buffers.py
popd


%files
%license %{srcname}-%{version}/license.txt
%{python3_sitelib}/%{srcname}-%{version}-py%{python3_version}.egg-info
%{python3_sitelib}/OpenGL/
%exclude %{python3_sitelib}/OpenGL/Tk
%{python3_sitearch}/OpenGL_accelerate/
%{python3_sitearch}/%{srcname}_accelerate-%{version}-py%{python3_version}.egg-info/


%files -n python3-pyopengl-tk
%{python3_sitelib}/OpenGL/Tk


%changelog
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
