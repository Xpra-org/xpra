%define _disable_source_fetch 0

Name:           python3-pylsqpack
Version:        0.3.16
Release:        1%{?dist}
Summary:        pylsqpack is a wrapper around the ls-qpack library
Group:          Development/Languages
License:        MIT
URL:            https://github.com/aiortc/pylsqpack
Source0:        https://files.pythonhosted.org/packages/54/cf/7eac98d6ffb5c6ad0e5fba84a6ca39993c93f9e0208055d35a788e4a0049/pylsqpack-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)
BuildRequires:  python3-devel
BuildRequires:  python3-setuptools
BuildRequires:  gcc
Requires:       python3

%description
It provides Python Decoder and Encoder objects
to read or write HTTP/3 headers compressed with QPACK.


%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "b67a6ce3f6937d850681827714be730aa361c049e37752e3ed9df11e7f232ffb" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n pylsqpack-%{version}


%build
%{__python3} setup.py build


%install
rm -rf $RPM_BUILD_ROOT
%{__python3} setup.py install -O1 --skip-build --root $RPM_BUILD_ROOT


%clean
rm -rf $RPM_BUILD_ROOT


%files
%defattr(-,root,root,-)
%doc PKG-INFO
%{python3_sitearch}/pylsqpack*


%changelog
* Mon Oct 24 2022 Antoine Martin <antoine@xpra.org> - 0.3.16-1
- initial packaging
