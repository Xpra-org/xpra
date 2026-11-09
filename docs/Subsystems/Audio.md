# Audio Subsystem

For usage related information, see [audio feature](../Features/Audio.md).


<div class="docs-section-heading" markdown="1">

## Implementations

</div>

The prefix for all packets and capabilities is `audio`.

| Component         | Link                                                                                                 |
|-------------------|------------------------------------------------------------------------------------------------------|
| client            | [xpra.client.subsystem.audio](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/audio.py) |
| client connection | [xpra.server.source.audio](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/audio.py) |
| server            | [xpra.server.subsystem.audio](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/audio.py) |

<div class="docs-section-heading" markdown="1">

## Common

</div>

[xpra.audio](https://github.com/Xpra-org/xpra/tree/master/xpra/audio/) contains the components used for capturing and playing back audio streams
using [GStreamer](https://gstreamer.freedesktop.org/). \
In order to avoid interfering with the performance of the main thread,
all audio processing is done in a separate process. \
For historical reasons, this is done using a [subprocess wrapper](https://github.com/Xpra-org/xpra/tree/master/xpra/audio/wrapper.py)
rather than the builtin [multiprocessing](https://docs.python.org/3/library/multiprocessing.html) module.

### Pulseaudio

[xpra.audio.pulseaudio](https://github.com/Xpra-org/xpra/tree/master/xpra/audio/pulseaudio) is often used for playback on Linux systems. \
This is also the preferred backend for audio capture in server sessions.
The xpra server will usually start a pulseaudio instance hidden away
in a per-session user prefix so that multiple sessions can forward audio streams
independently.

<div class="docs-section-heading" markdown="1">

## Capabilities

</div>

Discovering the audio codecs available can take a while, so the capabilities are
exchanged asynchronously. The client's `hello` only contains `audio: {"async": true}`.
Once its audio codecs are known, the client sends an `audio-capabilities` packet,
and the server answers with its own `audio-capabilities` packet once its audio
subsystem is ready. Both contain:

| Capability | Type            | Purpose                                            |
|------------|-----------------|----------------------------------------------------|
| `decoders` | List of strings | The audio formats that can be received and decoded |
| `encoders` | List of strings | The audio formats that can be encoded and sent     |
| `send`     | boolean         | If sending audio is enabled                        |
| `receive`  | boolean         | If receiving audio is enabled                      |
| `level`, `signal` | boolean  | The peer accepts `audio-level` / `audio-signal` packets |
| `stream-packet` | boolean    | The peer accepts `audio-stream` packets            |
| `keepalive` | boolean        | The peer will echo `audio-keepalive` packets, see below |
| `keepalive.interval`, `keepalive.timeout` | integer | In seconds, `5` and `10` by default |

Codec names are a codec optionally followed by `+` and a container:
`opus+ogg`, `opus+mka`, `opus+rtp`, `vorbis+ogg`, `vorbis+mka`, `flac+ogg`,
`aac+mpeg4`, `mp3`, `mp3+mpeg4`, `mp3+id3v2`, `wav`, `wav+lz4`, `wavpack`.
The `data` of `audio-data` packets is the stream exactly as produced by the
corresponding GStreamer muxer: a receiver feeds the packets, in order, to a demuxer
and decoder for that format. `opus+ogg` is the usual choice.

**Starting and stopping:** speaker forwarding is started by the client: it sends
`audio-control "start" <codec>` when it is ready to play the stream. It stops it with
`audio-control "stop" <sequence>`, followed by `audio-control "new-sequence" <sequence+1>`.
Each stream has a sequence number, sent in the `audio-data` metadata (`sequence`):
packets with an older sequence number belong to a stream that has been stopped
and MUST be discarded. The other `audio-control` commands are `fadein [codec, ms]`
and `fadeout [ms]`, plus `sync` and `av-sync-delta` when audio-video synchronization
is enabled.

The `audio-data` metadata also contains `time`: the sender's monotonic clock, in
milliseconds, when the data was captured.

**Keepalive:** a peer that advertised `keepalive` MUST, while it receives a stream,
send `audio-keepalive <time>` every `keepalive.interval` seconds, echoing the latest
`time` value it received. A sender whose stream is not echoed within
`keepalive.timeout` seconds stops it, or drops data until the echoes resume.

You can run [xpra.audio.gstreamer_util](https://github.com/Xpra-org/xpra/blob/master/xpra/audio/gstreamer_util.py) to see which
encoders and decoders are available on the system.


<div class="docs-section-heading" markdown="1">

## Network Packets

</div>

This protocol is identical in both directions.
Audio being forwarded from the server to the client (aka "_speaker forwarding_")
uses the same packets as audio coming from the client to the server (aka "_microphone forwarding_").

| Packet Type     | Arguments                                                                                    | Purpose                    | Information                                                                                                                      |
|-----------------|----------------------------------------------------------------------------------------------|----------------------------|----------------------------------------------------------------------------------------------------------------------------------|
| `audio-stream`  | `event` : string (`start` or `end`)<br/>`codec` : string<br/>`sequence` : integer            | Start or end of a stream   | Only sent to peers advertising the `stream-packet` audio capability                                                              |
| `audio-data`    | `codec` : string <br/>`data` : bytes<br/>`attributes` : dictionary                           | Audio stream data          | Older peers send initial and final packets without `data`, using the `start-of-stream` / `end-of-stream` attributes instead of `audio-stream` |
| `audio-control` | `subcommand` : string<br/>(ie: `start`, `stop`, `sync`, `new-sequence`)<br/>`argument` : Any | Send a request to the peer | |
| `audio-capabilities` | capabilities dictionary | Update audio formats and directions | Sent when asynchronous audio capability discovery completes |
| `audio-keepalive` | `time` of the latest `audio-data` received | Keep an active stream alive | Either direction |
| `audio-level` | sample dictionary | Publish meter values | Server to client when requested |
| `audio-signal` | boolean | Publish whether a non-silent signal is present | Server to client when requested |
