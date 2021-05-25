# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

%define version 3.0
%define build_no 1

Name: 			xpra-html5
Version: 		%{version}
Release: 		%{build_no}%{?dist}
License: 		GPL
Summary:		Xpra HTML5 client
Group:			Networking
BuildArch:		noarch
URL:			http://xpra.org/
Packager:		Antoine Martin <antoine@xpra.org>
Vendor:			http://xpra.org/
Source:			%{name}-%{version}.tar.bz2
BuildRoot:		%{_tmppath}/%{name}-%{version}-root

Conflicts:		xpra < 2.1
%if 0%{?fedora}
BuildRequires:	uglify-js
BuildRequires:	js-jquery
Requires:		js-jquery
%endif
%description
This package contains Xpra's HTML5 client.

%prep
%setup -q -n %{name}-%{version}

%build

%install
rm -rf $RPM_BUILD_ROOT
python setup_html5.py %{buildroot}/usr/share/xpra/www

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root)
%{_datadir}/xpra/www
%doc html5/LICENSE

%changelog
* Mon Sep 30 2019 Antoine Martin <antoine@xpra.org> 3.0-1
- version bump

* Thu Feb 21 2019 Antoine Martin <antoine@xpra.org> 2.5-0
- add license

* Thu Jul 27 2017 Antoine Martin <antoine@xpra.org> 2.2-3
- split html5 client from main RPM package
