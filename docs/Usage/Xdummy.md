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

### Sizing `VideoRam`

The `VideoRam` value in `xorg.conf` (in kB) caps the dummy driver's
framebuffer pool. Three things share that pool:

1. **Virtual root-window back buffer.** Sized by the active
   `Display` subsection — i.e. the one matching the server's
   `DefaultDepth` at startup, *not* all `Display` subsections summed.
   The cost is roughly `Virtual.w × Virtual.h × bytes_per_pixel`. With
   the shipped `DefaultDepth 24` and `Virtual 11520×6318`, that's
   about 218 MB. Switching to depth 30 makes it ~292 MB; depth 16,
   ~146 MB. Bumping `Virtual` to `16384×16384` would push it past
   1 GB at 24 bpp, which is why the commented-out
   `Virtual 16384 16384` is annotated *"requires more ram"* in the
   shipped config.
2. **Drawable buffers / pixmaps allocated by client X11 apps.** This
   is highly app-dependent and is the second biggest contributor in
   practice. Software-OpenGL apps (Mesa's `llvmpipe` running under
   Xdummy) allocate **very large** pixmaps here — `vglrun`
   short-circuits this by routing GL through the host GPU instead.
   See [OpenGL](OpenGL.md) and the
   [Memory](Memory.md#virtualgl--vglrun) doc for measured impact.
3. **Cursor and offscreen buffers.** Small.

Practical reductions, in order of impact:

- **Lower `Virtual`** to match your largest client display. A
  `Virtual 3840×2160` configuration uses ~32 MB of back-buffer
  instead of ~218 MB at depth 24 — and pixmap allocations scale with
  the same dimensions.
- **Use `vglrun`** for OpenGL applications to keep their backing
  buffers off Xdummy entirely.
- **Don't expand `VideoRam` further than you need.** The default
  768 MB is a generous ceiling for a single 24-bit `11520×6318`
  back buffer plus a healthy pixmap pool; smaller setups (e.g. a
  single `1920×1080` desktop) work fine at 192 MB.

> Note: *removing* unused `Display` subsections (depths 8, 16, 30) is
> sometimes suggested as a memory optimization. It isn't: only the
> subsection matching `DefaultDepth` is active, and the others sit
> there as configuration in case you start Xorg at a different depth.
> They do not consume framebuffer memory.

See [Memory.md](Memory.md) for measured RSS deltas and how to read
the `display.memory.*` keys from `xpra info` to verify your tuning.

### History

The current defaults are the result of several sizing rounds — see the
[CHANGELOG](../CHANGELOG.md) entries:
*"increased default memory allocation of the dummy driver"*,
*"reduce Xdummy memory usage by limiting to lower maximum resolutions"*,
and *"fix x11 server pixmap memory leak"*.

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
