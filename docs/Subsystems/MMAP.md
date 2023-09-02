# MMAP

The `mmap` modules are used for fast memory transfers
between client and server when both reside on the same host.

## Implementations

| Component         | Link                                                        |
|-------------------|-------------------------------------------------------------|
| client            | [xpra.client.mixins.mmap](../../xpra/client/mixins/mmap.py) |
| client connection | [xpra.server.source.mmap](../../xpra/server/source/mmap.py) |
| server            | [xpra.server.mixins.mmap](../../xpra/server/mixins/mmap.py) |


## Capabilities

The client and server should expose the following capabilities in their `hello` packet
using the `clipboard` prefix.

The client creates an `mmap` backing file,
writes a random token at a random position within this mmap area
and sends the following capabilities:

| Capability    | Value                                |
|---------------|--------------------------------------|
| `file`        | path to the mmap backing file        |
| `size`        | size of the mmap area                |
| `token`       | random token value generated         |
| `token_index` | position where the token was written |
| `token_bytes` | length of the token in bytes         |

The server should attempt to open the mmap file specified,
and verify that the token is found.

To use this mmap file, it must write a new token
and return this information to the client.
(using the same format, excluding the `file` and `size` that the client has already specified)

The client then verifies that the mmap file can be used bi-directionally.


## Network Packets

There are no specific `mmap` packets used, `mmap` is used as an [encoding](../Usage/Encodings.md).
