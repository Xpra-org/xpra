%{!?__python2: %define __python2 python2}
%{!?python2_sitelib: %global python2_sitelib %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib())")}
%define _disable_source_fetch 0
%global debug_package %{nil}

Name:           python2-pbr
Version:        5.8.0
Release:        1.xpra1%{?dist}
Summary:        PBR is a library that injects some useful and sensible default behaviors into your setuptools run
License:        Apache Software License
URL:            https://docs.openstack.org/pbr/latest/
Source0:        https://files.pythonhosted.org/packages/f5/0c/3fa7b1f9006e4d454a49b48eac995167cf8617e19375c6963a6b048af0d0/pbr-%{version}.tar.gz
BuildRequires:  python2
BuildRequires:  python2-devel
BuildRequires:  python2-setuptools

%description
PBR is a library that injects some useful and sensible default behaviors into your setuptools run. It started off life as the chunks of code that were copied between all of the OpenStack projects. Around the time that OpenStack hit 18 different projects each with at least 3 active branches, it seemed like a good time to make that code into a proper reusable library.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "672d8ebee84921862110f23fcec2acea191ef58543d34dfe9ef3d9f13c31cddf" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi 
%setup -qn pbr-%{version}

%build
CFLAGS="%{optflags}" %{__python2} setup.py build

%install
%{__python2} setup.py install -O1 --skip-build --root %{buildroot}
mv %{buildroot}/usr/bin/pbr %{buildroot}/usr/bin/python2-pbr

%files
%{python2_sitelib}/pbr*
%{_bindir}/python2-pbr

%changelog
* Mon Jan 03 2022 Antoine Martin <antoine@xpra.org> - 5.8.0-1
- new upstream release

* Tue May 25 2021 Antoine Martin <antoine@xpra.org> - 5.6.0-1.xpra1
- verify source checksum

* Wed Feb 17 2021 Antoine Martin <antoine@xpra.org> - 5.5.1-1.xpra2
- verify source checksum

* Sun Jan 03 2021 Antoine Martin <antoine@xpra.org> - 5.5.1-1.xpra1
- initial package
