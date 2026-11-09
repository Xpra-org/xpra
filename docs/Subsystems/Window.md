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

With the `sharing=combine` server option, each client owns a distinct area of the
virtual display (see [display](./Display.md#combining-the-clients-displays)).
Every window is still sent to every client, but a client only shows the windows that
intersect its own area: the others have their `iconic`, `skip-taskbar` and `skip-pager`
metadata overridden to `True`, so that they stay out of the way until the window is
moved onto that client's area.
The positions in the window packets exchanged with a client are relative to its area.

Since a hidden window is not shown by that client, it is also treated as unmapped for it:
no pixels are sent for it until it becomes visible again.
The `window-unmap`, `window-map` and `window-configure` packets that a client sends for
a window it cannot see are ignored, so that echoing back the iconification the server
asked for does not hide the window for everyone else.

An X11 seamless server advertises `window.stacking = true`. Clients may then send
their current bottom-to-top window order using `window-stacking`; the topmost window
is the final ID in the list. X11 clients obtain this order from their local window
manager's `_NET_CLIENT_LIST_STACKING` root property, MS Windows clients from the
desktop z-order (`EnumWindows`), watching the `EVENT_OBJECT_REORDER` window event.

macOS clients use `+[NSWindow windowNumbersWithOptions:]`, which is already restricted
to the application's own windows and leaves out the ones which have been ordered out.
There is no macOS equivalent of the two mechanisms above: AppKit posts no public
notification for the z-order, only for the events which usually accompany a change of
it (a window becoming key or main, the application being activated, a window being
miniaturized or occluded), so the client also refreshes the order whenever it
re-stacks a window itself.

An X11 seamless server advertises `window.dismiss = true` when it accepts
`window-dismiss` requests. This packet unmaps an override-redirect popup, which
also releases any X11 keyboard or pointer grabs held on it. Regular windows,
tray icons, windows hidden from the requesting client, and readonly requests
are ignored. The popup's normal unmap handling sends `window-destroy` to clients.
The default `Control+Escape` shortcut releases local grabs and sends this request
for each popup known to the client.

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
| `window-map`   | `wid`, `x`, `y`, `w`, `h`, client properties, state map, monitor map | The client is showing the window                          |
| `window-unmap` | `wid`, optional iconified flag and state             | The client has hidden a window                                           |
| `window-configure` | `wid`, configuration dictionary                | The client has moved or resized a window                                 |
| `window-close` | `wid`                                               | The user has requested to close the window                               |
| `window-dismiss` | `wid`                                             | Unmap an override-redirect popup (`window.dismiss` capability required)  |
| `window-focus` | `wid`, optional modifiers                           | The window has received keyboard focus                                   |
| `window-action`| `wid`, `action`, optional arguments                 | Trigger one of the actions listed in the window's `actions` metadata     |
| `window-stacking` | list of window IDs, bottom-to-top               | Report the client's current stacking order                               |
| `window-refresh`| `wid`, `0`, `quality`, options, client properties  | Request a full refresh of the window contents (`wid` 0: all windows)     |
| `window-signal` | `wid`, signal name                                 | Send a signal to the window's process (`window.signals` capability)      |
| `window-ack`   | `wid`, `width`, `height`, `packet_sequence`, `decode_time`, `message` | Acknowledge receipt and decoding of a `window-draw` packet |

The Win32 native client rebases absolute window positions against the top-left
of its monitor layout. Packets also include the pre-normalization coordinates
as `raw-position` metadata.

<div class="docs-section-heading" markdown="1">

## Window lifecycle

</div>

1. Right after its `hello`, the server sends a `window-create` for every window that
   already exists, then one for each new window. Pixel updates (`window-draw`)
   follow immediately: the client does not need to send anything first.
2. The client shows the window and sends `window-map` with the geometry it actually
   used. The server then applies that geometry and sends a full refresh.
   Override-redirect windows (menus, tooltips: `override-redirect` metadata) are
   never mapped or configured by the client: their position is the server's.
3. Each user-initiated move or resize is sent as a `window-configure`.
   The server moves or resizes windows with `window-move-resize` and
   `window-resized`.
4. A window the user minimizes is sent as `window-unmap` with `iconified=true`;
   showing it again is a new `window-map`. Closing it by the user is a request,
   `window-close`: the application decides, and the window only goes away
   when the server sends `window-destroy`.
5. `window-destroy` ends the window: any later packet for that `wid` is ignored.

All the coordinates and sizes exchanged are in the server's pixel space. A client
that scales the display (see [display](Display.md)) converts them both ways.
Positions are absolute positions on the server's display, unless the client uses
the `monitor-relative` mode described below.

The `resize_counter` sent with `window-move-resize` and `window-resized` is an
opaque server value. The client stores the last one it received for each window
and sends it back as `resize-counter` in its following `window-configure`, so the
server can tell whether the client had seen its latest resize.

<div class="docs-section-heading" markdown="1">

## Server capabilities

</div>

These are found in the server's `window` map, which is only sent to clients that set `server-features`:

| Capability       | Type             | Information                                                         |
|------------------|------------------|---------------------------------------------------------------------|
| `states`         | list of strings  | The `state` map keys the server applies: `iconified`, `focused`, `fullscreen`, `above`, `below`, `sticky`, `maximized` |
| `frame-extents`  | boolean          | The server uses the `frame` value of the state map                  |
| `configure.delta`| boolean          | Advertised by X11 seamless servers, has no defined semantics: ignore it |
| `stacking`       | boolean          | The server accepts `window-stacking`                                |
| `dismiss`        | boolean          | The server accepts `window-dismiss`                                 |
| `signals`        | list of strings  | The signal names accepted by `window-signal`                        |
| `dragndrop`      | boolean          | The server supports drag and drop between client and server windows |

<div class="docs-section-heading" markdown="1">

## Window metadata

</div>

`window-create` and `window-metadata` carry a metadata map. In `window-create`,
**keys whose value equals the default are omitted**: a client MUST start from the
defaults below and apply the map on top. `window-metadata` only carries the keys
that changed. The client chooses the keys it receives with the top-level
`metadata.supported` capability (a list of key names). Without it, the server
sends: `title`, `icon-title`, `pid`, `iconic`, `size-constraints`, `class-instance`,
`client-machine`, `transient-for`, `window-type`, `fullscreen`, `maximized`,
`decorations`, `skip-taskbar`, `skip-pager`, `has-alpha`, `override-redirect`,
`tray`, `modal`, `role`, `opacity`, `xid`, `group-leader`, `opaque-region`,
`command`, `workspace`, `above`, `below`, `sticky`, `attention-requested`,
`set-initial-position`, `requested-position`, `content-types`, `parent`,
`relative-position`, `actions` and `colourspace`.
Keys a client does not recognise MUST be ignored.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `title` | string | `""` | Window title (UTF-8) |
| `icon-title` | string | `""` | Title to show when iconified |
| `class-instance` | pair of strings | `("", "")` | X11 `WM_CLASS`: instance then class name |
| `app-id` | string | `""` | Application identifier (Wayland, desktop file name) |
| `role` | string | `""` | X11 `WM_WINDOW_ROLE` |
| `command` | string | `""` | Command line of the application |
| `client-machine` | string | `""` | Host the application runs on |
| `locale` | string | `""` | Locale of the application |
| `pid`, `ppid`, `wm-pid` | integer | `0` | Process ids, `0` when unknown |
| `xid`, `hwnd` | integer | `0` | Native window identifiers on the server |
| `window-type` | list of strings | `()` | Window types, most specific first: `NORMAL`, `DIALOG`, `UTILITY`, `MENU`, `DROPDOWN_MENU`, `POPUP_MENU`, `TOOLTIP`, `NOTIFICATION`, `SPLASH`, `TOOLBAR`, `DOCK`, `DESKTOP`, `COMBO`, `DND` (the EWMH names without the `_NET_WM_WINDOW_TYPE_` prefix) |
| `override-redirect` | boolean | `False` | Unmanaged window: popup, menu or tooltip, placed by the server |
| `transient-for` | window id | absent | The window this one belongs to (dialogs) |
| `parent` | window id | absent | Parent window |
| `group-leader` | window id | absent | Group leader; may not match any window the client knows |
| `relative-position` | pair of integers | `()` | Position relative to `parent` |
| `children` | list of window ids | `()` | Child windows |
| `size-constraints` | map | `{}` | See below |
| `set-initial-position` | boolean | `False` | `requested-position` should be honoured |
| `requested-position` | pair of integers | `()` | The position the application asked for |
| `decorations` | integer | `-1` | Motif decoration hints: `-1` unset, `0` undecorated, other values decorated |
| `opacity` | integer | `-1` | `-1` unset, otherwise `0` (transparent) to `0xffffffff` (opaque) |
| `has-alpha` | boolean | `False` | The window has an alpha channel |
| `opaque-region` | list of rectangles | `()` | Areas that are fully opaque despite `has-alpha` |
| `depth` | integer | `24` | Bit depth |
| `colourspace` | map | sRGB | The colourspace of the window's pixels |
| `iconic` | boolean | `False` | The window is minimized |
| `maximized` | boolean | `False` | |
| `fullscreen` | boolean | `False` | |
| `fullscreen-monitors` | list of 4 integers | `()` | EWMH `_NET_WM_FULLSCREEN_MONITORS` |
| `above`, `below` | boolean | `False` | Stacking hints |
| `sticky` | boolean | `False` | Shown on all workspaces |
| `shaded` | boolean | `False` | |
| `skip-taskbar`, `skip-pager` | boolean | `False` | Keep out of the taskbar / pager |
| `modal` | boolean | `False` | Modal dialog for `transient-for` |
| `focused` | boolean | `False` | The window has the input focus on the server |
| `attention-requested` | boolean | `False` | Urgency hint |
| `workspace` | integer | `65535` | Workspace number, `65535` unset, `0xffffffff` all |
| `bypass-compositor` | integer | `0` | `0` no preference, `1` bypass, `2` do not bypass |
| `quality`, `speed` | integer | `-1` | Encoding preferences for this window, `-1` automatic |
| `content-types` | list of strings | `()` | Content hints such as `text`, `video`, `browser` |
| `tray` | boolean | `False` | This is a system tray icon (requires the `system_tray` capability) |
| `shadow` | boolean | `False` | The window shows a whole remote display (shadow servers) |
| `desktop` | boolean | `False` | The window shows a whole remote desktop |
| `actions` | list of strings | `()` | Names accepted by `window-action` for this window |
| `allowed-actions` | list of strings | `()` | EWMH `_NET_WM_ALLOWED_ACTIONS` |
| `protocols` | list of strings | `()` | X11 `WM_PROTOCOLS` |
| `state` | list of strings | `()` | Raw EWMH state names |
| `frame` | list of 4 integers | `()` | Frame extents: left, right, top, bottom |
| `shape` | map | `{}` | X11 shape rectangles |
| `strut` | map | `{}` | Reserved screen edges |

Window ids in `transient-for`, `parent` and `children` refer to other windows of
the same session. A client MUST cope with references to windows it does not know
(yet), for example by ignoring them.

The `size-constraints` map contains any of:

| Key | Type | Meaning |
|---|---|---|
| `minimum-size` | pair of integers | Minimum width and height |
| `maximum-size` | pair of integers | Maximum width and height |
| `base-size` | pair of integers | Base size for `increment` |
| `increment` | pair of integers | Resize step |
| `minimum-aspect-ratio`, `maximum-aspect-ratio` | pair of integers | Numerator and denominator |
| `gravity` | integer | X11 window gravity |

For readonly clients, the server sets the minimum and maximum sizes to the
current size.

<div class="docs-section-heading" markdown="1">

## Client side maps

</div>

**`window-map` and `window-configure` state map:** any of `iconified`, `maximized`,
`fullscreen`, `above`, `below`, `sticky`, `shaded`, `skip-pager`, `skip-taskbar`,
`focused` (booleans) and `frame` (4 integers: left, right, top, bottom). Only send
the keys whose value changed, and only the ones listed in the server's `window.states`.

**Monitor map:** `{"index": int, "position": [x, y]}`, the client monitor the window
is on and its position relative to that monitor. It is sent by clients that advertise
`display.monitor-relative` and lets the server resolve absolute positions itself.

**`window-configure` map:**

| Key | Type | Meaning |
|---|---|---|
| `geometry` | 4 integers | `x`, `y`, `w`, `h`; omit it when only the state changed |
| `resize-counter` | integer | The last `resize_counter` received for this window |
| `monitor` | map | Monitor map, as above |
| `state` | map | State map, as above |
| `properties` | map | Updated client properties, see below |
| `pointer` | map | Pointer position when the configure was caused by a pointer drag: `wid`, `position`, `device-id`, `properties` (with `modifiers`) |
| `drive` | boolean | `True` (the default) when the change comes from the user: the server then treats this client as the one in control |

**Client properties:** a map of per-window client settings, sent with `window-map`,
`window-configure` (`properties`) and `window-refresh`. The server echoes them back
in `window-create` when another client created the window. Known keys:
`workspace` (integer), `encoding.render-size` (pair), `encoding.transparency` (boolean,
false when the client window cannot show alpha), `encoding.full_csc_modes`,
`encodings`, `encodings.core`, `encodings.rgb_formats` (per-window overrides of the
`encoding` capabilities), `encoding.auto_refresh_encodings`, `encoding.full_frames_only`,
`bit-depth` and `decoder-speed`.

<div class="docs-section-heading" markdown="1">

## Constants

</div>

`window-initiate-moveresize` `direction` (EWMH `_NET_WM_MOVERESIZE`):

| Value | Direction | Value | Direction |
|---:|---|---:|---|
| 0 | size top-left | 6 | size bottom-left |
| 1 | size top | 7 | size left |
| 2 | size top-right | 8 | move |
| 3 | size right | 9 | size with keyboard |
| 4 | size bottom-right | 10 | move with keyboard |
| 5 | size bottom | 11 | cancel |

Its `source` is `0` unset, `1` normal application, `2` pager.

`window-restack` `detail` uses the X11 stack modes: `0` above, `1` below, `2` top-if,
`3` bottom-if, `4` opposite, relative to `sibling` (`0` for none). Clients that do
not advertise `window.restack` receive `window-raise` instead, for `detail=0` only.

`window-bell` carries the X11 XKB bell attributes: `percent` is the volume from
`-100` to `100`, `pitch` is in Hz and `duration` in milliseconds.

<div class="docs-section-heading" markdown="1">

## Window icons

</div>

`window-icon` carries `png` data, or `default` with an empty payload and a zero size
when the window has no icon of its own (only for `greedy` clients that list `default`).
The client selects the icon encodings with `encoding.window-icon`, and may
add an `encoding.icons` map with `size` (preferred size, default 64x64),
`max_size`, `greedy` (the client has no default icon of its own: always send one,
the server's fallback icon if needed) and `default.icons` (the `WM_CLASS` names
for which the client already has a themed icon, so the server does not send one).

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
