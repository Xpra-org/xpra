%{!?__python2: %define __python2 python2}
%{!?python2_sitearch: %define python2_sitearch %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print get_python_lib(1)")}

Name:           PyOpenGL-accelerate
Version:        3.1.0
Release:        1%{?dist}
Summary:        Acceleration code for PyOpenGL
License:        BSD
Group:          System Environment/Libraries
URL:            http://pyopengl.sourceforge.net/
Source0:        http://downloads.sourceforge.net/pyopengl/%{name}-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)
BuildRequires:  python-devel Cython PyOpenGL
#see: http://fedoraproject.org/wiki/Changes/Remove_Python-setuptools-devel
%if 0%{?fedora}
BuildRequires:  python-setuptools
%else
BuildRequires:  python-setuptools-devel
%endif
Requires:       PyOpenGL

%description
This set of C (Cython) extensions provides acceleration of common operations for slow points in PyOpenGL 3.x.


%prep
%setup -q -n %{name}-%{version}

%build
%{__python2} setup.py build


%install
rm -rf $RPM_BUILD_ROOT
%{__python2} setup.py install -O1 --skip-build --root="$RPM_BUILD_ROOT" \
  --prefix="%{_prefix}"


%clean
rm -rf $RPM_BUILD_ROOT


%files
%defattr(-,root,root,-)
%{python2_sitearch}/*OpenGL_accelerate*


%changelog
* Fri Aug 08 2014 Antoine Martin <antoine@devloop.org.uk> 3.1.0
- Initial packaging for xpra
