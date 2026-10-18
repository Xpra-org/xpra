# Other build platforms

**This page may well be out of date**, as these platforms are [not officially supported](https://github.com/Xpra-org/xpra/wiki/Platforms).


<div class="docs-section-heading" markdown="1">

## OpenBSD

</div>
Xpra builds and runs on OpenBSD 7.9 with the X11 server and tools from the base system.

Install the build and runtime dependencies:
```shell
doas pkg_add py3-setuptools py3-cython py3-gobject3 py3-cairo py3-numpy \
  py3-Pillow py3-lz4 py3-brotli py3-cryptography py3-dbus py3-yaml \
  py3-rencode py3-gstreamer1 py3-opengl xxhash x264 libvpx libwebp \
  libavif libde265 openh264 dav1d aom libqrencode zstd libnotify gtk+3
```

Build and install:
```shell
git clone https://github.com/Xpra-org/xpra
cd xpra
python3 setup.py build --without-nvidia --without-printing
doas python3 setup.py install --prefix=/usr/local
```

`Xvfb`, `xauth` and `xkbcomp` are part of the base system in `/usr/X11R6/bin`.
Xdummy is not supported on OpenBSD, so Xpra uses `Xvfb` for virtual displays.

When `XDG_RUNTIME_DIR` is not set, Xpra uses `~/.xpra` for its sockets
(the default on OpenBSD). Install `xdg-utils` for `xpra open` support.

<div class="docs-section-heading" markdown="1">

## [FreeBSD Ports](https://www.freebsd.org/ports/)

</div>
To install xpra using ports, just run:
```shell
cd /usr/ports/x11/xpra
make install clean
```

<div class="docs-section-heading" markdown="1">

## Compiling on FreeBSD

</div>
_These instructions are incomplete and outdated - feel free to update them!_

The Xvfb tool can be found in the package: `xorg-vfbserver` (not obvious!)
Other packages you will need for:
* running it: `xauth xkbcomp xkeyboard-config`
* building / downloading the source: `gcc cython subversion pkgconf`
* X11 libraries: `libXrandr libXtst libXcomposite libXdamage`
* GTK: `gobject-introspection gtk3`
* strongly recommended addons: `py311-PyOpenGL py311-PyOpenGL-accelerate`
* audio: `py311-gstreamer1 gstreamer1-plugins-flac gstreamer1-plugins-mad gstreamer1-plugins-ogg gstreamer1-plugins-opus gstreamer1-plugins-vorbis`


***

<div class="docs-section-heading" markdown="1">

## Raspberry Pi OS

</div>

Follow https://github.com/Xpra-org/xpra/issues/3288#issuecomment-931851564

<div class="docs-section-heading" markdown="1">

## displayfd workaround

</div>
Because of the Raspberry Pi's limited power, getting an answer from `displayfd` might take more than the ten seconds specified as the standard timeout. In order to change this, you can start xpra like this:
```shell
xpra seamless --env=XPRA_DISPLAY_FD_TIMEOUT=30 ...
```

Alternatively, always specify a display when use the `xpra seamless` subcommand.
