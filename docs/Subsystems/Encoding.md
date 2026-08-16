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

<div class="docs-section-heading" markdown="1">

## Network Packets

</div>

| Packet Type | Direction | Arguments | Purpose |
|-------------|-----------|-----------|---------|
| `encoding-set` | client to server | encoding name, optional window IDs | Select an encoding |
| `encoding-set` | server to client | properties dictionary | Publish updated encoding and video specifications |
| `encoding-options` | client to server | options dictionary | Update quality, speed, scaling or batching |
| `encoding-config` | client to server | encoding capability dictionary | Replace the client's decoder configuration |
