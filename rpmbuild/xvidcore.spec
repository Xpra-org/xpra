#global pre -rc1

Name:           xvidcore
Version:        1.3.4
Release:        1%{?dist}
Summary:        MPEG-4 Simple and Advanced Simple Profile codec

Group:          System Environment/Libraries
License:        GPLv2+
URL:            http://www.xvid.org/
Source0:        http://downloads.xvid.org/downloads/xvidcore-%{version}%{?pre}.tar.bz2

%ifarch %{ix86} x86_64
BuildRequires:  nasm >= 2.0
%endif

%description
The Xvid video codec implements MPEG-4 Simple Profile and Advanced Simple
Profile standards. It permits compressing and decompressing digital video
in order to reduce the required bandwidth of video data for transmission
over computer networks or efficient storage on CDs or DVDs. Due to its
unrivalled quality Xvid has gained great popularity and is used in many
other GPLed applications, like e.g. Transcode, MEncoder, MPlayer, Xine and
many more.

%package        devel
Summary:        Development files for the Xvid video codec
Group:          Development/Libraries
Requires:       %{name} = %{version}-%{release}

%description    devel
This package contains header files, static library and API
documentation for the Xvid video codec.


%prep
%setup -q -n %{name}
chmod -x examples/*.pl
f=AUTHORS ; iconv -f iso-8859-1 -t utf-8 -o $f.utf8 $f && touch -r $f $f.utf8 && mv $f.utf8 $f
# Yes, we want to see the build output.
%{__perl} -pi -e 's/^\t@(?!echo\b)/\t/' build/generic/Makefile


%build
cd build/generic
export CFLAGS="$RPM_OPT_FLAGS -ffast-math"
%configure
make %{?_smp_mflags}
cd -


%install
rm -rf $RPM_BUILD_ROOT
make -C build/generic install DESTDIR=$RPM_BUILD_ROOT
rm $RPM_BUILD_ROOT%{_libdir}/libxvidcore.a
chmod 755 $RPM_BUILD_ROOT%{_libdir}/libxvidcore.so.*


%post -p /sbin/ldconfig

%postun -p /sbin/ldconfig


%files
%doc LICENSE README AUTHORS ChangeLog
%{_libdir}/libxvidcore.so.*

%files devel
%doc CodingStyle TODO examples/
%{_includedir}/xvid.h
%{_libdir}/libxvidcore.so


%changelog
* Sat Mar 12 2016 Antoine Martin <antoine@nagafix.co.uk> - 1.3.4-1
- initial packaging for xpra (centos)
