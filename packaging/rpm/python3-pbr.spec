%define _disable_source_fetch 0
%global debug_package %{nil}

Name:           python3-pbr
Version:        5.11.1
Release:        1%{?dist}
Summary:        PBR is a library that injects some useful and sensible default behaviors into your setuptools run
License:        Apache Software License
URL:            https://docs.openstack.org/pbr/latest/
Source0:        https://files.pythonhosted.org/packages/02/d8/acee75603f31e27c51134a858e0dea28d321770c5eedb9d1d673eb7d3817/pbr-%{version}.tar.gz
BuildRequires:  python3-devel
BuildRequires:  python3-setuptools

%description
PBR is a library that injects some useful and sensible default behaviors into your setuptools run. It started off life as the chunks of code that were copied between all of the OpenStack projects. Around the time that OpenStack hit 18 different projects each with at least 3 active branches, it seemed like a good time to make that code into a proper reusable library.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "aefc51675b0b533d56bb5fd1c8c6c0522fe31896679882e1c4c63d5e4a0fccb3" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -qn pbr-%{version}

%build
CFLAGS="%{optflags}" %{__python3} setup.py build

%install
%{__python3} setup.py install -O1 --skip-build --root %{buildroot}

%files
%{python3_sitelib}/pbr*
%{_bindir}/pbr

%changelog
* Fri Feb 03 2023 Antoine Martin <antoine@xpra.org> - 5.11.1-1
- new upstream release

* Wed Dec 21 2022 Antoine Martin <antoine@xpra.org> - 5.11.0-1
- new upstream release

* Mon Jan 03 2022 Antoine Martin <antoine@xpra.org> - 5.9.0-1
- new upstream release

* Wed May 26 2021 Antoine Martin <antoine@xpra.org> - 5.6.0-1
- initial packaging for xpra python3 builds
