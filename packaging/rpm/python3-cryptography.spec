%define _disable_source_fetch 0
%define __python_requires %{nil}
%define __pythondist_requires %{nil}
# the rust extension links a cffi module compiled by the cc crate,
# which does not cope with gcc LTO objects:
%define _lto_cflags %{nil}
%global debug_package %{nil}

%if "%{getenv:PYTHON3}" == ""
%global python3 python3
%global py3rpmname python3
%else
%global python3 %{getenv:PYTHON3}
%global py3rpmname %(echo %{python3} | sed 's/t$/-freethreading/')
%endif
%define python3_sitearch %(%{python3} -Ic "from sysconfig import get_path; print(get_path('platlib').replace('/usr/local/', '/usr/'))" 2> /dev/null)

Name:           %{py3rpmname}-cryptography
Version:        50.0.2
Release:        1%{?dist}
Summary:        cryptography provides cryptographic recipes and primitives to Python developers
Group:          Development/Languages
License:        Apache-2.0 OR BSD-3-Clause
URL:            https://github.com/pyca/cryptography
Source0:        https://files.pythonhosted.org/packages/source/c/cryptography/cryptography-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)
BuildRequires:  %{py3rpmname}-devel
BuildRequires:  %{py3rpmname}-pip
BuildRequires:  gcc
# rust >= 1.83 is needed: RHEL 8.10 and 9.6 onwards have it
BuildRequires:  rust >= 1.83
BuildRequires:  cargo
BuildRequires:  pkgconfig
BuildRequires:  libffi-devel
%if 0%{?el8}
# cryptography 47 dropped support for OpenSSL 1.1.x,
# use the OpenSSL 3 package from EPEL instead:
BuildRequires:  openssl3-devel
Requires:       openssl3-libs
%else
BuildRequires:  openssl-devel >= 3.0
%endif
Requires:       %{py3rpmname} >= 3.9
# the module compiled with cffi 2.x also loads with the older _cffi_backend
# shipped by RHEL 8 and 9 (1.16), even though the metadata asks for cffi >= 2.0:
Requires:       %{py3rpmname}-cffi

%description
cryptography is a package which provides cryptographic recipes and primitives
to Python developers. It includes both high level recipes and low level
interfaces to common cryptographic algorithms such as symmetric ciphers,
message digests, and key derivation functions.

This build is needed by aioquic >= 1.9, which requires cryptography >= 48,
and for the alternative python interpreters which have no python3-cryptography.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "7b46165bb56eb4704e2eaaf86f3c940d19154535d9b0ca7d6d590b04060e00d5" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n cryptography-%{version}


%build
%if 0%{?el8}
export OPENSSL_LIB_DIR=%{_libdir}/openssl3
export OPENSSL_INCLUDE_DIR=%{_includedir}/openssl3
%endif
# cryptography builds with maturin, which is not packaged for RHEL:
# build a wheel with build isolation so that the pinned build dependencies
# (maturin, cffi >= 2.0, setuptools) are fetched automatically.
%{python3} -m pip wheel \
    --verbose \
    --no-deps \
    --wheel-dir=dist \
    .


%install
rm -rf $RPM_BUILD_ROOT
# install the wheel built in %%build (no rebuild, just unpack into the buildroot)
%{python3} -m pip install \
    --root %{buildroot} \
    --prefix %{_prefix} \
    --no-deps \
    --no-build-isolation \
    --no-warn-script-location \
    --ignore-installed \
    dist/cryptography-*.whl
rm -f %{buildroot}%{python3_sitearch}/cryptography-%{version}.dist-info/{RECORD,INSTALLER,REQUESTED,direct_url.json}


%clean
rm -rf $RPM_BUILD_ROOT


%files
%defattr(-,root,root,-)
%doc README.rst CHANGELOG.rst
%license LICENSE LICENSE.APACHE LICENSE.BSD
%{python3_sitearch}/cryptography
%{python3_sitearch}/cryptography-%{version}.dist-info


%changelog
* Tue Nov 24 2026 Antoine Martin <antoine@xpra.org> - 50.0.2-1
- initial packaging for RHEL 8 onwards, required by aioquic >= 1.9
