%define _disable_source_fetch 0
%define __python_requires %{nil}
%define __pythondist_requires %{nil}
Autoreq: 0

Name:           python3-aioquic
Version:        1.3.0
Release:        1%{?dist}
Summary:        aioquic is a library for the QUIC network protocol in Python
Group:          Development/Languages
License:        MIT
URL:            https://github.com/aiortc/aioquic
Source0:        https://files.pythonhosted.org/packages/source/a/aioquic/aioquic-%{version}.tar.gz
Patch0:         aioquic-pycrypto-tls-utc.patch
Patch1:         aioquic-licensenonsense.patch
BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)
BuildRequires:  python3-devel
BuildRequires:  python3-setuptools
BuildRequires:  python3-wheel
BuildRequires:  openssl-devel
BuildRequires:  gcc
Requires:       python3
Requires:       python3-cryptography
Requires:       python3-certifi
Requires:       python3-pyOpenSSL
Requires:       python3-pylsqpack
Recommends:     python3-uvloop

%description
It features a minimal TLS 1.3 implementation, a QUIC stack and an HTTP/3 stack.

QUIC was standardised in RFC 9000 and HTTP/3 in RFC 9114.
aioquic is regularly tested for interoperability against other QUIC implementations.

It provides Python Decoder and Encoder objects
to read or write HTTP/3 headers compressed with QPACK.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "28d070b2183e3e79afa9d4e7bd558960d0d53aeb98bc0cf0a358b279ba797c92" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n aioquic-%{version}
%patch -P 0 -p1
%patch -P 1 -p1


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
%{python3_sitearch}/aioquic*


%changelog
* Tue Oct 14 2025 Antoine Martin <antoine@xpra.org> - 1.3.0-1
- new upstream release

* Fri Jul 12 2024 Antoine Martin <antoine@xpra.org> - 1.2.0-1
- new upstream release

* Thu Mar 14 2024 Antoine Martin <antoine@xpra.org> - 1.0.0-1
- new upstream release

* Thu Jan 18 2024 Antoine Martin <antoine@xpra.org> - 0.9.25-2
- rebuild without auto-dependencies

* Wed Jan 10 2024 Antoine Martin <antoine@xpra.org> - 0.9.25-1
- new upstream release

* Fri Dec 29 2023 Antoine Martin <antoine@xpra.org> - 0.9.24-1
- new upstream release

* Sun Nov 12 2023 Antoine Martin <antoine@xpra.org> - 0.9.22-1
- new upstream release

* Wed Jul 12 2023 Antoine Martin <antoine@xpra.org> - 0.9.21-1
- initial packaging

* Mon Oct 24 2022 Antoine Martin <antoine@xpra.org> - 0.9.20-1
- initial packaging
