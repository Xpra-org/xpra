%global   real_name ffmpeg
Name:	     ffmpeg-xpra
Version:     3.4
Release:     1%{?dist}
Summary:     ffmpeg libraries for xpra

Group:       Applications/Multimedia
License:     GPL
URL:	     http://www.ffmpeg.org
Source0:     http://www.ffmpeg.org/releases/ffmpeg-%{version}.tar.bz2
BuildRoot:   %(mktemp -ud %{_tmppath}/%{real_name}-%{version}-%{release}-XXXXXX)

BuildRequires:	x264-xpra-devel
BuildRequires:	yasm


%description
ffmpeg libraries for xpra


%package devel
Summary:   Development package for %{real_name}
Group:     Development/libraries
Requires:  %{name} = %{version}-%{release}
Requires:  pkgconfig

%description devel
This package contains the development files for %{name}.


%prep
%setup -q -n %{real_name}-%{version}


%build
# set pkg_config_path for xpra video libs
PKG_CONFIG_PATH=%{_libdir}/xpra/pkgconfig ./configure \
	--prefix="%{_prefix}" \
	--libdir="%{_libdir}/xpra" \
	--shlibdir="%{_libdir}/xpra" \
	--mandir="%{_mandir}/xpra" \
	--incdir="%{_includedir}/xpra" \
	--extra-cflags="-I%{_includedir}/xpra" \
	--extra-ldflags="-L%{_libdir}/xpra" \
	--enable-runtime-cpudetect \
	--disable-avdevice \
	--enable-pic \
	--disable-zlib \
	--disable-filters \
	--disable-everything \
	--disable-doc \
	--disable-programs \
	--disable-libxcb \
	--enable-libx264 \
	--enable-libvpx \
	--enable-gpl \
	--enable-protocol=file \
	--enable-decoder=h264 \
	--enable-decoder=hevc \
	--enable-decoder=vp8 \
	--enable-decoder=vp9 \
	--enable-decoder=mpeg4 \
	--enable-encoder=libvpx_vp8 \
	--enable-encoder=libvpx_vp9 \
	--enable-encoder=mpeg4 \
	--enable-encoder=libx264 \
	--enable-encoder=aac \
	--enable-muxer=mp4 \
	--enable-muxer=webm \
	--enable-muxer=matroska \
	--enable-muxer=ogg \
	--enable-demuxer=h264 \
	--enable-demuxer=hevc \
	--enable-demuxer=m4v \
	--enable-demuxer=matroska \
	--enable-demuxer=ogg \
	--enable-shared \
	--enable-debug \
	--disable-stripping \
	--disable-symver \
	--enable-rpath
	#--enable-static

make %{?_smp_mflags}


%install
rm -rf %{buildroot}
make install DESTDIR=%{buildroot}

#%post -p /sbin/ldconfig
#%postun -p /sbin/ldconfig

%clean
rm -rf %{buildroot}


%files
%defattr(-,root,root,-)
%doc COPYING* CREDITS doc/ffserver.conf
%{_libdir}/xpra/libavcodec.so.*
%{_libdir}/xpra/libavfilter.so.*
%{_libdir}/xpra/libavformat.so.*
%{_libdir}/xpra/libavutil.so.*
%{_libdir}/xpra/libpostproc.so.*
%{_libdir}/xpra/libswresample.so.*
%{_libdir}/xpra/libswscale.so.*


%files devel
%doc MAINTAINERS doc/APIchanges
%defattr(-,root,root,-)
%{_includedir}/xpra/libavcodec/
%{_includedir}/xpra/libavfilter/
%{_includedir}/xpra/libavformat/
%{_includedir}/xpra/libavutil/
%{_includedir}/xpra/libpostproc/
%{_includedir}/xpra/libswresample/
%{_includedir}/xpra/libswscale/
%{_libdir}/xpra/libavcodec.a
%{_libdir}/xpra/libavfilter.a
%{_libdir}/xpra/libavformat.a
%{_libdir}/xpra/libavutil.a
%{_libdir}/xpra/libpostproc.a
%{_libdir}/xpra/libswresample.a
%{_libdir}/xpra/libswscale.a
%{_libdir}/xpra/libavcodec.so
%{_libdir}/xpra/libavfilter.so
%{_libdir}/xpra/libavformat.so
%{_libdir}/xpra/libavutil.so
%{_libdir}/xpra/libpostproc.so
%{_libdir}/xpra/libswresample.so
%{_libdir}/xpra/libswscale.so
%{_libdir}/xpra/pkgconfig/libavcodec.pc
%{_libdir}/xpra/pkgconfig/libavfilter.pc
%{_libdir}/xpra/pkgconfig/libavformat.pc
%{_libdir}/xpra/pkgconfig/libavutil.pc
%{_libdir}/xpra/pkgconfig/libpostproc.pc
%{_libdir}/xpra/pkgconfig/libswresample.pc
%{_libdir}/xpra/pkgconfig/libswscale.pc


%changelog
* Sat Oct 21 2017 Antoine Martin <antoine@devloop.org.uk> 3.4-1
- new upstream release

* Thu Sep 14 2017 Antoine Martin <antoine@devloop.org.uk> 3.3.4-1
- new upstream release

* Tue Aug 01 2017 Antoine Martin <antoine@devloop.org.uk> 3.3.3-1
- new upstream release

* Sun Jun 11 2017 Antoine Martin <antoine@devloop.org.uk> 3.3.2-1
- new upstream release

* Mon May 15 2017 Antoine Martin <antoine@devloop.org.uk> 3.3.1-1
- new upstream release

* Tue Apr 18 2017 Antoine Martin <antoine@devloop.org.uk> 3.3-3
- use xpra's PKG_CONFIG_PATH

* Tue Apr 18 2017 Antoine Martin <antoine@devloop.org.uk> 3.3-2
- enable rpath

* Fri Apr 14 2017 Antoine Martin <antoine@devloop.org.uk> 3.3-1
- new upstream release

* Mon Feb 13 2017 Antoine Martin <antoine@devloop.org.uk> 3.2.4-1
- new upstream release

* Fri Dec 09 2016 Antoine Martin <antoine@devloop.org.uk> 3.2.2-1
- new upstream release

* Sun Nov 27 2016 Antoine Martin <antoine@devloop.org.uk> 3.2.1-1
- new upstream release

* Fri Nov 04 2016 Antoine Martin <antoine@devloop.org.uk> 3.2-2
- add aac encoder for html5 client

* Sun Oct 30 2016 Antoine Martin <antoine@devloop.org.uk> 3.2-1
- new upstream release

* Sun Oct 23 2016 Antoine Martin <antoine@devloop.org.uk> 3.1.5-1
- new upstream release

* Sun Oct 09 2016 Antoine Martin <antoine@devloop.org.uk> 3.1.4-1
- new upstream release

* Sun Aug 28 2016 Antoine Martin <antoine@devloop.org.uk> 3.1.3-1
- new upstream release

* Sat Aug 20 2016 Antoine Martin <antoine@devloop.org.uk> 3.1.2-1
- new upstream release

* Fri Aug 05 2016 Antoine Martin <antoine@devloop.org.uk> 3.1.1-2
- add file protocol for testing muxer

* Mon Jul 04 2016 Antoine Martin <antoine@devloop.org.uk> 3.1.1-1
- new upstream release

* Mon Jun 27 2016 Antoine Martin <antoine@devloop.org.uk> 3.1-2
- new upstream release

* Sun Jun 12 2016 Antoine Martin <antoine@devloop.org.uk> 3.0.2-2
- include encoders and muxers for ffmpeg encoder

* Fri Apr 29 2016 Antoine Martin <antoine@devloop.org.uk> 3.0.2-1
- new upstream release

* Fri Apr 01 2016 Antoine Martin <antoine@devloop.org.uk> 3.0.1-1
- new upstream release
- include mpeg4, ogg, matroska and webm support

* Mon Feb 15 2016 Antoine Martin <antoine@devloop.org.uk> 3.0-1
- new upstream release

* Sat Feb 06 2016 Antoine Martin <antoine@devloop.org.uk> 2.8.6-1
- new upstream release

* Thu Jan 21 2016 Antoine Martin <antoine@devloop.org.uk> 2.8.5-1
- new upstream release

* Sun Dec 20 2015 Antoine Martin <antoine@devloop.org.uk> 2.8.4-1
- new upstream release

* Sun Nov 29 2015 Antoine Martin <antoine@devloop.org.uk> 2.8.3-1
- new upstream release

* Tue Nov 17 2015 Antoine Martin <antoine@devloop.org.uk> 2.8.2-1
- new upstream release

* Fri Oct 16 2015 Antoine Martin <antoine@devloop.org.uk> 2.8.1-1
- new upstream release

* Thu Sep 10 2015 Antoine Martin <antoine@devloop.org.uk> 2.8-1
- new upstream release

* Tue Jul 28 2015 Antoine Martin <antoine@devloop.org.uk> 2.7.2-1
- new upstream release

* Wed Jul 01 2015 Antoine Martin <antoine@devloop.org.uk> 2.7.1-1
- new upstream release

* Wed Jun 10 2015 Antoine Martin <antoine@devloop.org.uk> 2.7-1
- new upstream release

* Fri May 22 2015 Antoine Martin <antoine@devloop.org.uk> 2.6.3-1
- new upstream release

* Sat Apr 04 2015 Antoine Martin <antoine@devloop.org.uk> 2.6.1-1
- new upstream release

* Sat Apr 04 2015 Antoine Martin <antoine@devloop.org.uk> 2.4.8-1
- new upstream release

* Tue Mar 10 2015 Antoine Martin <antoine@devloop.org.uk> 2.4.7-1
- new upstream release

* Sun Jan 18 2015 Antoine Martin <antoine@devloop.org.uk> 2.4.6-1
- new upstream release

* Mon Dec 29 2014 Antoine Martin <antoine@devloop.org.uk> 2.4.5-1
- new upstream release

* Mon Dec 01 2014 Antoine Martin <antoine@devloop.org.uk> 2.4.4-1
- new upstream release

* Mon Nov 03 2014 Antoine Martin <antoine@devloop.org.uk> 2.4.3-1
- new upstream release

* Tue Oct 07 2014 Antoine Martin <antoine@devloop.org.uk> 2.4.2-1
- new upstream release

* Sun Sep 21 2014 Antoine Martin <antoine@devloop.org.uk> 2.4-1
- new upstream release

* Mon Aug 18 2014 Antoine Martin <antoine@devloop.org.uk> 2.3.3-1
- version bump

* Thu Aug 07 2014 Antoine Martin <antoine@devloop.org.uk> 2.3.2-1
- version bump, switch to 2.3.x

* Thu Aug 07 2014 Antoine Martin <antoine@devloop.org.uk> 2.2.6-1
- version bump

* Thu Jul 31 2014 Antoine Martin <antoine@devloop.org.uk> 2.2.5-1
- version bump

* Sun Jul 20 2014 Antoine Martin <antoine@devloop.org.uk> 2.2.4-1
- version bump

* Mon Jul 14 2014 Matthew Gyurgyik <pyther@pyther.net>
- initial package
