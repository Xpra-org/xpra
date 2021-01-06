# This file is part of Xpra.
# Copyright (C) 2014-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

%{!?__python3: %define __python3 python3}
%{!?python3_sitearch: %global python3_sitearch %(%{__python3} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))")}

#we don't want to depend on libcuda via RPM dependencies
#so that we can install NVidia drivers without using RPM packages:
%define __requires_exclude ^libcuda.*$

%global debug_package %{nil}

Name:           python3-pycuda
Version:        2020.1
Release:        1
URL:            http://mathema.tician.de/software/pycuda
Summary:        Python3 wrapper CUDA
License:        MIT
Group:          Development/Libraries/Python
Source:        	https://files.pythonhosted.org/packages/46/61/47d3235a4c13eec5a5f03594ddb268f4858734e02980afbcd806e6242fa5/pycuda-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-build
Provides:       python3-pycuda

BuildRequires:  gcc-c++
BuildRequires:  python3-devel
BuildRequires:  python3-setuptools
BuildRequires:  python3-numpy
BuildRequires:  boost-python3-devel
BuildRequires:  cuda

%description
PyCUDA lets you access Nvidia‘s CUDA parallel computation API from Python.

Requires:       python3-decorator
Requires:       python3-numpy
Requires:       python3-pytools
Requires:       python3-six

%prep
%setup -q -n pycuda-%{version}

%build
%{__python3} ./configure.py \
	--cuda-enable-gl \
	--cuda-root=/usr/local/cuda \
	--cudadrv-lib-dir=%{_libdir} \
	--boost-inc-dir=%{_includedir} \
	--boost-lib-dir=%{_libdir} \
	--no-cuda-enable-curand \
	--boost-python-libname=boost_python37
#	--boost-thread-libname=boost_thread
%{__python3} setup.py build
make

%install
%{__python3} setup.py install --prefix=%{_prefix} --root=%{buildroot}

%clean
rm -rf %{buildroot}

%files
%defattr(-,root,root)
%doc examples/ test/
%{python3_sitearch}/pycuda*

%changelog
* Wed Jan 06 2021 Antoine Martin <antoine@xpra.org> - 2020.1-1
- new upstream release

* Thu Sep 26 2019 Antoine Martin <antoine@xpra.org> - 2019.1.2-2
- build only for python3

* Wed Sep 25 2019 Antoine Martin <antoine@xpra.org> - 2019.1.2-1
- build for centos8
- new upstream release

* Mon May 20 2019 Antoine Martin <antoine@xpra.org> - 2019.1-1
- new upstream release
- remove patch which has been merged

* Sun Jan 13 2019 Antoine Martin <antoine@xpra.org> - 2018.1.1-3
- add patch for releasing the GIL during init and make_context

* Sun Jan 13 2019 Antoine Martin <antoine@xpra.org> - 2018.1.1-2
- add missing python six dependency

* Tue Sep 18 2018 Antoine Martin <antoine@xpra.org> - 2018.1.1-1
- new upstream release fixing Fedora 29 builds

* Thu Aug 02 2018 Antoine Martin <antoine@xpra.org> - 2018.1-1
- new upstream release

* Wed Aug 09 2017 Antoine Martin <antoine@xpra.org> - 2017.1.1-1
- new upstream release

* Tue Jul 18 2017 Antoine Martin <antoine@xpra.org> - 2017.1-2
- build python3 variant too

* Thu Jun 01 2017 Antoine Martin <antoine@xpra.org> - 2017.1-1
- new upstream release

* Sat Dec 24 2016 Antoine Martin <antoine@xpra.org> - 2016.1.2-2
- try harder to supersede the old package name

* Fri Jul 29 2016 Antoine Martin <antoine@xpra.org> - 2016.1.2-1
- new upstream release

* Sun Jul 17 2016 Antoine Martin <antoine@xpra.org> - 2016.1.1-1
- new upstream release
- rename and obsolete old python package name

* Fri Apr 01 2016 Antoine Martin <antoine@xpra.org> - 2016.1-1
- new upstream release

* Wed Nov 04 2015 Antoine Martin <antoine@xpra.org> - 2015.1.3-1
- new upstream release

* Wed Jul 01 2015 Antoine Martin <antoine@xpra.org> - 2015.1.2-1
- new upstream release

* Wed Jun 17 2015 Antoine Martin <antoine@xpra.org> - 2015.1-1
- new upstream release

* Sun Mar 29 2015 Antoine Martin <antoine@xpra.org> - 2014.1-3
- remove dependency on libcuda so the package can be installed without using the RPM drivers

* Fri Nov 07 2014 Antoine Martin <antoine@xpra.org> - 2014.1-2
- remove curand bindings which require libcurand found in full CUDA SDK

* Wed Sep 03 2014 Antoine Martin <antoine@xpra.org> - 2014.1-1
- initial packaging
