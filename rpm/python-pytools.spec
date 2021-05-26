%{!?__python2: %define __python2 python2}
%{!?python2_sitelib: %define python2_sitelib %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print get_python_lib()")}
%define _disable_source_fetch 0

Name:           python2-pytools
Version:        2019.1.1
Release:        3%{?dist}
Summary:        A collection of tools for python

Group:          Development/Languages
License:        MIT
URL:            http://pypi.python.org/pypi/pytools
Source0:        https://files.pythonhosted.org/packages/00/96/00416762a3eda8876a17d007df4a946f46b2e4ee1057e0b9714926472ef8/pytools-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)
%if 0%{?el7}
Provides:		python-pytools = %{version}-%{release}
Obsoletes:		python-pytools < %{version}-%{release}
Conflicts:		python-pytools < %{version}-%{release}
%endif

BuildArch:      noarch
BuildRequires:  python2-devel
BuildRequires:  python2-setuptools

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
if [ "${sha256}" != "ce2d702ae4ef10a70197b00b93141461140d00578f2a862fa946ca1446a300db" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n pytools-%{version}


%build
%{__python2} setup.py build


%install
rm -rf $RPM_BUILD_ROOT
%{__python2} setup.py install -O1 --skip-build --root $RPM_BUILD_ROOT


%clean
rm -rf $RPM_BUILD_ROOT


%files
%defattr(-,root,root,-)
%doc PKG-INFO
%{python2_sitelib}/*


%changelog
* Tue May 25 2021 Antoine Martin <antoine@xpra.org> - 2019.1.1-3
- verify source checksum

* Mon Oct 28 2019 Antoine Martin <antoine@xpra.org> - 2019.1.1-2
- Fedora 31 rebuild

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
