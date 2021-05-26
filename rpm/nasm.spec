Summary:	A portable x86 assembler which uses Intel-like syntax
Name:		nasm
Version:	2.14.02
Release:	1%{?dist}
License:	BSD
URL:		http://www.nasm.us
Source:		http://www.nasm.us/pub/nasm/releasebuilds/%{version}/%{name}-%{version}.tar.bz2

BuildRequires: perl(Env)
BuildRequires: autoconf
BuildRequires: gcc
BuildRequires: make


%description
NASM is the Netwide Assembler, a free portable assembler for the Intel
80x86 microprocessor series, using primarily the traditional Intel
instruction mnemonics and syntax.

%prep
%setup -q

%build
autoreconf
%configure
make all

%install
make DESTDIR=$RPM_BUILD_ROOT install

%files
%doc AUTHORS CHANGES README TODO
%{_bindir}/nasm
%{_bindir}/ndisasm
%{_mandir}/man1/nasm*
%{_mandir}/man1/ndisasm*

%changelog
* Thu Jan 10 2019 Antoine Martin <antoine@xpra.org> - 2.14.02
- packaging for xpra
