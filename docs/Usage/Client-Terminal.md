# Terminal client

The terminal client is a backend of the native [Xpra client](./Client.md) that draws forwarded
windows inside a terminal emulator instead of on a desktop. Window contents are sent to the
terminal as images using the [kitty graphics protocol](https://sw.kovidgoyal.net/kitty/graphics-protocol/),
keyboard input is read with the kitty keyboard protocol, and the pointer is read from SGR pixel
mouse reports.

It needs no display server, no GTK and no OpenGL on the client side, so it works over a plain
`ssh` login as long as the terminal emulator at the other end of that login speaks the graphics
protocol.

<div class="docs-section-heading" markdown="1">

## Requirements

</div>

* a terminal emulator implementing the kitty graphics protocol:
  [kitty](https://sw.kovidgoyal.net/kitty/), [Ghostty](https://ghostty.org/),
  [WezTerm](https://wezterm.org/) or [Konsole](https://konsole.kde.org/)
* a terminal reporting its size in pixels (`TIOCGWINSZ`), which all of the above do
* the client built with `--with-terminal_client` (the default, the rpm and debian packages ship it)

At startup the client asks the terminal whether it understands the graphics protocol. If no
answer arrives, the session is aborted with an error rather than filling the terminal with
escape sequences.

<div class="docs-section-heading" markdown="1">

## Usage

</div>

```shell
xpra attach ssh://host/100 --backend=terminal
```

`xpra attach --backend=help` lists every client backend available on the system.

With the default `--backend=auto`, this backend is also picked automatically: if there is no
`$DISPLAY` or `$WAYLAND_DISPLAY` (and the client isn't running on MS Windows or macOS, which
always have a display), standard input and output are a terminal, and that terminal identifies
itself as one of the emulators listed above. This is only a best-effort guess from environment
variables (`KITTY_WINDOW_ID`, `TERM`, `KONSOLE_VERSION`, `TERM_PROGRAM`) made before connecting -
actual protocol support is always confirmed with the startup probe described below.

The terminal is left alone until the connection handshake completes, so password prompts still
work normally. After that the client switches to the alternate screen, hides the cursor and puts
the terminal in raw mode; all of this is undone when the session ends.

Because the terminal is used for pixels, log output is written elsewhere: to standard error when
that is not the terminal, otherwise to `xpra-terminal-<pid>.log` in the first writable directory
listed by `XPRA_LOG_DIRS` - by default the xpra runtime directory (`/run/user/$UID/xpra`), then
the system temporary directory. The path is printed before the terminal switches to the alternate
screen, and if no directory can be written to, the client's own log output is discarded rather
than drawn over the session. Use `-d terminal` to trace the tty setup, graphics and input parsing.

<div class="docs-section-heading" markdown="1">

## Input and clipboard

</div>

**Keyboard** - the kitty keyboard protocol is enabled for the duration of the session. It
reports key presses, repeats and releases, the modifiers held, and the text a key produces.
Terminals that ignore it fall back to legacy escape sequences, which cannot report key
releases, so the client synthesises one for every press.

**Pointer** - SGR pixel mouse reporting (modes `1002`, `1003`, `1006` and `1016`) gives motion,
buttons and wheel events in pixels rather than character cells, which is what window hit
testing needs.

**Clipboard** - receive only, using `OSC 52`: what is copied in the remote session is offered
to the terminal's clipboard, and the client never claims the selection itself. Whether the
terminal accepts it is the terminal's decision - kitty, for instance, requires
`clipboard_control` to list `write-clipboard`. Pasting into the remote session is not
supported, because reading the clipboard back over `OSC 52` is disabled or gated behind a
user prompt by default in every terminal that implements it.

<div class="docs-section-heading" markdown="1">

## Limitations

</div>

* the terminal must support the kitty graphics protocol - there is no fallback renderer
* no [system tray](../Features/System-Tray.md) and no [notifications](../Features/Notifications.md)
* no client [OpenGL acceleration](./Client-OpenGL.md); windows are painted as images
* no window decorations, no menus and no session info dialogs
* the mouse cursor is painted by the client as one more image on top of the windows
* keyboard layout handling is minimal: the terminal reports characters, not keycodes, so
  server side keymaps are not synchronised
* damaged windows are re-sent whole by default, or patched through shared memory
  when the terminal runs on the same machine and answers the startup probe;
  `XPRA_TERMINAL_FRAME_EDITS=-1` probes for direct frame edits instead, `1` forces them
* the pixel coordinate base of SGR mouse reports varies between terminals:
  the client assumes `0` under kitty and `1` everywhere else,
  `XPRA_TERMINAL_MOUSE_COORDINATE_BASE=0|1` overrides it

<div class="docs-section-heading" markdown="1">

## See also

</div>

* [Client](./Client.md) - the native client and its options
* [Client implementations](./Clients.md) - the other clients that speak the xpra protocol
* [Keyboard](../Features/Keyboard.md) and [Clipboard](../Features/Clipboard.md)
