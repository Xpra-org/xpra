# ![Webcam](../images/icons/webcam.png) Webcam

For usage related information, see [webcam feature](../Features/Webcam.md).


## Implementations

The prefix for all packets and capabilities is `webcam`.

| Component         | Link                                                                                                   |
|-------------------|--------------------------------------------------------------------------------------------------------|
| client            | [xpra.client.mixins.webcam](https://github.com/Xpra-org/xpra/blob/master/xpra/client/mixins/webcam.py) |
| client connection | [xpra.server.source.webcam](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/webcam.py) |
| server            | [xpra.server.mixins.webcam](https://github.com/Xpra-org/xpra/blob/master/xpra/server/mixins/webcam.py) |


## Capabilities

The client exposes a single `webcam` boolean capability. \
The server exposes the following attributes using the  `webcam` capability prefix:
* `enabled` boolean
* `encodings` list of strings - encodings supported: only `png` or `jpeg` are guaranteed to be supported
* `devices` integer - the number of virtual video devices available


## Network Packets

| Packet Type           | Arguments                                                      | Direction        |
|-----------------------|----------------------------------------------------------------|------------------|
| `webcam-start`        | `device_id`, `width`, `height`                                 | client to server |
| `webcam-ack`          | `unused`, `frame_no`, `width`, `height`                        | server to client |
| `webcam-frame`        | `device_id`, `frame_no`, `encoding`, `width`, `height`, `data` | client to server |
| `webcam-stop`         | `device_no`                                                    |

`device_id`, `frame_no`, `width` and `height` are always integers, `encoding` is a string.

The `device_id` must be smaller than the number of virtual video `devices`.


### Flow

* client requests `webcam-start`
* the server responds with a `webcam-ack` for `frame_no` 0, the `width` and `height` may be different from the one requested
* the client can then send a `webcam-frame` for `frame_no` 1
* the server responds with a `webcam-ack` for each frame it receives
* the client must wait for the `webcam-ack` before sending the next frame
* whenever the client decides to stop forwarding the webcam, it must send a `webcam-stop` packet

If any of these steps fail, a `webcam-stop` packet must be sent to the peer.
