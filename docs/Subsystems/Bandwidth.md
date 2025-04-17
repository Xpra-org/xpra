# Bandwidth Subsystem


This subsystem allows the client to tell the server about bandwidth constraints.


## Implementations

| Component         | Link                                                                                                           |
|-------------------|----------------------------------------------------------------------------------------------------------------|
| client            | [xpra.client.subsystem.bandwidth](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/bandwidth.py) |
| client connection | [xpra.server.source.bandwidth](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/bandwidth.py)           |
| server            | [xpra.server.subsystem.bandwidth](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/bandwidth.py)     |


## Capabilities

| Capability            | Type    | Purpose                                                |
|-----------------------|---------|--------------------------------------------------------|
| `bandwidth-limit`     | integer | The desired bandwidth limit in bits per second         |
| `bandwidth-detection` | boolean | Whether the client wants to enable bandwidth detection |


## Network Packets

Only one packet type can be sent to the server.

| Packet Type       | Arguments                  | Purpose                                               |
|-------------------|----------------------------|-------------------------------------------------------|
| `bandwidth-limit` | `limit` in bits per second | The client can update the bandwidth limit at any time |
