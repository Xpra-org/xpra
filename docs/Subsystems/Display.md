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

| Capability              | Value                       | Information                             |
|-------------------------|-----------------------------|-----------------------------------------|
| `desktop_size`          | `width`: int, `height`: int | The display size, covering all monitors |
| `screen_sizes`          | list of screens             | Geometry of all screens, scaled         |
| `screen_sizes.unscaled` | list of screens             | Unscaled geometry of all screens        |
| `monitors`              | list of monitors            | Geometry of all monitors                |
| `dpi`                   | dictionary                  | DPI configuration                       |



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

This is why `combine` requires `XPRA_BACKWARDS_COMPATIBLE=0`: without those monitor
relative coordinates, the absolute positions sent by two different clients would be
indistinguishable and could not be mapped back onto the combined display.
It also requires a seamless server whose virtual display can be re-configured with
RandR 1.6 (the `dummy` driver with 16 outputs).
When any of those requirements is not met, the server warns and shares the display
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
| `display-configure`          | client to server | monitor configuration dictionary                        | The client sends its updated monitor layout to the server                                |
| `display-request-screenshot` | client to server |                                                         | The client requests a screenshot from the server                                         |
| `display-screenshot`         | server to client | `w`, `h`, `encoding`, `rowstride`, `data`                | The server sends a screenshot in response to `display-request-screenshot`                |
| `display-request-icon`       | client to server |                                                         | The client requests the session icon                                                     |
| `display-icon`               | server to client | `w`, `h`, `encoding`, `rowstride`, `data`                | The server sends the session icon                                                        |
