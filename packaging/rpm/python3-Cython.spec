%define _disable_source_fetch 0
%if 0%{?fedora} >= 42
# F42 builds tried to bring in some weird dependencies on paths like /usr/sbin/python3
AutoReqProv: no
autoreq: no
autoprov: no
%endif
%define __python_requires %{nil}
%define __pythondist_requires %{nil}
Autoreq: 0

Name:		python3-Cython
Version:	3.0.12
Release:	1%{?dist}
Summary:	A language for writing Python extension modules
Group:		Development/Tools
License:	Python
URL:		http://www.cython.org
Source0:    https://github.com/cython/cython/archive/refs/tags/%{version}.tar.gz
BuildRoot:	%{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)
Requires:       python3

BuildRequires:	python3-devel
BuildRequires:	python3-setuptools
BuildRequires:	gcc

%description
This is a development version of Pyrex, a language
for writing Python extension modules.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "a156fff948c2013f2c8c398612c018e2b52314fdf0228af8fbdb5585e13699c2" ]; then
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
# RHEL stream setuptools bug?
rm -fr %{buildroot}%{python3_sitearch}/UNKNOWN-*.egg-info

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
* Tue Feb 11 2025 Antoine Martin <antoine@xpra.org> 3.0.12-1
- new upstream release

* Mon Aug 05 2024 Antoine Martin <antoine@xpra.org> 3.0.11-1
- new upstream release

* Wed Mar 06 2024 Antoine Martin <antoine@xpra.org> 3.0.9-1
- new upstream release

* Wed Jan 10 2024 Antoine Martin <antoine@xpra.org> 3.0.8-1
- new upstream release

* Tue Dec 19 2023 Antoine Martin <antoine@xpra.org> 3.0.7-1
- new upstream release

* Tue Oct 31 2023 Antoine Martin <antoine@xpra.org> 3.0.5-1
- new upstream release

* Wed Oct 18 2023 Antoine Martin <antoine@xpra.org> 3.0.4-1
- new upstream release

* Thu Oct 05 2023 Antoine Martin <antoine@xpra.org> 3.0.3-1
- new upstream release

* Mon Jul 17 2023 Antoine Martin <antoine@xpra.org> 3.0.0-1
- new upstream release

* Thu Jul 13 2023 Antoine Martin <antoine@xpra.org> 3.0.0rc2-1
- new upstream release

* Wed Jul 12 2023 Antoine Martin <antoine@xpra.org> 3.0.0rc1-1
- new upstream release

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
