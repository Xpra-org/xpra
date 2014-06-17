Name:	  ffmpeg		
Version:  2.2.3
Release:  1%{?dist}
Summary:  Utilities and libraries to record, convert and stream audio and video	

Group:          Applications/Multimedia
License:	GPL
URL:		http://www.ffmpeg.org
Source0:	http://www.ffmpeg.org/releases/ffmpeg-%{version}.tar.bz2
BuildRoot:	%(mktemp -ud %{_tmppath}/%{name}-%{version}-%{release}-XXXXXX)

BuildRequires:	yasm, x264-devel
Requires:       %{name}-libs = %{version}-%{release}

%if 0%{?fc19}
BuildRequires: perl-podlators
%endif

%description
FFmpeg is a complete and free Internet live audio and video
broadcasting solution for Linux/Unix. It also includes a digital
VCR. It can encode in real time in many formats including MPEG1 audio
and video, MPEG4, h263, ac3, asf, avi, real, mjpeg, and flash.


%package libs
Summary:  Libraries for %{name}
Group:    System Environment/Libraries

%description    libs
FFmpeg is a complete and free Internet live audio and video
broadcasting solution for Linux/Unix. It also includes a digital
VCR. It can encode in real time in many formats including MPEG1 audio
and video, MPEG4, h263, ac3, asf, avi, real, mjpeg, and flash.
This package contains the libraries for %{name}

%package devel
Summary:  Development package for %{name}
Group:    Development/libraries
Requires: %{name}-libs = %{version}-%{release}
Requires: pkgconfig

%description devel
FFmpeg is a complete and free Internet live audio and video
broadcasting solution for Linux/Unix. It also includes a digital
VCR. It can encode in real time in many formats including MPEG1 audio
and video, MPEG4, h263, ac3, asf, avi, real, mjpeg, and flash.
This package contains development files for %{name}

%prep
%setup -q


%build
./configure \
    --prefix="%{_prefix}" \
    --libdir="%{_libdir}" \
    --shlibdir="%{_libdir}" \
    --mandir="%{_mandir}" \
    --incdir="%{_includedir}" \
    --enable-runtime-cpudetect \
    --disable-avdevice \
    --enable-pic \
    --disable-zlib \
    --disable-filters \
    --disable-everything \
    --enable-libx264 \
    --enable-libvpx \
    --enable-gpl \
    --enable-decoder=h264 \
    --enable-decoder=hevc \
    --enable-decoder=vp8 \
    --enable-decoder=vp9 \
    --enable-shared \
    --enable-static \
    --disable-symver

make %{?_smp_mflags}


%install
rm -rf %{buildroot}
make install DESTDIR=%{buildroot}


%post -p /sbin/ldconfig
%postun -p /sbin/ldconfig

%clean
rm -rf %{buildroot}


%files
%defattr(-,root,root,-)
%doc COPYING* CREDITS README doc/ffserver.conf
%{_bindir}/ffmpeg
%{_bindir}/ffprobe
%{_bindir}/ffserver
%{_datadir}/ffmpeg/
%{_datadir}/man/man1/ffmpeg*.1.gz
%{_datadir}/man/man1/ffprobe*.1.gz
%{_datadir}/man/man1/ffserver*.1.gz

%files libs
%{_libdir}/libavcodec.so.*
%{_libdir}/libavfilter.so.*
%{_libdir}/libavformat.so.*
%{_libdir}/libavutil.so.*
%{_libdir}/libpostproc.so.*
%{_libdir}/libswresample.so.*
%{_libdir}/libswscale.so.*
%{_datadir}/man/man3/lib*.3.gz


%files devel
%doc MAINTAINERS doc/APIchanges
%defattr(-,root,root,-)
%{_includedir}/libavcodec/
%{_includedir}/libavfilter/
%{_includedir}/libavformat/
%{_includedir}/libavutil/
%{_includedir}/libpostproc/
%{_includedir}/libswresample/
%{_includedir}/libswscale/
%{_libdir}/libavcodec.a
%{_libdir}/libavfilter.a
%{_libdir}/libavformat.a
%{_libdir}/libavutil.a
%{_libdir}/libpostproc.a
%{_libdir}/libswresample.a
%{_libdir}/libswscale.a
%{_libdir}/libavcodec.so
%{_libdir}/libavfilter.so
%{_libdir}/libavformat.so
%{_libdir}/libavutil.so
%{_libdir}/libpostproc.so
%{_libdir}/libswresample.so
%{_libdir}/libswscale.so
%{_libdir}/pkgconfig/libavcodec.pc
%{_libdir}/pkgconfig/libavfilter.pc
%{_libdir}/pkgconfig/libavformat.pc
%{_libdir}/pkgconfig/libavutil.pc
%{_libdir}/pkgconfig/libpostproc.pc
%{_libdir}/pkgconfig/libswresample.pc
%{_libdir}/pkgconfig/libswscale.pc



%changelog

