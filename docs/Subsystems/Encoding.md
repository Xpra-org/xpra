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

The client advertises an `encoding` map in its `hello`, and can replace it later
with an `encoding-config` packet. Only `options`, `core` and `rgb_formats` are
needed by a client that wants windows; everything else has a server default.

| Key | Type | Default | Purpose |
|---|---|---|---|
| `options` | list of strings | none, REQUIRED | Encodings the client accepts, including the pseudo encodings `rgb`, `grayscale` and `stream` |
| `core` | list of strings | `options` | The encodings its decoders actually implement: `rgb24` and `rgb32` rather than `rgb`. A client that wants windows but has no core encodings is rejected |
| `rgb_formats` | list of strings | none, REQUIRED for `rgb` | Pixel formats the client can paint `rgb24` / `rgb32` data in, see below |
| `rgb_lz4`, `rgb_zstd` | boolean | `False` | The client can decompress `rgb` pixel data compressed with LZ4 / Zstandard |
| `transparency` | boolean | `True` | The client can show windows with alpha |
| `window-icon` | list of strings | `()` | Encodings accepted for `window-icon`: `png`, and `default` |
| `icons` | map | `{}` | Window icon preferences, see [window icons](Window.md#window-icons) |
| `setting` | string | none | The encoding the user selected, if any |
| `quality`, `min-quality` | integer `1..100` | server defaults | Requested quality |
| `speed`, `min-speed` | integer `0..100` | server defaults | Requested speed |
| `scaling.control` | integer `0..100` | automatic | How eagerly the server may downscale video, `0` never |
| `full_csc_modes` | map | `{}` | For each encoding decoded through the video pipeline, the pixel formats the decoder can output, ie: `{"h264": ["YUV420P"], "jpeg": ["BGRX", "BGRA", "YUV420P"], "jpega": ["BGRA", "RGBA"]}`. A video encoding without an entry is never used |
| `video_max_size` | pair of integers | `(8192, 8192)` | Largest video frame the decoders can handle |
| `video_b_frames` | list of strings | `()` | Video encodings for which the client can handle B-frames (delayed frames) |
| `batch` | map | server defaults | Damage batching: `always`, `min_delay`, `max_delay`, `max_events`, `max_pixels`, `time_unit`, `delay` |
| `auto_refresh_encodings` | list of strings | automatic | Encodings to use for the lossless refresh after lossy updates |
| `full_frames_only` | boolean | `False` | Always send whole window frames, never sub-regions |
| `bit-depth` | integer | `24` | Bit depth of the client windows |
| `render-size` | pair of integers | none | The size the client renders windows at, when it scales them |
| `decoder-speed` | map | `{}` | Per-encoding relative decoding speed hints |
| `send-timestamps` | boolean | `False` | Add the server timestamp `ts` to the draw options |
| `max-soft-expired` | integer `0..100` | `5` | How many times in a row the server may send a delayed update despite a backlog of unacknowledged draws, before it waits for acknowledgements |
| `<codec>` | map | none | Codec profile maps, see below |

The `rgb_formats` names describe the byte order in memory: `BGRX` means that the
first byte of each pixel is blue, then green, red, and an unused byte. The usual
values are `BGRX`, `BGRA`, `RGBX`, `RGBA` (32 bits per pixel), `BGR`, `RGB`
(24 bits per pixel), `r210` and `BGR565`. Formats with an alpha channel are only
used for windows with `has-alpha` metadata when `transparency` is enabled.

A minimal client which can decode `png` and raw pixels sends:

```json
{
  "encoding": {
    "options": ["rgb", "png"],
    "core": ["rgb24", "rgb32", "png"],
    "rgb_formats": ["BGRX", "BGRA", "RGBX", "RGBA"],
    "rgb_lz4": true,
    "transparency": false,
    "window-icon": ["png"]
  }
}
```

The server's `hello` contains `encoding`, the encoding it selected (`auto` by
default). Its full list of encodings may take a moment to compute, so it is sent
in an `encoding-set` packet, right after the `hello` and again whenever it changes:

```text
["encoding-set", {"encodings": {"": [...], "core": [...], "with_quality": [...], ...}, "video": {...}}]
```

`encodings` lists what the server can send (with `rgb`, `grayscale` and the other
pseudo encodings), `encodings.core` the actual encodings. `with_speed`, `with_quality`
and `with_lossless_mode` list the encodings whose speed, quality or lossless mode the
user can tune, and `min-quality` and `min-speed` are the server's lower bounds.
`video` describes the server's video encoders, and is informational for clients.

The `h264` profile map accepts `<colourspace>.profile` (ie: `YUV420P.profile`
= `high`), `fast-decode` and `poc-type-2` (booleans). `poc-type-2` asks for
streams whose output order is the decoding order: servers assume it is needed when
it is missing.

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

<div class="docs-section-heading" markdown="1">

## Picture data

</div>

A `window-draw` packet paints the rectangle `x`, `y`, `w`, `h` of the window
`wid` (in window coordinates) with `data`, encoded using `encoding`. `rowstride`
only applies to raw pixel data and is zero otherwise. The options map tells the
client how to decode and when to present the result:

| Option | Type | Meaning |
|---|---|---|
| `flush` | integer | Number of draw packets still to come for the same screen update. The client SHOULD only present the window once it receives a packet with `flush` absent or zero |
| `rgb_format` | string | Pixel format of `rgb24`, `rgb32` and `mmap` data. Absent means `RGB` for `rgb24` and `RGBX` for `rgb32` |
| `lz4`, `zstd` | integer | The pixel data is compressed with this algorithm, the value is the compression level (informational). At most one is present |
| `scaled_size` | pair of integers | The picture was encoded at this size: the client upscales it to `w` x `h` |
| `window-size` | pair of integers | The server window size when the picture was captured |
| `scroll` | list | Motion vectors, see [the `scroll` encoding](Window.md#the-scroll-encoding) |
| `chunks` | list | `mmap` only: `(offset, length)` pairs, see [mmap](MMAP.md) |
| `transparency` | integer | `png/P` and `png/L`: this palette index or grey value is transparent |
| `has_alpha` | boolean | `webp`: the picture has an alpha channel |
| `alpha` | boolean | `avif`: the picture has an alpha channel |
| `alpha-offset` | integer | `jpega`: offset of the alpha plane, see below |
| `csc` | string | Video only: pixel format of the decoded frames, ie: `YUV420P` (the default), `YUV444P`, `NV12` |
| `full-range` | boolean | YUV data uses the full `0..255` range instead of the studio range |
| `frame` | integer | Video only: frame number in the stream, `0` starts a new stream |
| `type` | string | Video only: frame type, `IDR`, `I`, `P` or `B` |
| `delayed` | integer | Video only: frames held back by the encoder. A decoder that outputs nothing for this frame is not an error |
| `paint` | boolean | `False`: decode the frame but do not paint it |
| `quality` | integer | Informational, the quality used to encode the picture |

Other keys, such as `speed`, `subsampling`, `profile`, `encoder`, `pts`, `ts`,
`csc-type` or `scaling-quality`, are diagnostic and MAY be ignored.

### Encodings

| Encoding | `data` |
|---|---|
| `rgb24`, `rgb32` | Raw pixels in `rgb_format`, `h` rows of `rowstride` bytes each (`rowstride` may include padding). The number of bytes per pixel is the length of the `rgb_format` name, not the encoding name: `rgb24` pixels are often sent as 4-byte `BGRX`. When `lz4` is present: a 4-byte little-endian uncompressed size followed by one LZ4 block. When `zstd` is present: one Zstandard frame |
| `png`, `png/P`, `png/L` | A complete PNG file. `png/P` is palette based, `png/L` greyscale |
| `jpeg` | A complete JPEG (JFIF) file |
| `jpega` | A colour JPEG file immediately followed by a greyscale JPEG file holding the alpha channel, which starts at `alpha-offset` |
| `webp` | A complete WebP file, lossy or lossless |
| `avif` | A complete AVIF file |
| `jph` | A High Throughput JPEG 2000 (HTJ2K) codestream |
| `h264`, `h265` | One access unit in Annex B format (start codes). HEVC is called `h265` on the wire |
| `vp8`, `vp9` | One compressed frame, without any container (no IVF header) |
| `av1` | One temporal unit in the low-overhead OBU bitstream format |
| `scroll` | Empty, the motion vectors are in the `scroll` option |
| `mmap` | Empty, the pixels are in the shared memory area |

`rgb24` and `rgb32` are both advertised as `rgb` in `options`: the server uses
`rgb32` for windows with an alpha channel, `rgb24` for the others. `grayscale` is a pseudo encoding which asks the server
to drop the colour information. The container stream encodings such as `h264+mp4`
or `vp8+webm` (pseudo encoding `stream`) are not specified here and SHOULD NOT be
advertised by other implementations.

When a draw packet cannot be decoded, the client MUST still acknowledge it with
the decode error code (see below) so the server can send a replacement.

<div class="docs-section-heading" markdown="1">

## Acknowledgements and flow control

</div>

The client MUST answer every `window-draw` with exactly one `window-ack`,
after it has decoded (and, when `flush` is zero, painted) the picture:

```text
["window-ack", wid, w, h, sequence, decode_time_us, message, extra?]
```

`w` and `h` are the draw packet's dimensions and `sequence` its sequence number.
`decode_time_us` is the time taken to decode the picture in microseconds, or one of:

| Value | Meaning | Server reaction |
|---:|---|---|
| `0` | The client skipped this picture (ie: the window was being destroyed) | none |
| `-1` | Decoding failed | the video encoder is reset and the area is refreshed |
| `-2` | The client does not know this window | logged |
| `-3` | The picture was lost (datagram transports) | the encoder recovers, usually with a new keyframe |

`message` is an empty string, or an error description. `extra` is optional and
only used for fragmented draws: `{"missing": [...], "fragments": n}`.

The server uses the acknowledgements to measure latency and decoding speed and to
pace its updates. When too many draws remain unacknowledged, it delays further
updates and lowers quality and speed. If an update stays blocked for 7.5 seconds,
it logs a warning, discards the backlog and sends a full refresh. A client that
never acknowledges therefore gets updates in bursts every few seconds instead of
a continuous stream. With [mmap](MMAP.md), the acknowledgement is also what frees
the shared memory area.

<div class="docs-section-heading" markdown="1">

## Video streams

</div>

Video encodings form streams: the decoder for a window keeps its state from one
draw packet to the next, so packets MUST be decoded in order.

* A packet with `frame` zero starts a new stream: the client MUST discard any
  existing decoder for the window and create a new one, using the `csc` option and
  the packet's picture size (`scaled_size` when present).
* `window-eos` ends all the streams of a window: the client discards its video
  decoders. The next video packet starts a new stream.
* The server only uses B-frames for the encodings listed in `video_b_frames`. With
  B-frames, a decoder may return no picture for some packets (`delayed`): this is not
  an error. A packet with `paint=False` is decoded but not painted.
* There is no keyframe request packet. A client that lost its decoder state sends a
  `window-ack` with `-1` (decode error), or a `window-refresh`: the server then
  starts a new stream.
* Video pictures can be smaller than the window: the server may only stream a
  sub-region of the window, and send the rest with picture encodings.

<div class="docs-section-heading" markdown="1">

## Server internals

</div>

The rest of this page describes the reference server's implementation and is not
needed to implement the protocol.

### Server pipeline selection


[`video_pipeline.py`](../../xpra/server/window/video_pipeline.py) enumerates direct
video encoders and combinations of colourspace converters (CSC) and encoders.
It filters candidates against client output formats, applies scaling and content
preferences, and returns candidates in stable descending score order. It accepts
codec specifications, settings, and callbacks; it does not instantiate codecs or
require a display. Matching video subregions lower the quality target according
to their measured FPS, while matching non-video subregions raise it.

[`video_scoring.py`](../../xpra/server/window/video_scoring.py) calculates each
candidate's quality, speed, setup, size, and runtime scores. `PipelineScore` gives
names to the existing eleven tuple fields while retaining positional access,
unpacking, and equality with ordinary tuples. Current codec references and
detection state are read for each candidate, and specification runtime factors
remain live reads.

[`WindowVideoSource`](../../xpra/server/window/video_compress.py) gathers the
selection inputs and owns the score cache and its timestamp. Selection checks
cancellation while visiting candidates and may return a partial result. The
source checks cancellation again before publishing: cancellation clears the
cached parameters and scores, while still updating the calculation timestamp.
Codec creation, replacement, flushing, and cleanup retain their existing encode
thread ownership.

The direct tests need no server or codec instances. Run them, the source adapter
regressions, and the scorer tests from the source directory with:

```shell
PYTHONPATH=.:tests/unittests python3 -m unittest \
    unit.server.window.video_pipeline_test \
    unit.server.window.video_pipeline_source_test \
    unit.server.window.video_compress_test \
    unit.server.video_scoring_test
```
