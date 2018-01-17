Name:           python-websockify
Version:        0.8.0
Release:        1%{?dist}
Summary:        WSGI based adapter for the Websockets protocol

License:        LGPLv3
URL:            https://github.com/kanaka/websockify
Source0:        https://github.com/kanaka/websockify/archive/v%{version}.tar.gz#/websockify-%{version}.tar.gz
BuildArch:      noarch
BuildRequires:  python-devel
BuildRequires:  python-setuptools
Requires:       python-setuptools

%description
Python WSGI based adapter for the Websockets protocol

%prep
%setup -q -n websockify-%{version}

# TODO: Have the following handle multi line entries
sed -i '/setup_requires/d; /install_requires/d; /dependency_links/d' setup.py

%build
%{__python} setup.py build


%install
%{__python} setup.py install -O1 --skip-build --root %{buildroot}

rm -Rf %{buildroot}/usr/share/websockify
mkdir -p %{buildroot}%{_mandir}/man1/
install -m 444 docs/websockify.1 %{buildroot}%{_mandir}/man1/


%files
%doc LICENSE.txt docs
%{_mandir}/man1/websockify.1*
%{python_sitelib}/websockify/*
%{python_sitelib}/websockify-%{version}-py?.?.egg-info
%{_bindir}/websockify


%changelog
* Wed Jan 17 2018 Antoine Martin <antoine@devloop.org.uk> - 0.8.0-1
- initial CentOS packaging
