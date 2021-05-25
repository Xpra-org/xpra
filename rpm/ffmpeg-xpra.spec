%define _build_id_links none
%define _disable_source_fetch 0
%global __requires_exclude ^libx264.so.*$

%global   real_name ffmpeg
Name:	     ffmpeg-xpra
Version:     4.4
Release:     1%{?dist}
Summary:     ffmpeg libraries for xpra

Group:       Applications/Multimedia
License:     GPL
URL:	     http://www.ffmpeg.org
Source0:     http://www.ffmpeg.org/releases/ffmpeg-%{version}.tar.xz
BuildRoot:   %(mktemp -ud %{_tmppath}/%{real_name}-%{version}-%{release}-XXXXXX)
AutoProv:    0
AutoReq:     0
Requires:    x264-xpra

BuildRequires:	x264-xpra-devel
BuildRequires:	yasm
BuildRequires:	make
BuildRequires:	gcc

%description
ffmpeg libraries for xpra


%package devel
Summary:   Development package for %{real_name}
Group:     Development/libraries
Requires:  %{name} = %{version}-%{release}
Requires:  pkgconfig
Requires:  ffmpeg-xpra = %{version}
AutoReq:   0

%description devel
This package contains the development files for %{name}.


%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "06b10a183ce5371f915c6bb15b7b1fffbe046e8275099c96affc29e17645d909" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
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
	--enable-decoder=mpeg1video \
	--enable-decoder=mpeg2video \
	--enable-encoder=libvpx_vp8 \
	--enable-encoder=libvpx_vp9 \
	--enable-encoder=mpeg4 \
	--enable-encoder=mpeg1video \
	--enable-encoder=mpeg2video \
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
	--enable-pthreads \
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
#we don't care about the examples,
#and we can't turn them off using a build switch,
#so just delete them
rm -fr %{buildroot}/usr/share/ffmpeg/examples

#%post -p /sbin/ldconfig
#%postun -p /sbin/ldconfig

%clean
rm -rf %{buildroot}


%files
%defattr(-,root,root,-)
%doc COPYING* CREDITS
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
* Mon May 24 2021 Antoine Martin <antoine@xpra.org> 4.4-1
- new upstream release
