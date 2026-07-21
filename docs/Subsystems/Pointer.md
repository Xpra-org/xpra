# ![Pointer](../../fs/share/xpra/icons/pointer.png) Pointer


## Implementations

The prefix for all packets and capabilities should be `pointer`.\
(older versions used the `mouse` prefix)


| Component         | Link                                                                                                           |
|-------------------|----------------------------------------------------------------------------------------------------------------|
| client            | [xpra.client.subsystem.pointer](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/pointer.py) |
| client connection | [xpra.server.source.pointer](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/pointer.py)       |
| server            | [xpra.server.subsystem.pointer](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/pointer.py) |


## Platforms

There is some platform specific code to handle mouse wheel.\
Links pending.

## Capabilities

The client should expose the following `pointer` dictionary in its `hello` packet:

| Capability         | Value                           | Information                                                                   |
|--------------------|---------------------------------|-------------------------------------------------------------------------------|
| `initial-position` | `x` and `y` pair of coordinates | Optional                                                                      |
| `double_click`     | dictionary                      | contains just two integer attributes: `time` (in milliseconds) and `distance` |

Modern packets keep the `pointer` field as a non-negative
`(absolute_x, absolute_y)` pair normalized against the client monitor layout.
They carry alternative coordinate spaces in the properties dictionary:

- `raw-position`: the absolute position before layout normalization
- `window-position`: `(window_x, window_y)`
- `monitor`: `{"index": monitor_index, "position": (monitor_x, monitor_y)}`

Alternatively, the client can just supply the value `True` instead of the dictionary and the server will use default values.


## Network Packets

| Packet Type      | Direction        | Arguments                                                                       |
|------------------|------------------|---------------------------------------------------------------------------------|
| `pointer-motion` | client to server | `device_id`, `sequence`, `wid`, pointer, properties                            |
| `pointer-button` | client to server | `device_id`, `sequence`, `wid`, `button`, `pressed`, pointer, properties       |
| `pointer-wheel`  | client to server | `wid`, `button`, `distance`, pointer, modifiers, buttons, properties           |
| `input-devices`  | client to server |                                                                                 |
