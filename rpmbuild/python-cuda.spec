%if 0%{?rhel} && 0%{?rhel} <= 6
%{!?__python2: %global __python2 /usr/bin/python2}
%{!?python2_sitearch: %global python2_sitearch %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))")}
%endif

Name:           python-cuda
Version:        2014.1
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
./configure.py \
	--cuda-enable-gl \
	--cuda-root=/usr/local/cuda \
	--cudadrv-lib-dir=/usr/local/lib64 \
	--cudadrv-lib-dir=%{_libdir} \
	--boost-inc-dir=%{_includedir} \
	--boost-lib-dir=%{_libdir}
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

* Wed Sep 03 2014 Antoine Martin <antoine@devloop.org.uk - 2014.1-1
- initial packaging
