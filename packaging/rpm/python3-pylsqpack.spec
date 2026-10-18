%define _disable_source_fetch 0
%define __python_requires %{nil}
%define __pythondist_requires %{nil}
Autoreq: 0

Name:           python3-pylsqpack
%if 0%{?el8}
# Last release that builds with Python 3.6 and setuptools 39.2.
Version:        0.3.16
%else
Version:        0.3.23
%endif
Release:        3%{?dist}
Summary:        pylsqpack is a wrapper around the ls-qpack library
Group:          Development/Languages
License:        MIT
URL:            https://github.com/aiortc/pylsqpack
Source0:        https://files.pythonhosted.org/packages/source/p/pylsqpack/pylsqpack-%{version}.tar.gz
%if !0%{?el8}
Patch0:         pylsqpack-licensenonsense.patch
%endif
BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)
BuildRequires:  python3-devel
BuildRequires:  python3-setuptools
BuildRequires:  python3-wheel
BuildRequires:  gcc
Requires:       python3
# Versions from vendor/ls-qpack/lsqpack.h; bundled xxhash is unversioned.
%if 0%{?el8}
Provides:       bundled(ls-qpack) = 1.0.3
%else
Provides:       bundled(ls-qpack) = 2.6.2
%endif
Provides:       bundled(xxhash)

%description
It provides Python Decoder and Encoder objects
to read or write HTTP/3 headers compressed with QPACK.


%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
%if 0%{?el8}
if [ "${sha256}" != "b67a6ce3f6937d850681827714be730aa361c049e37752e3ed9df11e7f232ffb" ]; then
%else
if [ "${sha256}" != "f55b126940d8b3157331f123d4428d703a698a6db65a6a7891f7ec1b90c86c56" ]; then
%endif
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n pylsqpack-%{version}
%if !0%{?el8}
%patch -P 0 -p1
%endif


%build
%{__python3} setup.py build


%install
rm -rf $RPM_BUILD_ROOT
%{__python3} setup.py install -O1 --skip-build --root $RPM_BUILD_ROOT
# RHEL stream setuptools bug?
rm -fr %{buildroot}%{python3_sitearch}/UNKNOWN-*.egg-info


%clean
rm -rf $RPM_BUILD_ROOT


%files
%defattr(-,root,root,-)
%doc PKG-INFO
%{python3_sitearch}/pylsqpack*


%changelog
* Sun Oct 18 2026 Antoine Martin <antoine@xpra.org> - 0.3.23-3
- use 0.3.16 on EL8 for Python 3.6 and setuptools 39.2 compatibility
- use the matching source checksum and bundled ls-qpack version on EL8
- apply the pyproject license patch only to the newer source

* Sat Oct 17 2026 Antoine Martin <antoine@xpra.org> - 0.3.23-2
- declare the bundled ls-qpack and xxhash
- use the stable PyPI source URL

* Tue Oct 14 2025 Antoine Martin <antoine@xpra.org> - 0.3.23-1
- new upstream release

* Thu Jan 18 2024 Antoine Martin <antoine@xpra.org> - 0.3.18-2
- rebuild without auto-dependencies

* Sun Nov 12 2023 Antoine Martin <antoine@xpra.org> - 0.3.18-1
- new upstream release

* Tue Jun 06 2023 Antoine Martin <antoine@xpra.org> - 0.3.17-1
- new upstream release

* Mon Oct 24 2022 Antoine Martin <antoine@xpra.org> - 0.3.16-1
- initial packaging
