# Client OpenGL acceleration

The native Xpra client can use OpenGL to render forwarded windows efficiently.
This is a client-side feature: it is separate from the [OpenGL support for
applications running in an Xpra session](OpenGL.md).

## How it works

<div class="docs-grid" markdown="1">
<section class="docs-card" markdown="1">

### Automatic setup

Official packages include the required components and enable client OpenGL by
default where the native client supports it. At startup, Xpra probes the local
OpenGL implementation before enabling acceleration. The probe may take a few
seconds.

</section>

<section class="docs-card" markdown="1">

### Selective rendering

Xpra does not use OpenGL for every window. Small, short-lived, or rarely
updated windows are normally rendered without it because acceleration would
not provide a measurable benefit.

</section>

<section class="docs-card docs-card-wide" markdown="1">

### GPU-backed pixels

Window pixels are kept in GPU buffers, making repaints faster. Some updates,
including parts of the [video codec](Encodings.md) pipeline, can also be
processed directly on the GPU.

</section>
</div>

## Configure acceleration

The client checks OpenGL automatically. Override that decision with the
`opengl` option:

```shell
# Skip the safety probe and enable OpenGL
xpra attach --opengl=yes

# Disable client OpenGL completely
xpra attach --opengl=no
```

Use `opengl=yes` only when you understand the driver and have verified that it
is stable. If the native client is running on a Wayland display, client OpenGL
acceleration is not currently available.

## Inspect the driver

Open the **Features** pane in **Session Info** or check the client startup
output for basic driver information. For a detailed report, run:

```shell
xpra opengl
```

On Windows, the **OpenGL_check.exe** shortcut provides the same diagnostic
probe.

Xpra keeps a small list of drivers that are known to be unsafe or unsuitable;
see the [driver list](https://github.com/Xpra-org/xpra/blob/master/xpra/opengl/drivers.py)
for the current values. Software renderers such as `llvmpipe` are treated
differently from hardware drivers because they provide no GPU acceleration.

### Intel drivers

Intel hardware is not currently greylisted. Older Xpra releases did greylist
Intel drivers for a long period because of rendering glitches and crashes in
some driver versions. The historical reports remain useful when diagnosing an
older release or a particular legacy driver:

<details markdown="1">
<summary>Historical Intel driver reports</summary>

- [#1367](https://github.com/Xpra-org/xpra/issues/1367) enable more OpenGL chipsets
- [#1233](https://github.com/Xpra-org/xpra/issues/1233) whitelist more Intel chipsets
- [#1364](https://github.com/Xpra-org/xpra/issues/1364) random window painted solid white
- [#1469](https://github.com/Xpra-org/xpra/issues/1469) and [#1468](https://github.com/Xpra-org/xpra/issues/1468) window resizing problems
- [#1024](https://github.com/Xpra-org/xpra/issues/1024) `glTexParameteri` errors
- [#968](https://github.com/Xpra-org/xpra/issues/968) rendering dimensions
- [#809](https://github.com/Xpra-org/xpra/issues/809) rendering failures
</details>

## Further reading

- [Mesa driver documentation](https://docs.mesa3d.org/)
- [Mesa renderer coverage](https://mesamatrix.net/)
- [OpenGL wiki](https://www.opengl.org/wiki/Main_Page)
