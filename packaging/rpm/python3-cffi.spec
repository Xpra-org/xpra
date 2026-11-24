%define _disable_source_fetch 0
%define __python_requires %{nil}
%define __pythondist_requires %{nil}
%global debug_package %{nil}

%if "%{getenv:PYTHON3}" == ""
%global python3 python3
%global py3rpmname python3
%else
%global python3 %{getenv:PYTHON3}
%global py3rpmname %(echo %{python3} | sed 's/t$/-freethreading/')
%endif
%define python3_sitearch %(%{python3} -Ic "from sysconfig import get_path; print(get_path('platlib').replace('/usr/local/', '/usr/'))" 2> /dev/null)

Name:           %{py3rpmname}-cffi
Version:        2.1.1
Release:        1%{?dist}
Summary:        Foreign Function Interface for Python calling C code
Group:          Development/Languages
License:        MIT
URL:            https://github.com/python-cffi/cffi
Source0:        https://files.pythonhosted.org/packages/source/c/cffi/cffi-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)
BuildRequires:  %{py3rpmname}-devel
BuildRequires:  %{py3rpmname}-pip
BuildRequires:  %{py3rpmname}-setuptools >= 77.0.3
BuildRequires:  gcc
BuildRequires:  pkgconfig
BuildRequires:  libffi-devel
Requires:       %{py3rpmname} >= 3.10
# pycparser is only used for parsing C declarations (`ffi.cdef`),
# modules compiled with cffi (ie: cryptography) only need `_cffi_backend`:
Recommends:     %{py3rpmname}-pycparser

%description
Foreign Function Interface for Python calling C code.

This build is for the alternative python interpreters,
which are needed by python3-cryptography.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "dd31f52ea1086513bb9df30f8fcee9b8918323ae067a3d5b78bc826a000712be" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n cffi-%{version}


%build
%{python3} -m pip wheel \
    --verbose \
    --no-deps \
    --no-build-isolation \
    --wheel-dir=dist \
    .


%install
rm -rf $RPM_BUILD_ROOT
%{python3} -m pip install \
    --root %{buildroot} \
    --prefix %{_prefix} \
    --no-deps \
    --no-build-isolation \
    --no-warn-script-location \
    --ignore-installed \
    dist/cffi-*.whl
rm -f %{buildroot}%{python3_sitearch}/cffi-%{version}.dist-info/{RECORD,INSTALLER,REQUESTED,direct_url.json}
# the same script name would clash between interpreters, and nothing here needs it:
rm -f %{buildroot}%{_bindir}/cffi-gen-src


%clean
rm -rf $RPM_BUILD_ROOT


%files
%defattr(-,root,root,-)
%doc README.md
%license LICENSE
%{python3_sitearch}/cffi
%{python3_sitearch}/_cffi_backend*.so
%{python3_sitearch}/cffi-%{version}.dist-info


%changelog
* Tue Nov 24 2026 Antoine Martin <antoine@xpra.org> - 2.1.1-1
- initial packaging for the alternative python interpreters, required by python3-cryptography
