%global modname websocket
%global distname websocket-client
%global eggname websocket_client

Name:		python-websocket-client
Version:	0.48.0
Release:	1%{?dist}
Summary:	WebSocket client for python
Group:		Development/Libraries
License:	LGPLv2
URL:		http://pypi.python.org/pypi/websocket-client
Source0:	http://pypi.python.org/packages/source/w/%{distname}/%{eggname}-%{version}.tar.gz
BuildArch:	noarch
BuildRequires: python2-devel
BuildRequires: python-setuptools
BuildRequires: python-six
Requires:	python-six

%description
python-websocket-client module is WebSocket client for python. This
provides the low level APIs for WebSocket. All APIs are the synchronous
functions.

python-websocket-client supports only hybi-13.

%prep
%setup -q -n %{eggname}-%{version}
# Remove bundled egg-info in case it exists
rm -rf %{distname}.egg-info

%build
%{__python2} setup.py build

%install
%{__python2} setup.py install -O1 --skip-build --root=%{buildroot}
mv %{buildroot}/%{_bindir}/wsdump.py \
    %{buildroot}/%{_bindir}/wsdump

# remove tests that got installed into the buildroot
rm -rf %{buildroot}/%{python2_sitelib}/tests/

# Remove executable bit from installed files.
find %{buildroot}/%{python2_sitelib} -type f -exec chmod -x {} \;

%check
#%%{__python2} setup.py test

%files
%doc README.rst LICENSE
%{python2_sitelib}/%{modname}/
%{python2_sitelib}/%{eggname}*%{version}*
%{_bindir}/wsdump

%changelog
* Mon Jul 02 2018 Antoine Martin <antoine@devloop.org.uk> - 0.48.0-1
- Initial packaging for xpra repo based on centos extras
