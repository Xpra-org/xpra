%define _disable_source_fetch 0
%if "%{getenv:PYTHON3}" == ""
%global python3 python3
%else
%global python3 %{getenv:PYTHON3}
%undefine __pythondist_requires
%undefine __python_requires
%define python3_sitelib %(%{python3} -Ic "from sysconfig import get_path; print(get_path('purelib').replace('/usr/local/', '/usr/'))")
%define python3_sitearch %(%{python3} -Ic "from sysconfig import get_path; print(get_path('platlib').replace('/usr/local/', '/usr/'))")
%endif

Name:           %{python3}-pytools
Version:        2024.1.11
Release:        1%{?dist}
Summary:        A collection of tools for python
Group:          Development/Languages
License:        MIT
URL:            http://pypi.python.org/pypi/pytools
Source0:        https://files.pythonhosted.org/packages/source/p/pytools/pytools-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)
Provides:		%{python3}-pytools = %{version}-%{release}
BuildArch:      noarch
Requires:       %{python3}
BuildRequires:  %{python3}-devel
BuildRequires:  %{python3}-setuptools
BuildRequires:  %{python3}-pip
BuildRequires:  pyproject-rpm-macros

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
if [ "${sha256}" != "fa966e09857bcd9299f961d58fc128e8333e4ac5fcea52473af5aae88f814e38" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n pytools-%{version}


%build
# %pyproject_wheel
%{python3} -m pip wheel . --no-deps


%install
rm -rf $RPM_BUILD_ROOT
%{python3} -m pip install . --no-deps --root $RPM_BUILD_ROOT


%clean
rm -rf $RPM_BUILD_ROOT


%files
%defattr(-,root,root,-)
%doc PKG-INFO
%{python3_sitelib}/*


%changelog
* Sun Jul 28 2024 Antoine Martin <antoine@xpra.org> - 2024.1.11-1
- new upstream release

* Thu Apr 25 2024 Antoine Martin <antoine@xpra.org> - 2024.1.2-1
- new upstream release

* Tue Oct 17 2023 Antoine Martin <antoine@xpra.org> - 2023.1.1-1
- new upstream release

* Wed Feb 22 2023 Antoine Martin <antoine@xpra.org> - 2022.1.14-1
- new upstream release

* Wed Dec 21 2022 Antoine Martin <antoine@xpra.org> - 2022.1.13-1
- new upstream release

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
