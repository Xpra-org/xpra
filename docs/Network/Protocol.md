# Xpra Protocol

## Status of This Document

This document specifies the Xpra application protocol implemented by the
`master` branch in November 2026 (Xpra 8.0 development series). It is a
normative implementer specification for the modern protocol only.

If you are writing a new client or server, start with the
[porting guide](../Porting/README.md): it gives the reading order, the
transports, the authentication algorithm and an annotated session trace,
and links back to the relevant sections of this document.

Historical packet names, encoders, compressors, capability aliases and packet
layouts, which version 7 still uses with its own legacy peers when running with
`XPRA_BACKWARDS_COMPATIBLE=1`, are deliberately excluded.
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
are outside this specification: the mapping of the record stream onto each
transport, including QUIC datagrams, is described in
[transports](../Porting/Transports.md).

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
| `coord` | Integer from -65535 to 65535 |
| `str` | Unicode string |
| `bytes` | Arbitrary byte string |
| `list<T>` | Ordered sequence of `T`; a tuple is encoded as a list |
| `map` | String-keyed dictionary unless stated otherwise |
| `T?` | Optional trailing value of type `T` |
| `T...` | Zero or more trailing values of type `T` |

Window identifiers are written `wid:u64` but are limited to `0..2^48-1`.
The reference implementation is lenient when it reads packets: it accepts an
integer where a `bool` is expected, a UTF-8 byte string where a `str` is
expected, and converts numeric strings to integers. Senders MUST NOT rely on
this, and MUST use the declared types.

Receivers MUST validate argument count, type, integer range and identifiers
before using a packet. Receivers MUST tolerate, and ignore, trailing arguments
beyond those they know about. Unknown keys in an extensible map MUST be ignored unless
the map's definition says otherwise.

Capability names in this document use dots to denote a path: `encoding.options`
is either a literal key `"encoding.options"` or the `options` key of a nested
`encoding` map. Receivers MUST look up such a name by first checking for the
literal flat key, then for the nested form, splitting at the first dot and
recursing. The reference server still sends a few flat keys, such as
`wheel.precise` or `pointer.relative`. Code that reads a whole sub-map, such
as `encoding`, does not see flat keys, so senders SHOULD use nested maps.

A map can also carry a value for its own name under the empty-string key: in
`{"encodings": {"": ["png", "rgb"], "core": ["png", "rgb24"]}}`, `encodings` is
`["png", "rgb"]` and `encodings.core` is `["png", "rgb24"]`. Receivers looking up a
scalar or list value that turns out to be a map MUST use its `""` entry. Unknown packet types MUST be rejected or
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
declared payload length. This limit applies before allocation and before reading
the payload. Servers running modern-only (`XPRA_BACKWARDS_COMPATIBLE=0`) use
16 KiB (`16 * 1024`); servers that also accept version 7 peers (the default)
use 16 MiB, because those peers send larger `hello` packets. A client MUST keep
its `hello` packets, including the ones carrying a challenge response, below
16 KiB after compression. Large optional data such as a full keymap can be sent
after the handshake instead (see `keymap.delay` in the
[keyboard subsystem](../Subsystems/Keyboard.md)).

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
that many bytes. Lengths count bytes, not Unicode characters. Byte strings have
no fixed-length short form: even an empty byte string is encoded as `0/`.
Decoders MUST accept the long `len:` string form for any length, including
strings shorter than 64 bytes.

Lists and dictionaries with more than 63 values (respectively 24 pairs) use the
variable forms terminated by `127`. Decoders MUST accept the variable forms for
any size. A list is a list whatever its form: there is no separate tuple type.

The reference encoder always uses the smallest representation for an integer:
a fixed code, then 8, 16, 32 and 64-bit signed forms. Code `61` is only used
for integers outside the signed 64-bit range: its decimal representation MUST
be between 18 and 63 characters long, the reference decoder rejects or
misparses anything shorter. Floats are always encoded as binary64 (code `44`),
code `66` is decode-only.

Dictionary keys are usually strings, but a decoder MUST accept integer keys:
they appear in some `info` responses and in a few maps documented as using them.

A decoder parses exactly one top-level value. The reference decoder ignores
trailing bytes after it, conforming senders MUST NOT send any.

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
  -> [ssl-upgrade exchange -> TLS handshake -> client hello]
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
| `version` | `str` | dotted Xpra version, REQUIRED in a normal hello, see below |
| `protocol-version` | `list<int>` | minimum version accepted by the sender of this hello |
| `encoders` | `list<str>` | accepted packet encoders; includes `rencodeplus`; REQUIRED |
| `compressors` | `list<str>` | accepted record compressors: `lz4`, `brotli`, `zstd`, `none` |
| `compression_level` | `u8` | requested level, usually `0..9`; zero disables record compression |
| `chunks` | `bool` | whether raw chunks can be reassembled; default true |
| `ssl-upgrade` | `bool` | client can handle a negotiated TLS upgrade on plain TCP; default false |
| `request` | `str` | one-shot or special profile, Section 5.4 |
| `versions` | `bool` | request detailed server component versions; default false |
| `server-features` | `bool` | request server feature flags; default false |
| `username` | `str` | authentication identity |
| `digest` | `list<str>` | challenge digest algorithms accepted by the client |
| `salt-digest` | `list<str>` | salt combination digests accepted by the client |
| `challenge` | `bool` | the client already holds credentials and expects a `challenge` |
| `datagram-packet-types` | `list<str>` | packet types the sender accepts as unreliable datagrams; only on transports that carry datagrams, see [transports](../Porting/Transports.md#quic) |
| `uuid` | `str` | client instance identifier; when present MUST be a valid UUID string |
| `session-id` | `str` | identifies a client session across reconnections; when present MUST be a valid UUID string |
| `hostname`, `machine_id` | `str` | endpoint identity/advisory metadata |
| `build`, `platform`, `network` | `map` | extensible diagnostic metadata |

The effective record compression level is the lowest of the two peers' levels.

The `version` value is informational: compatibility is decided by
`protocol-version` alone, see below. A third-party implementation of this
document SHOULD announce the version of the protocol document it implements
(`8.0` for this one), not its own release number. The version of the
implementation itself belongs in `build.version` or in an implementation-specific key.

The server only offers an `ssl-upgrade` when the client sets the top-level
`ssl-upgrade` boolean to true. The legacy `packet-types` capability is ignored;
endpoints MUST use feature and subsystem capabilities to determine which
optional packets the peer supports.

The legacy `wants` capability is ignored. Clients request detailed component
versions and server feature flags using the `versions` and `server-features`
booleans. Other capability groups are provided by the enabled subsystems.

`protocol-version` is the only version check: an implementation MUST
disconnect, with `version error` for a server, if its own version is lower than
the value received, or if the value is not a valid version. A peer that
omits it is treated as requiring version 7.0. A receiver running modern-only
exposes 8.0 and relies on its peers to bail out. A version 7 peer that exposes a
`protocol-version` lower than 7.0 also talks to older peers: it switches to the
packets and capabilities described here once it receives a `protocol-version`
of 7.0 or later, which conforming implementations MUST therefore expose.

### 5.3 Authentication and Upgrade Packets

| Direction | Packet | Arguments |
|---|---|---|
| C -> S | `hello` | `capabilities:map` |
| S -> C | `hello` | `capabilities:map` |
| S -> C | `challenge` | `salt:bytes`, `auth_caps:map`, `digest:str`, `salt_digest:str`, `prompt:str` |
| C -> S | `hello` | original capabilities plus challenge response fields |
| S -> C | `ssl-upgrade` | `attributes:map` |
| C -> S | `ssl-upgrade` | `attributes:map` (empty) |
| either | `connection-close` | `reason:str`, `details:str...` |

The challenge algorithms, the response fields and test vectors are specified in
the [porting authentication guide](../Porting/Authentication.md). Each round of
a challenge is answered with a complete new `hello`, which the server validates
again from the start (version, encoders, ...). A client that already holds
credentials MAY set `challenge: true` in its first `hello`: the server then
always answers with a `challenge`, even when no authentication module needs one,
so that the client never sends its full capabilities before being challenged.

The server MAY answer a client `hello` with `ssl-upgrade` before authentication,
when the connection is plain TCP, the client set the top-level `ssl-upgrade`
boolean to true, it did not request `encryption`, and the server has a TLS
certificate. TLS and upgrades must also be enabled for that server connection.
The `attributes` contain `cert-data:bytes`, the contents of the server's
certificate file (PEM). The client sends `["ssl-upgrade", {}]`, finishes sending
that packet and stops packet I/O, performs a TLS client handshake on the same
socket, then sends its `hello` again over TLS.

A client MUST only advertise `ssl-upgrade: true` if it implements this exchange.
It should include the capability in its initial `hello`, including a minimal
`hello` sent to request a password challenge. An absent or false capability
disables this exchange. The reference Python client opts in with
`--ssl-upgrade=yes`; its upgrades are opportunistic and do not verify the server
certificate or hostname by default, see [TLS configuration](SSL.md#negotiated-tls-upgrades).

`connection-close` arguments are a short reason followed by optional details,
all plain strings. Receivers keep at most the first 8 and truncate each to 256
characters. Rejections caused by a configuration or policy MAY use a
`reason:detail` form within the first string. The standard reasons are:

| Category | Reasons |
|---|---|
| timeouts | `client ping timeout`, `login timeout`, `client exit timeout`, `idle timeout` |
| errors | `protocol error`, `version error`, `control command error`, `authentication failed`, `authentication error`, `permission error`, `server error`, `connection error`, `session not found error` |
| normal | `done`, `server exit`, `server upgrade`, `server shutdown`, `client request`, `detach request`, `new client`, `session busy` |
| sent by clients | `client exit` |

A reason containing `error`, or containing `timeout` other than `idle timeout`,
SHOULD be reported to the user as an error. Unknown reasons MUST be accepted
and displayed as they are.

Transport TLS configuration is described in the [TLS](SSL.md) document.

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
| `run` | `run:list<str>`, `run-wait-time:int?` | command result in `run_response` |
| `exec` | `run:list<str>` | immediate process launch result in `run_response` |
| `print` | `print:map` with `size:u64` | `printer` hello, then the client sends `printer-file` |
| `encode` | `encoding:map` | stateless encoder service |
| `detach` | none | disconnect attached clients as authorized |
| `exit` | none | terminate the server process as authorized |
| `stop` | none | stop the session as authorized |
| `register` | registration fields | register a session with a proxy registry |

Authorization is profile-specific. A server MUST NOT grant a request merely
because its name is recognized. Unknown requests MUST be rejected.

A `print` request only announces the size of the file, which would not fit in
the hello packet. If the server accepts the job, it raises its packet size limit
to fit a file of that size and replies with `printer: {"ready": true}`. The client
then sends a single `printer-file` packet, and the server closes the connection
with `done` once the job has been handled, or with an error message otherwise.
A refused request is answered with `printer: {"code": u8, "info": str}`
followed by `done`.

For `run`, `run-wait-time` is a nonnegative wait in milliseconds. An omitted,
invalid, or negative value selects the legacy immediate-launch behavior.
The client defaults to `XPRA_RUN_WAIT_TIME=5000`. A positive wait captures
stdout and stderr and returns when the command exits or the wait expires.
`run_response` contains `pid`, binary `stdout` and `stderr`, boolean
`stdout-truncated` and `stderr-truncated`, and `returncode` if the process
has exited. Each stream retains at most its first 1 MiB (less if required
by the configured packet size). Request or launch errors use `code` and
`message`. A successful immediate launch returns only `pid`.

At the deadline, the client receives one output snapshot and disconnects.
The command continues running, with subsequent output drained and discarded
by the server. Stdin is not forwarded. The `exec` profile forces zero wait
and is subject to both `exec` and existing `run` connection restrictions.
Compatibility-disabled clients use `exec`; compatibility-enabled clients
send `run` with `run-wait-time=0` instead.

The encoder service is selected by connecting to an encoder server and uses the
same handshake followed by the `encode` and `context-*` packets in Section 8.11.
Both ends only use the modern packets, so they expose a `protocol-version` of
8.0 and reject a peer whose `protocol-version` is missing or lower than 8.0,
as that peer may also use the legacy packets.
A listener or proxy may use `register` with `uuid`, session identity, display
addresses and connection options, and MAY hand the authenticated connection to
the selected session. Handover is an implementation action; the Xpra record
stream continues unchanged.

## 6. Capability Namespaces

Capabilities describe what the sender can receive or what local service it is
offering. Feature maps are extensible: omitted keys mean unsupported or their
documented default.

Most subsystems are enabled for a connection only when the client's `hello`
contains their key: an absent or false value disables the subsystem, a map
enables it with the settings it contains. The `display`, `window` and `encoding`
maps are REQUIRED for a client that wants to show windows: without a `display`
map the server creates no display state for the client, an empty `window` map
means no windows, and a client that wants windows but advertises no picture
encodings is rejected. See the [porting handshake guide](../Porting/Handshake.md)
for a minimal client `hello`.

| Key | Type | Interoperability fields | Specified in |
|---|---|---|---|
| `audio` | map | `async:bool` in the hello, then `audio-capabilities` packets | [audio](../Subsystems/Audio.md) |
| `bandwidth` | map | `limit:u64` (bits per second, 0 for none), `detection:bool` | [bandwidth](../Subsystems/Bandwidth.md) |
| `connection-data` | map | `adapter-type:str`, `jitter:u32`, `speed:u64` | [bandwidth](../Subsystems/Bandwidth.md) |
| `clipboard` | map | `notifications`, `selections`, `greedy`, `want_targets`, `preferred-targets`; `direction` (server only) | [clipboard](../Subsystems/Clipboard.md) |
| `command` | map | `menu:bool` | [command](../Subsystems/Command.md) |
| `cursor` | map | `encodings`, `default`, `max` (client); `sizes`, `default` (server) | [cursor](../Subsystems/Cursor.md) |
| `display` | map | `desktop_size`, `monitors`, `monitor-relative`, `dpi`, `refresh-rate`, ... | [display](../Subsystems/Display.md) |
| `encoding` | map | `options`, `core`, `rgb_formats`, `window-icon`, `full_csc_modes`, quality and speed, codec profiles | [encoding](../Subsystems/Encoding.md) |
| `events` | bool | the client accepts `events` packets | Section 7.1 |
| `file` | map | `enabled`, `ask`, `size-limit`, `chunks`, `open`, `open-ask`, `open-url`, `open-url-ask`, `request-file`, `ask-timeout` | [file transfers](../Subsystems/File.md) |
| `printer` | map | `printing`, `printing-ask` | [file transfers](../Subsystems/File.md) |
| `keyboard`, `modifiers`, `keymap`, `key_repeat`, `ibus` | top-level | enabled state, modifiers, repeat timing and keymap definition | [keyboard](../Subsystems/Keyboard.md) |
| `metadata.supported` | `list<str>` | the window metadata keys the client wants to receive | [window](../Subsystems/Window.md) |
| `mmap` | map | `read` and `write` area descriptors | [mmap](../Subsystems/MMAP.md) |
| `notification` | bool | the client can show notifications | [notification](../Subsystems/Notification.md) |
| `ping` | bool | the client answers `ping` packets, Section 7.1 | [ping](../Subsystems/Ping.md) |
| `pointer` | map | `initial-position`, `double_click`, `sync` | [pointer](../Subsystems/Pointer.md) |
| `bell`, `system_tray` | bool | the client handles `window-bell`, and tray windows | [window](../Subsystems/Window.md) |
| `webcam` | bool | the client may forward a webcam | [webcam](../Subsystems/Webcam.md) |
| `window` | map | `enabled`, `restack`, `grabs`, `min-size`, `max-size`, `sync-*` | [window](../Subsystems/Window.md) |

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
| either | `ping` | `monotonic_ms:u64`, `wallclock_ms:u64`, `sid:str` |
| either | `ping-echo` | `monotonic_ms:u64`, `load1:u64`, `load5:u64`, `load15:u64`, `latency_ms:i64`, `sid:str?` |
| S -> C | `startup-complete` | none |
| either | `setting-change` | `name:str`, `value:any` |
| S -> C | `events` | `name:str`, `values:any...` |
| S -> C | `control` | `command:str`, `arguments:any...` |
| C -> S | `control-request` | `request_id:u64`, `command:str`, `arguments:any...` |
| S -> C | `info-response` | `information:map` |
| C -> S | `info-request` | `client_uuids:list<str>`, `window_ids:list<u64>`, `categories:list<str>`, `subsystems:list<str>?` |
| C -> S | `shutdown-server` | `exit:bool`, `reason:str?` |
| C -> S | `suspend` | `suspended:bool` |
| C -> S | `bell-set` | `enabled:bool` |

`monotonic_ms` uses the sender's monotonic clock and is a correlation value;
`wallclock_ms` is the sender's wall-clock time (milliseconds since the epoch),
only used for diagnostics. The `ping-echo` MUST copy `monotonic_ms` and `sid`
from the `ping` it answers: the server ignores echoes whose `sid` does not match
its own. Load values are scaled by 1000. A negative latency means unknown.

A client that advertises `ping: true` MUST answer every `ping` with a
`ping-echo`: the server pings it every few seconds and disconnects it with
`client ping timeout` when no matching echo has been received for 60 seconds.
A client that does not advertise `ping` is never pinged by the server.

`events` packets are only sent to clients that advertise `events: true`. They
carry server lifecycle notifications such as `ready`, `suspend`, `resume`,
`exit`, `handshake-complete`, `startup-complete` and `connection-lost`, and MAY
be ignored.

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
| C -> S | `display-ungrab` | `wid:u64` (ignored) |
| C -> S | `display-monitor-configure` | `action:str`, `arguments:any...` |

`display-configure` carries the same monitor, desktop, DPI and scaling
structures advertised in the display capabilities, using the hyphenated key
names defined in the [display subsystem](../Subsystems/Display.md).
`display-ungrab` asks the server to release any keyboard or pointer grab held
by an application. `display-monitor-configure` adds (`"add", [w, h]`) or
removes (`"remove", "index", n` or `"remove", "wid", wid`) a virtual monitor
on servers that advertise monitor management.

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
| S -> C | `window-grab` | `wid:u64` |
| S -> C | `window-ungrab` | `wid:u64` |
| S -> C | `window-stacking` | `wids:list<u64>` |
| C -> S | `window-map` | `wid:u64`, `x:i16`, `y:i16`, `w:u16`, `h:u16`, `client_properties:map`, `state:map?`, `monitor:map?` |
| C -> S | `window-unmap` | `wid:u64`, `iconified:bool?`, `state:map?` |
| C -> S | `window-configure` | `wid:u64`, `configuration:map` |
| C -> S | `window-close` | `wid:u64` |
| C -> S | `window-dismiss` | `wid:u64` |
| C -> S | `window-focus` | `wid:u64`, `modifiers:list<str>?` |
| C -> S | `window-action` | `wid:u64`, `action:str`, `arguments:any...` |
| C -> S | `window-stacking` | `wids:list<u64>` |
| C -> S | `window-refresh` | `wid:u64`, `unused:u8` (0), `quality:u8`, `options:map`, `client_properties:map` |
| C -> S | `window-ack` | `wid:u64`, `width:u16`, `height:u16`, `sequence:u64`, `decode_time_us:i32`, `message:str`, `extra:map?` |
| C -> S | `window-signal` | `wid:u64`, `signal:str` |
| S -> C | `window-draw-fragment` | `window-draw` fields 1 to 10, then `index:u16`, `count:u16`, `group_start:u16`, `group_size:u16`, `previous_sequence:u64` |

Window IDs are allocated by the server, are in the range `1..2^48-1`, and remain
valid until `window-destroy`. On X11 servers they are the X11 window identifiers,
so they are neither small nor contiguous. In `window-refresh`, `wid` zero means
every window.

Every `window-draw` MUST be answered with exactly one `window-ack` carrying the
same `wid` and `sequence`, including draws that could not be decoded or that
refer to an unknown window. The server uses these acknowledgements for flow
control, the exact rules and the negative `decode_time_us` error codes are in
the [encoding subsystem](../Subsystems/Encoding.md#acknowledgements-and-flow-control).
`window-draw-fragment` is only used on transports that carry datagrams, such as
[QUIC](QUIC.md): each fragment carries part of the `data` of one `window-draw`.

`window-signal` sends a POSIX signal to the process that owns the window. The
server advertises the signal names it accepts in `window.signals`.
`window-dismiss` requires the server's `window.dismiss` capability and only
unmaps override-redirect popups. Readonly clients cannot dismiss remote windows.
The encoding and options of `window-draw` MUST have been advertised by the
client. A sequence acknowledgement MUST refer to the matching draw and window.
`window-stacking` lists windows from bottom to top. Servers forward it to
recording clients and clients advertising `window.sync-stacking`; this stream
does not require a connection `record` or `sync` permission.

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
| either | `pointer-motion` | `device:i64`, `sequence:u64`, `wid:u64`, `pointer:list<coord>`, `properties:map` |
| either | `pointer-button` | `device:i64`, `sequence:u64`, `wid:u64`, `button:u8`, `pressed:bool`, `pointer:list<coord>`, `properties:map` |
| C -> S | `pointer-wheel` | `wid:u64`, `button:u8`, `distance:i64`, `pointer:list<coord>`, `modifiers:list<str>`, `buttons:list<u8>`, `properties:map` |
| S -> C | `pointer-wheel` | `wid:u64`, `button:u8`, `distance:i64`, `pointer:list<coord>`, `modifiers:list<str>` |
| S -> C | `pointer-position` | `wid:u64`, `x:i16`, `y:i16`, `relative_x:i16?`, `relative_y:i16?` |
| C -> S | `pointer-devices` | `format:str`, `devices:map` |

Keyboard event properties include modifier names, key value, text, hardware
keycode and layout group. Pointer coordinates are `[x, y]`; extra device axes
may follow only when advertised. A `device` value of `-1` means "unspecified".

The `pointer-wheel` `button` is the X11 wheel button the motion corresponds to:
`4` up, `5` down, `6` left, `7` right. `distance` is the signed scroll distance
multiplied by 1000, where 1000 is one wheel click. Clients only send
`pointer-wheel` to servers that advertise `wheel.precise` or
`wheel.emulation`; otherwise they emulate the wheel with
`pointer-button` press and release pairs on the same buttons. See the
[pointer subsystem](../Subsystems/Pointer.md) for the properties.

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
| `clipboard-contents` | `request_id:u64`, `selection:str`, `data_type:str`, `data_format:u8`, `wire_encoding:str`, `data:any`, `truncated:u64` |
| `clipboard-contents-none` | `request_id:u64`, `selection:str?` |
| `clipboard-pending-requests` | `count:u8` |

The `clipboard-data` options are `claim:bool`, `greedy:bool`, `origin:str`,
`synchronous:bool`, `targets:list<str>` and `data:map`. Each `data` entry maps
a target name to `[data_type:str, data_format:u8, wire_encoding:str, wire_data:any]`.

Request IDs correlate exactly one contents response. A `clipboard-contents`
`truncated` value is the number of bytes dropped from the end of `data` to fit
the size limit, zero when complete. Receivers MUST enforce negotiated
selection, target and size limits before exposing clipboard data. The wire
encodings, the data formats and the request timeouts are specified in the
[clipboard subsystem](../Subsystems/Clipboard.md).

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
| either | `audio-stream` | `event:str` (`start` or `end`), `codec:str`, `sequence:i64` |
| either | `audio-keepalive` | `time:u64` |
| S -> C | `audio-level` | `sample:map` |
| S -> C | `audio-signal` | `present:bool` |

`audio-stream` marks the start and end of a stream, it is only sent to peers
that advertise `stream-packet` in their audio capabilities. Older peers mark the
start and end of a stream using `audio-data` packets without data, with
`start-of-stream` / `end-of-stream` metadata flags.
`audio-data` metadata carries the sequence, timestamp and codec properties.
A peer that advertises `keepalive` in its audio capabilities promises to echo,
while it receives a stream, the `time` metadata of the latest `audio-data` in an
`audio-keepalive` packet every few seconds. The sender then stops the stream (or
drops data) when the echoes stop arriving. Peers that do not advertise
`keepalive` are not subject to this. See the [audio subsystem](../Subsystems/Audio.md).
Codec and direction MUST have been negotiated. Implementations MAY
send audio level/signal packets to clients advertising `audio.level` and
`audio.signal`, respectively; their payload is codec-backend metadata and is
optional.

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
server. `printer-file` is only accepted on a `print` request connection
(Section 5.4).

| Packet | Arguments |
|---|---|
| `file-send` | `filename:str`, `mimetype:str`, `print:bool`, `open:bool`, `size:u64`, `data:bytes`, `options:map`, `send_id:str?` |
| `file-send-chunk` | `chunk_id:str`, `chunk_no:u32`, `data:bytes`, `has_more:bool` |
| `file-ack-chunk` | `chunk_id:str`, `ok:bool`, `message:bytes|str`, `chunk_no:u32` |
| `file-data-request` | `type:str`, `send_id:str`, `url:str`, `mimetype:str`, `size:u64`, `print:bool`, `open:bool`, `options:map?` |
| `file-data-response` | `send_id:str`, `accept:bool` |
| `file-request` | `filename:str`, `open:bool`, `send_id:str` |
| `file-open-url` | `url:str`, `send_id:str` |
| `printer-devices` | `printers:map` |
| `printer-file` | `filename:str`, `data:bytes`, `mimetype:str?`, `source_uuid:str?`, `title:str?`, `printer:str?`, `copies:u16?`, `options:map|str?` |

`file-send` options carry digests and, for chunked transfers,
`file-chunk-id`. A receiver MUST validate the declared size, negotiated maximum,
authorization, basename, chunk order and digest. `file-data-response` authorizes
only the exact pending `send_id`; it is not blanket permission to send data.
The chunked transfer protocol, digests and timeouts are specified in the
[file transfer subsystem](../Subsystems/File.md).

### 8.11 Encoder Service

| Direction | Packet | Arguments |
|---|---|---|
| C -> S | `encode` | `input_coding:str`, `pixel_format:str`, `pixels:bytes`, `width:u16`, `height:u16`, `rowstride:u32`, `options:map`, `metadata:map` |
| C -> S | `context-request` | `id:u64`, `codec_type:str`, `encoding:str`, `width:u16`, `height:u16`, `source_format:str`, `options:map` |
| C -> S | `context-compress` | `id:u64`, `metadata:map`, `pixels:bytes|list<bytes>`, `options:map`, `send_options:map` |
| C -> S | `context-close` | `id:u64`, `reason:str` |
| S -> C | `encoding-set` | `properties:map`, with the encoder specifications in `video` |
| S -> C | `encode-response` | `encoding:str`, `data:bytes`, `options:map`, `width:u16`, `height:u16`, `rowstride:u32`, `bpp:u8`, `metadata:map` |
| S -> C | `context-response` | `id:u64`, `accepted:bool`, `message:str`, `properties:map` |
| S -> C | `context-data` | `id:u64`, `data:bytes`, `client_options:map`, `reply_options:map` |

Context IDs are client-selected and unique within one connection. Dimensions,
formats and codec options MUST be supported by the encoder capabilities.

### 8.12 Miscellaneous Feature Packets

| Direction | Packet | Arguments |
|---|---|---|
| C -> S | `gsettings-update` | `settings:map` |
| C -> S | `pointer-devices` | `format:str`, `devices:map` |

These packets are only sent when the server advertised the corresponding
capability: `gsettings` for `gsettings-update` (see
[gsettings](../Subsystems/GSettings.md)), and an `input-devices` value of `xi`
or `uinput` for `pointer-devices` (see [pointer](../Subsystems/Pointer.md#input-devices)).

### 8.13 Recording Profile

A client advertising the recording capabilities receives normal window and
input packets plus these wrappers:

| Direction | Packet | Arguments |
|---|---|---|
| S -> C | `keyboard-record` | `wid:u64`, `event:map` |
| S -> C | `clipboard-record` | `direction:str`, `embedded_type:str`, `embedded_arguments:any...` |

The keyboard event map contains `press`, `name`, `keyval`, `keycode`,
`modifiers`, `is-modifier` and `sync`. The clipboard wrapper preserves the
original modern clipboard packet after the direction field: `direction` is
`server` for a packet the server received from the client that owns the
clipboard, and `client` for a packet the server sent to it.

This profile is used by xpra's session recording client and replay tool, see
[#4812](https://github.com/Xpra-org/xpra/issues/4812) for the design, the
recording format and the replay tool. A recording client is a normal client,
usually readonly, which sets `record: true` in the capability maps of the
subsystems it wants to capture: `window`, `display`, `keyboard`, `clipboard` and
`pointer` (the latter makes the server forward the other clients' pointer packets,
see [pointer synchronization](../Subsystems/Pointer.md#pointer-synchronization)).
`window.record` also enables `window.sync-position`, `window.sync-focus` and
`window.sync-stacking`, so the recording follows the other clients' window
management. Each request is only granted when the server's `record` socket option
allows that subsystem (`record=yes`, `all`, or a list of `windows`, `display`,
`keyboard` and `clipboard`; the default is `no`): when it does not, the server
sends the client a notification instead, and the client receives nothing for that
subsystem. `pointer.record` is governed by the `sync` socket option instead,
which is enabled by default.

Optional platform-specific packets MUST be negotiated through subsystem
capabilities and MUST use a subsystem prefix. A peer that does not advertise
that feature must not receive them.

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
- Servers bound the handshake: a connection that has not completed its `hello`
  within 21 seconds of being accepted is closed with `login timeout`, and each
  `challenge` must be answered within 120 seconds. Clients MUST NOT wait for
  user input before sending their first `hello`.
- Once established, the obligations that keep a session alive are answering
  `ping` (Section 7.1), acknowledging every `window-draw` (Section 8.2) and, for
  peers that advertised audio `keepalive`, echoing `audio-keepalive` (Section 8.8). The
  server's `idle-timeout` MAY also disconnect a client without user input.

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
stable subsystem prefix and MUST be negotiated through subsystem capabilities
before use.
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
