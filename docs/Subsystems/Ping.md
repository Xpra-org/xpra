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

The client sets the top-level `ping` capability to `True` when it answers `ping`
packets. The server only pings clients that do.


<div class="docs-section-heading" markdown="1">

## Network Packets

</div>

Both packet types may flow in either direction.

| Packet Type | Arguments |
|-------------|-----------|
| `ping` | monotonic timestamp in milliseconds, wall-clock time in milliseconds, source ID |
| `ping-echo` | echoed timestamp, 1/5/15-minute loads scaled by 1000, latency in milliseconds, echoed source ID |

The monotonic timestamp correlates the response with the request; it is not
wall-clock time. The source ID identifies the sender of the `ping`: the
`ping-echo` MUST echo both the timestamp and the source ID, the server ignores
echoes carrying any other source ID. The latency in a `ping-echo` is the
latency the sender of the echo measured from its own pings, in milliseconds: a
negative value means that no measurement is available. Load averages that are
not available are sent as zero.

The server pings each client every 5 seconds (the `pings` option), starting
5 seconds after the handshake. If no echo for a ping arrives within 60 seconds,
it disconnects the client with `client ping timeout`. A client SHOULD answer
immediately, from its network thread if it has one, rather than after its other
pending work.

Clients may also ping the server to measure latency: the server answers every
`ping` with a `ping-echo`.
