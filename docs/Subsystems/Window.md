# Window


This is one of the most used subsystems.\
It handles forwarding of window contents and events.

For background on how the `window-focus` packet is translated into the focus, activation
and stacking mechanisms of X11, MS Windows, macOS and Wayland,
see [window focus](Window-Focus.md).


<div class="docs-section-heading" markdown="1">

## Implementations

</div>

| Component         | Link                                                                                                           |
|-------------------|----------------------------------------------------------------------------------------------------------------|
| client            | [xpra.client.subsystem.windows](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/windows.py) |
| client connection | [xpra.server.source.windows](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/windows.py)       |
| server            | [xpra.server.subsystem.window](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/window.py)   |



<div class="docs-section-heading" markdown="1">

## Capabilities

</div>

Modern clients attach a monitor descriptor to map and configure packets. The
descriptor contains the client's monitor `index` and the window `position`
relative to that monitor.

The client exposes these in the `window` dictionary of its `hello` packet:

| Capability      | Information                                                                      |
|-----------------|----------------------------------------------------------------------------------|
| `enabled`       | The client wants window forwarding; an absent or empty dictionary disables it    |
| `restack`       | The client can handle `window-restack` packets, not just `window-raise`          |
| `grabs`         | The client can handle `window-grab` and `window-ungrab` packets                  |
| `sync-position` | Send `window-move-resize` when another client moves or resizes a window          |
| `sync-focus`    | Send `window-raise` when another client focuses a window                         |
| `sync-stacking` | Send `window-stacking` when another client reports its complete stacking order   |

`sync-position` and `sync-focus` are enabled by the `sharing=sync` client option,
and default to enabled for recording clients.
They can also be enabled individually, using `sharing=sync-position`, `sharing=sync-focus`,
or a comma separated list of these values.
They only take effect when more than one client is connected: the packets are sent
to every other client that requested the synchronization, never back to the client
that caused the change.

`sync-position` and `sync-focus` can be refused by the server using the `sync` socket option
(as the `position` and `focus` subsystems),
see [pointer synchronization](./Pointer.md#pointer-synchronization).
`sync-stacking` does not require a `sync` or `record` socket option. Recording
clients request it by default; regular GUI clients do not.

An X11 seamless server advertises `window.stacking = true`. Clients may then send
their current bottom-to-top window order using `window-stacking`; the topmost window
is the final ID in the list. X11 clients obtain this order from their local window
manager's `_NET_CLIENT_LIST_STACKING` root property, MS Windows clients from the
desktop z-order (`EnumWindows`), watching the `EVENT_OBJECT_REORDER` window event.

<div class="docs-section-heading" markdown="1">

## Network Packets

</div>

### Server-to-Client

| Packet Type                    | Arguments                                           | Information                                            |
|-------------------------------|------------------------------------------------------|--------------------------------------------------------|
| `window-create`               | `wid`, `x`, `y`, `w`, `h`, metadata, client properties | A new window has been created                       |
| `window-metadata`             | `wid`, metadata dictionary                          | One or more window properties have changed             |
| `window-move-resize`          | `wid`, `x`, `y`, `w`, `h`, `resize_counter`        | The window geometry has changed                        |
| `window-resized`              | `wid`, `w`, `h`, `resize_counter`                  | The window has been resized (position unchanged)       |
| `window-raise`                | `wid`                                               | The window should be raised to the top of the stack    |
| `window-restack`              | `wid`, `detail`, `sibling`                          | The window's stacking order has changed                |
| `window-initiate-moveresize`  | `wid`, `x_root`, `y_root`, `direction`, `button`, `source_indication` | The WM requests the client to start an interactive move/resize |
| `window-destroy`              | `wid`                                               | The window has been destroyed                          |
| `window-draw`                 | `wid`, `x`, `y`, `w`, `h`, `encoding`, `data`, `sequence`, `rowstride`, options | Pixel data for the window |
| `window-eos`                  | `wid`                                               | End all codec streams for the window                   |
| `window-icon`                 | `wid`, `w`, `h`, `encoding`, `data`                | Updated window icon                                    |
| `window-bell`                 | `wid`, `device`, `percent`, `pitch`, `duration`, `bell_class`, `bell_id`, `name` | A bell event |
| `window-grab`                 | `wid`                                               | The window has grabbed the pointer and keyboard         |
| `window-ungrab`               | `wid`                                               | The grab has been released                             |
| `window-stacking`             | list of window IDs, bottom-to-top                    | Complete stacking order reported by another client    |

### Client-to-Server

| Packet Type    | Arguments                                           | Information                                                              |
|----------------|-----------------------------------------------------|--------------------------------------------------------------------------|
| `window-map`   | `wid`, `x`, `y`, `w`, `h`, client properties, state, monitor | The client is ready to display a window                           |
| `window-unmap` | `wid`, optional iconified flag and state             | The client has hidden a window                                           |
| `window-configure` | `wid`, configuration dictionary                | The client has moved or resized a window                                 |
| `window-close` | `wid`                                               | The user has requested to close the window                               |
| `window-focus` | `wid`, optional modifiers                           | The window has received keyboard focus                                   |
| `window-action`| `wid`, `action`, optional arguments                 | Request a window manager action (eg: maximize, minimize)                 |
| `window-stacking` | list of window IDs, bottom-to-top               | Report the client's current stacking order                               |
| `window-refresh`| `wid`, options                                     | Request a full refresh of the window contents                            |
| `window-ack`   | `wid`, `width`, `height`, `packet_sequence`, `decode_time`, `message` | Acknowledge receipt and decoding of a `window-draw` packet |

The Win32 native client rebases absolute window positions against the top-left
of its monitor layout. Packets also include the pre-normalization coordinates
as `raw-position` metadata.

<div class="docs-section-heading" markdown="1">

## The `scroll` encoding

</div>

Instead of pixel data, a `window-draw` packet using the `scroll` encoding carries a list
of motion vectors in the `scroll` client option (very old servers overload the packet's
data argument instead). Each entry is a `(x, y, w, h, xdelta, ydelta)` tuple meaning:

> copy the rectangle at `(x, y, w, h)` to `(x+xdelta, y+ydelta)`

The areas which could not be expressed as motion vectors are sent as regular picture
encodings in the packets that follow, using the `flush` option to tell the client
how many more packets belong to the same screen update.

**All the rectangles in the list are relative to the same reference picture: the window
contents as they were before any of them was applied.**
Clients MUST copy from a snapshot of their window backing taken before painting the first
rectangle. The server does not order the list so that it can be applied in place - the
source of one rectangle regularly overlaps the destination of another, and the list can
describe two areas swapping places, which no ordering can satisfy. Applying the rectangles
sequentially in place corrupts the window contents.

The reference implementation is
[xpra.opengl.backing](https://github.com/Xpra-org/xpra/blob/master/xpra/opengl/backing.py):
it copies the FBO once, then blits every rectangle from that copy.
