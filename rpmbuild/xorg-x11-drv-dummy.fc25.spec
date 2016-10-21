%define tarball xf86-video-dummy
%define moduledir %(pkg-config xorg-server --variable=moduledir )
%define driverdir	%{moduledir}/drivers

%undefine _hardened_build

Summary:   Xorg X11 dummy video driver
Name:      xorg-x11-drv-dummy
Version:   0.3.6
Release:   26.xpra1%{?dist}
URL:       http://www.x.org
License:   MIT
Group:     User Interface/X Hardware Support

Source0:   ftp://ftp.x.org/pub/individual/driver/%{tarball}-%{version}.tar.bz2
Patch0:    0001-Remove-mibstore.h.patch
Patch1:    0002-Constant-DPI.patch
Patch2:    0003-fix-pointer-limits.patch
Patch3:    0004-honour-dac.patch
Patch4:    0005-support-for-30-bit-depth-in-dummy-driver.patch
Patch5:    0006-remove-dead-code-in-dummy-driver.patch

ExcludeArch: s390 s390x

BuildRequires: xorg-x11-server-devel >= 1.10.99.902
BuildRequires: autoconf automake libtool

Requires: Xorg %(xserver-sdk-abi-requires ansic)
Requires: Xorg %(xserver-sdk-abi-requires videodrv)

%description
X.Org X11 dummy video driver.

%prep
%setup -q -n %{tarball}-%{version}
%patch0 -p1 -b .mibstore
%patch1 -p1
%patch2 -p1
%patch3 -p1
%patch4 -p1
%patch5 -p1

%build
autoreconf -vif
%configure --disable-static
make

%install
rm -rf $RPM_BUILD_ROOT

make install DESTDIR=$RPM_BUILD_ROOT

# FIXME: Remove all libtool archives (*.la) from modules directory.  This
# should be fixed in upstream Makefile.am or whatever.
find $RPM_BUILD_ROOT -regex ".*\.la$" | xargs rm -f --

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root,-)
%{driverdir}/dummy_drv.so

%changelog
* Fri Oct 21 2016 Antoine Martin <antoine@nagafix.co.uk> - 0.3.6-26.xpra1
- rebuild for Fedora 25

* Tue Sep 20 2016 Antoine Martin <antoine@nagafix.co.uk> - 0.3.6-25.xpra3
- updated 30 bit patch

* Tue Sep 20 2016 Antoine Martin <antoine@nagafix.co.uk> - 0.3.6-25.xpra2
- add support for 30 bit depth

* Mon Apr 18 2016 Antoine Martin <antoine@nagafix.co.uk> - 0.3.6-25.xpra1
- Rebuilt with xpra fixes: DAC, DPI and pointer limits
