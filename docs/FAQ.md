# Frequently Asked Questions

Find answers to common questions about installing, using, and troubleshooting
Xpra. For a broader overview, start with the [documentation home](README.md) or
the [Usage guide](Usage/README.md).

<div class="docs-section-heading" markdown="1">

## Installation

Choose a supported release and resolve package-signing or distribution-specific
installation warnings before starting a session.

</div>

<div class="docs-grid" markdown="1">
<section class="docs-card" markdown="1">

### Which version should I use?

Always use the [latest released version](https://github.com/Xpra-org/xpra/wiki/Versions).

</section>

<section class="docs-card" markdown="1">

### Should I use the version shipped with my Linux distribution?

Emphatically [no](https://github.com/Xpra-org/xpra/wiki/Distribution-Packages).

</section>

<section class="docs-card" markdown="1">

### Which versions are supported?

See the [supported versions](https://github.com/Xpra-org/xpra/wiki/Versions) and
[platforms](https://github.com/Xpra-org/xpra/wiki/Platforms) pages for
compatibility information.

</section>

<section class="docs-card" markdown="1">

### Why do I get a GPG signature warning when installing?

You probably forgot to import the GPG key before installing the package. Use
key `0x17978FAF`, with signature
`B499 3B57 3231 48E3 7977 E5D8 7325 4CAD 1797 8FAF`.

</section>

<section class="docs-card" markdown="1">

### What does `KEYEXPIRED 1273837137` mean?

The old key expired. Please use the
[new key](https://github.com/Xpra-org/xpra/issues/3863).

</section>

<section class="docs-card" markdown="1">

### Debian says “Origin changed” when updating

Run:

```shell
apt-get update --allow-releaseinfo-change
```

</section>

<section class="docs-card" markdown="1">

### Aptitude says some index files failed to download

See the previous Debian update answer above.

</section>

<section class="docs-card" markdown="1">

### I found a security issue

Please [report it privately](SECURITY.md).

</section>
</div>

<div class="docs-section-heading" markdown="1">

## Usage questions

These answers cover desktop integration, clipboard forwarding, Windows clients,
and starting services inside sessions.

</div>

<div class="docs-grid" markdown="1">
<section class="docs-card" markdown="1">

### Where is Xpra’s system tray icon?

Some desktop environments
[cannot show a system tray icon](Features/System-Tray.md#caveats).

</section>

<section class="docs-card" markdown="1">

### Why does Xpra use CPU when the session is idle?

[Audio forwarding](Features/Audio.md) consumes a fairly constant amount of CPU
and bandwidth. Turn speaker forwarding off if you do not need it. Some
applications also repaint their windows unnecessarily; try minimizing them.

</section>

<section class="docs-card" markdown="1">

### Why does the clipboard keep flashing?

Make sure no other tool is also synchronizing the clipboard. Avoid clipboard
managers whenever possible.

</section>

<section class="docs-card" markdown="1">

### RDP or x2go causes clipboard problems

[RDP #696](https://github.com/Xpra-org/xpra/issues/696) and
[x2go #735](https://github.com/Xpra-org/xpra/issues/735) perform their own
clipboard synchronization, which interferes with Xpra. Disable one of the
synchronization mechanisms and avoid layering remote-desktop protocols.

</section>

<section class="docs-card" markdown="1">

### Where does `Xpra.exe` write command output?

`Xpra.exe` is a graphical application, so output goes to `Xpra.log` in
`%APPDATA%\\Xpra`. Use `Xpra_cmd.exe` when you need command-line output.

</section>

<section class="docs-card" markdown="1">

### How can I start `gpg-agent`, `dbus`, and similar services?

The solution is often distribution-specific. Add
`--start=/path/to/Xsession` to the server options, or add each application
individually with a `start` option.

</section>

<section class="docs-card" markdown="1">

### VirtualBox will not release the mouse

[Disable auto-capture keyboard](https://github.com/Xpra-org/xpra/issues/3118#issuecomment-838985119).

</section>
</div>

<div class="docs-section-heading" markdown="1">

## Problems

Use these recovery steps when an application is slow to start, a session has
stopped responding, or a desktop behaves differently inside Xpra.

</div>

<div class="docs-grid" markdown="1">
<section class="docs-card" markdown="1">

### GNOME applications take a long time to start

Try adding `--source-start=gnome-keyring-daemon` to the server. See
[the GNOME Terminal issue](https://github.com/Xpra-org/xpra/issues/3109); older
versions may require `--start=gnome-keyring-daemon` instead.

</section>

<section class="docs-card" markdown="1">

### Can I recover a crashed seamless or desktop session?

Generally yes, as long as the virtual display server (VFB) is still running.
Use `xpra recover`. If the Xpra server is gone, start a new one to reuse the
existing display. If it is running but unresponsive, kill it first; use
`kill -9` to prevent teardown code from stopping the VFB.

</section>

<section class="docs-card" markdown="1">

### Why does an application open on the wrong display?

If the application has no option to prevent this, use a different user account
to launch multiple instances on different displays. This is a common issue with
some applications, especially browsers.

</section>

<section class="docs-card" markdown="1">

### Why are application menus missing on Ubuntu?

Start applications with `xpra seamless --start=APP`, not
`DISPLAY=:N APP` (see [#1419](https://github.com/Xpra-org/xpra/issues/1419)).

</section>
</div>

<div class="docs-section-heading" markdown="1">

## Network

For connection types, encryption, and performance diagnostics, see the
[networking guide](Network/README.md).

</div>

<div class="docs-grid" markdown="1">
<section class="docs-card" markdown="1">

### How can multiple users connect through one port?

Use the [proxy server](Usage/Proxy-Server.md).

</section>

<section class="docs-card" markdown="1">

### How can Windows clients use an SSH key?

If the key is not detected correctly, use `pageant`: see the
[PuTTY FAQ](http://www.chiark.greenend.org.uk/~sgtatham/putty/faq.html#faq-options)
and tell Xpra to use PuTTY with `--ssh=plink`.

</section>
</div>

<div class="docs-section-heading" markdown="1">

## Warnings and messages

Most messages below are harmless diagnostics. The answer explains when a
warning can be ignored and when a configuration change is appropriate.

</div>

<div class="docs-grid" markdown="1">
<section class="docs-card" markdown="1">

### “`cannot create group socket '/run/xpra/USERNAME'`”

Usually followed by `[Errno 13] Permission denied`. This is harmless and safe
to ignore, or add your user to the `xpra` group. The server creates this socket
for sharing sessions through Unix group membership and the `socket-permissions`
option.

</section>

<section class="docs-card" markdown="1">

### `/run/user/$UID` does not exist

You probably used `su` or an `ssh` login. See
[why `/run/user/ID` is not created after `su` or `sudo`](https://bugzilla.redhat.com/show_bug.cgi?id=967509)
and use `machinectl shell --uid=username` instead.

</section>

<section class="docs-card docs-card-wide" markdown="1">

### `uinput` warnings

`uinput` is optional, so these warnings are safe to ignore:

- `Error: cannot query uinput device path`
- `cannot access python uinput module: No module named uinput`
- `cannot use uinput for virtual devices`
- `cannot access python uinput module: name 'ABS_MAX' is not defined` — the
  python-uinput package is broken; contact your distributor
- `Failed to open the uinput device: Permission denied` — the user lacks
  permission to open `/dev/uinput`

</section>

<section class="docs-card" markdown="1">

### “`found an existing window manager on screen ...`”

Xpra is a window manager, so two window managers cannot run on the same X11
display. To forward a whole desktop, see [desktop mode](Usage/Desktop.md);
otherwise stop the other window manager.

</section>

<section class="docs-card" markdown="1">

### “`cannot register our notification forwarder ...`”

The server started from a GUI session that already has a D-Bus instance and a
notification daemon, so notification forwarding cannot be enabled.

</section>

<section class="docs-card docs-card-wide" markdown="1">

### DPI mismatch warnings

“DPI set to NN x NN (wanted MM x MM)” means the VFB command does not preserve
DPI settings. You may want to use a patched [Xdummy](Usage/Xdummy.md).

</section>

<section class="docs-card" markdown="1">

### `xpra [errno 2] no such file or directory` over SSH

Xpra is not installed on the remote host.

</section>

<section class="docs-card" markdown="1">

### X11 keyboard warnings

`Unsupported high keycode XXX for name <INNN> ignored` is harmless and
unavoidable. See [Bug 1615700](https://bugzilla.redhat.com/show_bug.cgi?id=1615700#c1).

</section>

<section class="docs-card" markdown="1">

### MacOS reports a damaged application

Run:

```shell
sudo xattr -rd com.apple.quarantine /Applications/Xpra.app
```

</section>

<section class="docs-card" markdown="1">

### GTK reports an invalid object warning

`gi/overrides/Gtk.py:1632: Warning: g_object_ref: assertion 'G_IS_OBJECT (object)' failed`
is mostly harmless. It comes from GTK and cannot currently be silenced.

</section>

<section class="docs-card docs-card-wide" markdown="1">

### Other harmless macOS warnings

These messages are harmless and unavoidable on macOS:

- `gtk_window_add_accel_group: assertion 'GTK_IS_WINDOW (window)' failed`
- `gui.py: Warning: invalid cast from 'GtkMenuBar?' to 'GtkWindow?'`

</section>
</div>
