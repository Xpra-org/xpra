%define _disable_source_fetch 0
%global debug_package %{nil}

Name:           python3-pbr
Version:        5.11.0
Release:        1%{?dist}
Summary:        PBR is a library that injects some useful and sensible default behaviors into your setuptools run
License:        Apache Software License
URL:            https://docs.openstack.org/pbr/latest/
Source0:        https://files.pythonhosted.org/packages/52/fb/630d52aaca8fc7634a0711b6ae12a0e828b6f9264bd8051225025c3ed075/pbr-%{version}.tar.gz
BuildRequires:  python3-devel
BuildRequires:  python3-setuptools

%description
PBR is a library that injects some useful and sensible default behaviors into your setuptools run. It started off life as the chunks of code that were copied between all of the OpenStack projects. Around the time that OpenStack hit 18 different projects each with at least 3 active branches, it seemed like a good time to make that code into a proper reusable library.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "b97bc6695b2aff02144133c2e7399d5885223d42b7912ffaec2ca3898e673bfe" ]; then
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
* Wed Dec 21 2022 Antoine Martin <antoine@xpra.org> - 5.11.0-1
- new upstream release

* Mon Jan 03 2022 Antoine Martin <antoine@xpra.org> - 5.9.0-1
- new upstream release

* Wed May 26 2021 Antoine Martin <antoine@xpra.org> - 5.6.0-1
- initial packaging for xpra python3 builds
