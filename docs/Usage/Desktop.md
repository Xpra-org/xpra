# Desktop Mode

Desktop mode forwards a complete desktop session in a window, instead of
forwarding each application window separately as in [seamless mode](Seamless.md).
It requires an X11 server on the Xpra server and is not available on macOS or
Windows servers.

<div class="docs-section-heading" markdown="1">

## Choose a desktop mode

Use desktop mode for one virtual screen, or monitor mode when the client has
multiple displays and the server supports [Xdummy](Xdummy.md).

</div>

<div class="docs-grid" markdown="1">
<section class="docs-card" markdown="1">

### Desktop mode

`desktop` runs a full desktop environment in one virtual screen. Its behaviour
is similar to VNC, with the additional benefits of the Xpra protocol, including
audio and printer forwarding. See the [forwarded features](../Features/README.md).

You can also connect to a desktop session with a VNC client.

</section>

<section class="docs-card" markdown="1">

### Monitor mode

`monitor` is an improved version of `desktop` for multi-monitor clients. It
mirrors the client’s monitor layout and can expose a separate virtual monitor
for each client display, rather than placing the whole desktop in one window.

Monitor mode is supported only on server platforms where [Xdummy](Xdummy.md)
is available. It is not supported with the simpler Xvfb backend. See the
[Xdummy guide](Xdummy.md) for platform and package requirements.

</section>

<section class="docs-card docs-card-wide" markdown="1">

### Shadowing an existing desktop

To access an existing desktop session, use the [shadow server](Shadow.md).
Shadow mode is also available on macOS and Windows, where X11 desktop and
monitor servers are not.

</section>
</div>

<div class="docs-section-heading" markdown="1">

## Start a session

Start the server first, then connect from an Xpra client or a compatible VNC
client.

</div>

<div class="docs-grid" markdown="1">
<section class="docs-card" markdown="1">

### Desktop mode

```shell
xpra desktop --start=xterm
```

Then connect as usual from the client, or with a VNC client.

</section>

<section class="docs-card" markdown="1">

### Monitor mode

On a server with Xdummy support, start the multi-monitor session with:

```shell
xpra monitor --start=xterm
```

Attach from an Xpra client as usual. The server follows the client’s monitor
layout as it changes.

</section>

<section class="docs-card docs-card-wide" markdown="1">

### Start and connect in one command

Use the SSH syntax from the client when you want to start and attach in one
step:

```shell
xpra desktop --start=xterm ssh://USER@HOST/
```

Replace `desktop` with `monitor` when the server supports Xdummy and you want
multi-monitor mode.

</section>
</div>

<div class="docs-section-heading" markdown="1">

## Run a window manager or desktop environment

Replace the example application with the command that starts the window manager
or desktop environment of your choice.

</div>

<div class="docs-grid" markdown="1">
<section class="docs-card docs-card-wide" markdown="1">

### Example: Fluxbox

```shell
xpra desktop --start=fluxbox
```

The same `--start` option works with `monitor`. More featureful window
managers and desktop environments tend to use more bandwidth and may appear to
run more slowly.

</section>
</div>

<div class="docs-section-heading" markdown="1">

## Desktop size

The initial desktop size comes from the default resolution of the `xvfb`
backend. Resize the virtual screen at any time with regular X11 tools such as
`xrandr`.

</div>

<div class="docs-grid" markdown="1">
<section class="docs-card" markdown="1">

### Set the initial size

```shell
xpra desktop --resize-display="1024x768" --start=fluxbox
```

</section>

<section class="docs-card" markdown="1">

### Monitor mode sizing

Monitor mode uses the client’s monitor geometry. Configure the Xdummy virtual
size large enough for the maximum combined monitor layout; see the
[Xdummy configuration guide](Xdummy.md).

</section>
</div>

<div class="docs-section-heading" markdown="1">

## Caveats

</div>

<div class="docs-grid" markdown="1">
<section class="docs-card" markdown="1">

### End the session with the window manager

Use `--start-child` together with `--exit-with-children` if the session should
terminate when the window manager exits.

</section>

<section class="docs-card" markdown="1">

### Shutdown actions

Some desktop environments show options to shut down or reboot the system from
their start menu. Decide whether those actions are appropriate for the server.

</section>
</div>
