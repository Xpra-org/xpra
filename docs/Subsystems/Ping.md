# Ping


<div class="docs-section-heading" markdown="1">

## Implementations

</div>

| Component         | Link                                                                                                                     |
|-------------------|--------------------------------------------------------------------------------------------------------------------------|
| client            | [xpra.client.subsystem.ping](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/ping.py)         |
| client connection | [xpra.server.source.ping](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/ping.py)       |
| server            | [xpra.server.subsystem.ping](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/ping.py) |


<div class="docs-section-heading" markdown="1">

## Capabilities

</div>


<div class="docs-section-heading" markdown="1">

## Network Packets

</div>

Both packet types may flow in either direction.

| Packet Type | Arguments |
|-------------|-----------|
| `ping` | monotonic timestamp in milliseconds, optional source ID |
| `ping-echo` | echoed timestamp, 1/5/15-minute loads scaled by 1000, latency in milliseconds, optional source ID |

The timestamp correlates the response with the request; it is not wall-clock
time. A negative latency means that no latency measurement is available.
