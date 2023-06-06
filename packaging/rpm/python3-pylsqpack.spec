%define _disable_source_fetch 0

Name:           python3-pylsqpack
Version:        0.3.17
Release:        1%{?dist}
Summary:        pylsqpack is a wrapper around the ls-qpack library
Group:          Development/Languages
License:        MIT
URL:            https://github.com/aiortc/pylsqpack
Source0:        https://files.pythonhosted.org/packages/40/15/e38751187d1db74efce30d45e72ae0035e506101585e28eee525bc465f7e/pylsqpack-%{version}.tar.gz
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
if [ "${sha256}" != "2f20778db956dc7e4b1a8a79722d57a4650c45997fb65c1352cbf85eb7aa3ce2" ]; then
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
* Tue Jun 06 2023 Antoine Martin <antoine@xpra.org> - 0.3.17-1
- new upstream release

* Mon Oct 24 2022 Antoine Martin <antoine@xpra.org> - 0.3.16-1
- initial packaging
