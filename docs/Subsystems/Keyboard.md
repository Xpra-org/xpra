# ![Keyboard](../images/icons/keyboard.png) Keyboard

For usage related information, see [keyboard feature](../Features/Keyboard.md).


## Implementations

The prefix for all packets and capabilities should be `keyboard` - unfortunately, this work is not complete yet.

| Component         | Link                                                                                                             |
|-------------------|------------------------------------------------------------------------------------------------------------------|
| client            | [xpra.client.subsystem.keyboard](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/keyboard.py) |
| client connection | [xpra.server.source.keyboard](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/keyboard.py)       |
| server            | [xpra.server.subsystem.keyboard](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/keyboard.py) |


## Platforms

[xpra.keyboard](https://github.com/Xpra-org/xpra/tree/master/xpra/keyboard/)
contains the platform independent code, mostly constants.

| Platform | Link                                                                                                                                  |
|----------|---------------------------------------------------------------------------------------------------------------------------------------|
| `posix`  | [xpra.platform.posix.keyboard](https://github.com/Xpra-org/xpra/blob/master/xpra/platform/posix/keyboard.py) for both Wayland and X11 |
| `win32`  | [xpra.platform.win32.keyboard](https://github.com/Xpra-org/xpra/blob/master/xpra/platform/win32/keyboard.py)                         |
| `MacOS`  | [xpra.platform.darwin.keyboard](https://github.com/Xpra-org/xpra/blob/master/xpra/platform/darwin/keyboard.py)                       |


## Capabilities

The client should expose the following capabilities in its `hello` packet:

| Capability          | Value               | Information                                        |
|---------------------|---------------------|----------------------------------------------------|
| `keyboard`          | `enabled` : boolean | Whether keyboard support is enabled                |
| `ibus`              | `enabled` : boolean | The client supports ibus layouts                   |
| `modifiers`      | list of strings     | The names of the modifier keys                     |
| `keymap`            | dictionary          | Extensive keyboard definition                      |
| `key_repeat` | pair of integers    | The key repeat delay and interval, in milliseconds |
| `keyboard_sync`         | `enabled` : boolean | Legacy                                             |

The `keymap` may also be updated by the client at any time using the `keyboard-layout` packet.\
To save space in the initial `hello` packet, the full keymap may be sent separately afterwards.


## Network Packets

| Packet Type      | Arguments                                                                                                                                             | Information                                                         |
|------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------|
| `key-action`     | `keyname` : string, `pressed` : boolean, `modifiers` : list of strings, `keyval` : integer, `string` : string, `keycode` : integer, `group` : integer | The client should try to populate as many attributes as possible.   |
| `keymap-changed` | `attributes` : dictionary                                                                                                                             | The number of clipboard requests waiting                            |

The attributes should contain a `keymap` key with another dictionary.


## Keymap Dictionary

| Attribute | Data Type                   | Description                                                           | Example values                                              |
|-----------|-----------------------------|-----------------------------------------------------------------------|-------------------------------------------------------------|
| `backend` | string                      | The type of keyboard backend requested                                | `ibus`                                                      |
| `layout`  | string                      | The main layout requested                                             | `us`                                                        |
| `layouts` | list of strings             | The layouts that should be enabled                                    | `us,gb`                                                     |
| `variant` | string                      | The main layout variant                                               | `nodeadkeys`                                                |
| `variants` | list of strings             | The other layout variants that should be enabled                      | -                                                           |
| `raw`     | boolean                     | When raw mode is enabled, the server does not perform any translation | `false`                                                     |
| `sync` | boolean                     | Legacy flag                                                           | `false`                                                     |
| `query_struct` | dictionary                  | Legacy X11 keyboard definition                                        | `{"rules": "evdev", "model": "pc105+inet", "layout": "gb"}` |
| `mod_meanings` | dictionary                  | Mapping from short modifier codes to modifier names                   |                                                             |
| `mod_managed` | list of strings             | Legacy                                                                |                                                             |
| `mod_pointermissing` | list of strings             | List of modifiers that may be missing from pointer packets            | `("CapsLock", "NumLock")`                                    |
| `keycodes` | list of keycode definitions | See below | -                                                           |                                                          |
| `x11_keycodes` | map of keycode integers to lists of strings | |                                                             |


### Keycodes

Each entry in the list of `keycodes` is made of:

| Attribute | Data Type | Description |
|-----------|-----------|-------------|
| `keyval` | integer | platform specific key value |
| `name` | string | name of the key |
| `keycode` | integer | platform specific key code |
| `group` | integer | keyboard layout group |
| `level` | integer | keyboard layout level |