# ![sound](../images/icons/sound.png) Audio Subsystem

For usage related information, see [audio feature](../Features/Audio.md).


## Implementations

The prefix for all packets and capabilities is `audio`.

| Component         | Link                                                                                                 |
|-------------------|------------------------------------------------------------------------------------------------------|
| client            | [xpra.client.mixins.audio](https://github.com/Xpra-org/xpra/blob/master/xpra/client/mixins/audio.py) |
| client connection | [xpra.server.source.audio](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/audio.py) |
| server            | [xpra.server.mixins.audio](https://github.com/Xpra-org/xpra/blob/master/xpra/server/mixins/audio.py) |

## Common

[xpra.audio](https://github.com/Xpra-org/xpra/tree/master/xpra/audio/) contains the components used for capturing and playing back audio streams
using [GStreamer](https://gstreamer.freedesktop.org/). \
In order to avoid interfering with the performance of the main thread,
all audio processing is done in a separate process. \
For historical reasons, this is done using a [subprocess wrapper](https://github.com/Xpra-org/xpra/tree/master/xpra/audio/wrapper.py)
rather than the builtin [multiprocessing](https://docs.python.org/3/library/multiprocessing.html) module.

### Pulseaudio

[xpra.audio.pulseaudio](https://github.com/Xpra-org/xpra/tree/master/xpra/audio/pulseaudio) is often used for playback on Linux systems. \
This is also the prefered backend for audio capture in server sessions.
The xpra server will usually start a pulseaudio instance hidden away
in a per-session user prefix so that multiple sessions can forward audio streams
independently.

## Capabilities

The client and server should expose the following capabilities in their `hello` packet
with the `audio` prefix:

| Capability | Type            | Purpose                                            |
|------------|-----------------|----------------------------------------------------|
| `decoders` | List of strings | The audio formats that can be received and decoded |
| `encoders` | List of strings | The audio formats that can be encoded and sent     |
| `send`     | boolean         | If sending audio is enabled                        |
| `receive`  | boolean         | If receiving audio is enabled                      |

The lists of `decoders` and `encoders` contain strings such as: `mp3`, `opus+ogg`, `vorbis`... \
You can run [xpra.audio.gstreamer_util](https://github.com/Xpra-org/xpra/blob/master/xpra/audio/gstreamer_util.py) to see which
encoders and decoders are available on the system.


## Network Packets

This protocol is identical in both directions.
Audio being forwarded from the server to the client (aka "_speaker forwarding_")
uses the same packets as audio coming from the client to the server (aka "_microphone forwarding_").

| Packet Type          | Arguments                                                                                    | Purpose                    | Information                                                                                                                      |
|----------------------|----------------------------------------------------------------------------------------------|----------------------------|----------------------------------------------------------------------------------------------------------------------------------|
| `sound-data`         | `codec` : string <br/>`data` : bytes<br/>`attributes` : dictionary                           | Audio stream data          | The initial and final packets may omit the `data` argument and should set the `start-of-stream` / `end-of-stream` attributes     |
| `sound-control`      | `subcommand` : string<br/>(ie: `start`, `stop`, `sync`, `new-sequence`)<br/>`argument` : Any | Send a request to the peer |
