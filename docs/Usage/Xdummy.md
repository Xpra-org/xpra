# ![X11](../images/icons/X11.png) Xdummy

`Xdummy` is used with [seamless](Seamless.md) and [desktop](Desktop.md) servers sessions on [posix platforms](https://github.com/Xpra-org/xpra/wiki/Platforms).

`Xdummy` was originally developed by Karl Runge as a [script](http://www.karlrunge.com/x11vnc/Xdummy) to allow a standard X11 server to be used by non-root users with the [dummy video driver](https://github.com/Xpra-org/xf86-video-dummy)

Since then, the X11 server gained the ability to run without those `LD_SO_PRELOAD` hacks and this is now available for most distributions.


## Why use `Xdummy` instead of `Xvfb`?

`Xvfb` lacks the ability to simulate arbitrary [DPI](../Features/DPI.md) values and add or remove virtual monitors at runtime. \
This affects some X11 application's geometry and font rendering, and prevents the use of the `monitor` subcommand.

## Usage
<details>
  <summary>Xdummy standalone</summary>

You can start a new display using the dummy driver without needing any special privileges (no root, no suid), you should specify your own log and config files:
```shell
Xorg -noreset +extension GLX +extension RANDR +extension RENDER \
     -logfile ./10.log -config /etc/xpra/xorg.conf :10
```
This is roughly equivallent to running `Xvfb :10`. \
You can find a sample configuration file for dummy here: [xorg.conf](https://github.com/Xpra-org/xpra/tree/master/fs/etc/xpra/xorg.conf).

With distributions that have `Xdummy` support and xpra version 6.3 or later, you can also just run:
```shell
xpra xvfb :10
```
Starting with version 6.3, you can configure xpra to use Xdummy as `xvfb` command using the GUI command `xpra configure vfb`. \
Or from the command line using `xpra set xvfb Xdummy`.
</details>
<details>
  <summary>Xdummy with Xpra</summary>

With the official Xpra packages, `Xdummy` should have been configured automatically for you when installing -  but this is not enabled on Debian or Ubuntu due to distribution bugs. \
You can choose at [build time](../Build/README.md) whether or not to use `Xdummy` using the `--with[out]-Xdummy` build switch. \
If your packages do not enable `Xdummy` by default,
you may still be able to [change your settings at runtime](https://github.com/Xpra-org/xpra/issues/4456#issuecomment-2572596302).
</details>


## Configuration

By default, the configuration file shipped with xpra allocates 768MB of memory, and a maximum `virtual size` of `11520 6318`. \
You may want to increase these values to use very high resolutions or many virtual monitors.

## Packaging

### versions required

Most recent distributions now ship compatible packages:
* `Xorg` version 1.12 or later
* `dummy` driver version 0.3.5 or later

Starting with dummy version 0.4.0, only one optional patch is added to the version found in the xpra repositories: https://github.com/Xpra-org/xpra/blob/master/packaging/rpm/patches/0006-Dummy-Disconnect.patch

### Other issues

<details>
  <summary>libGL Driver Conflicts</summary>

With older distributions that do not use [libglvnd](https://github.com/NVIDIA/libglvnd), proprietary drivers usually install their own copy of `libGL` which conflicts with the use of software OpenGL rendering. You cannot use this GL library to render directly on `Xdummy` (or `Xvfb`).

The best way to deal with this is to use [VirtualGL](http://www.virtualgl.org/) to take advantage of the `OpenGL` acceleration provided by the graphics card, just run: `vglrun yourapplication`.

To make `vglrun` work properly with Nvidia proprietary drivers make sure to create `/etc/X11/xorg.conf` using `sudo nvidia-xconfig`.

The alternative is often to disable `OpenGL` altogether, more information here: [#580](https://github.com/Xpra-org/xpra/issues/580)
</details>

<details>
  <summary>Debian and Ubuntu</summary>

Debian and Ubuntu do weird things with their Xorg server which prevents it from running Xdummy (tty permission issues). \
Warning: this may also interfere with other sessions running on the same server when they should be completely isolated from each other. \
[Crashing other X11 sessions](https://github.com/Xpra-org/xpra/issues/2834) is a serious security issue, caused by Debian's packaging and still left unsolved after many years.

</details>

<details>
  <summary>non-suid binary</summary>

If you distribution ships the newer version but only installs a suid Xorg binary, Xpra should have installed the [xpra_Xdummy](https://github.com/Xpra-org/xpra/tree/master/fs/bin/xpra_Xdummy) wrapper script and configured xpra.conf to use it instead of the regular Xorg binary.

This script executes `Xorg` via `ld-linux.so`, which takes care of stripping the suid bit. \
Some more exotic distributions have issues with non world-readable binaries which prevent this from working.
</details>
