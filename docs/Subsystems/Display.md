# Display


This subsystem deals with the synchronization of the client's display and its configuration (ie: `DPI`, `HDR`, etc),
in particular sending updated screen configuration whenever the number of monitors or their configuration changes.

The client may also apply scaling, which changes the display size exposed to the server. \
This can be used to reduce the amount of pixels needed to cover a monitor.

<div class="docs-section-heading" markdown="1">

## Implementations

</div>

| Component         | Link                                                                                                           |
|-------------------|----------------------------------------------------------------------------------------------------------------|
| client            | [xpra.client.subsystem.display](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/display.py) |
| client connection | [xpra.server.source.display](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/display.py)       |
| server            | [xpra.server.subsystem.display](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/display.py) |


<div class="docs-section-heading" markdown="1">

## Capabilities

</div>

The client MUST send a `display` map in its `hello`: the server does not create
any display state for a client without one (and the reference client also expects
one in the server's `hello`). All its keys are optional:

| Key | Type | Information |
|---|---|---|
| `desktop_size` | pair of integers | Size of the whole client display, covering all monitors (after client-side scaling). Each value must be in `1..32767` |
| `desktop_size.unscaled` | pair of integers | The same size before scaling, only when the client scales |
| `monitors` | map | Monitor index (integer) to monitor definition, see below. At most 16 monitors |
| `monitor-relative` | boolean | The client attaches `monitor` descriptors to its window and pointer packets, default `True` |
| `refresh-rate` | integer | Display refresh rate in Hz, `-1` unknown |
| `vrefresh` | integer | Same as `refresh-rate` |
| `dpi` | map | `x` and `y` (integers), and `""` for the average |
| `screen-scaling` | map | `enabled` (boolean) and `values`: the client's horizontal and vertical scaling factors multiplied by 1000. Informational |
| `antialias` | map | Font antialiasing settings: `enabled`, `hinting`, `hintstyle`, `orientation`, `contrast` |
| `desktops` | integer | Number of virtual desktops (workspaces) |
| `desktop.names` | list of strings | Their names |
| `resize-events` | boolean | The client handles `display-resized`, default `True` |
| `show-desktop` | boolean | The client handles `display-show-desktop` |
| `desktop-fullscreen` | boolean | The client shows the remote desktop fullscreen (desktop mode) |
| `icc`, `display-icc` | map | Colour profile information |
| `opengl` | map | The client's OpenGL properties, informational |

Each monitor definition contains any of:

| Key | Type | Information |
|---|---|---|
| `geometry` | 4 integers | `x`, `y`, `width`, `height`, in the same coordinate space as `desktop_size` |
| `workarea` | 4 integers | The part of the monitor not used by panels and docks |
| `primary` | boolean | |
| `name`, `manufacturer`, `model` | string | At most 64 characters |
| `width-mm`, `height-mm` | integer | Physical size |
| `refresh-rate` | integer | In mHz (ie: `60000`); values below `1000` are taken as Hz |
| `scale-factor` | integer | The platform's integer scale factor (`1`, `2`) |
| `subpixel-layout` | string | |
| `depth` | integer | Bit depth |
| `hdr` | boolean | |
| `colorspace` | string | Free-form platform information |
| `colourspace` | map | Preferred colourspace |

The server answers with its own `display` map:

| Key | Type | Information |
|---|---|---|
| `desktop_size` | pair of integers | The display size given to this client: the size it requested when the server could match it, or the closest size available |
| `actual_desktop_size`, `root_window_size` | pair of integers | The server's real display size |
| `max_desktop_size` | pair of integers | The largest display size the server can configure |
| `name`, `address` | string | Display name and address (ie: `:10`) |

A client that scales converts every position and size it exchanges with the server:
positions in the server's packets are in server pixels.

The server advertises its display mode in the top-level `mode` capability:
`shadow`, `desktop`, `monitor`, or `seamless`. Clients prefer this value to the
legacy top-level `shadow`, `desktop`, and `monitor` booleans, falling back to
those flags when `mode` is absent or unrecognized. Servers still send the legacy
flags for older clients.

The top-level `multi-monitors`, `monitors`, and `monitors.add-*` capabilities
describe monitor features and configuration independently of the display mode.
For example, a shadow server can support virtual monitors while its mode remains
`shadow`.



<div class="docs-section-heading" markdown="1">

## Combining the clients' displays

</div>

Normally, every client that shares a session sees the same virtual display:
its size is the largest width and height requested by any of them.

With `--sharing=combine`, the virtual display is instead made large enough to hold
every client's monitors placed side by side, and each client is given its own area of it.

Each client is told that the display is exactly the size of its own area, and
the server translates between the two coordinate spaces:

* the positions the server sends to a client (`window-create`, `window-move-resize`,
  `window-initiate-moveresize`, `pointer-position`) have the origin of that client's area subtracted
* the positions the client sends back are resolved from the `monitor` descriptor
  attached to its `window-map`, `window-configure` and pointer packets, which is
  offset by that same origin

Only the clients that advertise the `monitor-relative` display capability are given an area:
without those monitor relative coordinates, the absolute positions sent by a client could
not be mapped back onto the combined display.
Clients are assumed to send them unless they advertise `monitor-relative=False`,
those are left out of the combined layout and see the whole display, as they would with `sharing=yes`.

`combine` also requires a seamless server whose virtual display can be re-configured with
RandR 1.6 (the `dummy` driver with 16 outputs).
When that requirement is not met, the server warns and shares the display
as it would with `sharing=yes`.

Every window is still sent to every client, so that moving one from one user's screen
to the next is just a metadata update rather than a new window: see
[window](./Window.md) for how the windows outside a client's area are hidden.

Note that each user can only move a window within their own screen, which covers their
own area of the display: a window can straddle the boundary between two areas (and is
then shown by both clients), but pushing it all the way onto another client's area
requires the application itself to move it, or a window manager request.


<div class="docs-section-heading" markdown="1">

## Network Packets

</div>

| Packet Type                  | Direction        | Arguments                                               | Information                                                                              |
|------------------------------|------------------|---------------------------------------------------------|------------------------------------------------------------------------------------------|
| `display-show-desktop`       | server to client | `show` : boolean                                        | The server is requesting the client to show or hide the desktop                          |
| `display-resized`            | server to client | `width`: int, `height`: int, `max_w`: int, `max_h`: int | The server has updated its display, the client may need to adjust its scaling properties |
| `display-configure`          | client to server | configuration dictionary, see below                     | The client sends its updated monitor layout to the server                                |
| `display-request-screenshot` | client to server |                                                         | The client requests a screenshot from the server                                         |
| `display-screenshot`         | server to client | `w`, `h`, `encoding`, `rowstride`, `data`                | The server sends a screenshot in response to `display-request-screenshot`                |
| `display-request-icon`       | client to server |                                                         | The client requests the session icon                                                     |
| `display-icon`               | server to client | `w`, `h`, `encoding`, `rowstride`, `data`                | The server sends the session icon                                                        |

The `display-configure` map is sent whenever the client's monitor layout, DPI or
desktops change. Its keys are hyphenated, unlike the `hello` keys:
`desktop-size` and `desktop-size-unscaled` (pairs), `monitors` (same format as above),
`dpi` (`x`, `y`), `icc` (`global`, `display`), `desktops`, `desktop-names` and
`vrefresh` (Hz, `0..240`).

`display-resized` tells the client the server's new display size and maximum size,
ie: after another client changed it.
