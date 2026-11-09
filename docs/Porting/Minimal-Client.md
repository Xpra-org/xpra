# Minimal client

This page walks through a complete session as seen by a minimal client: one which
connects over TCP, authenticates with a password, shows the windows using the `rgb`
and `png` encodings, and sends keyboard and pointer events. Everything it needs is
specified in the pages linked from each step.

The trace below was recorded from such a client, connected to `xpra start --start=xterm`
with password authentication, then shortened: values in angle brackets were elided. Packets are shown as JSON-like lists; on the wire they are
rencodeplus lists inside xpra records ([protocol](../Network/Protocol.md) sections 3 and 4).

<div class="docs-section-heading" markdown="1">

## The record layer

</div>

Reading a packet:

```text
loop:
    header = read 8 bytes
    check header[0] == 'P'
    flags, compression, index = header[1], header[2], header[3]
    size = big-endian u32 from header[4:8]
    check size against the current limit
    payload = read size bytes
    if compression != 0:
        level = compression & 0x0f, algorithm = compression & 0xf0
        0x10: payload = lz4 block decompress (size = little-endian u32 prefix)
        0x40: brotli, 0x80: zstd
    if index > 0:
        chunks[index] = payload        # raw chunk, wait for the main packet
        continue
    packet = rencodeplus decode (flags & 0x10) or YAML (flags & 0x04)
    for each index, data in chunks: packet[index] = data
    clear chunks
    dispatch packet
```

Writing a packet:

```text
payload = rencodeplus encode [type, arg1, arg2, ...]
if len(payload) > 378 and the peer accepts lz4:
    payload = u32 little-endian len(payload) + lz4 block(payload), compression = 0x11
header = 'P', 0x10, compression, 0, big-endian u32 len(payload)
send header + payload
```

The rest of this page only shows packets.

<div class="docs-section-heading" markdown="1">

## Connecting and authenticating

</div>

```text
C->S ["hello", {"version": "8.0", "protocol-version": [8, 0], "encoders": ["rencodeplus"], "compressors": ["lz4", "none"],
                "digest": ["hmac+sha256", "hmac+sha512"], "salt-digest": ["hmac+sha256", "hmac+sha512"],
                "display": {...}, "window": {"enabled": true}, "encoding": {...},
                "keyboard": true, "pointer": {...}, "ping": true, "server-features": true, ...}]
```

The full capabilities are shown in the [handshake](Handshake.md#minimal-client-hello).

This example omits the optional `ssl-upgrade` capability, so the server proceeds
without offering a TLS upgrade. A client that implements the
[upgrade exchange](../Network/Protocol.md#53-authentication-and-upgrade-packets)
can set the top-level `ssl-upgrade` boolean to true in its first `hello` and
handle an upgrade before authentication.

```text
S->C ["challenge", <64 random bytes>, {}, "hmac+sha512", "hmac+sha512", "password for user 'antoine'"]
```

The server needs a password and picked `hmac+sha512` from the client's lists. The client
computes the response as described in [authentication](Authentication.md) and sends its
`hello` again, with the response:

```text
C->S ["hello", {...same capabilities..., "challenge_response": b"78f1...", "challenge_client_salt": <32 bytes>,
                "challenge_padding": <384 random bytes>}]
```

With a wrong password, the server would answer `["connection-close", "authentication failed"]`.

<div class="docs-section-heading" markdown="1">

## Session start

</div>

```text
S->C ["hello", {"version": "8.0", "mode": "seamless", "encoders": ["rencodeplus", "yaml", "none"],
                "compressors": ["lz4", "brotli", "none"], "encoding": "auto",
                "display": {"desktop_size": [1920, 1080], "actual_desktop_size": [1920, 1080],
                            "max_desktop_size": [3840, 2160], "name": ":117", ...}, ...}]
S->C ["encoding-set", {"encodings": {"": [...], "core": [...], ...}, "video": {...}}]
```

The session is established: the client checks the server's `protocol-version`, encoders and
compressors ([handshake](Handshake.md#the-servers-hello)). The server then sends the
windows that already exist:

```text
S->C ["window-create", 0xa0000c, 0, 0, 499, 316, {"title": "user@host:~", "class-instance": ["xterm", "XTerm"], ...}, {}]
C->S ["window-map", 0xa0000c, 0, 0, 499, 316, {}, {}]
S->C ["startup-complete"]
S->C ["cursor-default"]
S->C ["window-icon", 0xa0000c, <w>, <h>, "png", <png data>]
S->C ["window-draw", 0xa0000c, 0, 0, 499, 316, "png", <3178 bytes>, 1, 0, {"flush": 0, "window-size": [499, 316]}]
C->S ["window-ack", 0xa0000c, 499, 316, 1, 1250, ""]
```

* `window-create` gives the window's position and size on the server's display, and its
  metadata ([window](../Subsystems/Window.md#window-metadata)). The client creates a
  native window, and since this is not an override-redirect window, it sends a `window-map`
  once it has shown it.
* The first `window-draw` contains the whole window, as a PNG file. The client decodes it,
  paints it at `0,0` in the window, and since `flush` is zero, presents the window.
  It then acknowledges the draw with its sequence number (`1`) and the decoding time in
  microseconds ([acknowledgements](../Subsystems/Encoding.md#acknowledgements-and-flow-control)).

<div class="docs-section-heading" markdown="1">

## Input and updates

</div>

The user types `ls` and presses Return in the terminal:

```text
C->S ["window-focus", 0xa0000c, []]
C->S ["pointer-motion", -1, 0, 0xa0000c, [249, 158], {}]
C->S ["keyboard-event", 0xa0000c, "l", true, {"modifiers": []}]
C->S ["keyboard-event", 0xa0000c, "l", false, {"modifiers": []}]
C->S ["keyboard-event", 0xa0000c, "s", true, {"modifiers": []}]
C->S ["keyboard-event", 0xa0000c, "s", false, {"modifiers": []}]
C->S ["keyboard-event", 0xa0000c, "Return", true, {"modifiers": []}]
C->S ["keyboard-event", 0xa0000c, "Return", false, {"modifiers": []}]
```

Key names are X11 keysym names ([keyboard](../Subsystems/Keyboard.md)), and pointer
positions are absolute positions on the server's display ([pointer](../Subsystems/Pointer.md)).
The terminal updates its contents, and the server sends the areas that changed:

```text
S->C ["window-draw", 0xa0000c, 221, 15, 18, 13, "rgb24", <936 bytes>, 2, 72, {"rgb_format": "BGRX", "lz4": 1, "flush": 0, ...}]
C->S ["window-ack", 0xa0000c, 18, 13, 2, 40, ""]
S->C ["window-draw", 0xa0000c, 221, 54, 6, 13, "rgb24", <312 bytes>, 3, 24, {"rgb_format": "BGRX", "flush": 9, ...}]
S->C ["window-draw", 0xa0000c, 209, 54, 12, 13, "rgb24", <624 bytes>, 4, 48, {"rgb_format": "BGRX", "lz4": 1, "flush": 8, ...}]
S->C ["window-draw", 0xa0000c, 17, 54, 192, 13, "rgb24", <9984 bytes>, 5, 768, {"rgb_format": "BGRX", "lz4": 2, "flush": 7, ...}]
...
```

* `rgb24` pixels sent as `BGRX`: 4 bytes per pixel, rows of `rowstride` bytes (`72` for an
  18 pixel wide area).
* With `lz4`, the data starts with the uncompressed size as a little-endian u32 (here `936`
  for 13 rows of 72 bytes), followed by an LZ4 block. Without it, the data is the raw pixels.
* `flush` counts down the packets that belong to the same update: the client paints each
  one as it arrives, but only needs to present the window when `flush` reaches zero.
* Every draw is acknowledged.

<div class="docs-section-heading" markdown="1">

## Keeping the connection alive

</div>

Every few seconds:

```text
S->C ["ping", 12345678, 1762706520000, "5f0c..."]
C->S ["ping-echo", 12345678, 0, 0, 0, -1, "5f0c..."]
```

The client echoes the timestamp and the source ID; it has no load average or latency
measurement to report ([ping](../Subsystems/Ping.md)).

<div class="docs-section-heading" markdown="1">

## Disconnecting

</div>

```text
C->S ["connection-close", "client exit"]
```

The client closes the socket. The session keeps running on the server, and the client
can connect again later: the server will send the existing windows again.

<div class="docs-section-heading" markdown="1">

## What to add next

</div>

* `window-move-resize`, `window-resized`, `window-metadata`, `window-destroy` and
  `window-configure` to track window changes ([window](../Subsystems/Window.md)).
* `display-configure` when the client's screen layout changes ([display](../Subsystems/Display.md)).
* `cursor-data`, to show the application's cursors ([cursor](../Subsystems/Cursor.md)).
* More encodings and video ([encoding](../Subsystems/Encoding.md)).
* Then the other [features](Features.md).
