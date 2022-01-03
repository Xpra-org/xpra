%define _disable_source_fetch 0

Name:           python3-pytools
Version:        2021.2.9
Release:        1%{?dist}
Summary:        A collection of tools for python
Group:          Development/Languages
License:        MIT
URL:            http://pypi.python.org/pypi/pytools
Source0:        https://files.pythonhosted.org/packages/46/4b/d0f2b0076f73fc792810cb217a19e24b09a417f261fdb12112859a551076/pytools-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)
Provides:		python3-pytools = %{version}-%{release}
BuildArch:      noarch
BuildRequires:  python3-devel python3-setuptools

%description
Pytools are a few interesting things that are missing from the Python Standard
Library.

Small tool functions such as ::
* len_iterable,
* argmin,
* tuple generation,
* permutation generation,
* ASCII table pretty printing,
* GvR's mokeypatch_xxx() hack,
* The elusive flatten, and much more.
* Michele Simionato's decorator module
* A time-series logging module, pytools.log.
* Batch job submission, pytools.batchjob.
* A lexer, pytools.lex.


%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "db6cf83c9ba0a165d545029e2301621486d1e9ef295684072e5cd75316a13755" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n pytools-%{version}


%build
%{__python3} setup.py build


%install
rm -rf $RPM_BUILD_ROOT
%{__python3} setup.py install -O1 --skip-build --root $RPM_BUILD_ROOT


%clean
rm -rf $RPM_BUILD_ROOT


%files
%defattr(-,root,root,-)
%doc PKG-INFO
%{python3_sitelib}/*


%changelog
* Mon Jan 03 2022 Antoine Martin <antoine@xpra.org> - 2021.2.9-1
- new upstream release

* Sun Oct 03 2021 Antoine Martin <antoine@xpra.org> - 2021.2.8-1
- new upstream release

* Sun Mar 28 2021 Antoine Martin <antoine@xpra.org> - 2021.2.6-1
- new upstream release

* Sun Mar 28 2021 Antoine Martin <antoine@xpra.org> - 2021.2.1-1
- new upstream release

* Wed Feb 17 2021 Antoine Martin <antoine@xpra.org> - 2020.4.4-2
- verify source checksum

* Thu Jan 07 2021 Antoine Martin <antoine@xpra.org> - 2020.4.4-1
- new upstream release

* Thu Sep 26 2019 Antoine Martin <antoine@xpra.org> - 2019.1.1-2
- drop support for python2

* Mon May 20 2019 Antoine Martin <antoine@xpra.org> - 2019.1.1-1
- new upstream release

* Tue Jul 03 2018 Antoine Martin <antoine@xpra.org> - 2018.5.2-1
- new upstream release
- try harder to prevent rpm db conflicts

* Sat Dec 24 2016 Antoine Martin <antoine@xpra.org> - 2016.2.1-3
- try harder to supersede the old package name

* Sun Jul 17 2016 Antoine Martin <antoine@xpra.org> - 2016.2.1-2
- rename and obsolete old python package name

* Thu May 26 2016 Antoine Martin <antoine@xpra.org> - 2016.2.1-1
- new upstream release

* Thu Jul 16 2015 Antoine Martin <antoine@xpra.org> - 2015.1.2-1
- new upstream release

* Wed Jun 17 2015 Antoine Martin <antoine@xpra.org> - 2014.3.5-1
- new upstream release

* Thu Sep 04 2014 Antoine Martin <antoine@xpra.org> - 2014.3-1
- Initial packaging for xpra
