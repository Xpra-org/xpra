# Run remote applications alongside your local ones

Seamless mode is Xpra’s usual way to run an application on another computer
while using it as if it were local. Each remote application gets its own window
on your desktop: you can move, resize, minimize, and switch to it alongside
your local applications.

Choose [desktop mode](Desktop.md) if you want a complete remote desktop in one
window. Choose [shadow mode](Shadow.md) if you need to see or control a desktop
that is already running.

## Start an application

If you can log in to the remote computer with SSH, this command starts an
application there and displays it on your computer:

```shell
xpra seamless ssh://USER@HOST/ --start-child=xterm
```

Replace `USER` and `HOST` with your login name and the server name. Replace
`xterm` with the graphical application you want to run, such as `firefox` or
`gedit`.

The application window should appear on your desktop. You can disconnect and
later reconnect without stopping the remote application:

```shell
xpra attach ssh://USER@HOST/
```

The display part of the address can be omitted when that account has only one
active Xpra session. See [SSH connections](../Network/SSH.md) for more ways to
connect.

If you prefer a graphical tool, open **Xpra** from your application menu,
choose **Start**, then choose a seamless application session.

<details markdown="1">
<summary>Start the server and connect in separate steps</summary>

On the remote computer, start an Xpra server on a free display. `:100` is an
example display number:

```shell
xpra seamless :100 --start-child=xterm
```

Then, on your computer, attach to that session:

```shell
xpra attach ssh://USER@HOST/100
```

If both client and server run under the same account on the same machine, use:

```shell
xpra attach :100
```
</details>

## Why choose seamless mode?

<div class="docs-grid" markdown="1">
<section class="docs-card" markdown="1">

### It fits your desktop

Remote windows are managed by your local operating system and window manager.
Place them across your monitors, switch between them normally, and use them
alongside local applications.

</section>

<section class="docs-card" markdown="1">

### It sends only what you need

Xpra forwards the applications you choose instead of capturing a whole remote
screen. This is often more comfortable and uses less bandwidth than a complete
remote desktop when you only need a few applications.

</section>

<section class="docs-card" markdown="1">

### Your session survives disconnection

The applications keep running on the server after you disconnect, so you can
return to the same work later. Use [session features](../Features/README.md)
to forward clipboard contents, audio, printers, and more.

</section>
</div>

## Things to know

- Seamless server sessions require a supported display environment and are not
  available on macOS or Windows servers. On those systems, [shadow mode](Shadow.md)
  can share an existing desktop.
- In the [HTML5 client](https://github.com/Xpra-org/xpra-html5), remote windows
  stay inside the browser page. Use a regular Xpra client when you want them to
  behave as native windows on your desktop.

<details markdown="1">
<summary>Choose or troubleshoot a display backend</summary>

The X11 backend is the default and offers the broadest compatibility:

```shell
xpra seamless --backend=x11 --start-child=xterm
```

The newer Wayland backend can be selected explicitly:

```shell
xpra seamless --backend=wayland --start-child=weston-terminal
```

The Wayland backend is experimental and may require the separate
`xpra-server-wayland` package. Use the X11 backend unless you need Wayland
specifically.

Some experiments can shadow only selected applications or windows as an
approximation of seamless mode. They are not reliable enough to recommend for
general use; see [issue #3476](https://github.com/Xpra-org/xpra/issues/3476)
for the current status.
</details>

## Next steps

- [Connect to and configure Xpra clients](Client.md)
- [Forward desktop integration features](../Features/README.md)
- [Use SSH or another connection method](../Network/README.md)
