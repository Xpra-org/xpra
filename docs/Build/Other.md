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
Other packages you will need for:
* running it: `xauth xkbcomp xkeyboard-config`
* building / downloading the source: `gcc cython subversion pkgconf`
* X11 libraries: `libXrandr libXtst libXcomposite libXdamage`
* GTK: `gobject-introspection gtk3`
* strongly recommended addons: `py311-PyOpenGL py311-PyOpenGL-accelerate`
* audio: `py311-gstreamer1 gstreamer1-plugins-flac gstreamer1-plugins-mad gstreamer1-plugins-ogg gstreamer1-plugins-opus gstreamer1-plugins-vorbis`


***

# Raspberry Pi OS

Follow https://github.com/Xpra-org/xpra/issues/3288#issuecomment-931851564

## displayfd workaround
Because of the Raspberry Pi's limited power, getting an answer from `displayfd` might take more than the ten seconds specified as the standard timeout. In order to change this, you can start xpra like this:
```shell
xpra start --env=XPRA_DISPLAY_FD_TIMEOUT=30 ...
```

Alternatively, always specify a display when use the `xpra start` subcommand.
