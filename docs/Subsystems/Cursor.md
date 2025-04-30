# Cursor


This subsystem synchronizes the pointer cursor between the server's (often virtual) screen
and the client.


## Implementations

| Component         | Link                                                                                                         |
|-------------------|--------------------------------------------------------------------------------------------------------------|
| client            | [xpra.client.subsystem.cursor](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/cursor.py) |
| client connection | [xpra.server.source.cursor](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/cursor.py)      |
| server            | [xpra.server.subsystem.cursor](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/cursor.py) |



## Capabilities

| Capability | Type    | Purpose                                    |
|------------|---------|--------------------------------------------|
| `cursors`  | boolean | The client wants to receive cursor updates |


## Network Packets

| Packet Type | Arguments |
|-------------|-----------|
| `cursors`   | TBD       |
