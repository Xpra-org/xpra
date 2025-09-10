# This file is part of Xpra.
# Copyright (C) 2014-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#we don't want to depend on libcuda via RPM dependencies
#so that we can install NVidia drivers without using RPM packages:
%define __requires_exclude ^libcuda.*$

%define _disable_source_fetch 0
%if "%{getenv:PYTHON3}" == ""
%global python3 python3
%define systemboost 1
%else
%global python3 %{getenv:PYTHON3}
%define systemboost 0
%undefine __pythondist_requires
%undefine __python_requires
%endif
%define python3_sitearch %(%{python3} -Ic "from sysconfig import get_path; print(get_path('platlib').replace('/usr/local/', '/usr/'))" 2> /dev/null)

%global debug_package %{nil}

%define STUBS_DIR targets/x86_64-linux/lib/stubs/
%ifarch aarch64
%define STUBS_DIR targets/sbsa-linux/lib/stubs/
%endif

Name:           %{python3}-pycuda
Version:        2025.1.2
Release:        1
URL:            http://mathema.tician.de/software/pycuda
Summary:        Python3 wrapper CUDA
License:        MIT
Group:          Development/Libraries/Python
Source0:        https://files.pythonhosted.org/packages/source/p/pycuda/pycuda-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-build
Provides:       %{python3}-pycuda

BuildRequires:	coreutils
BuildRequires:  make
BuildRequires:  gcc-c++
BuildRequires:  %{python3}-devel
BuildRequires:  %{python3}-setuptools
BuildRequires:  %{python3}-numpy
BuildRequires:  boost-python3-devel
BuildRequires:  libglvnd-devel
BuildRequires:  cuda

%description
PyCUDA lets you access Nvidia‘s CUDA parallel computation API from Python.


Requires:       %{python3}
Requires:       %{python3}-decorator
Requires:       %{python3}-numpy
Requires:       %{python3}-pytools
Requires:       %{python3}-six

Suggests:       nvidia-driver-cuda-libs

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "0dd82911d72d8e03c63128ae44e99cfb7b4689094aba6cc5193d8e944717aafa" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n pycuda-%{version}

%build
CUDA=/opt/cuda
# get the python version number like "312" for 3.12:
%define py_mm %(%{python3} -c 'import sys;print("%i%i" % sys.version_info[:2])')
%{python3} ./configure.py \
	--cuda-enable-gl \
	--cuda-root=$CUDA \
	--cudadrv-lib-dir=%{_libdir} \
	--boost-inc-dir=%{_includedir} \
	--boost-lib-dir=%{_libdir} \
%if %{systemboost}
	--no-use-shipped-boost \
	--boost-python-libname=boost_python%{py_mm} \
%endif
	--no-cuda-enable-curand
#	--boost-thread-libname=boost_thread
NPROCS=${NPROCS:-`nproc`}
LDFLAGS=-L$CUDA/%{STUBS_DIR} CXXFLAGS=-L$CUDA/%{STUBS_DIR} %{python3} setup.py build -j ${NPROCS}
#make

%install
CUDA=/opt/cuda
LDFLAGS=-L$CUDA/%{STUBS_DIR} CXXFLAGS=-L$CUDA/%{STUBS_DIR} %{python3} setup.py install --prefix=%{_prefix} --root=%{buildroot}
# RHEL stream setuptools bug?
rm -fr %{buildroot}%{python3_sitearch}/UNKNOWN-*.egg-info

%clean
rm -rf %{buildroot}

%files
%defattr(-,root,root)
%doc examples/ test/
%{python3_sitearch}/pycuda*

%changelog
* Wed Sep 10 2025 Antoine Martin <antoine@xpra.org> - 2025.1.2-1
- new upstream release

* Mon Jun 09 2025 Antoine Martin <antoine@xpra.org> - 2025.1.1-1
- new upstream release

* Sat Feb 08 2025 Antoine Martin <antoine@xpra.org> - 2025.1-1
- new upstream release

* Fri Aug 16 2024 Antoine Martin <antoine@xpra.org> - 2024.1.2-2
- link against the system boost-python library for 'python3' builds
- add patch for Python 3.13 compatibility: new buffer interface

* Tue Jul 30 2024 Antoine Martin <antoine@xpra.org> - 2024.1.2-1
- new upstream release

* Wed Jul 24 2024 Antoine Martin <antoine@xpra.org> - 2024.1.1-1
- new upstream release

* Wed Jan 03 2024 Antoine Martin <antoine@xpra.org> - 2024.1-1
- new upstream release

* Sat Nov 11 2023 Antoine Martin <antoine@xpra.org> - 2023.1-1
- new upstream release

* Wed Dec 21 2022 Antoine Martin <antoine@xpra.org> - 2022.2.2-1
- new upstream release

* Wed Dec 21 2022 Antoine Martin <antoine@xpra.org> - 2022.2.1-1
- new upstream release

* Tue Nov 22 2022 Antoine Martin <antoine@xpra.org> - 2022.2-1
- new upstream release
- remove context cleanup failures patch (merged)

* Tue Aug 16 2022 Antoine Martin <antoine@xpra.org> - 2022.1-2
- add patch to show context cleanup failures

* Sat Jun 25 2022 Antoine Martin <antoine@xpra.org> - 2022.1-1
- new upstream release

* Sun May 02 2021 Antoine Martin <antoine@xpra.org> - 2021.1-1
- new upstream release

* Wed Feb 17 2021 Antoine Martin <antoine@xpra.org> - 2020.1-3
- verify source checksum

* Thu Jan 07 2021 Antoine Martin <antoine@xpra.org> - 2020.1-2
- add weak dependency on the driver RPM which provides libcuda

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
