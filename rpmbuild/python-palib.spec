# Remove private provides from .so files in the python_sitearch directory
%global __provides_exclude_from ^%{python_sitearch}/.*\\.so$

%if 0%{?rhel} && 0%{?rhel} <= 6
%{!?__python2: %global __python2 /usr/bin/python2}
%{!?python2_sitelib: %global python2_sitelib %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib())")}
%endif

#this spec file is for both Fedora and CentOS
#only Fedora has Python3 at present:
%if 0%{?fedora}
%define with_python3 1
%endif

Name:           python-palib
Version:        1.0
Release:        1%{?dist}
Summary:        Python bindings for pulseaudio
License:        GPLv3+
URL:            https://code.google.com/p/pypactl/source/browse/trunk
Source0:        palib-%{version}.tar.xz
BuildArch:      noarch

%description
Python bindings for pulseaudio

%if 0%{?with_python3}
%package -n python3-palib
Summary:        Python3 bindings for pulseaudio

%description -n python3-palib
Python3 bindings for pulseaudio
%endif

%prep
%setup -qn palib-%{version}

%if 0%{?with_python3}
rm -rf %{py3dir}
cp -a . %{py3dir}
%endif

%build
CFLAGS="%{optflags}" %{__python2} setup.py build

%if 0%{?with_python3}
pushd %{py3dir}
CFLAGS="%{optflags}" %{__python3} setup.py build
popd
%endif

%install
%if 0%{?with_python3}
pushd %{py3dir}
%{__python3} setup.py install --root %{buildroot}
popd
%endif

%{__python2} setup.py install --root %{buildroot}

%files
%{python2_sitelib}/palib*

%if 0%{?with_python3}
%files -n python3-palib
%{python3_sitelib}/palib*
%endif

%changelog
* Thu May 28 2015 Antoine Martin <antoine@devloop.org.uk> 1.0-1
- Initial package
