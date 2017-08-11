
%global with_python3 1

# No python3 on el6
%if 0%{?el6}%{?el7}
%global with_python3 0
%endif

Name:           python2-uinput
Version:        0.11.2
Release:        1%{?dist}
Summary:        Pythonic API to the Linux uinput kernel module

License:        GPLv3
URL:            http://pypi.python.org/pypi/python-uinput/
Source0:        https://pypi.python.org/packages/54/b7/be7d0e8bbbbd440fef31242974d92d4edd21eb95ed96078b18cf207c7ccb/python-uinput-0.11.2.tar.gz

Provides:		python-uinput
Obsoletes:      python-uinput < 0.11.2
Conflicts:		python-uinput < 0.11.2

BuildRequires:  python-devel
BuildRequires:  kernel-headers
BuildRequires:  libudev-devel

%if %{?with_python3}
BuildRequires:  python3-devel
%endif # if with_python3


%filter_provides_in %{python_sitearch}/.*\.so$
%filter_provides_in %{python3_sitearch}/.*\.so$
%filter_setup


%description
Python-uinput is Python interface to the Linux uinput kernel module
which allows attaching userspace device drivers into kernel.


%if 0%{?with_python3}
%package -n     python3-uinput
Summary:        Pythonic API to the Linux uinput kernel module


%description -n python3-uinput
Python-uinput is Python interface to the Linux uinput kernel module
which
allows attaching userspace device drivers into kernel.
%endif # with_python3


%prep
%setup -q -n python-uinput-%{version}

# Use unversioned .so
sed -i "s/libudev.so.0/libudev.so/" setup.py

%if 0%{?with_python3}
rm -rf %{py3dir}
cp -a . %{py3dir}
find %{py3dir} -name '*.py' | xargs sed -i '1s|^#!python|#!%{__python3}|'
%endif # with_python3


%build
CFLAGS="$RPM_OPT_FLAGS" %{__python} setup.py build

%if 0%{?with_python3}
pushd %{py3dir}
CFLAGS="$RPM_OPT_FLAGS" %{__python3} setup.py build
popd
%endif # with_python3


%install
# Must do the subpackages' install first because the scripts in /usr/bin are
# overwritten with every setup.py install (and we want the python2 version
# to be the default for now).
%if 0%{?with_python3}
pushd %{py3dir}
%{__python3} setup.py install --skip-build --root %{buildroot}
popd
%endif # with_python3

%{__python} setup.py install --skip-build --root %{buildroot}

chmod a-x examples/*


%files
%doc COPYING NEWS README examples
%{python_sitearch}/python_uinput-%{version}-py?.?.egg-info
%{python_sitearch}/_libsuinput.so
%{python_sitearch}/uinput
%if 0%{?with_python3}


%files -n python3-uinput
%doc COPYING NEWS README examples
%{python3_sitearch}/python_uinput-%{version}-py?.?.egg-info
%{python3_sitearch}/_libsuinput.*.so
%{python3_sitearch}/uinput
%endif # with_python3


%changelog
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
