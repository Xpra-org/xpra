# Cursor


This subsystem synchronizes the pointer cursor between the server's (often virtual) screen
and the client.

The prefix for all packets and capabilities is `cursor`.


## Implementations

| Component         | Link                                                                                                          |
|-------------------|---------------------------------------------------------------------------------------------------------------|
| client            | [xpra.client.subsystem.cursor](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/cursor.py)  |
| client connection | [xpra.server.source.cursor](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/cursor.py)        |
| server            | [xpra.server.subsystem.cursor](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/cursor.py)  |


## Client Capabilities

| Capability     | Type             | Purpose                                                |
|----------------|------------------|--------------------------------------------------------|
| `encodings`    | array of strings | The types of cursor packets that the client can handle |

The supported encodings are:
* `raw`: plain uncompressed `BGRA` pixel data
* `png`: pixel data compressed using lossless full color `PNG`
* `default`: the client can update the default cursor

## Server Capabilities

| Capability     | Type               | Purpose                                   |
|----------------|--------------------|-------------------------------------------|
| `default`      | cursor packet data | The default cursor to use                 |
| `default_size` | integer            | The default size of cursors on the server |
| `max_size`     | pair of integers   | The maximum size of the server cursors    |


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
    'default_size': 45,
    'max_size': [64, 64],
  }
}
```


## Network Packets

| Packet Type  | Arguments          | Purpose                                      |
|--------------|--------------------|----------------------------------------------|
| `cursor-set` | boolean            | Tell the server to enable or disable cursors |
| `cursor`     | cursor packet data | Use the cursor specified                     |

### Cursor Packet Data

TBD
