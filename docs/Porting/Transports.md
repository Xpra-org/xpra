# Transports

The [protocol](../Network/Protocol.md) starts once a transport has delivered an
ordered, reliable byte stream between the client and the server. This page
describes how to obtain that stream. For configuring the server side, see
[network](../Network/README.md).

In every case **the client speaks first**: no bytes precede the client's first
record, and the first record is the client's `hello`. A server never sends anything
before it has received that `hello`, except for the transport's own handshake.

<div class="docs-section-heading" markdown="1">

## TCP

</div>

The default port is `14500`. The record stream is sent as-is over the socket.

A single TCP port can serve several protocols: the server peeks at the first bytes
the client sends (up to one second, 8 KiB) and recognizes:

| First bytes | Protocol |
|---|---|
| a valid xpra header (`P`, chunk index 0, payload size from 8 bytes to 256 MiB) | xpra |
| `0x16` | TLS, then the server peeks again inside the TLS stream |
| `SSH-` | SSH, see below |
| `GET`, `POST`, or an `HTTP/` request line | HTTP: WebSocket upgrade, or the built-in web server |
| `RFB ` | VNC |
| `0x03 0x00` | RDP |

A client that sends nothing is treated as a VNC client after `rfb-upgrade` seconds
(`5` by default). Each of these upgrades can be disabled on the server, so a client
should use the transport the user asked for rather than rely on them.

<div class="docs-section-heading" markdown="1">

## TLS

</div>

URL schemes `ssl://` and `wss://`. Default port `443`. A plain TLS client handshake,
then the record stream inside it. Server certificates are verified as usual for TLS:
see [TLS](../Network/SSL.md) for the options and the use of private CAs.

A server with a certificate can also offer a TLS upgrade on a plain TCP connection
before authentication, if the client sets the top-level `ssl-upgrade` boolean to
true in its initial `hello`. An absent or false capability disables this exchange.
The client acknowledges the offer, completes a TLS handshake on the same socket,
then sends its `hello` again. See the
[protocol](../Network/Protocol.md#53-authentication-and-upgrade-packets) for the
exchange and the [TLS guide](../Network/SSL.md#negotiated-tls-upgrades) for the
Python client's opt-in and certificate verification defaults.

<div class="docs-section-heading" markdown="1">

## WebSocket

</div>

URL schemes `ws://` and `wss://` (WebSocket over TLS). Default ports `80` and `443`,
but xpra servers usually serve WebSockets on their TCP port.

* The client sends a standard RFC 6455 upgrade request: `GET /` (the server ignores
  the path), `Upgrade: websocket`, `Connection: Upgrade`, `Sec-WebSocket-Version: 13`,
  a random `Sec-WebSocket-Key`.
* The request MUST include `Sec-WebSocket-Protocol: binary`. The server rejects the
  upgrade otherwise, and its `101 Switching Protocols` response selects `binary`.
* After the upgrade, the record stream is carried in the payload of binary frames
  (opcode `2`). RFC 6455 requires clients to mask their frames: xpra servers accept
  both masked and unmasked frames, and the reference client does not mask
  (`XPRA_WEBSOCKET_MASK`). Browser based clients always mask. The frame boundaries carry no
  meaning: a frame can contain part of a record, or several records, and receivers MUST
  reassemble the byte stream. Servers also accept text frames, and treat them the same way.
* Ping, pong and close frames follow RFC 6455.

The same port usually serves the [HTML5 client](https://github.com/Xpra-org/xpra-html5)
over plain HTTP, and the `ws` connection is then made to that same address.

<div class="docs-section-heading" markdown="1">

## SSH

</div>

URL scheme `ssh://[user@]host[:port]/[display]`. The client opens an SSH session with its
usual SSH implementation and authentication, and runs the xpra proxy command on the
remote host as the session's command:

```shell
xpra _proxy :DISPLAY
```

`:DISPLAY` is omitted when the user did not specify a display: the server side then
picks the only session available, or fails. The record stream is then exchanged over
the SSH channel's stdin and stdout. Since `xpra` may not be on the remote `PATH`, the
reference client runs a small shell fragment that tries several locations:

```shell
sh -c 'if command -v "xpra" > /dev/null 2>&1; then xpra _proxy :10;
elif [ -x $XDG_RUNTIME_DIR/xpra/run-xpra ]; then $XDG_RUNTIME_DIR/xpra/run-xpra _proxy :10;
else echo "no xpra command found"; exit 1; fi'
```

Servers can also accept SSH connections on their own TCP port, without a system SSH
server: the client then connects to that port with SSH and runs the same command.

<div class="docs-section-heading" markdown="1">

## Local sockets

</div>

On POSIX, servers listen on Unix domain sockets in the user's socket directories,
usually `$XDG_RUNTIME_DIR/xpra/` and `~/.xpra/`. The socket of display `:10` is
`socket` in the session directory, ie: `$XDG_RUNTIME_DIR/xpra/10/socket`, and older
servers also create one directly in the socket directory, named after the hostname
and the display: `HOSTNAME-10`. On MS Windows, the equivalent is
a named pipe. The record stream is sent as-is.

Local connections can also use [shared memory](../Subsystems/MMAP.md) to transfer pixels.

<div class="docs-section-heading" markdown="1">

## QUIC

</div>

QUIC connections use HTTP/3 over UDP, default port `14500`. TLS is part of QUIC: the
server needs a certificate, configured like [TLS](../Network/SSL.md), and clients verify
it as usual. The ALPN protocol is `h3`. See [QUIC](../Network/QUIC.md) for the server
configuration.

Xpra uses one of two HTTP/3 mappings, both of which start with an extended `CONNECT`
request (RFC 9220) on a new bidirectional stream. The URL path is passed as `:path`,
and `:authority` is the server's host name.

### WebSocket over HTTP/3 (`quic://`)

This is what `quic://host:port/` uses. The client sends these request headers:

| Header | Value |
|---|---|
| `:method` | `CONNECT` |
| `:protocol` | `websocket` |
| `:scheme` | `https` |
| `:authority`, `:path` | the server host, the URL path (`/` by default) |
| `sec-websocket-version` | `13` |
| `sec-websocket-protocol` | `xpra` |

Note that the WebSocket sub-protocol is `xpra` here, not `binary` as for WebSockets
over TCP: the server rejects the request otherwise. The server may also check the
`origin` header against its `http-origin` option, and answers `403` when it does not match.

The server accepts with `:status 200` and `sec-websocket-protocol: xpra`. From then on,
the DATA frames of that HTTP/3 stream carry a WebSocket byte stream, exactly as over TCP
(see [WebSocket](#websocket) above): binary WebSocket frames containing the xpra record
stream, with arbitrary boundaries. Closing uses a WebSocket close frame, then the end
of the HTTP/3 stream.

**Datagrams.** On these connections, some packets can also be sent as unreliable QUIC
datagrams, which are never retransmitted:

* both sides list the packet types they accept as datagrams in their `hello`, in
  `datagram-packet-types` (a list of strings, ie: `["audio-data", "window-draw-fragment"]`),
  and only send a packet type as a datagram if the peer accepts it. Datagrams are only
  accepted once the peer's `hello` has been processed;
* each datagram is an HTTP/3 datagram (RFC 9297) associated with the WebSocket's
  `CONNECT` stream: its payload starts with the quarter stream id of that stream,
  followed by exactly **one complete WebSocket binary frame** (`FIN` set), whose payload
  is exactly **one complete xpra record**: the 8-byte header and the main packet,
  optionally compressed, without raw chunks;
* a packet that does not fit in a datagram is sent on the stream instead. The usable
  size is the QUIC datagram frame size negotiated by the peers minus the packet overhead
  (about 1100 bytes with the default 1200-byte QUIC packets);
* invalid datagrams, or datagrams of a packet type that was not accepted, are dropped
  without closing the connection;
* the order of datagrams relative to each other and to the stream is not preserved:
  only packet types designed to tolerate loss and re-ordering can be sent this way,
  currently `audio-data` and `window-draw-fragment`. The start and end of audio streams
  are always sent on the stream (`audio-stream` packets).

**Substreams.** Servers can be configured (`XPRA_QUIC_SUBSTREAM_PACKET_TYPES`,
disabled by default) to move some packet types to separate HTTP/3 streams, so that
a large packet on one does not delay the others. The server announces each new
stream with an HTTP/3 `PUSH_PROMISE`, then sends response headers on it containing
`substream` (the id of the main stream) and `stream-type` (ie: `audio`). Its data
is a WebSocket byte stream like the main one. Clients that do not implement push
should keep push disabled: the server then uses the main stream only.

### WebTransport (`wt://`)

`wt://host:port/path` uses WebTransport (draft 02) instead:

| Header | Value |
|---|---|
| `:method` | `CONNECT` |
| `:protocol` | `webtransport` |
| `:scheme` | `https` |
| `:authority`, `:path` | the server host, the URL path |

The client MUST enable the HTTP/3 WebTransport settings, and the `CONNECT` request
MUST be the first request of the connection (stream `0`). The server accepts with
`:status 200` and `sec-webtransport-http3-draft: draft02`. The xpra record stream is
then carried **without any WebSocket framing**. The reference implementations send it
as HTTP/3 DATA frames on the `CONNECT` stream itself; the server also accepts it on a
WebTransport bidirectional stream opened by the client, and then replies on the stream
it last received data on. A client MUST NOT send anything before the server's `200`. WebTransport datagrams are not used: `datagram-packet-types` is not
advertised on these connections.

<div class="docs-section-heading" markdown="1">

## Proxies

</div>

A [proxy server](../Usage/Proxy-Server.md) accepts connections on behalf of the sessions
it manages. To the client, it looks exactly like a server: it authenticates the client,
then forwards the record stream to the selected session, and the session's own `hello`
reaches the client. Clients choose the session by putting its display or name in the URL
path, or by sending the session options as capabilities, see
[authentication](../Usage/Authentication.md#session-lookup-and-the-proxy-server).
