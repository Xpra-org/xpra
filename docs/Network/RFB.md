# RFB / VNC

`RFB` ("Remote FrameBuffer") is the protocol used by [VNC](https://en.wikipedia.org/wiki/RFB_protocol).
Xpra speaks it in both directions:

* as a **server**, it can accept connections from standard VNC clients (the `bind-rfb` option)
* as a **client**, it can connect to any standard VNC / RFB server (`vnc://` URLs) and display it
  like a regular xpra session

This page covers both. See also: [network](README.md), [SSL](SSL.md), [authentication](../Usage/Authentication.md),
[desktop](../Usage/Desktop.md) and [shadow](../Usage/Shadow.md) servers.

***

## What this adds to xpra

RFB is a single-framebuffer protocol: a session is one screen of pixels, with pointer and keyboard
input, an optional text clipboard and a server-rendered cursor. It has no concept of individual
application windows.

That model maps cleanly onto xpra's whole-desktop session types but not onto its
[seamless](../Usage/Seamless.md) mode (which forwards individual windows). So:

| Direction | Mode | Supported with |
|-----------|------|----------------|
| Xpra **server** ← VNC client | exposes one framebuffer | [desktop](../Usage/Desktop.md) and [shadow](../Usage/Shadow.md) servers **only** — **not** [seamless](../Usage/Seamless.md) |
| Xpra **client** → VNC server | renders one framebuffer as a single window | any RFB / VNC server |

When xpra acts as a VNC client, the remote desktop is presented as a single fixed-size window. The
client negotiates the RFB protocol version (3.3 / 3.7 / 3.8), authenticates, and decodes the screen
updates. It also forwards pointer and keyboard input, follows server-side desktop resizes, renders
the remote cursor locally, and synchronizes the text clipboard in both directions.

***

## Using xpra as a VNC server

Any [desktop](../Usage/Desktop.md) or [shadow](../Usage/Shadow.md) server can listen for VNC clients
by adding a `bind-rfb` socket:

```shell
xpra shadow --bind-rfb=0.0.0.0:5900
```
```shell
xpra desktop --start=xterm --bind-rfb=0.0.0.0:5900
```

Then connect with any VNC viewer (including xpra's own client, see below):
```shell
vncviewer localhost:5900
```

Secure it with the `rfb-auth` option (see [authentication](../Usage/Authentication.md)):
```shell
xpra shadow --bind-rfb=0.0.0.0:5900,auth=file,filename=password.txt
```

A plain `TCP` socket can also be upgraded to RFB automatically after a short delay, so a single port
can serve both xpra and VNC clients - this is the `rfb-upgrade` option (in seconds, `0` to disable):
```shell
xpra desktop --start=xterm --bind-tcp=0.0.0.0:10000 --rfb-upgrade=5
```

***

## Connecting to a real VNC server

Use a `vnc://` URL (the `rfb://` scheme is an alias). The default port is `5900`:

<details>
  <summary>Basic connection</summary>

```shell
xpra attach vnc://localhost:5900/
```
The remote desktop appears as a single xpra window. The standard xpra client options apply
(window scaling, the system tray menu, etc).
</details>

<details>
  <summary>With a VNC password</summary>

VNC password authentication (the classic DES challenge) is supported. The client will prompt for the
password, or you can supply it non-interactively with a password file:
```shell
xpra attach vnc://localhost:5900/ --password-file=password.txt
```
</details>

<details>
  <summary>Over an encrypted connection (VeNCrypt / TLS)</summary>

If the VNC server offers `VeNCrypt` with an X509 certificate (for example TigerVNC's `Xvnc` started
with `-SecurityTypes X509None -X509Cert cert.pem -X509Key key.pem`), xpra will negotiate VeNCrypt and
upgrade the connection to TLS before authenticating - reusing the same [SSL](SSL.md) machinery as the
rest of xpra. The usual `--ssl-*` options control certificate verification.

For a self-signed certificate you can either verify against its CA file:
```shell
xpra attach vnc://host:5900/ --ssl-ca-certs=/path/to/cert.pem
```
or, *for testing only*, skip verification:
```shell
xpra attach vnc://host:5900/ --ssl-server-verify-mode=none
```
</details>

<details>
  <summary>Tunnelled over SSH</summary>

`vnc+ssh://` connects to the VNC server through an SSH tunnel. When a display number is given in the
path it is mapped to the matching VNC port (`5900 + display`):
```shell
xpra attach vnc+ssh://user@host/2
```
This logs in over SSH and connects to `vnc://localhost:5902/` on the remote host.
</details>

***

## Capabilities and limitations (VNC client)

The VNC client is intended to be lightweight and interoperable, not a full-featured VNC viewer.

Supported:
* protocol versions 3.3, 3.7 and 3.8
* authentication: `None`, `VNC` (password), and `VeNCrypt` over TLS with an X509 server certificate
* encodings: `RAW` and `Tight` (including JPEG)
* pseudo-encodings: `Cursor` (the remote cursor is rendered locally) and desktop resize
  (`DesktopSize` / `ExtendedDesktopSize`)
* pointer and keyboard input
* a bidirectional plain-text clipboard

Not (yet) supported:
* other encodings such as `ZRLE`, `Hextile`, `ZLIB` or `CopyRect`
* the anonymous-DH variant of `VeNCrypt` (only the X509 certificate variants), and `SASL` / `Tight` /
  `RealVNC` / `Ultra` authentication
* non-text clipboard contents and file transfers
