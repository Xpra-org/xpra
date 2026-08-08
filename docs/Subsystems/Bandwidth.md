# Bandwidth Subsystem


This subsystem allows the client to tell the server about bandwidth constraints.


<div class="docs-section-heading" markdown="1">

## Implementations

</div>

| Component         | Link                                                                                                           |
|-------------------|----------------------------------------------------------------------------------------------------------------|
| client            | [xpra.client.subsystem.bandwidth](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/bandwidth.py) |
| client connection | [xpra.server.source.bandwidth](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/bandwidth.py)           |
| server            | [xpra.server.subsystem.bandwidth](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/bandwidth.py)     |


<div class="docs-section-heading" markdown="1">

## Capabilities

</div>

| Capability            | Type    | Purpose                                                |
|-----------------------|---------|--------------------------------------------------------|
| `bandwidth-limit`     | integer | The desired bandwidth limit in bits per second         |
| `bandwidth-detection` | boolean | Whether the client wants to enable bandwidth detection |


<div class="docs-section-heading" markdown="1">

## Network Packets

</div>

Only one packet type can be sent to the server.

| Packet Type       | Arguments                  | Purpose                                               |
|-------------------|----------------------------|-------------------------------------------------------|
| `bandwidth-limit` | `limit` in bits per second | The client can update the bandwidth limit at any time |
