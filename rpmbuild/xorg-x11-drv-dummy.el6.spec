%define tarball xf86-video-dummy
%define moduledir %(pkg-config xorg-server --variable=moduledir )
%define driverdir	%{moduledir}/drivers

Summary:   Xorg X11 dummy video driver
Name:      xorg-x11-drv-dummy
Version:   0.3.6
Release:   15.xpra4%{?dist}
URL:       http://www.x.org
License:   MIT
Group:     User Interface/X Hardware Support
BuildRoot: %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)

Source0:   ftp://ftp.x.org/pub/individual/driver/%{tarball}-%{version}.tar.bz2
Patch0:    0001-Remove-mibstore.h.patch
Patch1:    0002-Constant-DPI.patch
Patch2:    0003-fix-pointer-limits.patch

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
* Wed Nov 05 2014 Antoine Martin <antoine@nagafix.co.uk> - 0.3.6-15.xpra4
- add cursor limit fix

* Thu Oct 30 2014 Antoine Martin <antoine@nagafix.co.uk> - 0.3.6-15.xpra3
- force rebuild for CentOS 6.6

* Sat Oct 25 2014 Antoine Martin <antoine@nagafix.co.uk> - 0.3.6-15.xpra2
- force rebuild for ABI break

* Sat Oct 25 2014 Antoine Martin <antoine@nagafix.co.uk> - 0.3.6-15.xpra1
- version bump to ensure our patched version does not get "upgraded"

* Fri Apr 18 2014 Antoine Martin <antoine@nagafix.co.uk> - 0.3.6-2.xpra2
- Add DPI override via root window property

* Wed Apr 16 2014 Antoine Martin <antoine@nagafix.co.uk> - 0.3.6-2.xpra1
- Add "ConstantDPI" support

* Wed Aug 22 2012 Dave Airlie <airlied@redhat.com> - 0.3.6-2
- rebuild for server ABI requires

* Thu Aug 02 2012 Dave Airlie <airlied@redhat.com> 0.3.6-1
- rebase to upstream release 0.3.6, as in f18.

* Tue Jun 28 2011 Ben Skeggs <bskeggs@redhat.com> 0.3.4-1
- upstream release 0.3.4

* Tue Dec 01 2009 Adam Jackson <ajax@redhat.com> 0.3.3-1
- dummy 0.3.3

* Mon Jul 27 2009 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0.3.2-2.1
- Rebuilt for https://fedoraproject.org/wiki/Fedora_12_Mass_Rebuild

* Wed Jul 15 2009 Adam Jackson <ajax@redhat.com> - 0.3.2-1.1
- ABI bump

* Thu Jul 02 2009 Adam Jackson <ajax@redhat.com> 0.3.2-1
- dummy 0.3.2

* Thu Feb 26 2009 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0.3.1-2
- Rebuilt for https://fedoraproject.org/wiki/Fedora_11_Mass_Rebuild

* Tue Feb 24 2009 Adam Jackson <ajax@redhat.com> 0.3.1-1
- dummy 0.3.1

* Thu Mar 20 2008 Dave Airlie <airlied@redhat.com> 0.3.0-1
- Latest upstream release

* Wed Feb 20 2008 Fedora Release Engineering <rel-eng@fedoraproject.org> - 0.2.0-8
- Autorebuild for GCC 4.3

* Wed Jan 09 2008 Adam Jackson <ajax@redhat.com> 0.2.0-7
- Rebuild for new server ABI.

* Tue Nov 13 2007 Adam Jackson <ajax@redhat.com> 0.2.0-6
- Require xserver 1.4.99.1

* Wed Aug 22 2007 Adam Jackson <ajax@redhat.com> - 0.2.0-5
- Rebuild for PPC toolchain bug

* Mon Jun 18 2007 Adam Jackson <ajax@redhat.com> 0.2.0-4
- Update Requires and BuildRequires.  Disown the module directories.  Add
  Requires: hwdata.

* Fri Feb 16 2007 Adam Jackson <ajax@redhat.com> 0.2.0-3
- ExclusiveArch -> ExcludeArch

* Wed Jul 12 2006 Jesse Keating <jkeating@redhat.com> - sh: line 0: fg: no job control
- rebuild

* Tue May 23 2006 Adam Jackson <ajackson@redhat.com> 0.2.0-2
- Rebuild for 7.1 ABI fix.

* Sun Apr  9 2006 Adam Jackson <ajackson@redhat.com> 0.2.0-1
- Update to 0.2.0 from 7.1RC1.

* Fri Feb 10 2006 Jesse Keating <jkeating@redhat.com> - 0.1.0.5-1.2
- bump again for double-long bug on ppc(64)

* Tue Feb 07 2006 Jesse Keating <jkeating@redhat.com> - 0.1.0.5-1.1
- rebuilt for new gcc4.1 snapshot and glibc changes

* Wed Jan 18 2006 Mike A. Harris <mharris@redhat.com> 0.1.0.5-1
- Updated xorg-x11-drv-dummy to version 0.1.0.5 from X11R7.0

* Tue Dec 20 2005 Mike A. Harris <mharris@redhat.com> 0.1.0.4-1
- Updated xorg-x11-drv-dummy to version 0.1.0.4 from X11R7 RC4
- Removed 'x' suffix from manpage dirs to match RC4 upstream.

* Wed Nov 16 2005 Mike A. Harris <mharris@redhat.com> 0.1.0.2-1
- Updated xorg-x11-drv-dummy to version 0.1.0.2 from X11R7 RC2

* Fri Nov 4 2005 Mike A. Harris <mharris@redhat.com> 0.1.0.1-1
- Updated xorg-x11-drv-dummy to version 0.1.0.1 from X11R7 RC1
- Fix *.la file removal.

* Mon Oct 3 2005 Mike A. Harris <mharris@redhat.com> 1.0.0-1
- Update BuildRoot to use Fedora Packaging Guidelines.
- Deglob file manifest.
- Add alpha/sparc/sparc64 to "ExclusiveArch"

* Fri Sep 2 2005 Mike A. Harris <mharris@redhat.com> 0.1.0-0
- Initial spec file for dummy video driver generated automatically
  by my xorg-driverspecgen script.
