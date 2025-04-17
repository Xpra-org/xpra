# Cursor


This subsystem synchronizes the client and the server's encodings so that each end can use the most appropriate
codecs for exchanging data.


## Implementations

| Component         | Link                                                                                                           |
|-------------------|----------------------------------------------------------------------------------------------------------------|
| client            | [xpra.client.subsystem.cursors](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/cursors.py) |
| client connection | [xpra.server.source.cursors](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/cursors.py)       |
| server            | [xpra.server.subsystem.cursors](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/cursors.py) |



## Capabilities

| Capability | Type    | Purpose                                    |
|------------|---------|--------------------------------------------|
| `cursors`  | boolean | The client wants to receive cursor updates |


## Network Packets

| Packet Type | Arguments |
|-------------|-----------|
| `cursors`   | TBD       |
