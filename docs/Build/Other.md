**This page may well be out of date**, as these platforms are [not officially supported](https://github.com/Xpra-org/xpra/wiki/Platforms).


# ![FreeBSD](../images/icons/freebsd.png)

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
* strongly recommended addons: `py37-PyOpenGL py37-PyOpenGL-accelerate`
* audio: `py37-gstreamer1 gstreamer1-plugins-flac gstreamer1-plugins-mad gstreamer1-plugins-ogg gstreamer1-plugins-opus gstreamer1-plugins-vorbis`


***

# Raspberry Pi OS

Follow https://github.com/Xpra-org/xpra/issues/3288#issuecomment-931851564


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
                libx264-dev libvpx-dev \
                xvfb xauth x11-xkb-utils \
                zlib1g zlib1g-dev liblzo2-2 liblzo2-dev
```
some system-supplied Python tools may just be too old, so get new ones directly from the world of Python:
```shell
apt-get install python-pip
pip install --upgrade pip
pip install lz4
```
to be able to use most of xpra's features, you may also want to install:
```shell
apt-get install python-netifaces dbus-x11 python-dbus \
    hicolor-icon-theme python-avahi python-numpy \
    gstreamer1.0-x gstreamer1.0-tools \
    python-pil python-lzo python-setuptools
```
build xpra from source as per [wiki](./README.md)

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
