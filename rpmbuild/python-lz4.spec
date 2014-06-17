#
# spec file for package python-lz4
#
# Copyright (c) 2013-2014
#
%if 0%{?rhel} && 0%{?rhel} <= 6
%{!?__python2: %global __python2 /usr/bin/python2}
%{!?python2_sitearch: %global python2_sitearch %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))")}
%endif

Name:           python-lz4
Version:        0.6.1
Release:        1%{?dist}
Url:            https://github.com/steeve/python-lz4
Summary:        LZ4 Bindings for Python
License:        GPLv2+
Group:          Development/Languages/Python
Source:         https://pypi.python.org/packages/source/l/lz4/lz4-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-build

BuildRequires:  python-devel
%if 0%{?el6}
BuildRequires:  python-nose1.1
%else
BuildRequires:  python-nose
%endif

%description
This package provides bindings for the lz4 compression library
http://code.google.com/p/lz4/ by Yann Collet.

%prep
%setup -q -n lz4-%{version}

%build
export CFLAGS="%{optflags}"
python setup.py build

%install
python setup.py install --prefix=%{_prefix} --root=%{buildroot}

%clean
rm -rf %{buildroot}

%files
%defattr(-,root,root,-)
%doc README.rst
%{python2_sitearch}/*

%changelog
* Fri Mar 21 2014 Antoine Martin <antoine@devloop.org.uk - 0.6.1-0
- New upstream release

* Wed Jan 15 2014 Antoine Martin <antoine@devloop.org.uk - 0.6.0-1.0
- Fix version in specfile
- build debuginfo packages

* Sun Dec 8 2013 Stephen Gauthier <sgauthier@spikes.com> - 0.6.0-0
- First version for Fedora Extras

