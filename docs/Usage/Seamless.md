# Seamless mode

Seamless mode is Xpra’s usual mode for forwarding individual applications. It
is started with `xpra seamless` (or the legacy alias `xpra start`). Each remote
window appears alongside the client’s local applications instead of inside a
single remote-desktop window.

## Why use seamless mode?

<div class="docs-grid" markdown="1">
<section class="docs-card" markdown="1">

### Native window management

The client’s operating system and window manager control each forwarded
window. Moving, minimizing, resizing, and switching windows therefore remain
responsive even when the connection has noticeable latency.

</section>

<section class="docs-card" markdown="1">

### No remote desktop canvas

Unlike [desktop](Desktop.md), [monitor](Desktop.md#monitor-mode), and
[shadow](Shadow.md) mode, seamless mode does not stream a complete desktop or
screen. There is no large remote desktop window to navigate, and applications
can be placed naturally across the client’s monitors.

</section>

<section class="docs-card docs-card-wide" markdown="1">

### Efficient, focused sessions

Only the windows and features you choose to forward are presented to the
client. This is usually easier to use and wastes less bandwidth than encoding
an entire desktop, especially when only a few applications are needed.

With the [HTML5 client](https://github.com/Xpra-org/xpra-html5), forwarded
windows remain inside the browser’s canvas; native desktop placement requires a
regular Xpra client.

</section>
</div>

## Display backends

The X11 backend is the default:

```shell
xpra seamless --backend=x11 --start=xterm
```

The newer Wayland backend can be selected explicitly:

```shell
xpra seamless --backend=wayland --start=xterm
```

The Wayland backend is experimental and may require the separate
`xpra-server-wayland` package. Use the X11 backend when you need the broadest
compatibility.

## Limitations

Seamless server sessions require a supported display environment and are not
available on Windows or macOS servers. On those platforms, use
[shadow mode](Shadow.md) to access an existing desktop or choose a different
session mode.

Some experiments attempt to shadow only selected applications or windows as an
approximation of seamless mode, but this is not reliable enough to recommend
as a general solution. See [issue #3476](https://github.com/Xpra-org/xpra/issues/3476)
for the current status.
