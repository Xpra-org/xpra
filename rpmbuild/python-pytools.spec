%{!?python_sitelib: %define python_sitelib %(%{__python} -c "from distutils.sysconfig import get_python_lib; print get_python_lib()")}

Name:           python-pytools
Version:        2014.3.5
Release:        1%{?dist}
Summary:        A collection of tools for python

Group:          Development/Languages
License:        MIT
URL:            http://pypi.python.org/pypi/pytools
Source0:        http://pypi.python.org/packages/source/p/pytools/pytools-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)

BuildArch:      noarch
BuildRequires:  python-devel python-setuptools

%description
A collection of tools for Python

Pytools is a big bag of things that are "missing" from the Python standard library.
This is mainly a dependency of my other software packages, and is probably of little interest to you unless you use those.
If you're curious nonetheless, here's what's on offer:
* A ton of small tool functions such as len_iterable, argmin, tuple generation, permutation generation, ASCII table pretty printing, GvR's mokeypatch_xxx() hack, the elusive flatten, and much more.
* Michele Simionato's decorator module
* A time-series logging module, pytools.log.
* Batch job submission, pytools.batchjob.
* A lexer, pytools.lex.


%prep
%setup -q -n pytools-%{version}


%build
%{__python} setup.py build


%install
rm -rf $RPM_BUILD_ROOT
%{__python} setup.py install -O1 --skip-build --root $RPM_BUILD_ROOT


%clean
rm -rf $RPM_BUILD_ROOT


%files
%defattr(-,root,root,-)
%doc README PKG-INFO
%{python_sitelib}/*


%changelog
* Wed Jun 17 2015 Antoine Martin <antoine@devloop.org.uk - 2014.3.5
- new upstream release

* Thu Sep 04 2014 Antoine Martin <antoine@devloop.org.uk - 2014.3
- Initial packaging for xpra
