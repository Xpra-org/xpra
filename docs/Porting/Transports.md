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

A server with a certificate can also upgrade a plain TCP connection: see `ssl-upgrade`
in the [protocol](../Network/Protocol.md#53-authentication-and-upgrade-packets).

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
  (opcode `2`), masked as required for client frames. The frame boundaries carry no
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

URL scheme `quic://`, default port `14500` over UDP. QUIC connections use HTTP/3
and are configured like TLS connections, see [QUIC](../Network/QUIC.md). The way the
record stream and the datagrams are mapped onto HTTP/3 is not specified yet: new
implementations should start with TCP, TLS or WebSocket.

<div class="docs-section-heading" markdown="1">

## Proxies

</div>

A [proxy server](../Usage/Proxy-Server.md) accepts connections on behalf of the sessions
it manages. To the client, it looks exactly like a server: it authenticates the client,
then forwards the record stream to the selected session, and the session's own `hello`
reaches the client. Clients choose the session by putting its display or name in the URL
path, or by sending the session options as capabilities, see
[authentication](../Usage/Authentication.md#session-lookup-and-the-proxy-server).
