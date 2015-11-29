%{!?__python2: %define __python2 python2}
%{!?python2_sitearch: %define python2_sitearch %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print get_python_lib(1)")}

#this spec file is for both Fedora and CentOS
#only Fedora has Python3 at present:
%if 0%{?fedora}
%define with_python3 1
%endif

%global VERSION 3.1.1a1
%global RPMVERSION %{VERSION}r1

Name:           PyOpenGL-accelerate
Version:        %{RPMVERSION}
Release:        1%{?dist}
Summary:        Acceleration code for PyOpenGL
License:        BSD
Group:          System Environment/Libraries
URL:            http://pyopengl.sourceforge.net/
Source0:        http://downloads.sourceforge.net/pyopengl/%{name}-%{VERSION}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)
BuildRequires:  python-devel
BuildRequires:  PyOpenGL
%if 0%{?suse_version}
BuildRequires:  python-Cython
%else
BuildRequires:  Cython
%endif

#see: http://fedoraproject.org/wiki/Changes/Remove_Python-setuptools-devel
%if 0%{?fedora}%{?suse_version}
BuildRequires:  python-setuptools
%else
BuildRequires:  python-setuptools-devel
%endif
Requires:       PyOpenGL = %{RPMVERSION}

%description
This set of C (Cython) extensions provides acceleration of common operations for slow points in PyOpenGL 3.x.


%if 0%{?with_python3}
%package -n python3-PyOpenGL-accelerate
Summary:        Acceleration code for PyOpenGL
Group:          System Environment/Libraries

%description -n python3-PyOpenGL-accelerate
This set of C (Cython) extensions provides acceleration of common operations for slow points in PyOpenGL 3.x.
%endif


%prep
%setup -q -n %{name}-%{VERSION}

%if 0%{?with_python3}
rm -rf %{py3dir}
cp -a . %{py3dir}
%endif

%build
%{__python2} setup.py build

%if 0%{?with_python3}
pushd %{py3dir}
%{__python3} setup.py build
popd
%endif

%install
rm -rf $RPM_BUILD_ROOT
%{__python2} setup.py install -O1 --skip-build --root="$RPM_BUILD_ROOT" \
  --prefix="%{_prefix}"

%if 0%{?with_python3}
%{__python3} setup.py install --root %{buildroot}
%endif

%clean
rm -rf $RPM_BUILD_ROOT


%files
%defattr(-,root,root,-)
%{python2_sitearch}/*OpenGL_accelerate*

%if 0%{?with_python3}
%files -n python3-PyOpenGL-accelerate
%defattr(-,root,root)
%{python3_sitearch}/*OpenGL_accelerate*
%endif


%changelog
* Sat Nov 28 2015 Antoine Martin <antoine@nagafix.co.uk> 3.1.1a1r1-1
- Force bump to ensure this supercedes the previous "final" builds

* Fri Nov 13 2015 Antoine Martin <antoine@nagafix.co.uk> 3.1.1a1-2
- Force rebuild with version lockstep change

* Sun Jul 12 2015 Antoine Martin <antoine@nagafix.co.uk> 3.1.1a1-1
- Force rebuild to workaround breakage caused by Fedora packaging differences
- Use new alpha build (no issues found so far)

* Wed Sep 17 2014 Antoine Martin <antoine@nagafix.co.uk> 3.1.0-2
- Add Python3 package

* Fri Aug 08 2014 Antoine Martin <antoine@devloop.org.uk> 3.1.0-1
- Initial packaging for xpra
