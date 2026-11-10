# Handshake

This page describes how a client establishes a session: what it must send, what it
must check in the server's answer, and what keeps the connection alive afterwards.
The packet layouts are in the [protocol specification](../Network/Protocol.md), sections 5 to 7.

<div class="docs-section-heading" markdown="1">

## Sequence

</div>

```text
client                                   server
  | -- hello (capabilities) -------------> |
  | <------------- challenge (optional) -- |   repeated for each authentication step
  | -- hello (capabilities + response) --> |
  | <-------------------- hello ---------- |   or connection-close
  | <---- window-create, window-draw, ... -|   existing windows, cursor, ...
  | <---------- startup-complete --------- |
  | <==== application packets, both ways =>|
  | -- connection-close "client exit" ---> |
```

* The client's first record MUST be a `hello`, encoded with `rencodeplus`, and MAY be
  compressed with LZ4. It MUST be smaller than 16 KiB
  ([limits](../Network/Protocol.md#34-limits)).
* On plain TCP, a client that implements TLS upgrades MAY set the top-level
  `ssl-upgrade` boolean to true, including in an initial `hello` requesting a
  password challenge. The server may then offer an `ssl-upgrade` before
  authentication: the client acknowledges it, completes the TLS handshake, and
  sends its `hello` again over TLS. See the
  [upgrade exchange](../Network/Protocol.md#53-authentication-and-upgrade-packets).
  An absent or false capability disables this exchange.
* The server answers with a `challenge` when it needs credentials, see
  [authentication](Authentication.md): the client then sends a complete new `hello`,
  with the same capabilities plus the response.
* When the server accepts the client, it sends its own `hello`. From then on, either
  side may send any packet the other one advertised support for.
* The server may refuse the connection at any point with `connection-close`: the
  client should show the reason to the user.
* The server closes connections that have not completed the handshake within 21 seconds,
  or that take more than 120 seconds to answer a `challenge`.

<div class="docs-section-heading" markdown="1">

## Minimal client `hello`

</div>

This is close to the smallest `hello` that gives a working session with windows,
keyboard and pointer input (shown as JSON, sent as rencodeplus):

```json
{
  "version": "1.0",
  "protocol-version": [8, 0],
  "encoders": ["rencodeplus"],
  "compressors": ["lz4", "none"],
  "compression_level": 1,
  "uuid": "1b4e28ba2fa1411d8f2c8b6b0e2a2f3c",
  "username": "user",
  "digest": ["hmac+sha256", "hmac+sha512"],
  "salt-digest": ["hmac+sha256", "hmac+sha512"],
  "ping": true,
  "server-features": true,
  "display": {
    "desktop_size": [1920, 1080],
    "monitors": {
      "0": {"geometry": [0, 0, 1920, 1080], "primary": true}
    }
  },
  "window": {"enabled": true},
  "encoding": {
    "options": ["rgb", "png"],
    "core": ["rgb24", "rgb32", "png"],
    "rgb_formats": ["BGRX", "BGRA", "RGBX", "RGBA"],
    "rgb_lz4": true,
    "transparency": false,
    "window-icon": ["png"]
  },
  "keyboard": true,
  "modifiers": [],
  "keymap": {"layout": "us"},
  "pointer": {"double_click": {"time": 400, "distance": [5, 5]}},
  "cursor": {"encodings": ["raw", "png"]}
}
```

Notes:

* `protocol-version` is required: it is the minimum protocol version you are willing
  to talk to, and it must be at least `[7, 0]`. Use `[8, 0]`, since you only implement
  the modern packets. The server disconnects clients that require a newer version than
  its own, see [core capabilities](../Network/Protocol.md#52-core-capabilities).
* `version` is your client's own version, in any format: it has no requirements and
  is only informational.
* `encoders` is required, and MUST contain `rencodeplus`.
* `server-features: true` asks the server to include its feature flags in its `hello`:
  the `window`, `pointer`, `file`, `printer`, `notification`, `audio`, `webcam` and
  sharing capabilities, `readonly`, and the `wheel.*` pointer flags. Without it, the
  server's `hello` only contains the core, display, encoding, cursor and clipboard
  capabilities. Interactive clients should always set it.
* `uuid` (and `session-id`, if you send one) MUST be valid UUIDs: a random 32-character
  hexadecimal string is fine. Generate a new `uuid` for each client instance; the server
  uses it to recognize a client that reconnects.
* `client_type` is optional: a short name for your client (ie: `HTML5`), which the server
  shows in its connection and disconnection log messages and in its info. Avoid `top`, which
  the server reserves for monitoring clients that do not receive files or print jobs.
* `digest` and `salt-digest` are REQUIRED when the server uses authentication: without
  them, the server cannot generate a challenge and the connection fails. List only the
  digests you implement. Add `xor` to `digest` only if you are prepared to send the
  password itself to the server (some server authentication modules require it), and
  never over an unencrypted connection, see [authentication](Authentication.md).
* `display` MUST be present and non-empty, and `window` MUST be a non-empty map to
  receive windows. An `encoding` map listing at least one encoding is then required.
* `keyboard`, `pointer` and `cursor` must be true, or non-empty maps, to enable those
  subsystems: **an empty map counts as false**. The same applies to every subsystem.
* `keymap` can be much richer, see [keyboard](../Subsystems/Keyboard.md). With only a
  `layout`, the server maps the X11 key names sent in `keyboard-event` packets.
* `"monitors"` keys are monitor indexes: they are shown as strings here because JSON
  requires it, but they are integers on the wire.
* The coordinates and sizes in `display` are in server pixels: a client that scales
  its display divides its own dimensions by its scaling factor.

Everything else is optional. The [features](Features.md) page lists the capabilities
of each subsystem.

<div class="docs-section-heading" markdown="1">

## Sharing a session

</div>

When another client is already connected, the server's `sharing` and `lock` options
decide what happens. A client can influence it with three booleans:

| Capability | Default | Meaning |
|---|---|---|
| `share` | `False` | The client accepts sharing the session with other clients |
| `steal` | `True` | The client may take over the session: when false, it is refused with `session busy` if another client is connected |
| `lock` | `False` | No other client may connect while this one is |

A client which takes over the session causes the server to disconnect the other client
with `new client`. A client reconnecting with the same `uuid` replaces its previous
connection.

<div class="docs-section-heading" markdown="1">

## The server's `hello`

</div>

The client MUST check:

* `protocol-version`: disconnect if the server requires a newer protocol version than
  the one you implement (a server that omits it requires `7.0`), `version` is the server's
  own version and only informational;
* `encoders` and `compressors`: from now on, only send with an encoder and a compressor
  that the server listed;
* `display`: a map with the display size given to this client (`desktop_size`), the
  server's actual size and its maximum size, see [display](../Subsystems/Display.md);
* `encoding`: the picture encoding the server has selected. The list of encodings the
  server can send arrives in an `encoding-set` packet right after the `hello`, see
  [encoding](../Subsystems/Encoding.md#capabilities). It only matters for user interfaces:
  the server never sends an encoding the client did not advertise.

Other useful keys (most of them only when the client set `server-features`):

| Key | Information |
|---|---|
| `mode` | The type of session: `seamless` (individual windows), `desktop` (a whole desktop in one window), `monitor`, `shadow` (an existing display) |
| `server.mode` | A more detailed description of the server type, informational |
| `session_name`, `hostname` | For display to the user |
| `window` | Window management capabilities, see [window](../Subsystems/Window.md#server-capabilities) |
| `cursor`, `clipboard`, `file`, `printer`, `notification`, `audio` | Each subsystem's server capabilities, absent when the server does not support it |
| `readonly` | The server only accepts a readonly connection from this client: do not send input |
| `wheel.precise`, `wheel.emulation`, `pointer.relative` | Pointer features, see [pointer](../Subsystems/Pointer.md) |
| `start_time`, `current_time` | Server clock, in seconds since the epoch |
| `digest`, `salt-digest` | The digests the server supports |

A client that has credentials but was never sent a `challenge` SHOULD warn the user:
the server accepted the connection without verifying them.

<div class="docs-section-heading" markdown="1">

## After the handshake

</div>

Right after its `hello`, the server sends a `window-create` packet for each existing
window, followed by its contents (`window-draw`), the current cursor, pending
notifications and the clipboard state, then `startup-complete`. The client does not
need to request any of this. See the [window lifecycle](../Subsystems/Window.md#window-lifecycle).

If the client deferred its keymap (`keymap.delay`), it MUST send its `keyboard-config`
now.

<div class="docs-section-heading" markdown="1">

## Staying connected

</div>

A connection stays up as long as the client:

* answers each `ping` with a `ping-echo` copying its timestamp and source ID, within
  60 seconds (only when the client advertised `ping: true`);
* acknowledges each `window-draw` with a `window-ack`: missing acknowledgements do not
  disconnect the client, but the server then sends screen updates in bursts every few
  seconds instead of continuously;
* echoes `audio-keepalive` packets, if it advertised audio `keepalive` and receives audio.

The server's `idle-timeout` option, when set, also disconnects clients without user
activity (`idle timeout`).

<div class="docs-section-heading" markdown="1">

## Closing

</div>

To disconnect, send `["connection-close", "client exit"]`, then close the transport.
A client that wants the server to keep running shuts down that way: the session
continues and the client can reconnect later. To stop the session instead (which
terminates its applications), send `["shutdown-server", false]`, or
`["shutdown-server", true, reason]` to make the server process exit. The server's
`client-shutdown` option decides whether clients may do either, and the server ignores
both from readonly clients.

When the server closes the connection, its `connection-close` reason tells the client
whether this is an error (see [reasons](../Network/Protocol.md#53-authentication-and-upgrade-packets)).
A transport EOF without a `connection-close` is an abnormal disconnection: clients
usually try to reconnect.
