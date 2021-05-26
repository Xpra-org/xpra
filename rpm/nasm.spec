%define _disable_source_fetch 0

Summary: A portable x86 assembler which uses Intel-like syntax
Name:    nasm
Version: 2.15.03
Release: 1%{?dist}
License: BSD
URL:     http://www.nasm.us
Source0: https://www.nasm.us/pub/nasm/releasebuilds/%{version}/%{name}-%{version}.tar.xz
Patch0:  nasm-SourceSans-font-name.patch

BuildRequires: perl(Env)
BuildRequires: autoconf
BuildRequires: automake
BuildRequires: gcc
BuildRequires: make

%package rdoff
Summary: Tools for the RDOFF binary format, sometimes used with NASM

%description
NASM is the Netwide Assembler, a free portable assembler for the Intel
80x86 microprocessor series, using primarily the traditional Intel
instruction mnemonics and syntax.

%description rdoff
Tools for the operating-system independent RDOFF binary format, which
is sometimes used with the Netwide Assembler (NASM). These tools
include linker, library manager, loader, and information dump.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "c0c39a305f08ccf0c5c6edba4294dd2851b3925b6d9642dd1efd62f72829822f" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%autosetup -p1

%build
%configure
make all %{?_smp_mflags}

%install
%make_install install_rdf

%files
%license LICENSE
%doc AUTHORS CHANGES README.md
%{_bindir}/nasm
%{_bindir}/ndisasm
%{_mandir}/man1/nasm*
%{_mandir}/man1/ndisasm*

%files rdoff
%{_bindir}/ldrdf
%{_bindir}/rdf2bin
%{_bindir}/rdf2ihx
%{_bindir}/rdf2com
%{_bindir}/rdfdump
%{_bindir}/rdflib
%{_bindir}/rdx
%{_bindir}/rdf2ith
%{_bindir}/rdf2srec
%{_mandir}/man1/rd*
%{_mandir}/man1/ld*

%changelog
* Tue May 25 2021 Antoine Martin <antoine@xpra.org> - 2.15.03-1
- initial packaging for CentOS 7.x
