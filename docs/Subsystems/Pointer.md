# Pointer


<div class="docs-section-heading" markdown="1">

## Implementations

</div>

The prefix for all packets and capabilities should be `pointer`.\
(older versions used the `mouse` prefix)


| Component         | Link                                                                                                           |
|-------------------|----------------------------------------------------------------------------------------------------------------|
| client            | [xpra.client.subsystem.pointer](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/pointer.py) |
| client connection | [xpra.server.source.pointer](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/pointer.py)       |
| server            | [xpra.server.subsystem.pointer](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/pointer.py) |


<div class="docs-section-heading" markdown="1">

## Platforms

</div>

There is some platform specific code to handle mouse wheel.\
Links pending.

The client side wheel handling lives in the same
[pointer subsystem](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/pointer.py):
see [mouse wheel](#mouse-wheel) below.

<div class="docs-section-heading" markdown="1">

## Capabilities

</div>

The client should expose the following `pointer` dictionary in its `hello` packet:

| Capability         | Value                           | Information                                                                   |
|--------------------|---------------------------------|-------------------------------------------------------------------------------|
| `initial-position` | `x` and `y` pair of coordinates | Optional                                                                      |
| `double_click`     | dictionary                      | contains just two integer attributes: `time` (in milliseconds) and `distance` |
| `sync`             | boolean                         | Optional, see [pointer synchronization](#pointer-synchronization)             |
| `record`           | boolean                         | Optional, legacy alias for `sync`                                             |
| `grabs`            | boolean                         | Legacy only, superseded by the `window` capability of the same name          |

Modern packets keep the `pointer` field as a non-negative
`(absolute_x, absolute_y)` pair normalized against the client monitor layout.
They carry alternative coordinate spaces in the properties dictionary:

- `raw-position`: the absolute position before layout normalization
- `window-position`: `(window_x, window_y)`
- `monitor`: `{"index": monitor_index, "position": (monitor_x, monitor_y)}`

Alternatively, the client can just supply the value `True` instead of the dictionary and the server will use default values.

The server exposes these `hello` capabilities:

| Capability       | Value   | Information                                                                     |
|------------------|---------|----------------------------------------------------------------------------------|
| `input-devices`  | string  | the pointer device in use: `xtest`, `uinput`, `xi`, ..                          |
| `wheel.precise`  | boolean | whether the pointer device can inject fractional wheel motion, see [mouse wheel](#mouse-wheel) |
| `pointer.relative` | boolean | assumed available since v5.0.3                                                 |
| `pointer.optional` | boolean | the client may omit the pointer data from its packets                          |


<div class="docs-section-heading" markdown="1">

## Network Packets

</div>

| Packet Type      | Direction        | Arguments                                                                       |
|------------------|------------------|---------------------------------------------------------------------------------|
| `pointer-motion` | client to server | `device_id`, `sequence`, `wid`, pointer, properties                            |
| `pointer-button` | client to server | `device_id`, `sequence`, `wid`, `button`, `pressed`, pointer, properties       |
| `pointer-wheel`  | client to server | `wid`, `button`, `distance`, pointer, modifiers, buttons, properties           |
| `pointer-motion` | server to client | `device_id`, `sequence`, `wid`, pointer, properties                            |
| `pointer-button` | server to client | `device_id`, `sequence`, `wid`, `button`, `pressed`, pointer, properties       |
| `pointer-wheel`  | server to client | `wid`, `button`, `distance`, pointer, modifiers                                |
| `pointer-position` | server to client | `wid`, `x`, `y`, `relative-x`, `relative-y`                                  |


<div class="docs-section-heading" markdown="1">

## Pointer synchronization

</div>

When a client enables the `sync` capability, the server echoes back to it the pointer events
it receives from **all the other** clients connected to the same session,
using the exact same packet types.\
This is used by the recording client to capture the input events,
and by regular clients started with `sharing=sync` (or `sharing=sync-pointer`),
so that each user can see what the other users are doing:
the position received is shown as a pointer overlay,
in the same way as the pointer position updates sent by shadow servers.

Only the `pointer-motion` packets carry a `window-position` property,
so this is the only packet type which can update the overlay.

The server can refuse the synchronization requested by a client
using the `sync` socket option, which applies to the `pointer` synchronization
and to the window [`position` and `focus` synchronization](./Window.md#capabilities).\
Unlike the `record` socket option, it is enabled by default.
The value can be a boolean, `all`, or a comma separated list of subsystems:
```shell
xpra start --bind-tcp=0.0.0.0:10000,sync=no
xpra start --bind-tcp=0.0.0.0:10000,sync=pointer,focus
```


<div class="docs-section-heading" markdown="1">

## Mouse wheel

</div>

Wheel events reach the pointer subsystem as fractional deltas
(`wheel_event`, which accumulates them per axis).\
How they are sent depends on the server's `wheel.precise` capability,
**not** on the protocol version:

* if the server sets `wheel.precise`, the accumulated delta is sent as a single
  `pointer-wheel` packet carrying the exact distance multiplied by 1000.\
  Only the `uinput` and wayland pointer devices can do this.
* otherwise the delta is quantized into discrete steps and each step is emulated
  with a `pointer-button` press and release pair on the wheel button
  (4 / 5 for the vertical axis, 6 / 7 for the horizontal one), leaving the
  remainder to be accumulated for the next event.\
  This is what `xtest` (the default X11 pointer device), macos and win32 servers get.

So `pointer-wheel` is preferred whenever the server can make use of it,
and the button emulation is the fallback rather than a legacy path -
both are current, and which one is used is decided per session.

The `mousewheel` client option is parsed into a `wheel_map` translating the wheel
buttons, which is how the axes can be inverted (`invert-x`, `invert-y`,
`invert-z`, `invert-all`), and into a `wheel_smooth` flag - `coarse` disables
the smooth scrolling events at the toolkit level, so only the discrete
button events are generated.
