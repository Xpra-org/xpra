# Xpra Protocol

## Status of This Document

This document specifies the Xpra application protocol implemented by the
`master` branch on 16 August 2026 (Xpra 6.6 development series). It is a
normative implementer specification for the modern protocol only.

Historical packet names, encoders, compressors, capability aliases and packet
layouts accepted when `XPRA_BACKWARDS_COMPATIBLE=1` are deliberately excluded.
An implementation conforming to this document MUST NOT depend on them.

The key words **MUST**, **MUST NOT**, **REQUIRED**, **SHOULD**, **SHOULD NOT** and
**MAY** are to be interpreted as described by RFC 2119 and RFC 8174.

## 1. Scope

This specification covers:

- the Xpra record header, packet encoding, compression and raw chunks;
- connection establishment, capability negotiation and authentication;
- normal interactive sessions and one-shot request connections;
- control, encoder, proxy registration and listener flows;
- the application packet registry used by the current client and server.

It begins after the selected transport has delivered an ordered byte stream.
TCP, Unix-domain sockets, TLS, SSH, WebSocket and QUIC can provide that stream.
Transport handshakes, HTTP/WebSocket framing, SSH, QUIC, RFB and HTTP services
are outside this specification.

Xpra's AES packet extension is also outside this specification. A peer MAY
recognize protocol flag `0x02` as an extension marker, but a conforming
implementation need not implement it and MUST NOT advertise it merely because
it implements this RFC. Deployments SHOULD use TLS or SSH for confidentiality
and peer authentication.

## 2. Terminology and Data Model

`client` is the endpoint initiating an Xpra session connection. `server` is the
endpoint accepting it. Proxies act as a server on one connection and a client
on another.

Packets are written in this document as:

```text
[packet-type, argument-1, argument-2, ...]
```

The packet type MUST be a Unicode string. Packet arguments use these types:

| Notation | Meaning |
|---|---|
| `bool` | Boolean, distinct from an integer in packet schemas |
| `u8`, `u16`, `u32`, `u64` | Non-negative integer fitting that width |
| `i8`, `i16`, `i32`, `i64` | Signed integer fitting that width |
| `str` | Unicode string |
| `bytes` | Arbitrary byte string |
| `list<T>` | Ordered sequence of `T`; a tuple is encoded as a list |
| `map` | String-keyed dictionary unless stated otherwise |
| `T?` | Optional trailing value of type `T` |
| `T...` | Zero or more trailing values of type `T` |

Receivers MUST validate argument count, type, integer range and identifiers
before using a packet. Unknown keys in an extensible map MUST be ignored unless
the map's definition says otherwise. Unknown packet types MUST be rejected or
cause a clean connection close; they MUST NOT be interpreted as another type.

## 3. Record Layer

### 3.1 Header

Every Xpra record consists of an eight-byte header followed immediately by the
number of payload bytes declared by that header.

| Offset | Size | Field | Encoding |
|---:|---:|---|---|
| 0 | 1 | magic | ASCII `P` (`0x50`) |
| 1 | 1 | protocol flags | bit field, Section 3.2 |
| 2 | 1 | compression | bit field, Section 3.3 |
| 3 | 1 | chunk index | unsigned integer, Section 3.5 |
| 4 | 4 | payload length | unsigned 32-bit, network byte order |

The payload length does not include the header. A receiver MUST reject an
incorrect magic byte, an invalid flag combination or an unacceptable payload
length before allocating or reading the declared payload.

### 3.2 Protocol Flags

| Value | Name | Meaning |
|---:|---|---|
| `0x04` | YAML | main payload is YAML |
| `0x08` | flush | no packet is queued immediately after this record |
| `0x10` | rencodeplus | main payload is rencodeplus |
| `0x02` | cipher extension | outside this RFC |

A main record (chunk index zero) MUST set exactly one of `0x04` and `0x10`.
Values `0x00` (bencode) and `0x01` (rencode) are not valid modern encoders.
All unassigned bits MUST be zero.

A raw chunk MUST set neither encoder flag and MUST NOT set `flush`. The `flush`
flag is only a scheduling hint; it does not change packet semantics.

### 3.3 Compression Byte

Zero means no record-layer compression. A non-zero byte has a four-bit
compression level in its low nibble and exactly one compressor in its high
nibble:

| High bit | Compressor |
|---:|---|
| `0x10` | LZ4 block |
| `0x40` | Brotli |
| `0x80` | Zstandard |

For a compressed record, the level MUST be in `1..15` and exactly one listed
compressor bit MUST be set. A level without a compressor, multiple compressor
bits, or an unassigned bit is invalid. In particular, the former implicit zlib
form is invalid.

Compression applies independently to each record, including raw chunks. After
decompression the result is either an encoded main packet or the bytes of one
raw chunk.

An LZ4 payload starts with the uncompressed size as an unsigned 32-bit
**little-endian** integer, followed by one raw LZ4 block. Brotli and Zstandard
payloads are ordinary frames for those formats.

Packet compression is independent of image, video and audio codecs carried
inside packet arguments.

### 3.4 Limits

Before the peer's `hello` is accepted, an implementation MUST impose a maximum
declared payload length of 4 MiB (`4 * 1024 * 1024`). This limit applies before
allocation and before reading the payload.

After capability processing, the normal per-record limit is 16 MiB. A subsystem
MAY increase it when a negotiated operation requires a larger record. The
default absolute declared-payload limit is 256 MiB; display negotiation MAY
replace it with a dimension-derived bound large enough for the negotiated pixel
area. No decompressed record may exceed 256 MiB. Implementations MAY configure
smaller limits and reject the associated operation cleanly.

Senders normally avoid record compression below 378 bytes. This is an
optimization, not a receiver requirement.

### 3.5 Raw Chunks

Raw chunks move large byte arguments without copying them through the packet
encoder. Their chunk index is the zero-based position of the argument they
replace in the decoded main packet.

- Index zero is reserved for the main packet.
- A raw chunk index MUST be in `1..15`.
- At most three raw chunks MAY precede one main packet.
- Each raw chunk MUST precede its main packet.
- A main packet placeholder MUST exist at every received chunk index.
- A receiver MUST reject an index outside the decoded packet rather than grow
  or otherwise mutate the packet shape.
- On receipt of the main packet, each placeholder is replaced by the
  decompressed bytes of the matching chunk, then the complete packet is
  dispatched.

If the receiver advertises `chunks=false`, the sender MUST inline all arguments
in the main packet.

## 4. Packet Encoders

### 4.1 Requirements

Servers conforming to this RFC MUST implement rencodeplus and LZ4. Clients MUST
implement rencodeplus and SHOULD implement LZ4. YAML is OPTIONAL but
RECOMMENDED. Zstandard and Brotli are OPTIONAL.

The initial `hello` MUST use rencodeplus because negotiation has not occurred.
It MAY use LZ4, which is the required server-side compressor. Thereafter each
sender chooses an encoder and compressor offered by the receiver, independently
for each direction. Rencodeplus and LZ4 are preferred.

### 4.2 Rencodeplus

Rencodeplus is a self-delimiting binary representation. Multi-byte numeric
values use network byte order. Its type codes are:

| Code | Value |
|---:|---|
| `0..43` | integer equal to the code |
| `44` | IEEE-754 binary64, 8 bytes |
| `59` | variable list, values followed by `127` |
| `60` | variable dictionary, key/value pairs followed by `127` |
| `61` | base-10 integer bytes followed by `127` |
| `62` | signed 8-bit integer |
| `63` | signed 16-bit integer |
| `64` | signed 32-bit integer |
| `65` | signed 64-bit integer |
| `66` | IEEE-754 binary32, 4 bytes |
| `67`, `68`, `69` | `true`, `false`, `null` respectively |
| `70..101` | integers `-1..-32` respectively |
| `102..126` | dictionaries containing `0..24` pairs |
| `128..191` | UTF-8 strings containing `0..63` bytes |
| `192..255` | lists containing `0..63` values |

A longer UTF-8 string is encoded as ASCII decimal byte length, `:`, then that
many bytes. A byte string is encoded as ASCII decimal byte length, `/`, then
that many bytes. Lengths count bytes, not Unicode characters.

The packet encoder can represent null and floating-point values, but packet
schemas in this RFC do not use null and SHOULD avoid floats. Senders MUST use a
byte string, not a Unicode string, for opaque data.

### 4.3 YAML

A YAML main payload MUST decode to the same packet list data model. YAML tags or
object construction outside strings, integers, booleans, lists, dictionaries
and binary data MUST NOT be used. Receivers MUST use a safe loader.

## 5. Connection Establishment

### 5.1 State Machine

The ordinary sequence is:

```text
transport established
  -> client hello
  -> [server challenge -> client challenge response]*
  -> server hello
  -> established application traffic
  -> connection-close or transport EOF
```

The client sends `["hello", capabilities:map]`. The server either requests
authentication, accepts the connection with its own `hello`, answers a one-shot
request, offers an SSL upgrade, or closes the connection.

Except for `hello`, `challenge`, `ssl-upgrade` and `connection-close`, ordinary
application packets MUST NOT be sent until the peer's `hello` has been accepted.
The established connection remains asymmetric: advertised receive capabilities
govern what the other endpoint may send.

### 5.2 Core Capabilities

| Key | Type | Semantics |
|---|---|---|
| `version` | `str` | Xpra version; REQUIRED in a normal hello |
| `encoders` | `list<str>` | accepted packet encoders; includes `rencodeplus` |
| `compressors` | `list<str>` | accepted record compressors |
| `compression_level` | `u8` | requested level; zero disables compression |
| `chunks` | `bool` | whether raw chunks can be reassembled; default true |
| `packet-types` | `list<str>` | packet types accepted by the sender of this hello |
| `request` | `str` | one-shot or special profile, Section 5.4 |
| `wants` | `list<str>` | optional server capability groups requested |
| `username` | `str` | authentication identity |
| `digest` | `list<str>` | challenge digest algorithms accepted by client |
| `hostname`, `uuid`, `machine_id` | `str` | endpoint identity/advisory metadata |
| `build`, `platform`, `network` | `map` | extensible diagnostic metadata |

`packet-types` is an allow-list when present. A sender SHOULD NOT send an
optional packet absent from the peer's list. Mandatory handshake packets remain
valid even when omitted from that list.

### 5.3 Authentication and Upgrade Packets

| Direction | Packet | Arguments |
|---|---|---|
| C -> S | `hello` | `capabilities:map` |
| S -> C | `hello` | `capabilities:map` |
| S -> C | `challenge` | `salt:bytes`, `auth_caps:map`, `digest:str`, `salt_digest:str`, `prompt:str?` |
| C -> S | `hello` | original capabilities plus challenge response fields |
| S -> C | `ssl-upgrade` | `attributes:map` |
| either | `connection-close` | `reasons:list<str>` |

Challenge algorithms and transport TLS configuration are specified in the
[authentication](../Usage/Authentication.md) and [TLS](SSL.md) documents.

### 5.4 Connection Profiles

A `request` capability selects a profile. Unless stated otherwise, the server
answers with `hello` and closes after delivering the result.

| Request | Additional client capability | Result |
|---|---|---|
| absent | session capabilities | normal interactive attach |
| `connect_test` | `connect_test_request:str` | echo in `connect_test_response` |
| `version` | `full-version-request:bool?` | version hello |
| `id` | none | server identity hello |
| `info` | `subsystems:list<str>?` | information hello or `info-response` |
| `screenshot` | none | `display-screenshot` |
| `icon` | none | `display-icon` |
| `command` | `command_request:list<str>` | control-command response hello |
| `run` | `run:list<str>` | process launch result in `run_response` |
| `print` | `print:list` | submit file data as a print job |
| `encode` | `encoding:map` | stateless encoder service |
| `detach` | none | disconnect attached clients as authorized |
| `exit` | none | terminate the server process as authorized |
| `stop` | none | stop the session as authorized |
| `register` | registration fields | register a session with a proxy registry |

Authorization is profile-specific. A server MUST NOT grant a request merely
because its name is recognized. Unknown requests MUST be rejected.

The encoder service is selected by connecting to an encoder server and uses the
same handshake followed by the `encode` and `context-*` packets in Section 8.11.
A listener or proxy may use `register` with `uuid`, session identity, display
addresses and connection options, and MAY hand the authenticated connection to
the selected session. Handover is an implementation action; the Xpra record
stream continues unchanged.

## 6. Capability Namespaces

Capabilities describe what the sender can receive or what local service it is
offering. Feature maps are extensible: omitted keys mean unsupported or their
documented default.

| Namespace/key | Interoperability fields |
|---|---|
| `audio` | `send:bool`, `receive:bool`, `encoders:list<str>`, `decoders:list<str>`, codec properties |
| `bandwidth` | `limit:u64`, `detection:bool` |
| `clipboard` | `enabled`, `direction`, `selections`, `greedy`, `want_targets`, `preferred-targets`, `notification` |
| `command` | `start`, `start-child`, accepted signals and commands |
| `cursors` / `cursor` | enabled state, encodings, size, default and maximum sizes |
| display keys | `desktop_size`, `screen_sizes`, `monitors`, `dpi`, `screen-scaling`, `vrefresh` |
| `encoding` | accepted picture encodings, RGB formats, quality/speed/scaling and codec profiles |
| `file` | `enabled`, `ask`, `size-limit`, `chunks`, `open`, `open-url`, `ask-timeout` |
| `keyboard` / `keymap` | enabled state, modifiers, repeat timing and keymap definition |
| `mmap` | read/write area descriptors including file, size and token validation |
| `notifications` | enabled state and supported actions |
| `pointer` | synchronization, initial position and double-click parameters |
| `webcam` | enabled state and accepted image encodings |
| `window` | metadata supported, restacking, focus and position synchronization |

Pixel formats, codec option dictionaries, monitor records, keymaps, clipboard
targets and memory-map layouts are defined in the matching
[subsystem documents](../Subsystems/README.md). Diagnostic version keys and
unrecognized feature properties MUST be treated as advisory and ignored.

## 7. Core and Session Packets

The tables below are the modern packet registry. Integer widths are receiver
validation limits, not a separate on-wire integer representation.

### 7.1 Core, Status and Control

| Direction | Packet | Arguments |
|---|---|---|
| either | `ping` | `monotonic_ms:u64`, `sid:str?` |
| either | `ping-echo` | `monotonic_ms:u64`, `load1:u64`, `load5:u64`, `load15:u64`, `latency_ms:i64`, `sid:str?` |
| S -> C | `startup-complete` | none |
| either | `setting-change` | `name:str`, `value:any` |
| S -> C | `server-event` | `name:str`, `values:any...` |
| S -> C | `control` | `command:str`, `arguments:any...` |
| C -> S | `control-request` | `request_id:u64`, `command:str`, `arguments:any...` |
| S -> C | `info-response` | `information:map` |
| C -> S | `info-request` | `window_ids:list<u64>`, `categories:list<str>`, `subsystems:list<str>?` |
| C -> S | `shutdown-server` | `exit:bool`, `reason:str?` |
| C -> S | `suspend` | `suspended:bool` |
| C -> S | `bell-set` | `enabled:bool` |

Ping timestamps use the sender's monotonic clock and are correlation values,
not wall-clock time. Load values are scaled by 1000. A negative latency means
unknown.

`setting-change` is bidirectional, but asymmetric. A server MAY send any
setting. A server MUST apply an allow-list to the settings a client is permitted
to change, and MUST ignore any setting outside it. That allow-list holds
`readonly:bool`, and - on servers managing an X11 display - `xsettings:map`,
which carries the client's `xsettings-blob` and `resource-manager` values
for the server to apply to its own display.

### 7.2 Logging, Shell and Commands

| Direction | Packet | Arguments |
|---|---|---|
| either | `logging-event` | `level:u8`, `message:bytes|list<str>`, `time_ms:u64` |
| C -> S | `logging-control` | `action:str` (`start` or `stop`) |
| C -> S | `shell-exec` | `code:str` |
| S -> C | `shell-reply` | `returncode:u8`, `output:str` |
| C -> S | `command-start` | `name:str`, `command:list<str>`, `ignore:bool`, `sharing:bool` |
| C -> S | `command-signal` | `pid:u32`, `signal:str` |

### 7.3 Sharing and Bandwidth

| Direction | Packet | Arguments |
|---|---|---|
| C -> S | `sharing-toggle` | `enabled:bool` |
| C -> S | `sharing-lock` | `locked:bool` |
| C -> S | `bandwidth-limit` | `bits_per_second:u64` |
| C -> S | `bandwidth-status` | `attributes:map` |

## 8. Subsystem Packets

### 8.1 Display

| Direction | Packet | Arguments |
|---|---|---|
| C -> S | `display-configure` | `configuration:map` |
| C -> S | `display-request-screenshot` | none |
| C -> S | `display-request-icon` | none |
| S -> C | `display-screenshot` | `width:u16`, `height:u16`, `encoding:str`, `rowstride:u32`, `data:bytes` |
| S -> C | `display-icon` | `width:u16`, `height:u16`, `encoding:str`, `rowstride:u32`, `data:bytes` |
| S -> C | `display-show-desktop` | `show:bool` |
| S -> C | `display-resized` | `width:u16`, `height:u16`, `max_width:u16`, `max_height:u16` |

`display-configure` carries the same monitor, desktop, DPI and scaling
structures advertised in the display capabilities.

### 8.2 Windows and Drawing

| Direction | Packet | Arguments |
|---|---|---|
| S -> C | `window-create` | `wid:u64`, `x:i32`, `y:i32`, `w:u16`, `h:u16`, `metadata:map`, `client_properties:map` |
| S -> C | `window-metadata` | `wid:u64`, `metadata:map` |
| S -> C | `window-move-resize` | `wid:u64`, `x:i32`, `y:i32`, `w:u16`, `h:u16`, `resize_counter:u64` |
| S -> C | `window-resized` | `wid:u64`, `w:u16`, `h:u16`, `resize_counter:u64` |
| S -> C | `window-raise` | `wid:u64` |
| S -> C | `window-restack` | `wid:u64`, `detail:u8`, `sibling:u64` |
| S -> C | `window-initiate-moveresize` | `wid:u64`, `root_x:i32`, `root_y:i32`, `direction:u8`, `button:u8`, `source:u8` |
| S -> C | `window-destroy` | `wid:u64` |
| S -> C | `window-icon` | `wid:u64`, `w:u16`, `h:u16`, `encoding:str`, `data:bytes` |
| S -> C | `window-draw` | `wid:u64`, `x:i16`, `y:i16`, `w:u16`, `h:u16`, `encoding:str`, `data:bytes`, `sequence:u64`, `rowstride:u32`, `options:map` |
| S -> C | `window-eos` | `wid:u64` |
| S -> C | `window-bell` | `wid:u64`, `device:u16`, `percent:i8`, `pitch:i32`, `duration:i32`, `class:u32`, `id:u32`, `name:str` |
| C -> S | `window-map` | `wid:u64`, `x:i32`, `y:i32`, `w:u16`, `h:u16`, `client_properties:map`, `state:map?`, `monitor:i32?` |
| C -> S | `window-unmap` | `wid:u64`, `iconified:bool?`, `state:map?` |
| C -> S | `window-configure` | `wid:u64`, `configuration:map` |
| C -> S | `window-close` | `wid:u64` |
| C -> S | `window-focus` | `wid:u64`, `modifiers:list<str>?` |
| C -> S | `window-action` | `wid:u64`, `action:str`, `arguments:any...` |
| C -> S | `window-refresh` | `wid:u64`, `options:map` |
| C -> S | `window-ack` | `wid:u64`, `width:u16`, `height:u16`, `sequence:u64`, `decode_time_us:i32`, `message:str` |
| C -> S | `window-draw-ack` | `sequence:u64`, `wid:u64`, `width:u16`, `height:u16`, `decode_time_us:i32`, `message:str?` |

Window IDs are allocated by the server and remain valid until `window-destroy`.
The encoding and options of `window-draw` MUST have been advertised by the
client. A sequence acknowledgement MUST refer to the matching draw and window.

### 8.3 Encoding Control

| Direction | Packet | Arguments |
|---|---|---|
| C -> S | `encoding-set` | `encoding:str`, `window_ids:list<u64>?` |
| C -> S | `encoding-options` | `options:map` |
| C -> S | `encoding-config` | `configuration:map` |
| S -> C | `encoding-set` | `properties:map` |

The principal option keys are `quality`, `min-quality`, `speed`, `min-speed`,
`scaling`, `rgb_formats`, `full_csc_modes`, codec profile maps and batch delay
parameters. Values outside advertised ranges MUST be rejected or clamped.

### 8.4 Keyboard and Pointer

| Direction | Packet | Arguments |
|---|---|---|
| C -> S | `keyboard-event` | `wid:u64`, `keyname:str`, `pressed:bool`, `properties:map` |
| C -> S | `keyboard-config` | `configuration:map` |
| C -> S | `keyboard-sync` | `enabled:bool` |
| either | `pointer-motion` | `device:i64`, `sequence:u64`, `wid:u64`, `pointer:list<u16>`, `properties:map` |
| either | `pointer-button` | `device:i64`, `sequence:u64`, `wid:u64`, `button:u8`, `pressed:bool`, `pointer:list<u16>`, `properties:map` |
| C -> S | `pointer-wheel` | `wid:u64`, `axis:u8`, `delta:i64`, `pointer:list<u16>`, `modifiers:list<str>`, `buttons:list<u8>`, `properties:map` |
| S -> C | `pointer-wheel` | `wid:u64`, `axis:u8`, `delta:i64`, `pointer:list<u16>`, `modifiers:list<str>` |
| S -> C | `pointer-position` | `wid:u64`, `x:i32`, `y:i32`, `relative_x:i32`, `relative_y:i32` |
| S -> C | `pointer-grab` | `wid:u64` |
| S -> C | `pointer-ungrab` | `wid:u64` |

Keyboard event properties include modifier names, key value, text, hardware
keycode and layout group. Pointer coordinates are `[x, y]`; extra device axes
may follow only when advertised.

### 8.5 Cursor

| Direction | Packet | Arguments |
|---|---|---|
| C -> S | `cursor-set` | `enabled:bool` |
| S -> C | `cursor-data` | `encoding:str`, `w:u16`, `h:u16`, `hotspot_x:u16`, `hotspot_y:u16`, `serial:u64`, `data:bytes`, `name:str` |
| S -> C | `cursor-default` | none |

The cursor encoding MUST be in the client's advertised cursor encodings.

### 8.6 Clipboard

Clipboard packets can flow in either direction when the negotiated direction
permits it.

| Packet | Arguments |
|---|---|
| `clipboard-status` | `enabled:bool`, `reason:str?` |
| `clipboard-enable-selections` | `selections:list<str>` |
| `clipboard-data` | `selection:str`, `options:map` |
| `clipboard-request` | `request_id:u64`, `selection:str`, `target:str` |
| `clipboard-contents` | `request_id:u64`, `selection:str`, `data_type:str`, `data_format:u8`, `wire_encoding:str`, `data:any` |
| `clipboard-contents-none` | `request_id:u64`, `selection:str?` |
| `clipboard-pending-requests` | `count:u32` |

The `clipboard-data` options are `claim:bool`, `greedy:bool`,
`targets:list<str>` and `data:map`. Each `data` entry maps a target name to
`[data_type:str, data_format:u8, wire_encoding:str, wire_data:any]`.

Request IDs correlate exactly one contents response. Receivers MUST enforce
negotiated selection, target and size limits before exposing clipboard data.

### 8.7 Notifications

| Direction | Packet | Arguments |
|---|---|---|
| S -> C | `notification-show` | `dbus_id:str`, `id:u64`, `application:str`, `replaces:u64`, `icon_name:str`, `summary:str`, `body:str`, `expire_ms:i64`, `icon:any?`, `actions:list<str>?`, `hints:map?` |
| either | `notification-close` | `id:u64`, `reason:str?`, `text:str?` |
| C -> S | `notification-action` | `id:u64`, `action:str` |
| C -> S | `notification-status` | `enabled:bool` |

### 8.8 Audio

| Direction | Packet | Arguments |
|---|---|---|
| either | `audio-capabilities` | `capabilities:map` |
| either | `audio-control` | `command:str`, `arguments:any...` |
| either | `audio-data` | `codec:str`, `data:bytes`, `metadata:map`, `extra_data:bytes...` |
| either | `audio-keepalive` | `sequence:u64` |
| S -> C | `audio-level` | `sample:map` |
| S -> C | `audio-signal` | `present:bool` |

`audio-data` metadata marks stream start/end, sequence, timestamp and codec
properties. Codec and direction MUST have been negotiated. Implementations MAY
exchange audio level/signal packets advertised in `packet-types`; their payload
is codec-backend metadata and is optional.

### 8.9 Webcam

| Direction | Packet | Arguments |
|---|---|---|
| C -> S | `webcam-start` | `device:i64`, `width:u16`, `height:u16` |
| C -> S | `webcam-frame` | `device:i64`, `frame:u64`, `encoding:str`, `width:u16`, `height:u16`, `data:bytes`, `options:map` |
| S -> C | `webcam-ack` | `device:i64`, `frame:u64`, `width:u16`, `height:u16` |
| either | `webcam-stop` | `device:i64`, `reason:str?` |

### 8.10 Files, URLs and Printers

File packets may flow in either direction when the corresponding `file`
capability permits it. `printer-devices` and `printer-file` flow from client to
server.

| Packet | Arguments |
|---|---|
| `file-send` | `filename:str`, `mimetype:str`, `print:bool`, `open:bool`, `size:u64`, `data:bytes`, `options:map`, `send_id:str?` |
| `file-send-chunk` | `chunk_id:str`, `chunk_no:u32`, `data:bytes`, `has_more:bool` |
| `file-ack-chunk` | `chunk_id:str`, `ok:bool`, `message:bytes|str`, `chunk_no:u32` |
| `file-data-request` | `type:str`, `send_id:str`, `url:str`, `mimetype:str`, `size:u64`, `print:bool`, `open:bool`, `options:map?` |
| `file-data-response` | `send_id:str`, `accept:bool` |
| `file-request` | `filename:str`, `open:bool`, `send_id:str` |
| `open-url` | `url:str` |
| `printer-devices` | `printers:map` |
| `printer-file` | `filename:str`, `data:bytes`, `mimetype:str?`, `source_uuid:str?`, `title:str?`, `printer:str?`, `copies:u16?`, `options:map|str?` |

`file-send` options carry digests and, for chunked transfers,
`file-chunk-id`. A receiver MUST validate the declared size, negotiated maximum,
authorization, basename, chunk order and digest. `file-data-response` authorizes
only the exact pending `send_id`; it is not blanket permission to send data.

### 8.11 Encoder Service

| Direction | Packet | Arguments |
|---|---|---|
| C -> S | `encode` | `input_coding:str`, `pixel_format:str`, `pixels:bytes`, `width:u16`, `height:u16`, `rowstride:u32`, `options:map`, `metadata:map` |
| C -> S | `context-request` | `id:u64`, `codec_type:str`, `encoding:str`, `width:u16`, `height:u16`, `source_format:str`, `options:map` |
| C -> S | `context-compress` | `id:u64`, `metadata:map`, `pixels:bytes|list<bytes>`, `options:map`, `send_options:map` |
| C -> S | `context-close` | `id:u64`, `reason:str` |
| S -> C | `encodings` | `capabilities:map` |
| S -> C | `encode-response` | `encoding:str`, `data:bytes`, `options:map`, `width:u16`, `height:u16`, `rowstride:u32`, `bpp:u8`, `metadata:map` |
| S -> C | `context-response` | `id:u64`, `accepted:bool`, `message:str`, `properties:map` |
| S -> C | `context-data` | `id:u64`, `data:bytes`, `client_options:map`, `reply_options:map` |

Context IDs are client-selected and unique within one connection. Dimensions,
formats and codec options MUST be supported by the encoder capabilities.

### 8.12 Miscellaneous Feature Packets

| Direction | Packet | Arguments |
|---|---|---|
| C -> S | `gsettings-update` | `settings:map` |

### 8.13 Recording Profile

A client advertising the recording capabilities receives normal window and
input packets plus these wrappers:

| Direction | Packet | Arguments |
|---|---|---|
| S -> C | `keyboard-record` | `wid:u64`, `event:map` |
| S -> C | `clipboard-record` | `direction:str`, `embedded_type:str`, `embedded_arguments:any...` |

The keyboard event map contains `press`, `name`, `keyval`, `keycode`,
`modifiers`, `is-modifier` and `sync`. The clipboard wrapper preserves the
original modern clipboard packet after the direction field.

Optional platform-specific packets MUST be listed in `packet-types` and MUST use
a subsystem prefix. A peer that does not advertise that feature must not receive
them.

## 9. Ordering and Lifecycle Rules

- Packets on a connection are ordered as dispatched after chunk reassembly.
- A sender MUST NOT reuse a live window, request, transfer or encoder-context ID
  for a different object.
- A destroy, stop, close or end-of-stream packet terminates the corresponding
  object; later data for it MUST be ignored or rejected.
- An acknowledgement MUST not acknowledge data that has not been received and
  validated.
- A receiver MAY process explicitly thread-safe packets concurrently, but MUST
  preserve externally visible ordering for each object.
- `connection-close` SHOULD be sent before an orderly transport close. Transport
  EOF without it is an abnormal disconnect.

## 10. Error Handling

Malformed headers, invalid flags, oversized records, decompression failures,
packet decoder failures, invalid raw-chunk indices and structurally invalid
packets are protocol errors. The receiver MUST stop parsing the affected record
stream and SHOULD send `connection-close` when it can do so safely.

Before a stream has been identified as Xpra, a server MAY return a short
plain-text diagnostic for an HTTP request or another recognized protocol. Once
an Xpra header has been accepted, errors MUST use Xpra framing.

Application errors such as an unavailable codec, denied file, unknown window or
failed command SHOULD use the subsystem's response or a clean close and MUST NOT
be treated as permission to relax record validation.

## 11. Extensibility

New optional capabilities belong in a namespaced map. New packets SHOULD use a
stable subsystem prefix and MUST be advertised in `packet-types` before use.
Adding optional trailing fields is permitted only when the receiver can identify
and ignore them safely. Changing the meaning, order or type of an existing field
requires a new packet type or an explicitly negotiated capability.

Protocol and compressor flag bits, header fields and packet names in this
document are not implicitly extensible: unrecognized values are invalid unless
a future specification explicitly negotiates them.

## 12. Security Considerations

Xpra packet framing provides no confidentiality, integrity or authentication.
Implementations SHOULD use TLS or SSH on untrusted networks and MUST authenticate
before enabling privileged profiles or application packets.

All declared lengths, decompressed sizes, collection counts, raw chunk indices,
IDs, paths, URLs, codec dimensions and option maps are attacker-controlled.
Receivers MUST bound them before allocation or external side effects. File open,
URL open, printing, command execution, shell, shutdown, detach, registration,
clipboard and device forwarding require explicit local policy; capability
advertisement alone is not authorization.

YAML MUST be decoded without object construction. Compressed data and media
codecs MUST be subject to output and resource limits. Sensitive diagnostic
metadata SHOULD be omitted unless requested by an authenticated peer.
