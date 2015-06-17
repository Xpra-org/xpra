%if 0%{?rhel} && 0%{?rhel} <= 6
%{!?__python2: %global __python2 /usr/bin/python2}
%{!?python2_sitearch: %global python2_sitearch %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))")}
%endif

#we don't want to depend on libcuda via RPM dependencies
#so that we can install NVidia drivers without using RPM packages:
%define __requires_exclude ^libcuda.*$

Name:           python-pycuda
Version:        2015.1
Release:        1
Url:            http://mathema.tician.de/software/pycuda
Summary:        Python wrapper CUDA
License:        MIT
Group:          Development/Libraries/Python
Source:        	http://pypi.python.org/pypi/cuda/%{version}/pycuda-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-build

Requires:       python-decorator
Requires:       numpy
Requires:       python-pytools

BuildRequires:  gcc-c++
BuildRequires:  python-devel
BuildRequires:  python-distribute
BuildRequires:  boost-devel
BuildRequires:  numpy
BuildRequires:  cuda


%description
PyCUDA lets you access Nvidia‘s CUDA parallel computation API from Python.

%prep
%setup -q -n pycuda-%{version}

%build
%{__python} ./configure.py \
	--cuda-enable-gl \
	--cuda-root=/usr/local/cuda \
	--cudadrv-lib-dir=/usr/local/lib64 \
	--cudadrv-lib-dir=%{_libdir} \
	--boost-inc-dir=%{_includedir} \
	--boost-lib-dir=%{_libdir} \
	--no-cuda-enable-curand
#	--boost-python-libname=boost_python-mt \
#	--boost-thread-libname=boost_thread
python setup.py build
make

%install
python setup.py install --prefix=%{_prefix} --root=%{buildroot}

%clean
rm -rf %{buildroot}

%files
%defattr(-,root,root)
%doc examples/ test/
%{python2_sitearch}/pycuda*

%changelog
* Wed Jun 17 2015 Antoine Martin <antoine@devloop.org.uk - 2015.1-1
- new upstream release

* Sun Mar 29 2015 Antoine Martin <antoine@devloop.org.uk - 2014.1-3
- remove dependency on libcuda so the package can be installed without using the RPM drivers

* Fri Nov 07 2014 Antoine Martin <antoine@devloop.org.uk - 2014.1-2
- remove curand bindings which require libcurand found in full CUDA SDK

* Wed Sep 03 2014 Antoine Martin <antoine@devloop.org.uk - 2014.1-1
- initial packaging
