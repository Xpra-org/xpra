%define tarball xf86-video-dummy
%define moduledir %(pkg-config xorg-server --variable=moduledir )
%define driverdir	%{moduledir}/drivers

Summary:   Xorg X11 dummy video driver
Name:      xorg-x11-drv-dummy
Version:   0.3.6
Release:   2.xpra1%{?dist}
URL:       http://www.x.org
License:   MIT
Group:     User Interface/X Hardware Support
BuildRoot: %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)

Source0:   ftp://ftp.x.org/pub/individual/driver/%{tarball}-%{version}.tar.bz2
Patch0:    0001-Remove-mibstore.h.patch
Patch1:    0002-Constant-DPI.patch
Patch2:    0003-fix-pointer-limits.patch
Patch3:    0004-honour-dac.patch

ExcludeArch: s390 s390x

BuildRequires: xorg-x11-server-sdk >= 1.4.99.1

Requires:  hwdata
Requires:  Xorg %(xserver-sdk-abi-requires ansic)
Requires:  Xorg %(xserver-sdk-abi-requires videodrv)

%description
X.Org X11 dummy video driver.

%prep
%setup -q -n %{tarball}-%{version}
%patch0 -p1
%patch1 -p1
%patch2 -p1
%patch3 -p1

%build
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
* Tue Dec 22 2014 Antoine Martin <antoine@nagafix.co.uk> - 0.3.6-2.xpra1
- correctly versionned RPMs for each CentOS release
