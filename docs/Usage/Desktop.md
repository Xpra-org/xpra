# Remote desktop sessions

Use Xpra desktop mode when you want to use a complete remote Linux desktop,
rather than have each remote application appear as its own local window. The
remote desktop opens in one Xpra window and keeps running when you disconnect,
so you can reconnect later and carry on where you left off.

Desktop sessions need an X11-capable Linux or Unix server. If the desktop you
want to access is already running, use [shadow mode](Shadow.md) instead; it
also works with macOS and Windows servers.

## Choose what you want to do

<div class="docs-grid" markdown="1">
<section class="docs-card" markdown="1">

### Start a new remote desktop

Choose this when you want a separate, private desktop for remote work. Start
with [the quick start](#start-a-desktop) below.

</section>

<section class="docs-card" markdown="1">

### Reach a desktop already on screen

Choose [shadow mode](Shadow.md) when someone is already logged in at the
server and you need to view or control that same display.

</section>

<section class="docs-card" markdown="1">

### Run individual applications instead

Choose [seamless mode](Seamless.md) when you only need a few remote
applications and want their windows to mix with the windows on your computer.

</section>
</div>

## Start a desktop

You need to start an Xpra server on the remote computer, then connect to it
from your own computer. The easiest way to do both is over SSH:

```shell
xpra desktop --start-child=fluxbox ssh://USER@HOST/
```

Replace `USER` and `HOST` with your login name and the server name. `fluxbox`
is a small desktop window manager used as an example; replace it with the
command that starts the desktop environment installed on your server.

When you close the Xpra client window or choose **Disconnect**, the remote
desktop continues to run. Connect again with:

```shell
xpra attach ssh://USER@HOST/
```

If you prefer not to type commands, open **Xpra** from your application menu,
choose **Start**, then choose a desktop session. The graphical tool can start
a session on this computer or a remote host.

<details markdown="1">
<summary>Start the server and connect in separate steps</summary>

On the server, start a desktop session on a free display. `:100` is an example
display number:

```shell
xpra desktop :100 --start-child=fluxbox
```

Then, on your own computer, connect to it:

```shell
xpra attach ssh://USER@HOST/100
```

If the client is on the same machine and uses the same account, use:

```shell
xpra attach :100
```
</details>

## Pick the desktop style

For most people, `desktop` is the right choice. It creates one remote screen
and shows it in an Xpra window, much like a traditional remote-desktop tool.

If you regularly use several monitors, `monitor` can make the remote session
follow your local monitor layout. It needs additional server support, so start
with normal desktop mode unless you specifically need this behaviour.

<details markdown="1">
<summary>Use multiple monitors</summary>

On a server with [Xdummy](Xdummy.md) support, start the session with:

```shell
xpra monitor --start-child=fluxbox ssh://USER@HOST/
```

Monitor mode exposes a virtual monitor for each of the client’s displays and
updates the layout as it changes. It is unavailable with the simpler Xvfb
backend; see [Xdummy](Xdummy.md) for platform and package requirements.
</details>

## Things to know

- Use the desktop environment or window manager you already have installed.
  More elaborate desktops usually use more bandwidth and can feel slower over
  a constrained connection.
- A desktop session is separate from the computer’s physical display. To share
  that existing display, use [shadow mode](Shadow.md).
- Ensure that shutdown and reboot choices shown inside the remote desktop are
  appropriate for the server you are using.

<details markdown="1">
<summary>Compatibility, size, and session lifetime</summary>

Desktop and monitor servers require an X11 server and are not available on
macOS or Windows servers. You can attach with an Xpra client; a desktop
session can also accept a VNC client when VNC support is enabled.

The initial desktop size comes from the `xvfb` backend. Set it explicitly when
needed:

```shell
xpra desktop --resize-display="1024x768" --start-child=fluxbox
```

You can later resize the virtual screen with normal X11 tools such as
`xrandr`. Monitor mode instead uses the client’s monitor geometry; configure
the Xdummy virtual size for the largest combined layout you expect.

To end a session automatically when its window manager exits, use
`--start-child` with `--exit-with-children`. Otherwise, the session remains
available after its client disconnects.
</details>

## Next steps

- [Connect to and configure Xpra clients](Client.md)
- [Forward audio, clipboard, printers, and other features](../Features/README.md)
- [Use SSH or another connection method](../Network/README.md)
