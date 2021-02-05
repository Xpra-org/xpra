![X11](https://xpra.org/icons/X11.png)

`Xdummy` is used with [seamless](./Seamless.md) servers on [posix platforms](https://github.com/Xpra-org/xpra/wiki/Platforms).

`Xdummy` was originally developed by Karl Runge as a [script](http://www.karlrunge.com/x11vnc/Xdummy) to allow a standard X11 server to be used by non-root users with the [dummy video driver](https://github.com/Xpra-org/xf86-video-dummy)

Since then, the X11 server gained the ability to run without those `LD_SO_PRELOAD` hacks and this is now available for most distributions.


# Why use `Xdummy` instead of `Xvfb`?

The only feature that `Xvfb` currently lacks is the ability to simulate arbitrary [DPI](../Features/DPI.md) values, this is accomplished using custom patches which are not available with the default dummy driver builds from any distribution.

This is only an issue with applications that bypass the various ways they're supposed to retrieve the DPI preferences.

The downside of using `Xdummy` is its incomplete `RandR` support: the resolutions have to be pre-defined before starting the virtual display, whereas `Xvfb` now supports adding new resolutions at runtime. Therefore, Xvfb provides better screen resolution matching.


# Usage
## Xdummy standlone
You can start a new display using the dummy driver without needing any special privileges (no root, no suid), you should specify your own log and config files:

    Xorg -noreset +extension GLX +extension RANDR +extension RENDER \
         -logfile ./10.log -config /etc/xpra/xorg.conf :10

You can find a sample configuration file for dummy here: [xorg.conf](../blob/master/etc/xpra/xorg.conf).
It contains many of the most common resolutions you are likely to need, including those found on phones and tablets. 
However if your client uses unusual resolutions, for instance multiple screens of differing sizes, you may want to add new `Modelines` to match your specific resolution.

## Xdummy with Xpra
With Xpra, this should have been configured automatically for you when installing.
You choose at [build time](./Building) whether or not to use `Xdummy` using the `--with[out]-Xdummy` build switch.

You can also specify this virtual framebuffer alternative using the `--xvfb` command line switch or by setting the xvfb option in your `/etc/xpra/xpra.conf` config file:

    xvfb=Xorg -dpi 96 -noreset -nolisten tcp \
              +extension GLX +extension RANDR +extension RENDER \
              -logfile ${HOME}/.xpra/Xvfb-10.log -config ${HOME}/xorg.conf

The `-noreset` option is only needed if the window manager is not the first application started on the display, for example if you use the `--start-child=` option, or if you want the display to survive once the window manager exits - generally, this is a good idea since xpra could crash and when it exits cleanly via `xpra stop` it already takes care of shutting down the X11 server.

## libGL Driver Conflicts
With older distributions that do not use [libglvnd](https://github.com/NVIDIA/libglvnd), proprietary drivers usually install their own copy of `libGL` which conflicts with the use of software OpenGL rendering. You cannot use this GL library to render directly on `Xdummy` (or `Xvfb`).

The best way to deal with this is to use [VirtualGL](http://www.virtualgl.org/) to take advantage of the `OpenGL` acceleration provided by the graphics card, just run: `vglrun yourapplication`.

To make `vglrun` work properly with Nvidia proprietary drivers make sure to create `/etc/X11/xorg.conf` using `sudo nvidia-xconfig`.

The alternative is often to disable `OpenGL` altogether. (more information here: [#580](https://github.com/Xpra-org/xpra/issues/580)


# Configuration

## Defaults
By default the configuration file shipped with xpra allocates 768MB of memory and defines a large number of common screen resolutions, including common sizes for double and triple display setups.

## Modelines
Since it is impossible to pre-define all the combinations possible, if your client resolution does not match one of the pre-defined values, you may want to add this resolution to the configuration file.

Use a modeline calculator like [xtiming.sf.net](http://xtiming.sourceforge.net/cgi-bin/xtiming.pl) or using a command line utility like [gtf](http://gtf.sourceforge.net/) or [cvt](http://www.uruk.org/~erich/projects/cvt/) and add the new modeline to the X11 server config (usually located in `/etc/xpra/xorg.conf` with xpra)

The only restriction on modelines is the pixel clock defined for the dummy driver and monitor: at higher resolution, you may need to lower the vertical refresh rate to ensure the mode remains valid.
If your new resolution does not get used, check the X11 server log file (usually in `~/.xpra/Xorg.$DISPLAY.log` with xpra)

## Large Screens
If you have an unusually large display configuration (multiple monitors), you may also need to increase the memory and/or increase the "virtual size".


## Versions Required
Most recent distributions now ship compatible packages: Xorg version 1.12 or later, dummy driver version 0.3.5 or later; though some may have issues with non world-readable binaries (see below)

## Patches
* [Constant-DPI](../blob/master/packaging/rpm/0002-Constant-DPI.patch)
* [pointer-limits](../blob/master/packaging/rpm/0003-fix-pointer-limits.patch) to fix unresponsive clicks after resizing up - see [#349](https://github.com/Xpra-org/xpra/issues/349)

The dummy packages in the xpra repositories include those patches.


## Ubuntu
Ubuntu does weird things with their Xorg server which prevents it from running Xdummy (tty permission issues).

Status: at time of writing, Xdummy can be used with 18.04 but not with earlier versions.

Then there are also ABI problems with their HWE releases, which is why Xdummy is not used by default on Ubuntu.


## non-suid binary
If you distribution ships the newer version but only installs a suid Xorg binary, Xpra should have installed the [../blob/master/scripts/xpra_Xdummy xpra_Xdummy] wrapper script and configured xpra.conf to use it instead of the regular Xorg binary. 

This script executes `Xorg` via `ld-linux.so`, which takes care of stripping the suid bit.
