# Keyboard

For usage related information, see [keyboard feature](../Features/Keyboard.md).


<div class="docs-section-heading" markdown="1">

## Implementations

</div>

Packets use the `keyboard` prefix. The `hello` capabilities are still top-level keys, see below.

| Component         | Link                                                                                                             |
|-------------------|------------------------------------------------------------------------------------------------------------------|
| client            | [xpra.client.subsystem.keyboard](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/keyboard.py) |
| client connection | [xpra.server.source.keyboard](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/keyboard.py)       |
| server            | [xpra.server.subsystem.keyboard](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/keyboard.py) |


<div class="docs-section-heading" markdown="1">

## Platforms

</div>

[xpra.keyboard](https://github.com/Xpra-org/xpra/tree/master/xpra/keyboard/)
contains the platform independent code, mostly constants.

| Platform | Link                                                                                                                                  |
|----------|---------------------------------------------------------------------------------------------------------------------------------------|
| `posix`  | [xpra.platform.posix.keyboard](https://github.com/Xpra-org/xpra/blob/master/xpra/platform/posix/keyboard.py) for both Wayland and X11 |
| `win32`  | [xpra.platform.win32.keyboard](https://github.com/Xpra-org/xpra/blob/master/xpra/platform/win32/keyboard.py)                         |
| `MacOS`  | [xpra.platform.darwin.keyboard](https://github.com/Xpra-org/xpra/blob/master/xpra/platform/darwin/keyboard.py)                       |


<div class="docs-section-heading" markdown="1">

## Capabilities

</div>

The client exposes these top-level capabilities in its `hello` packet:

| Capability      | Value                | Information                                        |
|-----------------|----------------------|----------------------------------------------------|
| `keyboard`      | boolean              | Whether the client sends keyboard events           |
| `modifiers`     | list of strings      | The modifiers currently active, see below          |
| `keymap`        | dictionary           | The keyboard definition, see below                 |
| `key_repeat`    | pair of integers     | The key repeat delay and interval, in milliseconds |
| `keyboard_sync` | boolean              | Keyboard synchronization mode, see below           |
| `ibus`          | boolean              | The client supports ibus layouts                   |

The keymap can be updated at any time with a `keyboard-config` packet, ie: when the
user switches layout. A full keymap can be large: to keep the `hello` packet small
(see the pre-handshake size limit in the [protocol](../Network/Protocol.md#34-limits)),
the client may leave out `keycodes` and `x11_keycodes` and set `delay=True` in its
`keymap`. The server then waits for a `keyboard-config` packet, which the client MUST
send right after the handshake: until then, no keymap is applied.

**Modifiers** are named after the X11 modifier masks: `shift`, `lock`, `control`,
`mod1` to `mod5`. The keymap's `mod_meanings` tells the server which key names map
to which modifier, by default: `Shift_L` and `Shift_R` → `shift`, `Caps_Lock` → `lock`,
`Control_L` and `Control_R` → `control`, `Alt_L`, `Alt_R`, `Meta_L` and `Meta_R` → `mod1`,
`Num_Lock` → `mod2`, `Super_L` and `Super_R` → `mod3`, `Hyper_L` and `Hyper_R` → `mod4`,
`ISO_Level3_Shift` and `Mode_switch` → `mod5`. The server makes its own modifier
state match the list it receives with each key and pointer event.


<div class="docs-section-heading" markdown="1">

## Network Packets

</div>

| Packet Type       | Direction        | Arguments | Information |
|-------------------|------------------|-----------|-------------|
| `keyboard-event`  | client to server | `wid`, `keyname` : string, `pressed` : boolean, attributes : dictionary | A key was pressed or released |
| `keyboard-config` | client to server | keymap dictionary | Send an updated keymap to the server |
| `keyboard-sync`   | client to server | `enabled` : boolean | Enable or disable keyboard synchronization |

The `keyboard-event` attributes are `modifiers` (list of strings), `keyval`
(integer), `string` (the text the key produces), `keycode` (the client's
hardware keycode) and `group` (layout group). The client should populate as many
of them as possible.

`keyboard-config` carries the same keymap dictionary as the `keymap` capability,
not nested, plus `force=True` to make the server re-apply it even if it has not
changed. It may also contain `modifiers`.

**Key names** are X11 keysym names: `a`, `A`, `Return`, `BackSpace`, `Shift_L`,
`F1`, `KP_Enter`, `odiaeresis`. Unless the keymap provides the client's own keycodes
(`x11_keycodes`, or `keycodes` with `raw=True`), the server maps each key name and
modifier state to a keycode of its own keyboard, adding a keysym on the fly when
none matches. So a minimal client only needs to send correct key names and
modifiers. A `keycode` that is negative means that the key has no keycode.

**Key repeat:** with synchronization disabled (the default), the client forwards
the auto-repeat events of its own platform as separate presses, and the server
presses and immediately releases every non-modifier key. With synchronization
enabled, the server keeps the key pressed until the release event arrives, and
releases it by itself if no new event for that key arrives within the repeat
delay (bounded to 1 to 2 seconds), in case the release event was lost.


<div class="docs-section-heading" markdown="1">

## Keymap Dictionary

</div>

| Attribute | Data Type                   | Description                                                           | Example values                                              |
|-----------|-----------------------------|-----------------------------------------------------------------------|-------------------------------------------------------------|
| `backend` | string                      | The type of keyboard backend requested                                | `ibus`                                                      |
| `backend_name` | string                 | The backend specific layout name                                      |                                                             |
| `layout`  | string                      | The main layout requested                                             | `us`                                                        |
| `layouts` | list of strings             | The layouts that should be enabled                                    | `["us", "gb"]`                                              |
| `variant` | string                      | The main layout variant                                               | `nodeadkeys`                                                |
| `variants` | list of strings            | The other layout variants that should be enabled                      | -                                                           |
| `options` | string                      | XKB options                                                           | `grp:alt_shift_toggle`                                      |
| `layout_groups` | boolean               | The client uses layout groups                                         |                                                             |
| `raw`     | boolean                     | When raw mode is enabled, the server does not perform any translation | `false`                                                     |
| `delay`   | boolean                     | The keycodes will be sent later in a `keyboard-config` packet         | `false`                                                     |
| `sync` | boolean                        | Keyboard synchronization                                              | `false`                                                     |
| `query_struct` | dictionary             | X11 keyboard definition (`setxkbmap -query`)                          | `{"rules": "evdev", "model": "pc105+inet", "layout": "gb"}` |
| `native` | dictionary                   | Platform specific keyboard data                                       |                                                             |
| `mod_meanings` | dictionary             | Key names to modifier names, see above                                | `{"Alt_L": "mod1"}`                                         |
| `mod_managed` | list of strings         | Modifiers handled by the client platform                              |                                                             |
| `mod_pointermissing` | list of strings  | Modifiers that may be missing from pointer packets                    | `["lock", "mod2"]`                                          |
| `keycodes` | list of keycode definitions | See below | -                                                           |
| `x11_keycodes` | map of keycode integers to lists of strings | X11 clients only: their own keycodes and the keysym names for each level | `{38: ["a", "A"]}` |


### Keycodes

Each entry in the list of `keycodes` is a list of 5 values, in this order:

| Position | Data Type | Description |
|-----------|-----------|-------------|
| `keyval` | integer | platform specific key value |
| `name` | string | name of the key |
| `keycode` | integer | platform specific key code |
| `group` | integer | keyboard layout group |
| `level` | integer | keyboard layout level |
