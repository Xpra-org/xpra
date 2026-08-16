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

## Network Packets

</div>

| Packet Type                  | Direction        | Arguments                                               | Information                                                                              |
|------------------------------|------------------|---------------------------------------------------------|------------------------------------------------------------------------------------------|
| `show-desktop`               | server to client | `show` : boolean                                        | The server is requesting the client to show or hide the desktop                          |
| `desktop_size`               | server to client | `width`: int, `height`: int, `max_w`: int, `max_h`: int | The server has updated its display, the client may need to adjust its scaling properties |
| `display-configure`          | client to server | monitor configuration dictionary                        | The client sends its updated monitor layout to the server                                |
| `display-request-screenshot` | client to server |                                                         | The client requests a screenshot from the server                                         |
| `display-screenshot`         | server to client | `w`, `h`, `encoding`, `rowstride`, `data`                | The server sends a screenshot in response to `display-request-screenshot`                |
| `display-request-icon`       | client to server |                                                         | The client requests the session icon                                                     |
| `display-icon`               | server to client | `w`, `h`, `encoding`, `rowstride`, `data`                | The server sends the session icon                                                        |
