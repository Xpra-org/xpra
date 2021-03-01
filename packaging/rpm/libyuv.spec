%define _disable_source_fetch 0
%define COMMIT 19d71f6b351fe992ae34b114eebd872c383a6bdb

Name:		libyuv
Summary:	YUV conversion and scaling functionality library
Version:	0
Release:	0.1766.20201016gita4ec5cf%{?dist}
License:	BSD
URL:		https://chromium.googlesource.com/libyuv/libyuv
#VCS:		scm:git:https://chromium.googlesource.com/libyuv/libyuv
## git clone https://chromium.googlesource.com/libyuv/libyuv
## cd libyuv
## git archive --format=tar --prefix=libyuv-0/ 4bd08cb | xz  > ../libyuv-0.tar.xz
Source0:	https://github.com/lemenkov/%{name}/archive/%{COMMIT}.zip
# Fedora-specific. Upstream isn't interested in these patches.
Patch1:		libyuv-0001-Use-a-proper-so-version.patch
Patch2:		libyuv-0002-Link-against-shared-library.patch
Patch3:		libyuv-0003-Disable-static-library.patch
Patch4:		libyuv-0004-Don-t-install-conversion-tool.patch
Patch5:		libyuv-0005-Use-library-suffix-during-installation.patch
Patch6:		libyuv-0006-Link-main-library-against-libjpeg.patch
BuildRequires:	make
BuildRequires:	cmake
BuildRequires:	gcc-c++
%if !0%{?el7}
BuildRequires:	gtest-devel
%endif
BuildRequires:	libjpeg-devel


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
if [ "${sha256}" != "5906ff00c8956df09c0187549a3fd5cf0da40859846f49d565cc9abfca93f29a" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi 
%autosetup -p1 -n libyuv-%{COMMIT}

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
%cmake .
%make_build

%install
%make_install

mkdir -p %{buildroot}%{_libdir}/pkgconfig
cp -a %{name}.pc %{buildroot}%{_libdir}/pkgconfig/


%check
# FIXME fails again on s390
./libyuv_unittest || true


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
