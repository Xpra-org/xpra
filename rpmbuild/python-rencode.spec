# Remove private provides from .so files in the python_sitearch directory
%global __provides_exclude_from ^%{python_sitearch}/.*\\.so$
%{!?__python2: %define __python2 python2}
%{!?__python3: %define __python3 python3}
%{!?python2_sitearch: %global python2_sitearch %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))")}
%{!?python3_sitearch: %global python3_sitearch %(%{__python3} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))")}

#this spec file is for Fedora, openSUSE and CentOS
#CentOS does not have Python3 support:
%if 0%{?fedora}%{?suse_version}
%define with_python3 1
%endif

Name:           python2-rencode
Version:        1.0.5
Release:        5.xpra1%{?dist}
Summary:        Web safe object pickling/unpickling
License:        GPLv3+ and BSD
URL:            https://github.com/aresch/rencode
Source0:        https://github.com/aresch/rencode/archive/v%{version}.tar.gz
Provides:		python-rencode
Obsoletes:		python-rencode
Conflicts:		python-rencode
Patch0:         python-rencode-py36-importwarning.patch


%if 0%{?suse_version}
%{!?py3dir: %global py3dir %{_builddir}/python3-%{name}-%{version}-%{release}}
BuildRequires:  python-devel
BuildRequires:  python-Cython
%else
BuildRequires:  python2-devel
BuildRequires:  Cython
%endif
%if 0%{?with_python3}
BuildRequires:  python3-devel
BuildRequires:  python3-Cython
%endif

%description
The rencode module is a modified version of bencode from the
BitTorrent project.  For complex, heterogeneous data structures with
many small elements, r-encodings take up significantly less space than
b-encodings.

%if 0%{?with_python3}
%package -n python3-rencode
Summary:    Web safe object pickling/unpickling

%description -n python3-rencode
The rencode module is a modified version of bencode from the
BitTorrent project.  For complex, heterogeneous data structures with
many small elements, r-encodings take up significantly less space than
b-encodings.
%endif

%prep
%setup -qn rencode-%{version}

%if 0%{?with_python3}
rm -rf %{py3dir}
cp -a . %{py3dir}
pushd %{py3dir}
%patch0 -p1
popd
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
%{__python3} setup.py install --skip-build --root %{buildroot}
popd
%endif

%{__python2} setup.py install -O1 --skip-build --root %{buildroot}

#fix permissions on shared objects
chmod 0755 %{buildroot}%{python2_sitearch}/rencode/_rencode.so
%if 0%{?with_python3}
chmod 0755 %{buildroot}%{python3_sitearch}/rencode/_rencode.cpython-*.so
%endif

%check
pushd tests
ln -sf %{buildroot}%{python2_sitearch}/rencode rencode
%{__python2} test_rencode.py
%{__python2} timetest.py
popd

%if 0%{?with_python3}
pushd %{py3dir}/tests
ln -sf %{buildroot}%{python3_sitearch}/rencode rencode
%{__python3} test_rencode.py
%{__python3} timetest.py
popd
%endif

%files
%{python2_sitearch}/rencode
%{python2_sitearch}/rencode*.egg-info
%doc COPYING README.md

%if 0%{?with_python3}
%files -n python3-rencode
%{python3_sitearch}/rencode
%{python3_sitearch}/rencode*.egg-info
%doc COPYING README.md
%endif

%changelog
* Sun Jul 30 2017 Antoine Martin <antoine@devloop.org.uk> - 1.0.5-5.xpra1
- we're ahead of Fedora with the patch, make sure the release number is too

* Fri Jul 28 2017 Antoine Martin <antoine@devloop.org.uk> - 1.0.5-3
- avoid import warnings with python 3.6

* Sat Dec 24 2016 Antoine Martin <antoine@devloop.org.uk> - 1.0.5-2
- try harder to supersede the old package name

* Sat Jul 16 2016 Antoine Martin <antoine@devloop.org.uk> - 1.0.5-1
- new upstream release

* Sat Mar 12 2016 Antoine Martin <antoine@devloop.org.uk> - 1.0.4-1
- new upstream release

* Wed Sep 17 2014 Antoine Martin <antoine@devloop.org.uk> - 1.0.3-1
- Preparing for xpra unbundling, support builds without python3 (ie: CentOS)

* Sun Aug 17 2014 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 1.0.2-6.20121209svn33
- Rebuilt for https://fedoraproject.org/wiki/Fedora_21_22_Mass_Rebuild

* Sat Jun 07 2014 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 1.0.2-5.20121209svn33
- Rebuilt for https://fedoraproject.org/wiki/Fedora_21_Mass_Rebuild

* Wed May 28 2014 Kalev Lember <kalevlember@gmail.com> - 1.0.2-4.20121209svn33
- Rebuilt for https://fedoraproject.org/wiki/Changes/Python_3.4

* Sun Aug 04 2013 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 1.0.2-3.20121209svn33
- Rebuilt for https://fedoraproject.org/wiki/Fedora_20_Mass_Rebuild

* Mon May 06 2013 T.C. Hollingsworth <tchollingsworth@gmail.com> - 1.0.2-2.20121209svn33
- use macros consistently
- fix permissions on shared objects
- drop useless setuptools copypasta
- fix License tag

* Thu Apr 18 2013 T.C. Hollingsworth <tchollingsworth@gmail.com> - 1.0.2-1.20121209svn33
- initial package
