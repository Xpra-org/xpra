# Server OpenGL acceleration

This page describes running OpenGL applications inside an Xpra session. It is
separate from [client-side OpenGL rendering](Client-OpenGL.md), which improves
how the native client paints forwarded windows.

OpenGL applications work by default, but a normal virtual framebuffer uses a
software renderer. To use a physical GPU, choose one of the display setups
below.

## Choose a display setup

<div class="docs-grid" markdown="1">
<section class="docs-card docs-card-wide" markdown="1">

### VirtualGL (recommended)

[VirtualGL](https://www.virtualgl.org/) intercepts the application’s OpenGL
calls and runs them on a real GPU while Xpra forwards the resulting frames.
Start an application through `vglrun`:

```shell
xpra seamless --start="vglrun glxgears"
```

Or apply it to every child command so Xpra can identify the GPU process:

```shell
xpra seamless --exec-wrapper="vglrun" --start="glxgears"
```

</section>

<section class="docs-card" markdown="1">

### WSL

On Windows, [WSL](WSL.md) can provide GPU-accelerated OpenGL through the WSLg
display stack. Follow the platform-specific setup in the WSL guide.

</section>

<section class="docs-card" markdown="1">

### Xwayland

An X11 application can use a GPU-backed Xwayland display. Start Xwayland on a
display provided by a Wayland compositor, then let Xpra use that display:

```shell
Xwayland :20 &
xpra seamless :20 --use-display=yes --start=glxgears
```

The compositor and Xwayland configuration are platform-specific.

</section>
</div>

## Use an existing display

If a GPU is already driving a desktop display, you can [shadow](Shadow.md) it.
This is convenient for accessing an existing session, but screen capture is
usually less efficient than a dedicated [seamless](Seamless.md) or
[desktop](Desktop.md) session.

Alternatively, let Xpra manage an existing X11 display directly:

```shell
xpra seamless :0 --use-display=yes --start=glxgears
```

The display is no longer available to the local desktop while Xpra owns it.

## Caveats

<div class="docs-grid" markdown="1">
<section class="docs-card" markdown="1">

### Driver libraries

Proprietary drivers can conflict with software OpenGL. The
[GLVND](https://github.com/NVIDIA/libglvnd) dispatch layer allows multiple
OpenGL implementations to coexist.

</section>

<section class="docs-card" markdown="1">

### Session lifetime

VirtualGL and Xwayland may tie an application to a secondary X11 or Wayland
context. If that server is restarted, the application can crash. VirtualGL 3's
EGL backend avoids this limitation in supported configurations.

</section>

<section class="docs-card docs-card-wide" markdown="1">

### Mesa software rendering

Most non-NVIDIA systems use [Mesa](https://www.mesa3d.org/). Its software
renderer is usually `llvmpipe`; this is useful for compatibility but does not
provide hardware acceleration. Mesa’s [environment variables](https://docs.mesa3d.org/envvars.html)
and [driver documentation](https://docs.mesa3d.org/) are useful when tuning or
diagnosing a setup.

</section>
</div>

See the [VirtualGL documentation](https://github.com/VirtualGL/virtualgl/tree/master/doc)
for installation, security, and application-specific workarounds.
