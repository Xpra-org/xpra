%{!?__python2: %global __python2 /usr/bin/python2}
%{!?python2_sitelib: %global python2_sitelib %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print get_python_lib()")}

#this is a pure python package so debug is meaningless here:
%define debug_package %{nil}

Name:           python2-pynvml
Version:        7.352.0
Release:        1
URL:            http://pythonhosted.org/nvidia-ml-py/
Summary:        Python wrapper for NVML
License:        BSD
Group:          Development/Libraries/Python
Source:        	https://pypi.python.org/packages/72/31/378ca145e919ca415641a0f17f2669fa98c482a81f1f8fdfb72b1f9dbb37/nvidia-ml-py-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-build
Provides:       python-pynvml


%description
Python Bindings for the NVIDIA Management Library

%prep
%setup -q -n nvidia-ml-py-%{version}

%build
%{__python2} ./setup.py build

%install
%{__python2} ./setup.py install --prefix=%{_prefix} --root=%{buildroot}

%clean
rm -rf %{buildroot}

%files
%defattr(-,root,root)
%{python2_sitelib}/pynvml.py*
%{python2_sitelib}/nvidia_smi.py*
%{python2_sitelib}/nvidia_ml_py-%{version}-py*.egg-info

%changelog
* Mon Aug 29 2016 Antoine Martin <antoine@devloop.org.uk> - 7.352.0-1
- build newer version

* Fri Aug 05 2016 Antoine Martin <antoine@devloop.org.uk> - 4.304.04-1
- initial packaging
