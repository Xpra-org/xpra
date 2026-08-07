# Xdummy

`Xdummy` is an X11 server backend for Xpra’s [seamless](Seamless.md),
[desktop](Desktop.md), and [monitor](Desktop.md#monitor-mode) servers on
[POSIX platforms](https://github.com/Xpra-org/xpra/wiki/Platforms).

It was originally developed by Karl Runge as a
[script](http://www.karlrunge.com/x11vnc/Xdummy) that lets a standard X11
server run as a non-root user with the
[dummy video driver](https://github.com/Xpra-org/xf86-video-dummy). Modern X11
servers can do this without the original `LD_SO_PRELOAD` hacks, and most
distributions now provide the required support.

<div class="docs-section-heading" markdown="1">

## Why use Xdummy instead of Xvfb?

Xdummy provides the display features needed for high-DPI and multi-monitor
desktop sessions.

</div>

<div class="docs-grid" markdown="1">
<section class="docs-card" markdown="1">

### Arbitrary DPI

`Xvfb` cannot simulate arbitrary [DPI](../Features/DPI.md) values. This can
affect application geometry and font rendering.

</section>

<section class="docs-card" markdown="1">

### Dynamic monitors

Xdummy can add or remove virtual monitors at runtime. This is required by
[monitor mode](Desktop.md#monitor-mode), the multi-monitor version of desktop
mode.

</section>
</div>

<div class="docs-section-heading" markdown="1">

## Usage

Use Xdummy directly for a standalone display, or configure Xpra to use it as
the `xvfb` backend.

</div>

<div class="docs-grid" markdown="1">
<section class="docs-card docs-card-wide" markdown="1">

### Run Xdummy standalone

Start a display with the dummy driver without root or setuid privileges. Use
your own log and configuration files:

```shell
Xorg -noreset +extension GLX +extension RANDR +extension RENDER \
     -logfile ./10.log -config /etc/xpra/xorg.conf :10
```

This is roughly equivalent to `Xvfb :10`. A sample dummy configuration is
available as [xorg.conf](https://github.com/Xpra-org/xpra/tree/master/fs/etc/xpra/xorg.conf).

</section>

<section class="docs-card" markdown="1">

### Start an Xdummy display through Xpra

With a distribution that supports Xdummy and Xpra 6.3 or later:

```shell
xpra xvfb :10
```

</section>

<section class="docs-card" markdown="1">

### Select Xdummy as the Xpra backend

Since Xpra 6.3, configure this through the GUI with `xpra configure vfb`, or
from the command line:

```shell
xpra set xvfb Xdummy
```

</section>

<section class="docs-card docs-card-wide" markdown="1">

### Xdummy with Xpra packages

Official Xpra packages normally configure Xdummy automatically. Debian and
Ubuntu do not enable it by default because of distribution bugs.

At [build time](../Build/README.md), select Xdummy with the
`--with-Xdummy` or `--without-Xdummy` build switch. If a package does not
enable it, you may still be able to [change the setting at runtime](https://github.com/Xpra-org/xpra/issues/4456#issuecomment-2572596302).

</section>
</div>

<div class="docs-section-heading" markdown="1">

## Configuration

The shipped configuration allocates 768 MB of memory and a maximum `virtual
size` of `11520 6318`. Increase these values when using very high resolutions
or many virtual monitors.

</div>

<div class="docs-grid" markdown="1">
<section class="docs-card docs-card-wide" markdown="1">

### Sizing `VideoRam`

The `VideoRam` value in `xorg.conf` (in kB) caps the dummy driver’s framebuffer
pool. Three things share that pool:

1. **Virtual root-window back buffer.** It is sized by the active `Display`
   subsection—the one matching `DefaultDepth` at startup, not all `Display`
   subsections combined. The cost is roughly `Virtual.w × Virtual.h ×
   bytes_per_pixel`. With `DefaultDepth 24` and `Virtual 11520×6318`, that is
   about 218 MB; depth 30 is about 292 MB and depth 16 about 146 MB. A
   `Virtual 16384 16384` display would exceed 1 GB at 24 bpp.
2. **Drawable buffers and pixmaps from client X11 applications.** This is
   application-dependent and often the second-largest contributor. Software
   OpenGL apps using Mesa’s `llvmpipe` can allocate very large pixmaps;
   `vglrun` avoids this by routing GL through the host GPU. See [OpenGL](OpenGL.md)
   and the [Memory](Memory.md#virtualgl--vglrun) guide.
3. **Cursor and offscreen buffers.** These are small.

</section>

<section class="docs-card docs-card-wide" markdown="1">

### Practical reductions

Reduce memory use in this order:

- **Lower `Virtual`** to match the largest client display. A `Virtual 3840×2160`
  configuration uses about 32 MB of back-buffer instead of about 218 MB at
  depth 24, and pixmap allocations scale with the same dimensions.
- **Use `vglrun`** for OpenGL applications to keep their backing buffers off
  Xdummy.
- **Do not expand `VideoRam` further than necessary.** The default 768 MB is a
  generous ceiling for a single 24-bit `11520×6318` back buffer and a healthy
  pixmap pool. Smaller setups, such as a `1920×1080` desktop, work at 192 MB.

</section>

<section class="docs-card" markdown="1">

### Display subsections

Removing unused `Display` subsections for depths 8, 16, or 30 does not save
framebuffer memory. Only the subsection matching `DefaultDepth` is active; the
others are configuration for starting Xorg at a different depth.

</section>

<section class="docs-card" markdown="1">

### Verify memory usage

See [Memory.md](Memory.md) for measured RSS deltas and how to read the
`display.memory.*` keys from `xpra info`.

</section>

<section class="docs-card docs-card-wide" markdown="1">

### History

The current defaults come from several sizing rounds documented in the
[CHANGELOG](../CHANGELOG.md): increased default dummy-driver memory, reduced
Xdummy memory usage through lower maximum resolutions, and fixes for the X11
server pixmap memory leak.

</section>
</div>

<div class="docs-section-heading" markdown="1">

## Packaging

Most recent distributions ship compatible Xorg and dummy-driver packages.

</div>

<div class="docs-grid" markdown="1">
<section class="docs-card" markdown="1">

### Required versions

- `Xorg` 1.12 or later
- `dummy` driver 0.3.5 or later

</section>

<section class="docs-card docs-card-wide" markdown="1">

### Optional dummy-driver patch

Since dummy driver 0.4.0, Xpra adds one optional patch to the version found in
the Xpra repositories:

[0006-Dummy-Disconnect.patch](https://github.com/Xpra-org/xpra/blob/master/packaging/rpm/patches/0006-Dummy-Disconnect.patch)

</section>
</div>

<div class="docs-section-heading" markdown="1">

## Other issues

These platform and graphics-driver issues can prevent Xdummy from starting or
can affect OpenGL applications.

</div>

<div class="docs-grid" markdown="1">
<section class="docs-card" markdown="1">

### libGL driver conflicts

Older distributions without [libglvnd](https://github.com/NVIDIA/libglvnd)
often install a proprietary `libGL` that conflicts with software OpenGL on
Xdummy or Xvfb. Use [VirtualGL](http://www.virtualgl.org/) and run
`vglrun yourapplication` to use the graphics card. With Nvidia drivers, create
`/etc/X11/xorg.conf` with `sudo nvidia-xconfig`.

Alternatively, disable OpenGL; see [#580](https://github.com/Xpra-org/xpra/issues/580).

</section>

<section class="docs-card" markdown="1">

### Debian and Ubuntu

Their Xorg packaging can prevent Xdummy from running because of TTY permission
issues. It may also interfere with other sessions that should be isolated;
[crashing other X11 sessions](https://github.com/Xpra-org/xpra/issues/2834) is a
serious security issue.

</section>

<section class="docs-card docs-card-wide" markdown="1">

### Non-setuid Xorg binary

If your distribution ships a newer Xorg but only installs a setuid binary, Xpra
should install the [xpra_Xdummy wrapper](https://github.com/Xpra-org/xpra/tree/master/fs/bin/xpra_Xdummy)
and configure `xpra.conf` to use it. The wrapper executes Xorg through
`ld-linux.so` to strip the setuid bit. Some distributions have issues with
non-world-readable binaries that prevent this from working.

</section>
</div>
