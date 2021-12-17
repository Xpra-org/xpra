%define _disable_source_fetch 0

Name:		python3-Cython
Version:	0.29.26
Release:	1%{?dist}
Summary:	A language for writing Python extension modules
Group:		Development/Tools
License:	Python
URL:		http://www.cython.org
Source0:    https://files.pythonhosted.org/packages/bc/fa/8604d92ef753e0036d807f1b3179813ab2fa283e3b19c926e11673c8205b/Cython-%{version}.tar.gz
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
if [ "${sha256}" != "af377d543a762867da11fcf6e558f7a4a535ff8693f30cce123fab10c00fa312" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n Cython-%{version}
find -name '*.py' | xargs sed -i '1s|^#!python|#!%{__python2}|'

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
* Mon Dec 06 2021 Antoine Martin <antoine@xpra.org> 0.29.25-1
- new upstream release
- switch to github for source snapshot

* Thu Nov 04 2021 Antoine Martin <antoine@xpra.org> 0.29.24-1
- CentOS Stream 9 (temporary?) replacement package
