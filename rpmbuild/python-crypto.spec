%global pythonver %(%{__python} -c "import sys; print sys.version[:3]" 2>/dev/null || echo 0.0)
%{!?python_sitearch: %global python_sitearch %(%{__python} -c "from distutils.sysconfig import get_python_lib; print get_python_lib(1)" 2>/dev/null)}

# Python3 introduced in Fedora 13
%global with_python3 %([ 0%{?fedora} -gt 12 ] && echo 1 || echo 0)

Summary:	Cryptography library for Python
Name:		python-crypto
Version:	2.6.1
Release:	2%{?dist}
# Mostly Public Domain apart from parts of HMAC.py and setup.py, which are Python
License:	Public Domain and Python
Group:		Development/Libraries
URL:		http://www.pycrypto.org/
Source0:	http://ftp.dlitz.net/pub/dlitz/crypto/pycrypto/pycrypto-%{version}.tar.gz
Patch0:		python-crypto-2.4-optflags.patch
Patch1:		python-crypto-2.4-fix-pubkey-size-divisions.patch
Provides:	pycrypto = %{version}-%{release}
BuildRequires:	python2-devel >= 2.2, gmp-devel >= 4.1
%if %{with_python3}
BuildRequires:	python-tools
BuildRequires:	python3-devel
%endif
BuildRoot:	%{_tmppath}/%{name}-%{version}-buildroot-%(id -nu)

# Don't want provides for python shared objects
%{?filter_provides_in: %filter_provides_in %{python_sitearch}/Crypto/.*\.so}
%if %{with_python3}
%{?filter_provides_in: %filter_provides_in %{python3_sitearch}/Crypto/.*\.so}
%endif
%{?filter_setup}

%description
PyCrypto is a collection of both secure hash functions (such as MD5 and
SHA), and various encryption algorithms (AES, DES, RSA, ElGamal, etc.).

%if %{with_python3}
%package -n python3-crypto
Summary:	Cryptography library for Python 3
Group:		Development/Libraries

%description -n python3-crypto
PyCrypto is a collection of both secure hash functions (such as MD5 and
SHA), and various encryption algorithms (AES, DES, RSA, ElGamal, etc.).

This is the Python 3 build of the package.
%endif

%prep
%setup -n pycrypto-%{version} -q

# Use distribution compiler flags rather than upstream's
%patch0 -p1

# Fix divisions within benchmarking suite:
%patch1 -p1

# Prepare python3 build (setup.py doesn't run 2to3 on pct-speedtest.py)
%if %{with_python3}
cp -a . %{py3dir}
2to3 -wn %{py3dir}/pct-speedtest.py
%endif

%build
CFLAGS="%{optflags} -fno-strict-aliasing" %{__python} setup.py build

%if %{with_python3}
cd %{py3dir}
CFLAGS="%{optflags} -fno-strict-aliasing" %{__python3} setup.py build
cd -
%endif

%install
rm -rf %{buildroot}
%{__python} setup.py install -O1 --skip-build --root %{buildroot}

# Remove group write permissions on shared objects
find %{buildroot}%{python_sitearch} -name '*.so' -exec chmod -c g-w {} \;

# Build for python3 too
%if %{with_python3}
cd %{py3dir}
%{__python3} setup.py install -O1 --skip-build --root %{buildroot}
cd -
find %{buildroot}%{python3_sitearch} -name '*.so' -exec chmod -c g-w {} \;
%endif

# See if there's any egg-info
if [ -f %{buildroot}%{python_sitearch}/pycrypto-%{version}-py%{pythonver}.egg-info ]; then
	echo %{python_sitearch}/pycrypto-%{version}-py%{pythonver}.egg-info
fi > egg-info

%check
%{__python} setup.py test

# Benchmark uses os.urandom(), which is available from python 2.4
%if %(%{__python} -c "import sys; print sys.hexversion >= 0x02040000 and 1 or 0" 2>/dev/null || echo 0)
PYTHONPATH=%{buildroot}%{python_sitearch} %{__python} pct-speedtest.py
%endif

# Test the python3 build too
%if %{with_python3}
cd %{py3dir}
%{__python3} setup.py test
PYTHONPATH=%{buildroot}%{python3_sitearch} %{__python3} pct-speedtest.py
cd -
%endif

%clean
rm -rf %{buildroot}

%files -f egg-info
%defattr(-,root,root,-)
%doc README TODO ACKS ChangeLog LEGAL/ COPYRIGHT Doc/
%{python_sitearch}/Crypto/

%if %{with_python3}
%files -n python3-crypto
%defattr(-,root,root,-)
%doc README TODO ACKS ChangeLog LEGAL/ COPYRIGHT Doc/
%{python3_sitearch}/Crypto/
%{python3_sitearch}/pycrypto-*py3.*.egg-info
%endif

%changelog
* Fri Aug 08 2014 Antoine Martin <antoine@devloop.org.uk> 2.6.1-2
- Initial packaging for xpra
