%global tarball xf86-video-dummy
%global moduledir %(pkg-config xorg-server --variable=moduledir )
%global driverdir %{moduledir}/drivers
%{!?make_build: %global make_build make}

%undefine _hardened_build

Summary:   Xorg X11 dummy video driver
Name:      xorg-x11-drv-dummy
Version:   0.3.8
Release:   1.xpra1%{?dist}
URL:       http://www.x.org
License:   MIT
Group:     User Interface/X Hardware Support

Source0:   ftp://ftp.x.org/pub/individual/driver/%{tarball}-%{version}.tar.bz2
Patch2:    0002-Constant-DPI.patch
Patch3:    0003-fix-pointer-limits.patch
Patch5:    0005-support-for-30-bit-depth-in-dummy-driver.patch

ExcludeArch: s390 s390x

BuildRequires: xorg-x11-server-devel >= 1.10.99.902
BuildRequires: autoconf automake libtool

Requires: Xorg %(xserver-sdk-abi-requires ansic)
Requires: Xorg %(xserver-sdk-abi-requires videodrv)

%description
X.Org X11 dummy video driver.

%prep
%setup -q -n %{tarball}-%{version}
%patch2 -p1
%patch3 -p1
%patch5 -p1
autoreconf -vif

%build
%configure --disable-static
%make_build

%install
rm -rf $RPM_BUILD_ROOT

make install DESTDIR=$RPM_BUILD_ROOT

# FIXME: Remove all libtool archives (*.la) from modules directory.  This
# should be fixed in upstream Makefile.am or whatever.
find $RPM_BUILD_ROOT -regex ".*\.la$" | xargs rm -f --

%files
%doc README
%{driverdir}/dummy_drv.so

%changelog
* Fri Dec 23 2016 Antoine Martin <antoine@nagafix.co.uk> - 0.3.8-1.xpra1
- new upstream release

* Thu Nov 24 2016 Antoine Martin <antoine@nagafix.co.uk> - 0.3.7-1.xpra1
- merge upstream updates

* Wed Nov  9 2016 Hans de Goede <hdegoede@redhat.com> - 0.3.7-1
- New upstream release 0.7.3
- Fix undefined symbol error with xserver-1.19 (rhbz#1393114)

* Sun Oct 30 2016 Antoine Martin <antoine@nagafix.co.uk> - 0.3.6-26.xpra3
- force rebuild against updated headers

* Wed Oct 26 2016 Antoine Martin <antoine@nagafix.co.uk> - 0.3.6-26.xpra2
- fix change-window-property API call

* Fri Oct 21 2016 Antoine Martin <antoine@nagafix.co.uk> - 0.3.6-26.xpra1
- rebuild for Fedora 25

* Tue Sep 20 2016 Antoine Martin <antoine@nagafix.co.uk> - 0.3.6-25.xpra3
- updated 30 bit patch

* Tue Sep 20 2016 Antoine Martin <antoine@nagafix.co.uk> - 0.3.6-25.xpra2
- add support for 30 bit depth

* Mon Apr 18 2016 Antoine Martin <antoine@nagafix.co.uk> - 0.3.6-25.xpra1
- Rebuilt with xpra fixes: DAC, DPI and pointer limits
