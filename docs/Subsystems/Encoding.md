# Encoding


This subsystem synchronizes the client and the server's encodings so that each end can use the most appropriate
codecs for exchanging data.


<div class="docs-section-heading" markdown="1">

## Implementations

</div>

| Component         | Link                                                                                                             |
|-------------------|------------------------------------------------------------------------------------------------------------------|
| client            | [xpra.client.subsystem.encoding](https://github.com/Xpra-org/xpra/blob/master/xpra/client/subsystem/encoding.py) |
| client connection | [xpra.server.source.encoding](https://github.com/Xpra-org/xpra/blob/master/xpra/server/source/encoding.py)     |
| server            | [xpra.server.subsystem.encoding](https://github.com/Xpra-org/xpra/blob/master/xpra/server/subsystem/encoding.py) |



<div class="docs-section-heading" markdown="1">

## Capabilities

</div>

The client advertises an `encoding` dictionary. The interoperability fields are:

| Capability | Purpose |
|------------|---------|
| `options` | Encodings the client can accept |
| `core` | Concrete decoder encodings, without aliases |
| `window-icon` | Encodings accepted for window icons |
| `setting` | Requested default encoding |
| `rgb_formats` | Raw RGB pixel formats the backing can paint |
| `full_csc_modes` | Pixel formats the client can decode for each encoding in the video pipeline |
| `quality`, `min-quality` | Requested quality bounds |
| `speed`, `min-speed` | Requested speed bounds |
| `video_max_size` | Maximum video dimensions |
| `batch` | Damage batching parameters |

The `full_csc_modes` map applies to video codecs (`h264`, `h265`, `vp8`, `vp9`,
`av1`) and to picture encodings (`jpeg`, `jpega`, `webp`) when used through the
video pipeline. For example: `{"h264": ["YUV420P"], "jpeg": ["BGRX", "BGRA", "YUV420P"], "jpega": ["BGRA", "RGBA"], "webp": ["BGRX", "BGRA"]}`.
A video codec without an entry is never used. A picture encoding without an
entry is only sent as a plain picture, never through the video pipeline.

Codec profile maps such as `h264` extend these fields. Unknown codec diagnostic
and version fields are advisory.

Any video codec map may also carry a `level` (ie: `h264` → `level` = `4.1`),
which caps the resolution, framerate and bitrate the server's encoder may use,
so that a client with a constrained decoder can ask for a stream it can keep up with.
A `<colourspace>.level` key applies to that colourspace only.
The level is written the same way for every codec, and the server converts it to
whatever its encoder expects. It is a request: a server whose encoder cannot honour
it logs a warning and encodes at the level it would have chosen anyway.
Without this capability, no level is imposed and every encoder signals the lowest
level the stream it is producing actually requires.

<div class="docs-section-heading" markdown="1">

## Network Packets

</div>

| Packet Type | Direction | Arguments | Purpose |
|-------------|-----------|-----------|---------|
| `encoding-set` | client to server | encoding name, optional window IDs | Select an encoding |
| `encoding-set` | server to client | properties dictionary | Publish updated encoding and video specifications |
| `encoding-options` | client to server | options dictionary | Update quality, speed, scaling or batching |
| `encoding-config` | client to server | encoding capability dictionary | Replace the client's decoder configuration |
