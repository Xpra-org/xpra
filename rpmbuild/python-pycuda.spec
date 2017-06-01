%{!?__python2: %global __python2 /usr/bin/python2}
%{!?python2_sitearch: %global python2_sitearch %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))")}

#we don't want to depend on libcuda via RPM dependencies
#so that we can install NVidia drivers without using RPM packages:
%define __requires_exclude ^libcuda.*$

Name:           python2-pycuda
Version:        2017.1
Release:        1
URL:            http://mathema.tician.de/software/pycuda
Summary:        Python wrapper CUDA
License:        MIT
Group:          Development/Libraries/Python
Source:        	https://pypi.python.org/packages/3b/55/22c03d8daa62a07c93d4b5771ec346f91477c904653186863f622f079e59/pycuda-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-build
Provides:       python-pycuda
Obsoletes:      python-pycuda
Conflicts:      python-pycuda

Requires:       python-decorator
Requires:       numpy
Requires:       python-pytools

BuildRequires:  gcc-c++
BuildRequires:  python-devel
%if 0%{?fedora}
BuildRequires:  python-setuptools
%else
BuildRequires:  python-distribute
%endif
BuildRequires:  boost-devel
BuildRequires:  numpy
BuildRequires:  cuda


%description
PyCUDA lets you access Nvidia‘s CUDA parallel computation API from Python.

%prep
%setup -q -n pycuda-%{version}

%build
%{__python2} ./configure.py \
	--cuda-enable-gl \
	--cuda-root=/usr/local/cuda \
	--cudadrv-lib-dir=/usr/local/lib64 \
	--cudadrv-lib-dir=%{_libdir} \
	--boost-inc-dir=%{_includedir} \
	--boost-lib-dir=%{_libdir} \
	--no-cuda-enable-curand
#	--boost-python-libname=boost_python-mt \
#	--boost-thread-libname=boost_thread
%{__python2} setup.py build
make

%install
%{__python2} setup.py install --prefix=%{_prefix} --root=%{buildroot}

%clean
rm -rf %{buildroot}

%files
%defattr(-,root,root)
%doc examples/ test/
%{python2_sitearch}/pycuda*

%changelog
* Thu Jun 01 2017 Antoine Martin <antoine@devloop.org.uk> - 2017.1-1
- new upstream release

* Sat Dec 24 2016 Antoine Martin <antoine@devloop.org.uk> - 2016.1.2-2
- try harder to supersede the old package name

* Fri Jul 29 2016 Antoine Martin <antoine@devloop.org.uk> - 2016.1.2-1
- new upstream release

* Sun Jul 17 2016 Antoine Martin <antoine@nagafix.co.uk> - 2016.1.1-1
- new upstream release
- rename and obsolete old python package name

* Fri Apr 01 2016 Antoine Martin <antoine@devloop.org.uk> - 2016.1-1
- new upstream release

* Wed Nov 04 2015 Antoine Martin <antoine@devloop.org.uk> - 2015.1.3-1
- new upstream release

* Wed Jul 01 2015 Antoine Martin <antoine@devloop.org.uk> - 2015.1.2-1
- new upstream release

* Wed Jun 17 2015 Antoine Martin <antoine@devloop.org.uk> - 2015.1-1
- new upstream release

* Sun Mar 29 2015 Antoine Martin <antoine@devloop.org.uk> - 2014.1-3
- remove dependency on libcuda so the package can be installed without using the RPM drivers

* Fri Nov 07 2014 Antoine Martin <antoine@devloop.org.uk> - 2014.1-2
- remove curand bindings which require libcurand found in full CUDA SDK

* Wed Sep 03 2014 Antoine Martin <antoine@devloop.org.uk> - 2014.1-1
- initial packaging
