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
%define python3_version %(%{python3} -c 'import sys;vi=sys.version_info;print(f"{vi[0]}.{vi[1]}")' 2> /dev/null)

%if 0%{?fedora} || 0%{?rhel} >= 9
%global blaslib flexiblas
%global siteblaslib flexiblas
%else
%global blaslib openblas
%global siteblaslib flexiblasp
%endif

%global modname numpy

Name:           numpy
Version:        1.26.4
Release:        1%{?dist}
Epoch:          1
Summary:        A fast multidimensional array facility for Python

# Everything is BSD except for class SafeEval in numpy/lib/utils.py which is Python
License:        BSD-3-Clause AND Apache-2.0
URL:            http://www.numpy.org/
Source0:        https://files.pythonhosted.org/packages/65/6e/09db70a523a96d25e115e71cc56a6f9031e7b8cd166c1ac8438307c14058/numpy-%{version}.tar.gz

%description
NumPy is a general-purpose array-processing package designed to
efficiently manipulate large multi-dimensional arrays of arbitrary
records without sacrificing too much speed for small multi-dimensional
arrays.  NumPy is built on the Numeric code base and adds features
introduced by numarray as well as an extended C-API and the ability to
create arrays of arbitrary type.

There are also basic facilities for discrete fourier transform,
basic linear algebra and random number generation. Also included in
this package is a version of f2py that works properly with NumPy.


%package -n %{python3}-numpy
Summary:        A fast multidimensional array facility for Python

License:        BSD-3-Clause
%{?python_provide:%python_provide python3-numpy}
Provides:       libnpymath-static = %{epoch}:%{version}-%{release}
Provides:       libnpymath-static%{?_isa} = %{epoch}:%{version}-%{release}
Provides:       numpy = %{epoch}:%{version}-%{release}
Provides:       numpy%{?_isa} = %{epoch}:%{version}-%{release}
Obsoletes:      numpy < 1:1.10.1-3

Requires:       %{python3}
BuildRequires:  %{python3}-devel
BuildRequires:  %{python3}-setuptools
BuildRequires:  %{python3}-Cython
BuildRequires:  gcc-gfortran
BuildRequires:  gcc
BuildRequires:  gcc-c++
BuildRequires:  lapack-devel
%if %{with tests}
BuildRequires:  %{python3}-hypothesis
BuildRequires:  %{python3}-pytest
BuildRequires:  %{python3}-test
BuildRequires:  %{python3}-typing-extensions
%endif
BuildRequires: %{blaslib}-devel
BuildRequires: chrpath

%description -n %{python3}-numpy
NumPy is a general-purpose array-processing package designed to
efficiently manipulate large multi-dimensional arrays of arbitrary
records without sacrificing too much speed for small multi-dimensional
arrays.  NumPy is built on the Numeric code base and adds features
introduced by numarray as well as an extended C-API and the ability to
create arrays of arbitrary type.

There are also basic facilities for discrete fourier transform,
basic linear algebra and random number generation. Also included in
this package is a version of f2py that works properly with NumPy.

%package -n %{python3}-numpy-doc
Summary:	Documentation for numpy
Requires:	python3-numpy = %{epoch}:%{version}-%{release}
BuildArch:	noarch

%description -n %{python3}-numpy-doc
This package provides the complete documentation for NumPy.


%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "2a02aba9ed12e4ac4eb3ea9421c420301a0c6460d9830d74a9df87efa4912010" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%autosetup -n %{name}-%{version} -p1

# Force re-cythonization (ifed for PKG-INFO presence in setup.py)
rm PKG-INFO

# openblas is provided by flexiblas by default; otherwise,
# Use openblas pthreads as recommended by upstream (see comment in site.cfg.example)
cat >> site.cfg <<EOF
[openblas]
libraries = %{siteblaslib}
library_dirs = %{_libdir}
EOF

%build
%set_build_flags

env OPENBLAS=%{_libdir} \
    BLAS=%{_libdir} \
    LAPACK=%{_libdir} CFLAGS="%{optflags}" \
    %{python3} setup.py build

%install
#%%{python3} setup.py install -O1 --skip-build --root %%{buildroot}
# skip-build currently broken, this works around it for now
env OPENBLAS=%{_libdir} \
    FFTW=%{_libdir} BLAS=%{_libdir} \
    LAPACK=%{_libdir} CFLAGS="%{optflags}" \
    %{python3} setup.py install --root %{buildroot} --prefix=%{_prefix}
rm -f %{buildroot}%{_bindir}/f2py
rm -f %{buildroot}%{_bindir}/f2py3
rm -f %{buildroot}%{_bindir}/f2py.numpy
rm -f %{buildroot}%{_bindir}/f2py%{python3_version}
rm -fr %{buildroot}%{python3_sitearch}/%{name}/f2py

# distutils from setuptools don't have the patch that was created to avoid standard runpath here
# we strip it manually instead
# ERROR   0001: file '...' contains a standard runpath '/usr/lib64' in [/usr/lib64]
chrpath --delete %{buildroot}%{python3_sitearch}/numpy/linalg/_umath_linalg.*.so
chrpath --delete %{buildroot}%{python3_sitearch}/numpy/linalg/lapack_lite.*.so
chrpath --delete %{buildroot}%{python3_sitearch}/numpy/core/_multiarray_umath.*.so


%files -n %{python3}-numpy
%license LICENSE.txt
%doc THANKS.txt site.cfg.example
%{python3_sitearch}/%{name}/__pycache__
%dir %{python3_sitearch}/%{name}
%{python3_sitearch}/%{name}/*.py*
%{python3_sitearch}/%{name}/*core
%{python3_sitearch}/%{name}/_utils
%{python3_sitearch}/%{name}/distutils
%{python3_sitearch}/%{name}/doc
%{python3_sitearch}/%{name}/fft
%{python3_sitearch}/%{name}/lib
%{python3_sitearch}/%{name}/linalg
%{python3_sitearch}/%{name}/ma
%{python3_sitearch}/%{name}/random
%{python3_sitearch}/%{name}/testing
%{python3_sitearch}/%{name}/tests
%{python3_sitearch}/%{name}/compat
%{python3_sitearch}/%{name}/matrixlib
%{python3_sitearch}/%{name}/polynomial
%{python3_sitearch}/%{name}-*.egg-info
%exclude %{python3_sitearch}/%{name}/LICENSE.txt
%{python3_sitearch}/%{name}/__init__.pxd
%{python3_sitearch}/%{name}/__init__.cython-30.pxd
%{python3_sitearch}/%{name}/py.typed
%{python3_sitearch}/%{name}/typing/
%{python3_sitearch}/%{name}/array_api/
%{python3_sitearch}/%{name}/_pyinstaller/
%{python3_sitearch}/%{name}/_typing/


%changelog
* Tue Feb 06 2024 Antoine Martin <antoine@xpra.org> - 1.26.4-1
- new upstream release

* Wed Jan 03 2024 Antoine Martin <antoine@xpra.org> - 1.26.3-1
- new upstream release

* Mon Nov 13 2023 Antoine Martin <antoine@xpra.org> - 1.26.2-1
- new upstream release

* Mon Oct 02 2023 Antoine Martin <antoine@xpra.org> - 1.26.0-1
- new upstream release
