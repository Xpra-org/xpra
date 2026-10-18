%define _disable_source_fetch 0
%define __python_requires %{nil}
%define __pythondist_requires %{nil}
Autoreq: 0

Name:           python3-pytools
%if 0%{?el8}
# Last release supporting Python 3.6.
Version:        2022.1.12
%else
%if 0%{?el9}
# Last release supporting EL9's Python 3.9.
Version:        2024.1.14
%else
Version:        2026.1.1
%endif
%endif
Release:        1%{?dist}
Summary:        A collection of tools for python
Group:          Development/Languages
License:        MIT
URL:            http://pypi.python.org/pypi/pytools
Source0:        https://files.pythonhosted.org/packages/source/p/pytools/pytools-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)
Provides:		python3-pytools = %{version}-%{release}
BuildArch:      noarch
Requires:       python3-platformdirs >= 2.2
%if 0%{?el8}%{?el9}
Requires:       python3
Requires:       python3-typing-extensions >= 4
%else
Requires:       python3 >= 3.10
Requires:       python3-typing-extensions >= 4.5
Requires:       python3-siphash24 >= 1.6
%endif
%if 0%{?el8}
Requires:       python3-dataclasses >= 0.7
%endif
%if 0%{?el8}%{?el9}
BuildRequires:  python3-devel
BuildRequires:  python3-setuptools
%else
BuildRequires:  python3-devel >= 3.10
BuildRequires:  python3-hatchling
BuildRequires:  python3-pip
BuildRequires:  pyproject-rpm-macros
%endif

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
%if 0%{?el8}
if [ "${sha256}" != "4d62875e9a2ab2a24e393a9a8b799492f1a721bffa840af3807bfd42871dd1f4" ]; then
%else
%if 0%{?el9}
if [ "${sha256}" != "39e5bbaf81fa432e688b82dd0980212d18f97b23e51a8c7afe7592249fe40ab1" ]; then
%else
if [ "${sha256}" != "260e0d88c9a903c65cfe34fbe818764f44a3f96e722e1a3645ce4d596add22b1" ]; then
%endif
%endif
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n pytools-%{version}
%if 0%{?el9}
# EL9's setuptools cannot read the newer source's pyproject metadata.
cat > setup.py << 'EOF'
from setuptools import find_packages, setup

setup(name="pytools",
      version="%{version}",
      description="A collection of tools for Python",
      license="MIT",
      packages=find_packages(include=["pytools", "pytools.*"]),
      package_data={"pytools": ["py.typed"]},
      python_requires=">=3.8",
      install_requires=["platformdirs>=2.2",
                        "typing-extensions>=4; python_version<'3.13'"])
EOF
%endif


%build
%if 0%{?el8}%{?el9}
%{__python3} setup.py build
%else
%pyproject_wheel
%endif


%install
rm -rf $RPM_BUILD_ROOT
%if 0%{?el8}%{?el9}
%{__python3} setup.py install -O1 --skip-build --root $RPM_BUILD_ROOT
# RHEL stream setuptools bug?
rm -fr %{buildroot}%{python3_sitearch}/UNKNOWN-*.egg-info
%else
%pyproject_install
%endif


%clean
rm -rf $RPM_BUILD_ROOT


%files
%defattr(-,root,root,-)
%doc PKG-INFO
%{python3_sitelib}/*


%changelog
* Sun Oct 18 2026 Antoine Martin <antoine@xpra.org> - 2026.1.1-1
- use the current upstream release outside EL8 and EL9
- build the newer source with Hatchling and declare its runtime dependencies
- keep the existing EL8 and EL9 versions and legacy build paths

* Sun Oct 18 2026 Antoine Martin <antoine@xpra.org> - 2024.1.14-1
- use the last release supporting EL9's Python 3.9
- retain 2022.1.12 on EL8 for Python 3.6 compatibility
- support EL9's setuptools and declare the runtime dependencies
- use the stable PyPI source URL and verify both source checksums

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
