# Remove private provides from .so files in the python_sitearch directory
%global __provides_exclude_from ^%{python2_sitearch}/.*\\.so$
%{!?__python3: %define __python3 python3}
%{!?python3_sitearch: %global python3_sitearch %(%{__python3} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))")}
%define _disable_source_fetch 0

Name:           python3-rencode
Version:        1.0.6
Release:        11.xpra1%{?dist}
Summary:        Web safe object pickling/unpickling
License:        GPLv3+ and BSD
URL:            https://github.com/aresch/rencode
Source0:        https://github.com/aresch/rencode/archive/v%{version}.tar.gz
Patch0:         python-rencode-readdmissingpyx.patch
Patch1:         python-rencode-nowheelreq.patch
Patch2:         python-rencode-rename.patch
Patch3:         python-rencode-typecode-dos.patch
BuildRequires:  gcc
BuildRequires:  python3-devel
BuildRequires:  python3-Cython
BuildRequires:  python3-pbr

%description
The rencode module is a modified version of bencode from the
BitTorrent project.  For complex, heterogeneous data structures with
many small elements, r-encodings take up significantly less space than
b-encodings.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "0ed61111f053ea37511da86ca7aed2a3cfda6bdaa1f54a237c4b86eea52f0733" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -qn rencode-%{version}
%patch0 -p1
%patch1 -p1
%patch2 -p1
%patch3 -p1

%build
CFLAGS="%{optflags}" %{__python3} setup.py build

%install
%{__python3} setup.py install --skip-build --root %{buildroot}
#fix permissions on shared objects
chmod 0755 %{buildroot}%{python3_sitearch}/rencode/_rencode.cpython-*.so

%check
pushd tests
ln -sf %{buildroot}%{python3_sitearch}/rencode rencode
%{__python3} test_rencode.py
%{__python3} timetest.py
popd

%files
%{python3_sitearch}/rencode
%{python3_sitearch}/rencode*.egg-info
%doc COPYING README.md

%changelog
* Wed Sep 01 2021 Antoine Martin <antoine@xpra.org> - 1.0.6-11.xpra1
- bump release number to ensure EPEL version is not installed

* Thu Aug 05 2021 Antoine Martin <antoine@xpra.org> - 1.0.6-4.xpra1
- fix DoS decoding invalid typecode in lists or dictionaries

* Wed Feb 17 2021 Antoine Martin <antoine@xpra.org> - 1.0.6-3.xpra1
- verify source checksum

* Sun Jan 03 2021 Antoine Martin <antoine@xpra.org> - 1.0.6-2.xpra1
- don't conflict with the newer python3 Fedora / CentOS 8 builds

* Mon Oct 22 2018 Antoine Martin <antoine@xpra.org> - 1.0.6-1.xpra1
- new upstream release

* Tue Jul 03 2018 Antoine Martin <antoine@xpra.org> - 1.0.5-8.xpra1
- try harder to prevent rpm db conflicts

* Sat Aug 05 2017 Antoine Martin <antoine@xpra.org> - 1.0.5-7.xpra1
- bump so we override fedora's package which lacks the import fix

* Sat Aug 05 2017 Antoine Martin <antoine@xpra.org> - 1.0.5-5.xpra2
- add patch to fix python 2.6 compatibility in the tests

* Sun Jul 30 2017 Antoine Martin <antoine@xpra.org> - 1.0.5-5.xpra1
- we're ahead of Fedora with the patch, make sure the release number is too

* Fri Jul 28 2017 Antoine Martin <antoine@xpra.org> - 1.0.5-3
- avoid import warnings with python 3.6

* Sat Dec 24 2016 Antoine Martin <antoine@xpra.org> - 1.0.5-2
- try harder to supersede the old package name

* Sat Jul 16 2016 Antoine Martin <antoine@xpra.org> - 1.0.5-1
- new upstream release

* Sat Mar 12 2016 Antoine Martin <antoine@xpra.org> - 1.0.4-1
- new upstream release

* Wed Sep 17 2014 Antoine Martin <antoine@xpra.org> - 1.0.3-1
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
