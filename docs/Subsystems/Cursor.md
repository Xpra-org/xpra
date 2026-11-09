# Cursor


This subsystem synchronizes the pointer cursor between the server's (often virtual) screen
and the client.

The prefix for all packets and capabilities is `cursor`.


<div class="docs-section-heading" markdown="1">

## Implementations

</div>

| Component         | Link                                                                                                          |
|-------------------|---------------------------------------------------------------------------------------------------------------|
| client            | [xpra.client.subsystem.cursor](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/cursor.py)  |
| client connection | [xpra.server.source.cursor](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/cursor.py)        |
| server            | [xpra.server.subsystem.cursor](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/cursor.py)  |


<div class="docs-section-heading" markdown="1">

## Client Capabilities

</div>

| Capability     | Type             | Purpose                                                |
|----------------|------------------|--------------------------------------------------------|
| `encodings`    | array of strings | The types of cursor packets that the client can handle |
| `default`      | pair of integers | The client's default cursor size, in server pixels     |
| `max`          | pair of integers | The largest cursor size the client can show            |

The supported encodings are:
* `raw`: uncompressed `RGBA` pixels (4 bytes per pixel, rows of `width * 4` bytes, straight alpha)
* `png`: pixel data compressed using lossless full color `PNG`
* `default`: the client can update the default cursor

<div class="docs-section-heading" markdown="1">

## Server Capabilities

</div>

The server's `cursor` map contains:

| Capability     | Type               | Purpose                                   |
|----------------|--------------------|-------------------------------------------|
| `sizes`        | map                | `default` (pair of integers): the default cursor size on the server; `max` (pair of integers): the largest cursor size |
| `default`      | list               | Only for clients that do not list the `default` encoding: the server's default cursor image, as `x`, `y`, `width`, `height`, `xhot`, `yhot`, `serial`, `pixels` (raw RGBA) and `name` |

### Example capabilities

* Client:
```json lines
{
  'cursor': {
    'encodings': ['raw', 'default', 'png'],
  },
}
```
* X11 seamless server:
```json lines
{
  'cursor': {
    'sizes': {
      'default': [45, 45],
      'max': [64, 64],
    },
  }
}
```


<div class="docs-section-heading" markdown="1">

## Network Packets

</div>

| Packet Type      | Direction        | Arguments          | Purpose                                      |
|------------------|------------------|--------------------|----------------------------------------------|
| `cursor-set`     | client to server | boolean            | Tell the server to enable or disable cursors |
| `cursor-data`    | server to client | cursor packet data | Use the cursor specified                     |
| `cursor-default` | server to client |                    | Restore the default cursor                   |

### Cursor Packet Data

`cursor-data` contains, in order: encoding, width, height, hotspot X, hotspot Y,
serial number, encoded bytes and cursor name. `raw` bytes are RGBA pixels
with straight (not premultiplied) alpha; `png` bytes contain a PNG image. The hotspot must lie within the cursor image.
An empty encoding string means that the server has no cursor encoding in common
with the client: the client should then use its default cursor.
The `serial` changes whenever the cursor image changes, and the `name` is the
cursor theme name when known (ie: `left_ptr`), which a client may use to show its
own native cursor instead.
`cursor-default` asks the client to restore its default cursor.
X11 and Wayland servers older than 7.0 send `png` cursors with the red and blue
channels swapped, and clients older than 7.0 swap them back.
