%define _disable_source_fetch 0

Name:		python3-Cython
Version:	0.29.28
Release:	1%{?dist}
Summary:	A language for writing Python extension modules
Group:		Development/Tools
License:	Python
URL:		http://www.cython.org
Source0:    https://files.pythonhosted.org/packages/cb/da/54a5d7a7d9afc90036d21f4b58229058270cc14b4c81a86d9b2c77fd072e/Cython-%{version}.tar.gz
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
if [ "${sha256}" != "d6fac2342802c30e51426828fe084ff4deb1b3387367cf98976bb2e64b6f8e45" ]; then
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
* Fri Jan 28 2022 Antoine Martin <antoine@xpra.org> 0.29.27-1
- new upstream release

* Mon Dec 06 2021 Antoine Martin <antoine@xpra.org> 0.29.25-1
- new upstream release

* Thu Nov 04 2021 Antoine Martin <antoine@xpra.org> 0.29.24-1
- CentOS Stream 9 (temporary?) replacement package
