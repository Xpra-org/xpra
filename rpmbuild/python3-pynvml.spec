# This file is part of Xpra.
# Copyright (C) 2015-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

%{!?__python3: %define __python3 python3}
%{!?python3_sitelib: %define python3_sitelib %(%{__python3} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib())")}

#this is a pure python package so debug is meaningless here:
%define debug_package %{nil}

Name:           python3-pynvml
Version:        11.450.51
Release:        1
URL:            http://pythonhosted.org/nvidia-ml-py/
Summary:        Python3 wrapper for NVML
License:        BSD
Group:          Development/Libraries/Python
Source:        	https://files.pythonhosted.org/packages/4c/e7/f6fef887708f601cda64c8fd48dcb80a0763cb6ee4eaf89939bdc165ce41/nvidia-ml-py-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-build
Provides:       python-pynvml

%description
Python Bindings for the NVIDIA Management Library

%prep
%setup -q -n nvidia-ml-py-%{version}

%build
%{__python3} ./setup.py build

%install
%{__python3} ./setup.py install --prefix=%{_prefix} --root=%{buildroot}
rm -f %{buildroot}/%{python3_sitelib}/__pycache__/example.*
rm -f %{buildroot}/%{python3_sitelib}/example.py

%clean
rm -rf %{buildroot}

%files
%defattr(-,root,root)
%{python3_sitelib}/__pycache__/pynvml*
%{python3_sitelib}/pynvml.py*
%{python3_sitelib}/nvidia_ml_py-%{version}-py*.egg-info

%changelog
* Sat Feb 06 2021 Antoine Martin <antoine@xpra.org> - 11.450.51-1
- new upstream release

* Fri Dec 06 2019 Antoine Martin <antoine@xpra.org> - 10.418.84-1
- new upstream release

* Thu Sep 26 2019 Antoine Martin <antoine@xpra.org> - 7.352.0-3
- drop support for python2

* Tue Jul 18 2017 Antoine Martin <antoine@xpra.org> - 7.352.0-2
- build python3 variant too

* Mon Aug 29 2016 Antoine Martin <antoine@xpra.org> - 7.352.0-1
- build newer version

* Fri Aug 05 2016 Antoine Martin <antoine@xpra.org> - 4.304.04-1
- initial packaging
