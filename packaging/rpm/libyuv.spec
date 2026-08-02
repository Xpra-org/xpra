%define _disable_source_fetch 0
%global git_commit 5d03bf9bab5693ccf692f18b538d8d9c00387c73
%global git_date 20260706
%global git_short 5d03bf9
# the Debian source package version for the same git snapshot,
# and the snapshot.debian.org timestamp it was first seen at:
%global deb_version 0.0.1949.%{git_date}
%global deb_snapshot 20260707T202226Z

Name:		libyuv
Summary:	YUV conversion and scaling functionality library
Version:	0
Release:	0.63.%{git_date}git%{git_short}.1%{?dist}
License:	BSD-3-Clause
URL:		https://chromium.googlesource.com/libyuv/libyuv
VCS:		git:%{url}
# Do not use `%%{url}/+archive/%%{git_commit}.tar.gz`:
# googlesource generates those tarballs on the fly and they are not reproducible,
# so the checksum below would break on every download.
# Debian ships the exact same tree as an immutable orig tarball
# (verified byte for byte against upstream commit %%{git_commit}).
# snapshot.debian.org keeps every version forever, so unlike the deb.debian.org
# pool this URL will not disappear when sid moves on to a newer snapshot.
Source0:	https://snapshot.debian.org/archive/debian/%{deb_snapshot}/pool/main/liby/%{name}/%{name}_%{deb_version}.orig.tar.xz
# Fedora-specific. Upstream isn't interested in these patches.
Patch1:		libyuv-0001-Use-a-proper-so-version.patch
Patch2:		libyuv-0002-Link-against-shared-library.patch
Patch3:		libyuv-0003-Use-GNUInstallDirs-during-installation.patch
Patch4:		libyuv-0004-Use-CTest-switches-for-testing.patch
Patch5:		libyuv-0005-arch-s390x-disable-little-endian-tests.patch
Patch6:		libyuv-0006-Don-t-install-tools-and-static-lib.patch
BuildRequires:	cmake
BuildRequires:	gcc-c++
BuildRequires:	pkgconfig(libjpeg)
%if 0%{?el8}
#CentOS 8 ships cmake with broken dependencies, fix it:
BuildRequires:	libarchive
%endif


%description
This is an open source project that includes YUV conversion and scaling
functionality. Converts all webcam formats to YUV (I420). Convert YUV to
formats for rendering/effects. Rotate by 90 degrees to adjust for mobile
devices in portrait mode. Scale YUV to prepare content for compression,
with point, bilinear or box filter.


%package devel
Summary: The development files for %{name}
Requires: %{name}%{?_isa} = %{version}-%{release}


%description devel
Additional header files for development with %{name}.


%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "28c3cd7d109c93202ce3e7fd5a5534db7c137929b06c6792d6a904fe2ac130d1" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi

%if 0%{?fedora} || 0%{?el8} || 0%{?el9}
echo "**********************************************************************"
echo "*** WARNING: this bundled libyuv package is meant for RHEL 10 only. ***"
echo "*** Fedora and RHEL 8 / 9 should use the distribution or EPEL RPM.  ***"
echo "*** Sleeping for 20 seconds so you can abort this build.            ***"
echo "**********************************************************************"
sleep 20
%endif

%autosetup -p1 -n %{name}-%{deb_version}

cat > %{name}.pc << EOF
prefix=%{_prefix}
exec_prefix=${prefix}
libdir=%{_libdir}
includedir=%{_includedir}

Name: %{name}
Description: %{summary}
Version: %{version}
Libs: -lyuv
EOF


%build
%cmake -DBUILD_TESTING=OFF
%cmake_build


%install
%cmake_install

install -D -p -m 0644 %{name}.pc %{buildroot}%{_libdir}/pkgconfig/%{name}.pc


%files
%license LICENSE
%doc AUTHORS PATENTS README.md
%{_libdir}/%{name}.so.*


%files devel
%{_includedir}/%{name}
%{_includedir}/%{name}.h
%{_libdir}/%{name}.so
%{_libdir}/pkgconfig/%{name}.pc


%changelog
* Sun Aug 02 2026 Antoine Martin <totaam@xpra.org> - 0-0.63.20260706git5d03bf9.1
- switch to Debian's immutable orig tarball: googlesource archives are not reproducible
- update to the 20260706 snapshot (libyuv 1949)

* Thu Jun 11 2026 Antoine Martin <totaam@xpra.org> - 0-0.62.20260213git6067afd.1
- update to the Fedora Rawhide libyuv snapshot
- use Fedora's current packaging patch stack

* Thu Feb 20 2025 Antoine Martin <totaam@xpra.org> - 0-0.1899.r2785.47ddac299.1
- new upstream git snapshot
- remove outdated patches
- bundle yuvconvert and static library

* Fri Feb 03 2023 Antoine Martin <totaam@xpra.org> - 0-0.1857.20230123gitb2528b0b.1
- new upstream git snapshot - now hosted on xpra.org

* Sun Aug 07 2022 Antoine Martin <totaam@xpra.org> - 0-0.1832.20220629git6900494.1
- new upstream git snapshot

* Tue May 25 2021 Antoine Martin <totaam@xpra.org> - 0-0.1766.20201016gita4ec5cf.1
- don't use jpeg, which also fixes CentOS 7.x builds

* Wed Apr 17 2019 Antoine Martin <totaam@xpra.org> - 0-0.1766.20201016gita4ec5cf
- Use newer snapshot on github mirror

* Wed Apr 17 2019 Peter Lemenkov <lemenkov@gmail.com> - 0-0.35.20190401git4bd08cb
- Fix linkage against libjpeg

* Tue Apr 16 2019 Peter Lemenkov <lemenkov@gmail.com> - 0-0.34.20190401git4bd08cb
- Fixed pkgconfig-file

* Tue Apr 09 2019 Peter Lemenkov <lemenkov@gmail.com> - 0-0.33.20190401git4bd08cb
- Update to the latest git snapshot

* Fri Feb 01 2019 Fedora Release Engineering <releng@fedoraproject.org> - 0-0.32.20180904git9a07219
- Rebuilt for https://fedoraproject.org/wiki/Fedora_30_Mass_Rebuild

* Mon Sep 24 2018 Peter Lemenkov <lemenkov@gmail.com> - 0-0.31.20180904git9a07219
- Update to the latest git snapshot

* Fri Jul 13 2018 Fedora Release Engineering <releng@fedoraproject.org> - 0-0.30.20121221svn522
- Rebuilt for https://fedoraproject.org/wiki/Fedora_29_Mass_Rebuild

* Wed Feb 07 2018 Fedora Release Engineering <releng@fedoraproject.org> - 0-0.29.20121221svn522
- Rebuilt for https://fedoraproject.org/wiki/Fedora_28_Mass_Rebuild

* Thu Aug 03 2017 Fedora Release Engineering <releng@fedoraproject.org> - 0-0.28.20121221svn522
- Rebuilt for https://fedoraproject.org/wiki/Fedora_27_Binutils_Mass_Rebuild

* Wed Jul 26 2017 Fedora Release Engineering <releng@fedoraproject.org> - 0-0.27.20121221svn522
- Rebuilt for https://fedoraproject.org/wiki/Fedora_27_Mass_Rebuild

* Fri Feb 10 2017 Fedora Release Engineering <releng@fedoraproject.org> - 0-0.26.20121221svn522
- Rebuilt for https://fedoraproject.org/wiki/Fedora_26_Mass_Rebuild

* Thu Feb 04 2016 Fedora Release Engineering <releng@fedoraproject.org> - 0-0.25.20121221svn522
- Rebuilt for https://fedoraproject.org/wiki/Fedora_24_Mass_Rebuild

* Wed Jun 17 2015 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0-0.24.20121221svn522
- Rebuilt for https://fedoraproject.org/wiki/Fedora_23_Mass_Rebuild

* Sat May 02 2015 Kalev Lember <kalevlember@gmail.com> - 0-0.23.20121221svn522
- Rebuilt for GCC 5 C++11 ABI change

* Sun Aug 17 2014 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0-0.22.20121221svn522
- Rebuilt for https://fedoraproject.org/wiki/Fedora_21_22_Mass_Rebuild

* Sat Jun 07 2014 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0-0.21.20121221svn522
- Rebuilt for https://fedoraproject.org/wiki/Fedora_21_Mass_Rebuild

* Sat Aug 03 2013 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0-0.20.20121221svn522
- Rebuilt for https://fedoraproject.org/wiki/Fedora_20_Mass_Rebuild

* Thu Feb 14 2013 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0-0.19.20121221svn522
- Rebuilt for https://fedoraproject.org/wiki/Fedora_19_Mass_Rebuild

* Fri Jan 18 2013 Adam Tkac <atkac redhat com> - 0-0.18.20121221svn522
- rebuild due to "jpeg8-ABI" feature drop

* Sun Dec 30 2012 Dan Horák <dan[at]danny.cz> - 0-0.17.20121221svn522
- add big endian fix

* Fri Dec 21 2012 Adam Tkac <atkac redhat com> - 0-0.16.20121221svn522
- rebuild against new libjpeg

* Fri Dec 21 2012 Peter Lemenkov <lemenkov@gmail.com> - 0-0.15.20121221svn522
- Next svn snapshot - ver. 522

* Thu Oct 04 2012 Peter Lemenkov <lemenkov@gmail.com> - 0-0.14.20121001svn389
- Next svn snapshot - ver. 389
- Enable NEON on ARM (if detected)

* Sat Sep 15 2012 Peter Lemenkov <lemenkov@gmail.com> - 0-0.13.20120915svn353
- Next svn snapshot - ver. 353
- Dropped upstreamed patch no.3

* Mon Jul 30 2012 Peter Lemenkov <lemenkov@gmail.com> - 0-0.12.20120727svn312
- Next svn snapshot - ver. 312

* Thu Jul 19 2012 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0-0.11.20120627svn296
- Rebuilt for https://fedoraproject.org/wiki/Fedora_18_Mass_Rebuild

* Thu Jul 05 2012 Peter Lemenkov <lemenkov@gmail.com> - 0-0.10.20120627svn296
- Next svn snapshot - ver. 296
- Dropped patch3 (header conflict) - fixed upstream

* Thu Jun 14 2012 Tom Callaway <spot@fedoraproject.org> - 0-0.9.20120518svn268
- resolve header conflict with duplicate definition in scale*.h

* Fri May 18 2012 Peter Lemenkov <lemenkov@gmail.com> - 0-0.8.20120518svn268
- Next svn snapshot - ver. 268
- Fixed failure on s390x and PPC64 (see rhbz #822494)
- Fixed FTBFS on EL5 (see rhbz #819179)

* Sat May 05 2012 Peter Lemenkov <lemenkov@gmail.com> - 0-0.7.20120505svn256
- Next svn snapshot - ver. 256

* Sun Apr 08 2012 Peter Lemenkov <lemenkov@gmail.com> - 0-0.6.20120406svn239
- Next svn snapshot - ver. 239

* Thu Mar 08 2012 Peter Lemenkov <lemenkov@gmail.com> - 0-0.5.20120308svn209
- Next svn ver. - 209
- Drop upstreamed patches
- Add libjpeg as a dependency

* Thu Feb 02 2012 Peter Lemenkov <lemenkov@gmail.com> - 0-0.4.20120202svn164
- Next svn ver. - 164
- Added two patches - no.2 and no.3

* Thu Jan 12 2012 Peter Lemenkov <lemenkov@gmail.com> - 0-0.3.20120109svn128
- Use bzip2 instead of xz (for EL-5)

* Wed Jan 11 2012 Peter Lemenkov <lemenkov@gmail.com> - 0-0.2.20120109svn128
- Update to svn rev. 128
- Enable unit-tests
- Dropped obsolete defattr directive
- Consistently use macros
- Explicitly add _isa to the Requires for *-devel sub-package

* Fri Jan  6 2012 Peter Lemenkov <lemenkov@gmail.com> - 0-0.1.20120105svn127
- Initial package
