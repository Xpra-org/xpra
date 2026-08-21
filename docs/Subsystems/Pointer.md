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
