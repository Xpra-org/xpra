# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#we don't want to depend on libcuda via RPM dependencies
#so that we can install NVidia drivers without using RPM packages:
%define __requires_exclude ^libcuda.*$

%define _disable_source_fetch 0
%if "%{getenv:PYTHON3}" == ""
%global python3 python3
%else
%global python3 %{getenv:PYTHON3}
%undefine __pythondist_requires
%undefine __python_requires
%endif
%define python3_sitearch %(%{python3} -Ic "from sysconfig import get_path; print(get_path('platlib').replace('/usr/local/', '/usr/'))" 2> /dev/null)

%global debug_package %{nil}
%global __requires_exclude ^(libnvjpeg|libnvidia-|libcudart).*\\.so.*$

Name:           %{python3}-torch-vision
Version:        0.29.2
Release:        1
URL:            https://github.com/pytorch/vision
Summary:        The torchvision package consists of popular datasets, model architectures, and common image transformations for computer vision
License:        BSD-3
Group:          Development/Libraries/Python
Source0:        https://github.com/pytorch/vision/archive/refs/tags/v%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-build

BuildRequires:  %{python3}-devel
BuildRequires:  %{python3}-setuptools
BuildRequires:  %{python3}-wheel
BuildRequires:  gcc
BuildRequires:  gcc-c++
BuildRequires:  pkgconfig(libwebp)
BuildRequires:  pkgconfig(libpng)
BuildRequires:  pkgconfig(libturbojpeg)
BuildRequires:  %{python3}-setuptools
BuildRequires:  %{python3}-torch >= 2.14.0
Requires:       %{python3}
Requires:       %{python3}-torch >= 2.14.0
Requires:       libwebp
Requires:       libpng
Requires:       turbojpeg

%description
The torchvision package consists of popular datasets, model architectures, and common image transformations for computer vision

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "6239575329eb0149ff7a7f5cabfab254129f758961afdba650aab37276d8196d" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n vision-%{version}

%build
%{python3} ./setup.py build

%install
%{python3} -W ignore ./setup.py install --prefix=%{_prefix} --root=%{buildroot}

%clean
rm -rf %{buildroot}

%files
%defattr(-,root,root)
%{python3_sitearch}/torchvision
%{python3_sitearch}/torchvision-*%{version}-*egg-info

%changelog
* Mon Nov 23 2026 Antoine Martin <antoine@xpra.org> - 0.29.2-1
- new upstream release

* Wed Oct 21 2026 Antoine Martin <antoine@xpra.org> - 0.29.1-2
- the package dependencies were part of the description

* Thu Oct 15 2026 Antoine Martin <antoine@xpra.org> - 0.29.1-1
- new upstream release

* Tue Jun 23 2026 Antoine Martin <antoine@xpra.org> - 0.27.1-1
- new upstream release

* Wed Apr 01 2026 Antoine Martin <antoine@xpra.org> - 0.26.0-1
- new upstream release

* Sat Feb 07 2026 Antoine Martin <antoine@xpra.org> - 0.25.0-1
- initial packaging
