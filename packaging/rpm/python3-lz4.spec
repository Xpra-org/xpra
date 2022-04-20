%define _disable_source_fetch 0
%global srcname lz4
%{?python_provide:%python_provide python3-%{srcname}}

Name:           python3-%{srcname}
Version:        3.0.2
Release:        8%{?dist}
URL:            https://github.com/%{name}/%{name}
Summary:        LZ4 Bindings for Python
License:        BSD
Source:         https://files.pythonhosted.org/packages/source/l/%{srcname}/%{srcname}-%{version}.tar.gz

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
if [ "${sha256}" != "9c9f6a8b71c18c24bd83537a4d616f0301623a5e98db7c7ca956d608e1bcd4c7" ]; then
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
* Mon Mar 21 2022 Antoine Martin <antoine@xpra.org> - 3.0.2-8
- initial packaging for CentOS 8 based on the Fedora spec file
