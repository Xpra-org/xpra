%define _disable_source_fetch 0
%global srcname lz4

Name:           python3-%{srcname}
Version:        4.0.2
Release:        1%{?dist}
URL:            https://github.com/%{name}/%{name}
Summary:        LZ4 Bindings for Python
License:        BSD
Source:         https://files.pythonhosted.org/packages/65/8d/4d913798e17735839c7666e81985bd230f739927d066890b511a78c542d8/%{srcname}-%{version}.tar.gz

%{?python_provide:%python_provide python3-%{srcname}}

BuildRequires:  lz4-devel
BuildRequires:  gcc

BuildRequires:  python3-devel
BuildRequires:  python3-setuptools
BuildRequires:  python3-setuptools_scm
BuildRequires:  python3-pkgconfig


%description
Python 3 bindings for the lz4 compression library.


%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "083b7172c2938412ae37c3a090250bfdd9e4a6e855442594f86c3608ed12729b" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%autosetup -n %{srcname}-%{version} -p1
# remove bundled lib so we build against the system lib:
rm lz4libs/lz4*.[ch]


%build
%py3_build


%install
%py3_install
# Fix permissions on shared objects
find %{buildroot}%{python3_sitearch} -name 'lz4*.so' \
    -exec chmod 0755 {} \;


%check
# just try importing:
PYTHONPATH=$RPM_BUILD_ROOT%{python3_sitearch} %{__python3} -c "import lz4"


%files -n python3-lz4
%license LICENSE
%doc README.rst
%{python3_sitearch}/lz4*


%changelog
* Sat Aug 06 2022 Antoine Martin <antoine@xpra.org> - 4.0.2-1
- new upstream release

* Mon Mar 21 2022 Antoine Martin <antoine@xpra.org> - 3.0.2-8
- initial packaging for CentOS 8 based on the Fedora spec file
