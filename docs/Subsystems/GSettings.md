# GSettings

This subsystem lets the client forward some of its desktop settings, such as the
theme, fonts or colour scheme, to the applications running on the server, using the
[GSettings](https://docs.gtk.org/gio/class.Settings.html) configuration system.

<div class="docs-section-heading" markdown="1">

## Implementations

</div>

| Component         | Link                                                                                                                 |
|-------------------|----------------------------------------------------------------------------------------------------------------------|
| client            | [xpra.client.subsystem.gsettings](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/gsettings.py)   |
| server            | [xpra.server.subsystem.gsettings](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/gsettings.py)   |

Both ends are configured with the `gsettings-sync` option, which takes `auto`
(the default list, see below), `no`, `all`, a list of `schema:key` patterns, or
fixed values as `schema:key=value(type)`.

<div class="docs-section-heading" markdown="1">

## Capabilities

</div>

The client sets the top-level `gsettings` capability to `True` when it has settings to
forward, and the server sets it when it accepts them. The client only sends settings
to a server that advertised it.

<div class="docs-section-heading" markdown="1">

## Network Packets

</div>

```text
["gsettings-update", {"schema:key": "value", ...}]
```

Sent by the client after the handshake with all its settings, then again with
the keys that change. Each key is a GSettings schema id and key name separated by a
colon, ie: `org.gnome.desktop.interface:gtk-theme`. Each value is the setting's value in
the [GVariant text format](https://docs.gtk.org/glib/gvariant-text-format.html), ie: `'Adwaita-dark'`,
`24`, `true`. The type annotation may be included (`@s 'Adwaita'`, `uint32 24`); without
one, the server parses the value using the type of the setting it replaces.

The server only applies the keys that match its own allow list, and only while a
single client is connected: with several clients, or once the client disconnects, it
restores the original values.

The default allow list contains the `org.gnome.desktop.interface` keys `gtk-theme`,
`icon-theme`, `cursor-theme`, `cursor-size`, `font-name`, `monospace-font-name`,
`document-font-name`, `color-scheme`, `font-antialiasing` and `font-hinting`, the
`org.gnome.desktop.wm.preferences` keys `theme`, `button-layout` and `titlebar-font`,
the `org.gnome.desktop.sound` keys `theme-name` and `event-sounds`, and
`org.gnome.desktop.a11y.interface:high-contrast`.

On MS Windows and macOS, the client has no GSettings: with `auto`, it sends values
derived from the platform's own appearance settings instead.
