%define _disable_source_fetch 0

Name:           python3-aioquic
Version:        0.9.20
Release:        1%{?dist}
Summary:        aioquic is a library for the QUIC network protocol in Python
Group:          Development/Languages
License:        MIT
URL:            https://github.com/aiortc/aioquic
Source0:        https://files.pythonhosted.org/packages/91/93/53f91b13c15b45386e0faa84c89f0e09a3eceb3903c856519b6681faf88c/aioquic-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)
BuildRequires:  python3-devel
BuildRequires:  python3-setuptools
BuildRequires:  openssl-devel
BuildRequires:  gcc
Requires:       python3
Requires:       python3-cryptography
Requires:       python3-certifi
Requires:       python3-pyOpenSSL
Requires:       python3-pylsqpack

%description
It features a minimal TLS 1.3 implementation, a QUIC stack and an HTTP/3 stack.

QUIC was standardised in RFC 9000 and HTTP/3 in RFC 9114.
aioquic is regularly tested for interoperability against other QUIC implementations.

It provides Python Decoder and Encoder objects
to read or write HTTP/3 headers compressed with QPACK.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "ec436aaace997b846b01e5200edbf7e3e56b91826a144efb9748fd8ddd332bbe" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n aioquic-%{version}


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
%{python3_sitearch}/aioquic*


%changelog
* Mon Oct 24 2022 Antoine Martin <antoine@xpra.org> - 0.9.20-1
- initial packaging
