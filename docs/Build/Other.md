**This page may well be out of date**, as these platforms are [not officially supported](https://github.com/Xpra-org/xpra/wiki/Platforms).


# ![FreeBSD](https://xpra.org/icons/freebsd.png)

## [FreeBSD Ports](https://www.freebsd.org/ports/)
To install xpra using ports, just run:
```shell
cd /usr/ports/x11/xpra
make install clean
```

## Compiling on FreeBSD
_These instructions are incomplete and outdated - feel free to update them!_

The Xvfb tool can be found in the package: `xorg-vfbserver` (not obvious!)
Other packages you will need:
* for running it: `xauth xkbcomp xkeyboard-config`
* for building / downloading the source: `gcc cython subversion pkgconf`
* X11 libraries: `libXrandr libXtst libXcomposite libXdamage`
* GTK: `gobject-introspection gtk3`
* strongly recommended addons: `py37-lz4 py37-rencode py37-PyOpenGL py37-PyOpenGL-accelerate`
* audio: `py37-gstreamer1 gstreamer1-plugins-flac gstreamer1-plugins-mad gstreamer1-plugins-ogg gstreamer1-plugins-opus gstreamer1-plugins-vorbis`


***

# OrangePI
These instructions are based on this mailing list post:
 [XPRA - installation on Orange PI Plus 2E](http://lists.devloop.org.uk/pipermail/shifter-users/2017-August/001999.html) running an Ubuntu Xenial variant:\
clean up potentially conflicting packages:
```shell
apt-get purge xpra
```
install the development packages (very similar to other [Debian](./Debian.md)):
```shell
apt-get install libx11-dev libxtst-dev libxcomposite-dev libxdamage-dev \
                libxkbfile-dev python-all-dev python-gobject-dev python-gtk2-dev \
                libx264-dev libvpx-dev libswscale-dev libavformat-dev libavcodec-dev \
                xvfb xauth x11-xkb-utils \
                zlib1g zlib1g-dev liblzo2-2 liblzo2-dev
```
some system-supplied Python tools may just be too old, so get new ones directly from the world of Python:
```shell
apt-get install python-pip
pip install --upgrade pip
pip install lz4
```
The system version of ffmpeg is too old, so compile a new one from source.
The build flags used here disable most features and only keep what is actually needed by xpra - you may want to keep more features enabled if you also intend to use the ffmpeg libraries for another purpose:
```shell
wget http://ffmpeg.org/releases/ffmpeg-4.3.1.tar.bz2
tar -jxf ffmpeg-4.3.1.tar.bz2
cd ffmpeg-4.3.1
LDPATH=/usr/lib/arm-linux-gnueabihf ./configure \
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
make
make install
```
to be able to use most of xpra's features, you may also want to install:
```shell
apt-get install python-netifaces dbus-x11 python-dbus python-rencode \
    hicolor-icon-theme python-avahi python-numpy \
    gstreamer1.0-x gstreamer1.0-tools \
    python-pil python-lzo python-setuptools
```
build xpra version 3.x from source as per [wiki](./README.md)

***

# Raspbian

These instructions are valid for Raspbian Stretch and are based on this gist: [Installing Xpra on a Raspberry Pi from Source](https://gist.github.com/xaviermerino/5bb83e0b471e67beaea6d5eeb80daf8c). (which uses an outdated version)

## Install The Dependencies
build dependencies:
```shell
apt-get install libx11-dev libxtst-dev libxcomposite-dev \
    libxdamage-dev libxkbfile-dev xauth x11-xkb-utils xserver-xorg-video-dummy \
    python-all-dev python-gobject-dev python-gtk2-dev cython \
    libx264-dev libvpx-dev node-uglify yui-compressor
```
A decent set of runtime dependencies:
```shell
apt-get install python-lz4 python-cryptography
pip install pyopengl pyopengl-accelerate rencode \
    netifaces websocket-client websockify pillow
```
build xpra from source as per [wiki](../Build/README.md)


## displayfd workaround
Because of the Raspberry Pi's limited power, getting an answer from `displayfd` might take more than the ten seconds specified as the standard timeout. In order to change this, you can start xpra like this:
```shell
xpra start --env=XPRA_DISPLAY_FD_TIMEOUT=30 ...
```

Alternatively, always specify a display when use the `xpra start` subcommand.
