# System Tray

## Xpra System Tray
Xpra forwards windows for remote applications (or desktops), and unless you interact with some of its options, it does not create any windows of its own so that it can stay out of the way.

Xpra uses a system tray icon with a popup menu to allow you to interact with its settings and the server the session is connected to.

You can toggle this feature using the option `tray=yes|no`.\
You can also delay showing this system tray until after a window is actually being forwarded using the `--delay-tray` command line option.


## System Tray Forwarding
Xpra also forwards the system tray of the applications it is remoting.

This feature is enabled by default and can be controlled using the `--system-tray=on|off` option.


## Caveats
Unfortunately, on some platforms like `gnome-shell`, it is effectively impossible for an application to show a system tray icon.

On such platforms, users may have to use the `#+F1` to bring up xpra's menu (typically that's `Control+F1` or `Alt+F1` on some platforms) or force enable the headerbar (`headerbar=force`).

System trays forwarded for remote applications will not be shown without installing an extension.
(ie: gnome-shell requires [topicons](https://extensions.gnome.org/extension/1031/topicons/) to function properly - for more information, see [#1720](https://github.com/Xpra-org/xpra/issues/1720))
