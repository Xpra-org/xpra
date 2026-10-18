%define _disable_source_fetch 0
%define __python_requires %{nil}
%define __pythondist_requires %{nil}
Autoreq: 0
%global debug_package %{nil}

Name:           python3-typing-extensions
Version:        4.1.1
Release:        1%{?dist}
Summary:        Backported and experimental Python type hints
Group:          Development/Languages
License:        Python
URL:            https://github.com/python/typing_extensions
Source0:        https://files.pythonhosted.org/packages/source/t/typing_extensions/typing_extensions-%{version}.tar.gz
BuildArch:      noarch
BuildRequires:  python3-devel python3-setuptools
Requires:       python3

%description
Typing extensions backports newer Python typing features to older Python
versions. This version provides ParamSpec and Concatenate on EL8's Python 3.6.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "1a9462dcc3347a79b1f1c0271fbe79e844580bb598bafa1ed208b94da3cdcd42" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n typing_extensions-%{version}
# Build with EL8's setuptools 39.2 rather than the upstream flit backend.
cat > setup.py << 'EOF'
from setuptools import setup

setup(name="typing_extensions",
      version="%{version}",
      description="Backported and experimental Python type hints",
      license="Python",
      py_modules=["typing_extensions"],
      package_dir={"": "src"},
      python_requires=">=3.6")
EOF

%build
%{__python3} setup.py build

%install
rm -rf %{buildroot}
%{__python3} setup.py install -O1 --skip-build --root %{buildroot}

%clean
rm -rf %{buildroot}

%files
%license LICENSE
%doc PKG-INFO
%{python3_sitelib}/typing_extensions.py
%{python3_sitelib}/__pycache__/typing_extensions*.pyc
%{python3_sitelib}/typing_extensions-*.egg-info/

%changelog
* Sun Oct 18 2026 Antoine Martin <antoine@xpra.org> - 4.1.1-1
- package the Python 3.6 compatible dependency for EL8 pytools
- build with EL8's setuptools and verify the source checksum
