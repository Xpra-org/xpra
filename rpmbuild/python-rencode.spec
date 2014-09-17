# Remove private provides from .so files in the python_sitearch directory
%global __provides_exclude_from ^%{python_sitearch}/.*\\.so$

#this spec file is for both Fedora and CentOS
#only Fedora has Python3 at present:
%if 0%{?fedora} == 0
%define with_python3 1
%endif

Name:           python-rencode
Version:        1.0.3
Release:        1%{?dist}
Summary:        Web safe object pickling/unpickling
License:        GPLv3+ and BSD
URL:            http://code.google.com/p/rencode/
Source0:        rencode-%{version}.tar.xz

BuildRequires:  python2-devel
BuildRequires:  Cython
%if 0%{?with_python3} == 0
BuildRequires:  python3-devel
BuildRequires:  python3-Cython
%endif

%description
The rencode module is a modified version of bencode from the
BitTorrent project.  For complex, heterogeneous data structures with
many small elements, r-encodings take up significantly less space than
b-encodings.

%if 0%{?with_python3} == 0
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

%if 0%{?with_python3} == 0
rm -rf %{py3dir}
cp -a . %{py3dir}
find %{py3dir} -name '*.py' | xargs sed -i '1s|^#!python|#!%{__python3}|'
%endif

find -name '*.py' | xargs sed -i '1s|^#!python|#!%{__python}|'

%build
CFLAGS="%{optflags}" %{__python} setup.py build

%if 0%{?with_python3} == 0
pushd %{py3dir}
CFLAGS="%{optflags}" %{__python3} setup.py build
popd
%endif

%install
%if 0%{?with_python3} == 0
pushd %{py3dir}
%{__python3} setup.py install --skip-build --root %{buildroot}
popd
%endif

%{__python} setup.py install -O1 --skip-build --root %{buildroot}

#fix permissions on shared objects
chmod 0755 %{buildroot}%{python_sitearch}/rencode/_rencode.so
%if 0%{?with_python3} == 0
chmod 0755 %{buildroot}%{python3_sitearch}/rencode/_rencode.cpython-*.so
%endif

%check
pushd tests
ln -sf %{buildroot}%{python_sitearch}/rencode rencode
%{__python} test_rencode.py
%{__python} timetest.py
popd

%if 0%{?with_python3} == 0
pushd %{py3dir}/tests
ln -sf %{buildroot}%{python3_sitearch}/rencode rencode
%{__python3} test_rencode.py
%{__python3} timetest.py
popd
%endif

%files
%{python_sitearch}/rencode
%{python_sitearch}/rencode*.egg-info
%doc COPYING README

%if 0%{?with_python3} == 0
%files -n python3-rencode
%{python3_sitearch}/rencode
%{python3_sitearch}/rencode*.egg-info
%doc COPYING README
%endif

%changelog
* Wed Sep 17 2014 Antoine Martin <antoine@devloop.org.uk> 1.0.3-1
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
