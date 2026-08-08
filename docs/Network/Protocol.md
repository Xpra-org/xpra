# Protocol

See also: [network layer](../).

Every packet exchanged between xpra servers and clients
must follow exactly the same format: an 8 byte header followed by
the packet data encoded using [rencodeplus](https://github.com/Xpra-org/xpra/tree/master/xpra/net/rencodeplus)
or `yaml`, optionally compressed using `lz4`, `zstd` or `brotli`. \
Only when a connection uses a protocol which cannot be identified,
xpra may respond with a plain-text error message without any packet header.


<div class="docs-section-heading" markdown="1">

## Framing

</div>

When connecting over websockets, SSL, SSH or QUIC, the transport layer
will obviously add its own framing. \
Please refer to these protocols for the information on the packet framing used
by each of these network protocols. \
Only xpra's own application layer protocol is documented here.

---

<div class="docs-section-heading" markdown="1">

## Packet Header

</div>

The [packet header](https://github.com/Xpra-org/xpra/blob/master/xpra/net/protocol/header.py)
is made of 8 bytes, all multi-byte values use network byte order (big endian):

| Index | Type          | Length in Bytes | Contents                    |
|-------|---------------|-----------------|-----------------------------|
| 0     | Byte          | 1               | `P` (`0x50`)                |
| 1     | Byte          | 1               | protocol flags              |
| 2     | Byte          | 1               | compression flags and level |
| 3     | Byte          | 1               | chunk index                 |
| 4..7  | Unsigned Long | 4               | payload size                |

The _payload size_ is the number of bytes that follow the header,
excluding any padding added by the [encryption](Encryption.md) layer - see below.

### Protocol Flags

The _protocol flags_ is an 8-bit bitmask value. \
Exactly one packet encoder flag must be set:
* `16` (`0x10`) for `rencodeplus` packet data, this is the encoder used by default
* `4` (`0x4`) for `yaml` packet data

The values `0` (`bencode`) and `1` (`rencode`) are no longer supported. \
The encoder flag can then be ORed with:
* `8` to set the `flush` flag which notifies the packet layer that there aren't any other packets immediately following this one
* `2` to set the `cipher` flag for [AES encrypted packets](AES.md)

The `flush` flag is only ever set on the main packet (_chunk index_ of zero).

### Compression Flags and Level

If this byte is zero, the payload is not compressed.
Or at least, not compressed at the network layer: pixel and audio data may still be compressed but this is handled
by their respective subsystem and not the transport layer.

This bitmask value is used to indicate how the packet payload is compressed. \
The lower 4 bits indicate the compression level (a value between 1 and 15).
The higher 4 bits indicate which compressor was used, only one of these flags may be set:
* `16` (`0x10`) for `lz4`
* `64` (`0x40`) for `brotli`
* `128` (`0x80`) for `zstd`

A non-zero compression level without any compressor flag used to mean `zlib`,
which is no longer supported and is now rejected as an invalid compression flag.

### Chunk Index

The chunk index is used for sending large payloads and bypassing the packet encoder. \
It is a value between 0 and 15, and the main packet always uses the index zero. \
Packet chunks do not use a packet encoder, so their _protocol flags_ carry no encoder flag.
They may still be compressed and encrypted, using the same header fields as any other packet. \
The receiver must replace the item found at _chunk index_ in the main packet.

Example for sending a hypothetical packet `("example-large-packet", "foo", 20MB data)`, send 2 chunks for better performance:
* send the `20MB data` with a chunk index of 2 (zero based)
* send `("example-large-packet", "foo", "")` with a chunk  index of 0 (0 is the main packet)

The receiver must reassemble the original packet from these two chunks. \
The main packet must be sent last: the receiver buffers the chunks it receives
until the packet with a chunk index of zero arrives. \
A maximum of 3 chunks may be sent before the main packet. \
Peers that cannot reassemble chunked packets can set the `chunks` capability to `false`
in their `hello` packet, in which case all the data is inlined in the main packet instead.

### Encryption

By default, the cipher is used as a stream cipher (the `stream` capability):
it is initialized just once using the initialization vector exchanged during the handshake,
so each payload has exactly the same size as the data it encrypts and no padding is added.

When `stream` is negotiated to `false`,
each packet carries its own 16 bytes initialization vector, prepended to the encrypted data. \
And if the cipher mode uses a non-zero block size (only `CBC` does),
the data is also padded to a multiple of that block size. \
In that case, the _payload size_ is the size of the data plus the initialization vector,
it does **not** include the padding:
the receiver must calculate the padding size from the block size
and read _payload size_ + _padding size_ bytes from the connection.

See [encryption](Encryption.md) and [AES](AES.md) for details.

---

<div class="docs-section-heading" markdown="1">

## Payload

</div>

The main payload has a chunk index of zero. \
Once decompressed according to the _compression flags_ if needed,
it must be decoded according to the _protocol flags_ using `rencodeplus` or `yaml`.

It consists of a list of items.
The first item in that list is the packet-type string. \
The packet type can be followed by a variable number of optional arguments.

### Packet Type

The packet-type is a string which is used for dispatching
the packet to the correct handler. \
Each [subsystem](../Subsystems) should use the same prefix for all its packet types.

Packet types are always sent as strings.
The integer packet-type aliases negotiated via the `hello` packet were removed in version 6.3.

### Arguments

The only data types that should be used are:
* integers
* booleans
* dictionaries
* iterables: lists and tuples - tuples are encoded as lists
* byte arrays
* strings

`None` values are invalid and are rejected when the packet is encoded. \
Floating point numbers can be encoded but should be avoided.

### Size Limits

The payload size found in the header is validated before any data is read:
* the absolute maximum packet size is 256MB, larger values are rejected outright as invalid headers
* the maximum packet size is 16MB by default (`XPRA_MAX_PACKET_SIZE`),
this value may be increased by each end after the handshake
* payloads which decompress to more than 256MB (`XPRA_MAX_DECOMPRESSED_SIZE`) are rejected

Payloads smaller than 378 bytes (`XPRA_MIN_COMPRESS_SIZE`) are not compressed.

---

<div class="docs-section-heading" markdown="1">

## Hello

</div>

The `hello` packet is the initial packet used as handshake.
The connection is not fully established until both ends have received a `hello` packet.

The `hello` packet contains a single argument which is a dictionary
containing all the capabilities advertised by the peer.

For example, `hello` packets are expected to contain a `version` capability
containing the version string. \
They may also include a `username` value, which can be used for [authentication](../Usage/Authentication.md). \
Each [subsystem](../Subsystems) will also add its own attributes.

The first `hello` packet is sent before anything has been negotiated,
so it must use the packet encoder enabled by default: `rencodeplus`. \
It may already be compressed, since the sender does not yet know what its peer supports,
it can only use its own default compressor: `lz4`. \
The capabilities relevant to this protocol layer are:

| Capability          | Type            | Contents                                                                    |
|---------------------|-----------------|-----------------------------------------------------------------------------|
| `encoders`          | list of strings | the packet encoders supported, ie: `["rencodeplus", "yaml"]`                |
| `compressors`       | list of strings | the compressors supported, ie: `["lz4", "zstd", "brotli"]`                  |
| `compression_level` | integer         | `0` disables compression                                                    |
| `chunks`            | boolean         | set to `false` if chunked packets cannot be reassembled, defaults to `true` |

Each end selects the encoder and compressor it will use for sending
from the lists advertised by its peer,
so the two directions may end up using different settings. \
`rencodeplus` is preferred over `yaml`, and `lz4` over `zstd` and `brotli`.
