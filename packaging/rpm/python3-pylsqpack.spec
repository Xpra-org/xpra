%define _disable_source_fetch 0
%define __python_requires %{nil}
%define __pythondist_requires %{nil}
Autoreq: 0

Name:           python3-pylsqpack
Version:        0.3.23
Release:        1%{?dist}
Summary:        pylsqpack is a wrapper around the ls-qpack library
Group:          Development/Languages
License:        MIT
URL:            https://github.com/aiortc/pylsqpack
Source0:        https://files.pythonhosted.org/packages/93/1d/3f400f2e7413caec3cd58a9718bcab97d6e66ffb037af79cb45f06ac8813/pylsqpack-%{version}.tar.gz
Patch0:         pylsqpack-licensenonsense.patch
BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)
BuildRequires:  python3-devel
BuildRequires:  python3-setuptools
BuildRequires:  python3-wheel
BuildRequires:  gcc
Requires:       python3

%description
It provides Python Decoder and Encoder objects
to read or write HTTP/3 headers compressed with QPACK.


%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "f55b126940d8b3157331f123d4428d703a698a6db65a6a7891f7ec1b90c86c56" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n pylsqpack-%{version}
%patch -P 0 -p1


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
