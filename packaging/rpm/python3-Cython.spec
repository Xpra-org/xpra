%define _disable_source_fetch 0

Name:		python3-Cython
Version:	3.0.0b3
Release:	1%{?dist}
Summary:	A language for writing Python extension modules
Group:		Development/Tools
License:	Python
URL:		http://www.cython.org
Source0:    https://github.com/cython/cython/archive/refs/tags/%{version}.tar.gz
BuildRoot:	%{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)
Requires:   python3

BuildRequires:	python3-devel
BuildRequires:	python3-setuptools
BuildRequires:	gcc

%description
This is a development version of Pyrex, a language
for writing Python extension modules.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "06fb018a0c380cf247d8be2ec4ae1f06978ea905bbecafd9efd67744b7b7a97e" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n cython-%{version}

%build
CFLAGS="$RPM_OPT_FLAGS" %{__python3} setup.py build

%install
rm -rf %{buildroot}
%{__python3} setup.py install -O1 --skip-build --root %{buildroot}
rm -rf %{buildroot}%{python3_sitelib}/setuptools/tests

%clean
rm -rf %{buildroot}

#these tests take way too long:
#%check
#%{__python3} runtests.py -x numpy

%files
%defattr(-,root,root,-)
%{python3_sitearch}/*
%{_bindir}/cygdb
%{_bindir}/cython
%{_bindir}/cythonize
%doc *.txt Demos Tools

%changelog
* Thu May 25 2023 Antoine Martin <antoine@xpra.org> 3.0.0b3-1
- new upstream release
- Python 3.12 patch is no longer needed

* Mon Sep 19 2022 Antoine Martin <antoine@xpra.org> 3.0.0b2-2
- add Python 3.12 patch

* Mon Sep 19 2022 Antoine Martin <antoine@xpra.org> 3.0.0a11-1
- switch to 3.0 branch to support python 3.11

* Wed May 18 2022 Antoine Martin <antoine@xpra.org> 0.29.30-1
- new upstream release

* Fri Jan 28 2022 Antoine Martin <antoine@xpra.org> 0.29.27-1
- new upstream release

* Mon Dec 06 2021 Antoine Martin <antoine@xpra.org> 0.29.25-1
- new upstream release

* Thu Nov 04 2021 Antoine Martin <antoine@xpra.org> 0.29.24-1
- CentOS Stream 9 (temporary?) replacement package
