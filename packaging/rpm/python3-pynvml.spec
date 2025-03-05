# This file is part of Xpra.
# Copyright (C) 2015-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

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

#this is a pure python package so debug is meaningless here:
%define debug_package %{nil}

Name:           %{python3}-pynvml
Version:        12.570.86
Release:        1
URL:            http://pythonhosted.org/nvidia-ml-py/
Summary:        Python3 wrapper for NVML
License:        BSD
Group:          Development/Libraries/Python
Source0:        https://files.pythonhosted.org/packages/source/n/nvidia_ml_py/nvidia_ml_py-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-build
Requires:       %{python3}
BuildRequires:  %{python3}-devel
BuildRequires:  %{python3}-setuptools

%description
Python Bindings for the NVIDIA Management Library

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "0508d4a0c7b6d015cf574530b95a62ed4fc89da3b8b47e1aefe6777db170ec8b" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n nvidia_ml_py-%{version}

%build
%{python3} ./setup.py build

%install
%{python3} ./setup.py install --prefix=%{_prefix} --root=%{buildroot}
rm -f %{buildroot}/%{python3_sitelib}/__pycache__/example.*
rm -f %{buildroot}/%{python3_sitelib}/example.py
rm -fr %{buildroot}%{python3_sitearch}/UNKNOWN-*.egg-info

%clean
rm -rf %{buildroot}

%files
%defattr(-,root,root)
%{python3_sitelib}/__pycache__/pynvml*
%{python3_sitelib}/pynvml.py*
%{python3_sitelib}/nvidia_ml_py-%{version}*-py*.egg-info

%changelog
* Mon Jan 27 2025 Antoine Martin <antoine@xpra.org> - 12.570.86-1
- new upstream release

* Tue Sep 03 2024 Antoine Martin <antoine@xpra.org> - 12.560.30-1
- new upstream release

* Mon Jun 03 2024 Antoine Martin <antoine@xpra.org> - 12.555.43-1
- new upstream release

* Thu Apr 25 2024 Antoine Martin <antoine@xpra.org> - 12.550.52-1
- new upstream release

* Sat Nov 11 2023 Antoine Martin <antoine@xpra.org> - 12.535.133-1
- new upstream release

* Wed Jul 12 2023 Antoine Martin <antoine@xpra.org> - 12.535.77-1
- new upstream release

* Sun Mar 12 2023 Antoine Martin <antoine@xpra.org> - 11.525.112-1
- new upstream release

* Wed Feb 22 2023 Antoine Martin <antoine@xpra.org> - 11.525.84-1
- new upstream release

* Fri Jun 10 2022 Antoine Martin <antoine@xpra.org> - 11.515.48-1
- new upstream release

* Mon Feb 07 2022 Antoine Martin <antoine@xpra.org> - 11.515.0-1
- new upstream release

* Thu Nov 04 2021 Antoine Martin <antoine@xpra.org> - 11.495.46-1
- new upstream release

* Sat Sep 04 2021 Antoine Martin <antoine@xpra.org> - 11.470.66-1
- new upstream release

* Sat Jul 24 2021 Antoine Martin <antoine@xpra.org> - 11.460.79-1
- new upstream release

* Wed Feb 17 2021 Antoine Martin <antoine@xpra.org> - 11.450.51-2
- verify source checksum

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
