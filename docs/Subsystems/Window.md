# Window


This is one of the most used subsystems.\
It handles forwarding of window contents and events.


## Implementations

| Component         | Link                                                                                                           |
|-------------------|----------------------------------------------------------------------------------------------------------------|
| client            | [xpra.client.subsystem.windows](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/windows.py) |
| client connection | [xpra.server.source.windows](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/windows.py)       |
| server            | [xpra.server.subsystem.window](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/window.py)   |



## Capabilities

TBD

## Network Packets

### Server-to-Client

| Packet Type                    | Arguments                                           | Information                                            |
|-------------------------------|------------------------------------------------------|--------------------------------------------------------|
| `window-create`               | `wid`, metadata, client properties                  | A new window has been created                          |
| `window-metadata`             | `wid`, metadata dictionary                          | One or more window properties have changed             |
| `window-move-resize`          | `wid`, `x`, `y`, `w`, `h`, `resize_counter`        | The window geometry has changed                        |
| `window-resized`              | `wid`, `w`, `h`, `resize_counter`                  | The window has been resized (position unchanged)       |
| `window-raise`                | `wid`                                               | The window should be raised to the top of the stack    |
| `window-restack`              | `wid`, `detail`, `sibling`                          | The window's stacking order has changed                |
| `window-initiate-moveresize`  | `wid`, `x_root`, `y_root`, `direction`, `button`, `source_indication` | The WM requests the client to start an interactive move/resize |
| `window-destroy`              | `wid`                                               | The window has been destroyed                          |
| `window-draw`                 | `wid`, `x`, `y`, `w`, `h`, `encoding`, `data`, ... | Pixel data for the window                              |
| `window-icon`                 | `wid`, `w`, `h`, `encoding`, `data`                | Updated window icon                                    |
| `window-bell`                 | `wid`, `device`, `percent`, `pitch`, `duration`, `bell_class`, `bell_id`, `name` | A bell event |

### Client-to-Server

| Packet Type    | Arguments                                           | Information                                                              |
|----------------|-----------------------------------------------------|--------------------------------------------------------------------------|
| `window-map`   | `wid`, `x`, `y`, `w`, `h`, client properties       | The client is ready to display a window                                  |
| `window-unmap` | `wid`                                               | The client has hidden a window                                           |
| `window-configure` | `wid`, `x`, `y`, `w`, `h`, properties          | The client has moved or resized a window                                 |
| `window-close` | `wid`                                               | The user has requested to close the window                               |
| `window-focus` | `wid`                                               | The window has received keyboard focus                                   |
| `window-action`| `wid`, `action`                                     | Request a window manager action (eg: maximize, minimize)                 |
| `window-refresh`| `wid`, options                                     | Request a full refresh of the window contents                            |
| `window-draw-ack` | `wid`, `packet_sequence`, `decode_time`, `message` | Acknowledge receipt and decoding of a `window-draw` packet              |
