%{!?python2_sitelib: %define python2_sitelib %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print get_python_lib()")}

Name:           python2-pytools
Version:        2018.5.2
Release:        1%{?dist}
Summary:        A collection of tools for python

Group:          Development/Languages
License:        MIT
URL:            http://pypi.python.org/pypi/pytools
Source0:        https://files.pythonhosted.org/packages/90/6a/7b706e4730db0ee5724c677cceafcac1bc9710c61612442a689e7b0aa5c4/pytools-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)
Provides:		python-pytools = %{version}-%{release}
Obsoletes:		python-pytools < %{version}-%{release}
Conflicts:		python-pytools < %{version}-%{release}

BuildArch:      noarch
BuildRequires:  python-devel python-setuptools

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
%doc README PKG-INFO
%{python2_sitelib}/*


%changelog
* Tue Jul 03 2018 Antoine Martin <antoine@devloop.org.uk> - 2018.5.2-1
- new upstream release
- try harder to prevent rpm db conflicts

* Sat Dec 24 2016 Antoine Martin <antoine@devloop.org.uk> - 2016.2.1-3
- try harder to supersede the old package name

* Sun Jul 17 2016 Antoine Martin <antoine@nagafix.co.uk> - 2016.2.1-2
- rename and obsolete old python package name

* Thu May 26 2016 Antoine Martin <antoine@devloop.org.uk> - 2016.2.1-1
- new upstream release

* Thu Jul 16 2015 Antoine Martin <antoine@devloop.org.uk> - 2015.1.2-1
- new upstream release

* Wed Jun 17 2015 Antoine Martin <antoine@devloop.org.uk> - 2014.3.5-1
- new upstream release

* Thu Sep 04 2014 Antoine Martin <antoine@devloop.org.uk> - 2014.3-1
- Initial packaging for xpra
