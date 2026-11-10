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
| `double_click`     | dictionary                      | `time`: integer, in milliseconds; `distance`: a pair of integers, the maximum `x` and `y` distance in pixels, ie: `[5, 5]`. On X11, the server sets `Net/DoubleClickTime` and `Net/DoubleClickDistance` (the average of the two distances) from positive values only |
| `sync`             | boolean                         | Optional, see [pointer synchronization](#pointer-synchronization)             |
| `record`           | boolean                         | Optional, legacy alias for `sync`                                             |
| `grabs`            | boolean                         | Legacy only, superseded by the `window` capability of the same name          |

Modern packets keep the `pointer` field as an
`(absolute_x, absolute_y)` pair normalized against the client monitor layout.
Legacy packets append the window-relative position: `(absolute_x, absolute_y, window_x, window_y)`.\
Each coordinate must be within -65535 and 65535: they can be negative,
ie: on a monitor to the left of the primary one, or outside the window while dragging.
When the server knows the window, it uses the window-relative position rather than the absolute one.
They carry alternative coordinate spaces in the properties dictionary:

- `raw-position`: the absolute position before layout normalization
- `window-position`: `(window_x, window_y)`
- `monitor`: `{"index": monitor_index, "position": (monitor_x, monitor_y)}`

Alternatively, the client can just supply the value `True` instead of the dictionary and the server will use default values.

The server exposes these top-level `hello` capabilities (flat keys), to clients that set `server-features`:

| Capability       | Value   | Information                                                                     |
|------------------|---------|----------------------------------------------------------------------------------|
| `input-devices`  | string  | the pointer device in use: `xtest`, `uinput`, `xi`, ..                          |
| `wheel.precise`  | boolean | whether the pointer device can inject fractional wheel motion, see [mouse wheel](#mouse-wheel) |
| `wheel.emulation` | boolean | the server emulates the wheel with button events when its device cannot do it, so `pointer-wheel` packets are always accepted |
| `pointer.relative` | boolean | assumed available since v5.0.3                                                 |
| `pointer.optional` | boolean | the client may omit the pointer data from its packets                          |


<div class="docs-section-heading" markdown="1">

## Network Packets

</div>

| Packet Type      | Direction        | Arguments                                                                       |
|------------------|------------------|---------------------------------------------------------------------------------|
| `pointer-motion` | client to server | `device_id`, `sequence`, `wid`, pointer, properties                            |
| `pointer-button` | client to server | `device_id`, `sequence`, `wid`, `button`, `pressed`, pointer, properties       |
| `pointer-wheel`  | client to server | `wid`, `button`, `distance` (x1000), pointer, modifiers, buttons, properties (`scaled-distance`) |
| `pointer-motion` | server to client | `device_id`, `sequence`, `wid`, pointer, properties                            |
| `pointer-button` | server to client | `device_id`, `sequence`, `wid`, `button`, `pressed`, pointer, properties       |
| `pointer-wheel`  | server to client | `wid`, `button`, `distance`, pointer, modifiers                                |
| `pointer-position` | server to client | `wid`, `x`, `y`, `relative-x`, `relative-y`                                  |
| `pointer-devices` | client to server | format, devices dictionary                                                    |


Packet details:

* `device_id` identifies the input device, `-1` when unknown or unspecified.
* `sequence` is a per-device counter, incremented by the client for each event
  (`0` when the device is `-1`).
* `wid` is the window under the pointer. When the server does not know that window, it uses
  the absolute position.
* `button` numbers follow X11: `1` left, `2` middle, `3` right, `4` / `5` wheel up / down,
  `6` / `7` wheel left / right; higher numbers are extra buttons.
* the properties dictionary may contain `modifiers` (the modifiers currently pressed,
  see [keyboard](Keyboard.md)), `buttons` (the buttons currently pressed),
  `raw-button` / `raw-buttons` (the same values before the client's button mapping),
  `raw-position`, `window-position` and `monitor` (described above), and for
  `pointer-wheel`, `scaled-distance`.
* `pointer-position`: the server moved the pointer to `x`, `y`, which is at
  `relative_x`, `relative_y` within window `wid`. Clients usually only show it as an
  overlay rather than moving the real pointer.

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
(`wheel_event`, which accumulates them per axis), and are sent as
`pointer-wheel` packets carrying the exact distance multiplied by 1000.

The deltas are in wheel clicks, positive up and right. Toolkits which use
the opposite convention have to flip them first, ie: GTK's smooth scroll
`delta_y` is positive downwards, while win32's `WM_MOUSEWHEEL` and
`WM_MOUSEHWHEEL` are already positive up and right (in multiples of
`WHEEL_DELTA`, 120). The sign picks the wheel button: `4` up, `5` down, `6` left,
`7` right, and the packet's `distance` keeps the sign of the delta:

| scroll | button | `distance` |
|--------|--------|------------|
| up     | `4`    | positive   |
| down   | `5`    | negative   |
| left   | `6`    | negative   |
| right  | `7`    | positive   |

The `mousewheel` inversion (see below) swaps the button but not the sign,
so the button is what decides the direction on the server: every pointer
device only uses the magnitude of the distance.

What the server does with them depends on its pointer device:

* devices which can inject fractional wheel motion (`uinput` and wayland)
  apply the distance directly - these advertise `wheel.precise`
* the others (`xtest`, which is the X11 default, macos and win32) quantize the
  distance into discrete steps and emulate each step with a button press and
  release pair on the wheel button (4 / 5 for the vertical axis, 6 / 7 for the
  horizontal one), keeping the remainder for the next event

So `pointer-wheel` is the packet used in both cases, and the button emulation is
a server side implementation detail rather than a legacy path.

The emulation used to be done by the clients, which is why the scroll speed
settings (`XPRA_MOUSE_SCROLL_MULTIPLIER` and `XPRA_MOUSE_SCROLL_SQRT_SCALE`)
are still applied client side: the client sends the distance those settings
turn into, as the `scaled-distance` property of the packet (with the same sign), and that is what
the server quantizes.\
Servers with a precise device ignore it and use the exact `distance`,
and servers too old to know about it just ignore the extra property.

What is left over after quantizing is always less than half a click, so it is
carried over to the next event: this is how a slow scroll eventually adds up
to a click.  It can only ever shorten the next scroll, never reverse it.

Clients too old to know about `wheel.emulation` still emulate the wheel
themselves when the server does not advertise `wheel.precise`,
sending `pointer-button` packets instead.

The `mousewheel` client option is parsed into a `wheel_map` translating the wheel
buttons, which is how the axes can be inverted (`invert-x`, `invert-y`,
`invert-z`, `invert-all`), and into a `wheel_smooth` flag - `coarse` disables
the smooth scrolling events at the toolkit level, so only the discrete
button events are generated.


<div class="docs-section-heading" markdown="1">

## Input devices

</div>

The server's `input-devices` capability names the device it uses to inject pointer
events: `xtest` (the X11 default), `uinput` (a virtual kernel device, which supports
precise wheel motion) or `xi`. With `touchpad-device`, the server also has a virtual
touchpad, used for absolute pointer devices such as pens and touchscreens.

X11 clients using XInput2 can describe their own input devices, so that the server can
map them, when the server's `input-devices` is `xi` or `uinput`:

```text
["pointer-devices", "xi", {device_id: device_info, ...}]
```

The only format defined is `xi`. Each `device_info` map contains:

| Key | Type | Information |
|---|---|---|
| `name` | string | The device name |
| `use` | string | `master pointer`, `master keyboard`, `slave pointer`, `slave keyboard` or `floating slave` |
| `attachment` | integer | The master device of a slave device |
| `enabled` | boolean | |
| `classes` | map | Class index to class info: `type` (ie: `valuator`, `button`, `scroll`, `touch`), and for valuators: `number`, `label`, `min`, `max`, `value`, `resolution`, `mode` (`0` relative, `1` absolute) |
| `properties` | map | XInput device properties, informational |

The server routes the events of slave pointer devices that have two absolute valuators
covering `0` to `2^24 - 1` to its touchpad device. The client sends this packet after
the handshake, and again whenever its devices change. The `device_id` keys are the
ones the client then uses in the `device` argument of its pointer packets.

Such clients also add XInput2 details to the properties of their pointer packets:
`device`, `x`, `y`, `x_root`, `y_root`, `valuators` and `raw-valuators`, all as
fixed point `(value * 1000000, 1000000)` pairs. These are informational: servers do not
need them to process the event.
