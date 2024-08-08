%define _disable_source_fetch 0

Summary: A portable x86 assembler which uses Intel-like syntax
Name:    nasm
Version: 2.16.03
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
if [ "${sha256}" != "1412a1c760bbd05db026b6c0d1657affd6631cd0a63cddb6f73cc6d4aa616148" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%autosetup

%build
%configure
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
* Thu Apr 25 2024 Antoine Martin <antoine@xpra.org> - 2.16.03-1
- new upstream release

* Wed Feb 22 2023 Antoine Martin <antoine@xpra.org> - 2.16.01-1
- new upstream release
- rdoff package removed

* Thu Nov 04 2021 Antoine Martin <antoine@xpra.org> - 2.15.05-1
- new upstream release

* Tue May 25 2021 Antoine Martin <antoine@xpra.org> - 2.15.03-1
- initial packaging for CentOS 7.x
