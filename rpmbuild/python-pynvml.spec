# This file is part of Xpra.
# Copyright (C) 2015-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

%{!?__python2: %global __python2 python2}
%{!?__python3: %define __python3 python3}
%{!?python2_sitearch: %global python2_sitearch %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))")}
%{!?python3_sitearch: %global python3_sitearch %(%{__python3} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))")}

#this is a pure python package so debug is meaningless here:
%define debug_package %{nil}

Name:           python2-pynvml
Version:        7.352.0
Release:        2
URL:            http://pythonhosted.org/nvidia-ml-py/
Summary:        Python wrapper for NVML
License:        BSD
Group:          Development/Libraries/Python
Source:        	https://pypi.python.org/packages/72/31/378ca145e919ca415641a0f17f2669fa98c482a81f1f8fdfb72b1f9dbb37/nvidia-ml-py-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-build
Provides:       python-pynvml

%description
Python Bindings for the NVIDIA Management Library

%if 0%{?fedora}
%package -n python3-pynvml
Summary:        Python3 wrapper for NVML
License:        BSD
Group:          Development/Libraries/Python

%description -n python3-pynvml
Python Bindings for the NVIDIA Management Library
%endif

%prep
%setup -q -n nvidia-ml-py-%{version}

%build
%{__python2} ./setup.py build
%if 0%{?fedora}
rm -fr %{py3dir}
cp -r . %{py3dir}
find %{py3dir} -name "*.py" -exec 2to3 -w {} \;
%endif

%install
%{__python2} ./setup.py install --prefix=%{_prefix} --root=%{buildroot}
%if 0%{?fedora}
pushd %{py3dir}
%{__python3} ./setup.py install --prefix=%{_prefix} --root=%{buildroot}
popd
%endif

%clean
rm -rf %{buildroot}

%files
%defattr(-,root,root)
%{python2_sitelib}/pynvml.py*
%{python2_sitelib}/nvidia_smi.py*
%{python2_sitelib}/nvidia_ml_py-%{version}-py*.egg-info

%if 0%{?fedora}
%files -n python3-pynvml
%defattr(-,root,root)
%{python3_sitelib}/__pycache__/nvidia*
%{python3_sitelib}/__pycache__/pynvml*
%{python3_sitelib}/pynvml.py*
%{python3_sitelib}/nvidia_smi.py*
%{python3_sitelib}/nvidia_ml_py-%{version}-py*.egg-info
%endif

%changelog
* Tue Jul 18 2017 Antoine Martin <antoine@devloop.org.uk> - 7.352.0-2
- build python3 variant too

* Mon Aug 29 2016 Antoine Martin <antoine@devloop.org.uk> - 7.352.0-1
- build newer version

* Fri Aug 05 2016 Antoine Martin <antoine@devloop.org.uk> - 4.304.04-1
- initial packaging
