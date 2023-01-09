%define _disable_source_fetch 0

Name:           python3-uinput
Version:        0.11.2
Release:        6%{?dist}
Summary:        Pythonic API to the Linux uinput kernel module
License:        GPLv3
URL:            http://pypi.python.org/pypi/python-uinput/
Source0:        https://pypi.python.org/packages/54/b7/be7d0e8bbbbd440fef31242974d92d4edd21eb95ed96078b18cf207c7ccb/python-uinput-0.11.2.tar.gz

BuildRequires:  gcc
BuildRequires:  python3-devel
BuildRequires:  kernel-headers
BuildRequires:  libudev-devel


%filter_provides_in %{python3_sitearch}/.*\.so$
%filter_setup


%description
Python3-uinput is Python interface to the Linux uinput kernel module
which allows attaching userspace device drivers into kernel.


%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "99392b676c77b5795b86b7d75274db33fe754fd1e06fb3d58b167c797dc47f0c" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n python-uinput-%{version}

# Use unversioned .so
sed -i "s/libudev.so.0/libudev.so/" setup.py

find . -name '*.py' | xargs sed -i '1s|^#!python|#!%{__python3}|'


%build
CFLAGS="$RPM_OPT_FLAGS" %{__python3} setup.py build


%install
%{__python3} setup.py install --skip-build --root %{buildroot}
chmod a-x examples/*


%files
%doc COPYING NEWS README examples
%{python3_sitearch}/python_uinput-%{version}-py?.*.egg-info
%{python3_sitearch}/_libsuinput.*.so
%{python3_sitearch}/uinput


%changelog
* Wed Feb 17 2021 Antoine Martin <antoine@xpra.org> - 0.11.2-6
- verify source checksum

* Thu Sep 26 2019 Antoine Martin <antoine@xpra.org> - 0.11.2-5
- drop support for python2

* Tue Jul 03 2018 Antoine Martin <antoine@xpra.org> - 0.11.2-3
- use python2 explicitly

* Mon Jan 22 2018 Antoine Martin <antoine@xpra.org> - 0.11.2-2
- more explicit python version, sitearch paths

* Fri Aug 11 2017 Miro Hrončok <mhroncok@redhat.com> - 0.11.2-1
- new upstream release

* Mon Dec 19 2016 Miro Hrončok <mhroncok@redhat.com> - 0.10.1-10
- Rebuild for Python 3.6

* Tue Jul 19 2016 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0.10.1-9
- https://fedoraproject.org/wiki/Changes/Automatic_Provides_for_Python_RPM_Packages

* Thu Feb 04 2016 Fedora Release Engineering <releng@fedoraproject.org> - 0.10.1-8
- Rebuilt for https://fedoraproject.org/wiki/Fedora_24_Mass_Rebuild

* Tue Nov 10 2015 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0.10.1-7
- Rebuilt for https://fedoraproject.org/wiki/Changes/python3.5

* Thu Jun 18 2015 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0.10.1-6
- Rebuilt for https://fedoraproject.org/wiki/Fedora_23_Mass_Rebuild

* Sun Aug 17 2014 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0.10.1-5
- Rebuilt for https://fedoraproject.org/wiki/Fedora_21_22_Mass_Rebuild

* Sat Jun 07 2014 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0.10.1-4
- Rebuilt for https://fedoraproject.org/wiki/Fedora_21_Mass_Rebuild

* Wed May 28 2014 Kalev Lember <kalevlember@gmail.com> - 0.10.1-3
- Rebuilt for https://fedoraproject.org/wiki/Changes/Python_3.4

* Fri Mar 28 2014 Fabian Deutsch <fabiand@fedoraproject.org> - 0.10.1-2
- Don't  build py3 on el6

* Fri Feb 28 2014 Fabian Deutsch <fabiand@fedoraproject.org> - 0.10.1-1
- Update to latest upstram

* Sun Aug 04 2013 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0.9-4
- Rebuilt for https://fedoraproject.org/wiki/Fedora_20_Mass_Rebuild

* Thu Feb 14 2013 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0.9-3
- Rebuilt for https://fedoraproject.org/wiki/Fedora_19_Mass_Rebuild

* Tue Nov 20 2012 Fabian Deutsch <fabiand@fedoraproject.org> - 0.9-2
- Add documentation and examples

* Mon Nov 19 2012 Fabian Deutsch <fabian.deutsch@gmx.de> - 0.9-1
- Initial package.
