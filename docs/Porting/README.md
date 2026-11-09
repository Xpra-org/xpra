# Porting

This section is for developers who want to implement the xpra protocol: a new
client (the most common case), a proxy, or a server. It is the entry point to the
technical documentation, and is meant to be sufficient without reading the xpra
source code.

Existing implementations in other languages are listed in
[client implementations](../Usage/Clients.md): they are useful references, and the
smaller ones (`go-xpra`, `rust-xpra`) show how little is needed for a working client.

<div class="docs-section-heading" markdown="1">

## Reading order

</div>

| Step | Page | What it covers |
|---:|---|---|
| 1 | [Transports](Transports.md) | Getting a byte stream to the server: TCP, WebSocket, TLS, SSH |
| 2 | [Protocol](../Network/Protocol.md) | The normative specification: record header, packet encoding, compression, the packet registry |
| 3 | [Handshake](Handshake.md) | The `hello` exchange, the minimal client capabilities, what keeps a connection alive |
| 4 | [Authentication](Authentication.md) | The `challenge` packet and how to compute the response, with test vectors |
| 5 | [Minimal client](Minimal-Client.md) | An annotated trace of a complete session, from `hello` to `connection-close` |
| 6 | [Features](Features.md) | Every optional feature, and where it is specified |

The [protocol specification](../Network/Protocol.md) defines the wire format of every
packet. The [subsystem pages](../Subsystems/README.md) define the contents of the
capability maps and option dictionaries, and the behaviour expected around the packets.

<div class="docs-section-heading" markdown="1">

## Implementation levels

</div>

A client does not need to implement everything: features that are not advertised in
its `hello` are not enabled by the server. A useful plan is to implement these levels
in order, testing each one against a real server (see [testing](#testing) below).

**Level 0 — connect**
* one transport, usually TCP or WebSocket ([transports](Transports.md))
* the record layer, `rencodeplus` and LZ4 ([protocol](../Network/Protocol.md) sections 3 and 4)
* `hello`, `connection-close`, `ping` / `ping-echo` ([handshake](Handshake.md))
* the `hmac` challenge, if the server requires a password ([authentication](Authentication.md))

At this level, a client can already use the one-shot requests: `info`, `version`,
`screenshot`, `command`, `run` ([protocol](../Network/Protocol.md#54-connection-profiles)).

**Level 1 — windows**
* `window-create`, `window-metadata`, `window-move-resize`, `window-resized`, `window-destroy`,
  `window-map`, `window-unmap`, `window-configure`, `window-close` ([window](../Subsystems/Window.md))
* `window-draw` with `rgb` (with LZ4) and `png`, and `window-ack` for every draw ([encoding](../Subsystems/Encoding.md))
* `keyboard-event` with X11 key names and modifiers ([keyboard](../Subsystems/Keyboard.md))
* `pointer-motion`, `pointer-button`, `pointer-wheel` ([pointer](../Subsystems/Pointer.md))
* `display-configure` when the client's screen changes ([display](../Subsystems/Display.md))

This is a usable client.

**Level 2 — integration**
* cursors, window icons, bell ([cursor](../Subsystems/Cursor.md), [window](../Subsystems/Window.md))
* the clipboard ([clipboard](../Subsystems/Clipboard.md))
* notifications ([notification](../Subsystems/Notification.md))
* more picture encodings: `jpeg`, `webp`, and the `scroll` encoding
* video: `h264`, `vp8`, `vp9`, `av1` ([encoding](../Subsystems/Encoding.md#video-streams))

**Level 3 — everything else**
* audio ([audio](../Subsystems/Audio.md)), file transfers and printing ([file](../Subsystems/File.md)),
  webcam ([webcam](../Subsystems/Webcam.md)), shared memory ([mmap](../Subsystems/MMAP.md)), see [features](Features.md)

<div class="docs-section-heading" markdown="1">

## Rules of thumb

</div>

* Advertise only what you implement. The server adapts to the client's capabilities,
  and an absent capability is the safe default.
* Ignore what you do not understand: unknown capability keys, metadata keys, draw
  options and trailing packet arguments MUST be ignored. Unknown packet types should be
  logged and dropped, or close the connection cleanly.
* Validate everything you receive before using it: sizes, indexes, window ids,
  dimensions. The [security considerations](../Network/Protocol.md#12-security-considerations)
  apply to clients as much as to servers.
* Answer every `ping` and acknowledge every `window-draw`, even the ones you could not
  decode. Servers rely on both.
* All the coordinates are in the server's pixel space. A client that scales its
  display converts them both ways.
* Use dotted capability names as paths into nested maps (`encoding.options` is the
  `options` key of the `encoding` map), and accept the flat form too when reading
  ([protocol](../Network/Protocol.md#2-terminology-and-data-model)).

<div class="docs-section-heading" markdown="1">

## Testing

</div>

Start a server without a real display, ie:

```shell
xpra start :100 --start=xterm --bind-tcp=127.0.0.1:10000 --daemon=no
```

With a password:

```shell
echo -n "secret" > password.txt
xpra start :100 --start=xterm "--bind-tcp=127.0.0.1:10000,auth=file(filename=password.txt)" --daemon=no
```

Useful tools when developing a client:
* `-d network,auth` on the server shows the packets exchanged and the authentication steps,
  and `XPRA_LOG_HELLO=1` prints the `hello` packets in full
* `xpra info tcp://127.0.0.1:10000/` shows the state of the server, as seen by the server,
  including the capabilities it has recorded for each connected client
* the reference client, `xpra attach tcp://127.0.0.1:10000/`, run with `-d network`,
  shows what a complete client sends
* `xpra version tcp://127.0.0.1:10000/` and `xpra id tcp://127.0.0.1:10000/` exercise the
  simplest one-shot requests, which need no authentication

See also [debugging](../Debugging.md) and [logging](../Usage/Logging.md).
