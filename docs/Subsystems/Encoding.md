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
| `full_csc_modes` | Codec-to-colourspace conversion modes |
| `quality`, `min-quality` | Requested quality bounds |
| `speed`, `min-speed` | Requested speed bounds |
| `video_max_size` | Maximum video dimensions |
| `batch` | Damage batching parameters |

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

## Server pipeline selection

</div>

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

<div class="docs-section-heading" markdown="1">

## Network Packets

</div>

| Packet Type | Direction | Arguments | Purpose |
|-------------|-----------|-----------|---------|
| `encoding-set` | client to server | encoding name, optional window IDs | Select an encoding |
| `encoding-set` | server to client | properties dictionary | Publish updated encoding and video specifications |
| `encoding-options` | client to server | options dictionary | Update quality, speed, scaling or batching |
| `encoding-config` | client to server | encoding capability dictionary | Replace the client's decoder configuration |
