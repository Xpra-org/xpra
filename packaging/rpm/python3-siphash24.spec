%define _disable_source_fetch 0
%global csiphash_version 1.1.0
%global cstdaux_version 1.5.0

Name:           python3-siphash24
Version:        1.6
Release:        1%{?dist}
Summary:        Streaming SipHash-1-3 and SipHash-2-4 implementations for Python
License:        Apache-2.0 OR LGPL-2.1-or-later
URL:            https://github.com/dnicolodi/python-siphash24
Source0:        https://files.pythonhosted.org/packages/source/s/siphash24/siphash24-%{version}.tar.gz
# Versions pinned by the upstream Meson wrap files.
Source1:        https://github.com/c-util/c-siphash/archive/refs/tags/v%{csiphash_version}.tar.gz#/c-siphash-%{csiphash_version}.tar.gz
Source2:        https://github.com/c-util/c-stdaux/archive/refs/tags/v%{cstdaux_version}.tar.gz#/c-stdaux-%{cstdaux_version}.tar.gz
BuildRequires:  gcc
BuildRequires:  python3-devel
BuildRequires:  python3-pip
BuildRequires:  python3-meson-python >= 0.14
BuildRequires:  python3dist(cython) >= 3.0.2
BuildRequires:  meson >= 1.0
BuildRequires:  ninja-build
BuildRequires:  pyproject-rpm-macros
Requires:       python3
Provides:       bundled(libcsiphash) = %{csiphash_version}
Provides:       bundled(libcstdaux) = %{cstdaux_version}

%description
SipHash24 provides streaming-capable SipHash-1-3 and SipHash-2-4 functions
for Python. It supplies the hashing backend required by newer pytools releases.

%prep
echo '242d6901a81260f618938635a25ae7f208e744f7ee6c571f1b255c1c4c62917d  %{SOURCE0}' | sha256sum -c -
echo 'a70c71effbcd553858250d109dd39599b9e3d5a91d46f0beb731bf6799893e63  %{SOURCE1}' | sha256sum -c -
echo '19fb163160c25babf1f2ecf817e6eb696decfb5e33490dcd9cf68c2ecae97d13  %{SOURCE2}' | sha256sum -c -
%setup -q -n siphash24-%{version} -a 1 -a 2
mv c-siphash-%{csiphash_version} subprojects/libcsiphash-1
mv c-stdaux-%{cstdaux_version} subprojects/libcstdaux-1

%build
# All subprojects are supplied above; keep the build offline.
%pyproject_wheel -Csetup-args=--wrap-mode=nodownload

%install
%pyproject_install

%check
PYTHONPATH=%{buildroot}%{python3_sitearch} %{__python3} test.py

%files
%license LICENSES/*.txt
%doc README.rst
%{python3_sitearch}/siphash24.*.so
%{python3_sitearch}/siphash24-*.dist-info/

%changelog
* Sun Oct 18 2026 Antoine Martin <antoine@xpra.org> - 1.6-1
- package the SipHash backend required by pytools 2026.1.1
- verify all source archives and build the pinned C subprojects offline
- run the upstream reference-vector tests
