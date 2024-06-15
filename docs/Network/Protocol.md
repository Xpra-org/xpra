# ![Protocol](../images/icons/connect.png) Protocol

See also: [network layer](../).

Every packet exchanged between xpra servers and clients
must follow exactly the same format: an 8 byte header followed by
the packet data encoded using [rencodeplus](https://github.com/Xpra-org/xpra/tree/master/xpra/net/rencodeplus),
optionally compressed using `lz4`. \
Only when a connection uses a protocol which cannot be identified,
xpra may respond with a plain-text error message without any packet header.


## Framing

When connecting over websockets, SSL, SSH or QUIC, the transport layer
will obviously add its own framing. \
Please refer to these protocols for the information on the packet framing used
by each of these network protocols. \
Only xpra's own application layer protocol is documented here.

---

## Packet Header

The [packet header](https://github.com/Xpra-org/xpra/blob/master/xpra/net/protocol/header.py)
is made of 8 bytes:

| Index     | Type | Length in Bytes | Contents          |
|-----------|------|-----------------|-------------------|
| 0         | Byte | 1               | `P`               |
| 1         | Byte | 1               | protocol flags    |
| 2         | Byte | 1               | compression level |
| 3         | Byte | 1               | chunk index       |
| 4         | Long | 4               | payload size      |

### Protocol Flags

The _protocol flags_ is an 8-bit bitmask value. \
It must contain the value `16` for `rencodeplus` packet data. Other values are no longer supported. \
This value can then be ORed with:
* `8` to set the `flush` flag which notifies the packet layer that there aren't any other packets immediately following this one
* `2` to set the `cipher` flag for [AES encrypted packets](AES.md)

### Compression Level

If the compression level is zero, the payload is not compressed.
Or at least, not compressed at the network layer: pixel and audio data may still be compressed but this is handled
by their respective subsystem and not the transport layer.

This bitmask value is used to indicate how the packet payload is compressed. \
The lower 4 bits indicate the compression level.
The higher 4 bits indicate which compressor was used:
* `16` for `lz4`
* `64` for `brotli`

### Chunk Index

The chunk index is used for sending large payloads and bypassing the packet encoder. \
Packet chunks do not normally use a packet encoder or compressor. \
The receiver must replace the item found at _chunk index_ in the main packet.

Example for sending a hypothetical packet `("example-large-packet", "foo", 20MB data)`, send 2 chunks for better performance:
* send the `20MB data` with a chunk index of 2 (zero based)
* send `("example-large-packet", "foo", "")` with a chunk  index of 0 (0 is the main packet)

The receiver must reassemble the original packet from these two chunks.


---

## Payload

The main payload has a chunk index of zero. \
Once decompressed according to the _compression level_ flag if needed,
it must be decoded according to the _protocol flags_ using `rencodeplus`.

It consists of a list of items.
The first item in that list is the packet-type string. \
The packet type can be followed by a variable number of optional arguments.

### Packet Type

The packet-type is a string which is used for dispatching
the packet to the correct handler. \
Each [subsystem](../Subsystems) should use the same prefix for all its packet types.

The packet-type may also be sent as an integer once the `hello` packet
has been processed by the peer if the `hello` packet contains an `aliases` capability
containing the mapping from packet-type to integer.

### Arguments

The only data types that should be used are:
* integers
* booleans
* dictionaries
* iterables: lists and tuples
* byte arrays
* strings

Floating point numbers and `None` values can be encoded but should be avoided.

---

## Hello

The `hello` packet is the initial packet used as handshake.
The connection is not fully established until both ends have received a `hello` packet.

The `hello` packet contains a single argument which is a dictionary
containing all the capabilities advertised by the peer.

For example, `hello` packets are expected to contain a `version` capability
containing the version string. \
They may also include a `username` value, which can be used for [authentication](../Usage/Authentication.md). \
Each [subsystem](../Subsystems) will also add its own attributes.
