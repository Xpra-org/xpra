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
Version:        0.7.0
Release:        0%{?dist}
Url:            https://github.com/steeve/python-lz4
Summary:        LZ4 Bindings for Python
License:        GPLv2+
Group:          Development/Languages/Python
Source:         https://pypi.python.org/packages/source/l/lz4/lz4-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-build
BuildRequires:  python-devel
Patch0:         lz4-skip-nose-vs-sphinx-mess.patch

%description
This package provides bindings for the lz4 compression library
http://code.google.com/p/lz4/ by Yann Collet.

#FIXME: this is fugly
%if %(egrep -q 'Fedora release 2|CentOS Linux release 7|RedHat Linux release 7' /etc/redhat-release && echo 0 || echo 1)
%debug_package
%endif

%prep
%setup -q -n lz4-%{version}
#only needed on centos (a fairly brutal solution):
%if 0%{?fedora:1}
#should work... until things get out of sync again
%else
%patch0 -p1
%endif

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
* Mon Jul 07 2014 Antoine Martin <antoine@devloop.org.uk - 0.7.0-0
- New upstream release

* Fri Mar 21 2014 Antoine Martin <antoine@devloop.org.uk - 0.6.1-0
- New upstream release

* Wed Jan 15 2014 Antoine Martin <antoine@devloop.org.uk - 0.6.0-1.0
- Fix version in specfile
- build debuginfo packages

* Sun Dec 8 2013 Stephen Gauthier <sgauthier@spikes.com> - 0.6.0-0
- First version for Fedora Extras
