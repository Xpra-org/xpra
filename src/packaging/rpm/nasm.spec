%define _disable_source_fetch 0

Summary: A portable x86 assembler which uses Intel-like syntax
Name:    nasm
Version: 2.16
Release: 1%{?dist}
License: BSD
URL:     http://www.nasm.us
Source0: https://www.nasm.us/pub/nasm/releasebuilds/%{version}/%{name}-%{version}.tar.xz

BuildRequires: perl(Env)
BuildRequires: autoconf
BuildRequires: automake
BuildRequires: gcc
BuildRequires: make

%description
NASM is the Netwide Assembler, a free portable assembler for the Intel
80x86 microprocessor series, using primarily the traditional Intel
instruction mnemonics and syntax.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "f05e2dc04bdb075487207d775770e9e508e250e63da8bf6c769976d66dd55249" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%autosetup

%build
%configure --disable-pdf-compression
make all %{?_smp_mflags}

%install
%make_install

%files
%license LICENSE
%doc AUTHORS CHANGES README.md
%{_bindir}/nasm
%{_bindir}/ndisasm
%{_mandir}/man1/nasm*
%{_mandir}/man1/ndisasm*

%changelog
* Wed Dec 21 2022 Antoine Martin <antoine@xpra.org> - 2.16-1
- new upstream release

* Thu Nov 04 2021 Antoine Martin <antoine@xpra.org> - 2.15.05-1
- new upstream release

* Tue May 25 2021 Antoine Martin <antoine@xpra.org> - 2.15.03-1
- initial packaging for CentOS 7.x
