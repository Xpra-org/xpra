%define _disable_source_fetch 0
%if 0%{?fedora} >= 42
# F42 builds tried to bring in some weird dependencies on paths like /usr/sbin/python3
AutoReqProv: no
autoreq: no
autoprov: no
%endif
%if "%{getenv:PYTHON3}" == ""
%global python3 python3
%define bin_prefix %{nil}
%else
%global python3 %{getenv:PYTHON3}
%define bin_prefix %{python3}-
%undefine __pythondist_requires
%undefine __python_requires
%define python3_sitelib %(%{python3} -Ic "from sysconfig import get_path; print(get_path('purelib').replace('/usr/local/', '/usr/'))" 2> /dev/null)
%define python3_sitearch %(%{python3} -Ic "from sysconfig import get_path; print(get_path('platlib').replace('/usr/local/', '/usr/'))" 2> /dev/null)
%endif

Name:		%{python3}-cython
Version:	3.0.12
Release:	1%{?dist}
Summary:	A language for writing Python extension modules
Group:		Development/Tools
License:	Python
URL:		http://www.cython.org
Source0:    https://github.com/cython/cython/archive/refs/tags/%{version}.tar.gz
BuildRoot:	%{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)
Requires:   %{python3}
Provides:   %{python3}-Cython = %{version}-%{release}
Obsoletes:  %{python3}-Cython < %{version}-%{release}
Conflicts:  %{python3}-Cython < %{version}-%{release}

BuildRequires:	coreutils
BuildRequires:	%{python3}-devel
BuildRequires:	%{python3}-setuptools
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
NPROCS=${NPROCS:-`nproc`}
CFLAGS="$RPM_OPT_FLAGS" %{python3} setup.py build -j ${NPROCS}

%install
rm -rf %{buildroot}
%{python3} setup.py install -O1 --skip-build --root %{buildroot}
rm -fr %{buildroot}%{python3_sitearch}/UNKNOWN-*.egg-info
%if "%{bin_prefix}" != ""
mv %{buildroot}%{_bindir}/cygdb %{buildroot}%{_bindir}/%{bin_prefix}cygdb
mv %{buildroot}%{_bindir}/cython %{buildroot}%{_bindir}/%{bin_prefix}cython
mv %{buildroot}%{_bindir}/cythonize %{buildroot}%{_bindir}/%{bin_prefix}cythonize
%endif

%clean
rm -rf %{buildroot}

#these tests take way too long:
#%check
#%{python3} runtests.py -x numpy

%files
%defattr(-,root,root,-)
%{python3_sitearch}/*
%{_bindir}/%{bin_prefix}cygdb
%{_bindir}/%{bin_prefix}cython
%{_bindir}/%{bin_prefix}cythonize
%doc *.txt Demos Tools

%changelog
* Tue Feb 11 2025 Antoine Martin <antoine@xpra.org> 3.0.12-1
- new upstream release

* Mon Aug 05 2024 Antoine Martin <antoine@xpra.org> 3.0.11-1
- new upstream release

* Thu Jun 27 2024 Antoine Martin <antoine@xpra.org> 3.0.10-2
- conflict with old package name to upgrade it

* Sun Mar 31 2024 Antoine Martin <antoine@xpra.org> 3.0.10-1
- new upstream release

* Wed Jan 10 2024 Antoine Martin <antoine@xpra.org> 3.0.8-1
- new upstream release

* Tue Dec 19 2023 Antoine Martin <antoine@xpra.org> 3.0.7-1
- new upstream release

* Sun Nov 26 2023 Antoine Martin <antoine@xpra.org> 3.0.6-1
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
