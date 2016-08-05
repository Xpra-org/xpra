%{!?__python2: %global __python2 /usr/bin/python2}
%{!?python2_sitelib: %global python_sitelib %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print get_python_lib()")}

#this is a pure python package so debug is meaningless here:
%define debug_package %{nil}

Name:           python2-pynvml
Version:        4.304.04
Release:        1
URL:            http://pythonhosted.org/nvidia-ml-py/
Summary:        Python wrapper for NVML
License:        BSD
Group:          Development/Libraries/Python
Source:        	https://pypi.python.org/packages/bf/0a/390865781cbc4984d54ea178931cd86e50a60fbc948ea0464cd1ff3ec273/nvidia-ml-py-%{version}.tar.gz
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
* Fri Aug 05 2016 Antoine Martin <antoine@devloop.org.uk> - 4.304.04-1
- initial packaging
