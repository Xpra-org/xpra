# Logging

For usage related information, see [logging usage](../Usage/Logging.md).

The `logging` modules are used for sending log events to the peer.

It is generally used for sending client log messages to the server,
but it can also be used in the opposite direction.

## Implementations

The prefix for all packets and capabilities is `logging`.

| Component         | Link                                                                                                           |
|-------------------|----------------------------------------------------------------------------------------------------------------|
| client            | [xpra.client.subsystem.logging](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/logging.py) |
| client connection | none                                                                                                           |
| server            | [xpra.server.subsystem.logging](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/logging.py) |


## Capabilities

The server exposes two flags using the `remote-logging` capability prefix:
* `receive` if the server is able to receive log events from the client
* `send` if the server is able to send its log events to the client

## Network Packets

| Packet Type       | Arguments                                                                        | Direction        |
|-------------------|----------------------------------------------------------------------------------|------------------|
| `logging-event`   | `level` : integer<br/>`message` : string or list of strings<br/>`time` : integer | both             |
| `logging-control` | `action` : string, only either `start` or `stop`                                 | client to server |

The `logging` packets can be sent to the server if it exposes the `receive` capability,
or sent from the server to the client following a `start` `logging-control` request.
