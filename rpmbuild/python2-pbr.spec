# Remove private provides from .so files in the python_sitearch directory
%global __provides_exclude_from ^%{python2_sitearch}/.*\\.so$
%{!?__python2: %define __python2 python2}
%{!?python2_sitelib: %global python2_sitelib %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib())")}

Name:           python2-pbr
Version:        5.5.1
Release:        1.xpra1%{?dist}
Summary:        PBR is a library that injects some useful and sensible default behaviors into your setuptools run
License:        Apache Software License
URL:            https://docs.openstack.org/pbr/latest/
Source0:        https://files.pythonhosted.org/packages/65/e2/8cb5e718a3a63e8c22677fde5e3d8d18d12a551a1bbd4557217e38a97ad0/pbr-%{version}.tar.gz
%if 0%{?el7}
Provides:	python-pbr = %{version}-%{release}
Obsoletes:	python-pbr < %{version}-%{release}
Conflicts:	python-pbr < %{version}-%{release}
%endif

BuildRequires:  python2-devel
BuildRequires:  python2-setuptools

%description
PBR is a library that injects some useful and sensible default behaviors into your setuptools run. It started off life as the chunks of code that were copied between all of the OpenStack projects. Around the time that OpenStack hit 18 different projects each with at least 3 active branches, it seemed like a good time to make that code into a proper reusable library.

%global debug_package %{nil}

%prep
%setup -qn pbr-%{version}

%build
CFLAGS="%{optflags}" %{__python2} setup.py build

%install
%{__python2} setup.py install -O1 --skip-build --root %{buildroot}
mv %{buildroot}/usr/bin/pbr %{buildroot}/usr/bin/python2-pbr

%files
%{python2_sitelib}/pbr*
%{_bindir}/python2-pbr

%changelog
* Sun Jan 03 2021 Antoine Martin <antoine@xpra.org> - 5.5.1-1.xpra1
- initial package
