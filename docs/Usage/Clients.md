# Xpra Clients

Any application that speaks the [xpra network protocol](../Network/Protocol.md) can be used as an xpra client.\
The reference implementation is the [xpra client](./Client.md) shipped with the xpra server itself, but a number of
alternative clients exist, with varying degrees of completeness.

Servers negotiate their capabilities with each client during the `hello` handshake, so features that a client does not
implement are simply not enabled for that connection.

## Client implementations

| Client                                                         | Language / Toolkit             | Maintained by                                  | License  |
|----------------------------------------------------------------|--------------------------------|------------------------------------------------|----------|
| [xpra](./Client.md)                                            | Python + GTK3 (Cython codecs)  | [Xpra-org](https://github.com/Xpra-org/xpra)   | GPLv2    |
| [xpra-html5](https://github.com/Xpra-org/xpra-html5)           | JavaScript, runs in a browser  | [Xpra-org](https://github.com/Xpra-org)        | MPL-2.0  |
| [vispra](https://github.com/MajidNajafi/vispra)                | TypeScript + SolidJS, browser  | third party                                    | MIT      |
| [rust-xpra](https://github.com/Xpra-org/rust-xpra)             | Rust                           | [Xpra-org](https://github.com/Xpra-org)        | GPLv3    |
| [go-xpra](https://github.com/Xpra-org/go-xpra)                 | Go                             | [Xpra-org](https://github.com/Xpra-org)        | GPLv3    |

The [xpra client](./Client.md) is the default client: it is the only one that implements the complete feature set, and
the only one available as a native package for Linux, MS Windows and MacOS.\
The two browser based clients, `xpra-html5` and `vispra`, are served over `ws` / `wss` connections - the xpra server's
builtin web server will pick up `xpra-html5` automatically when it is installed.\
The `rust` and `go` clients are experimental implementations used mostly for validating the protocol.

## Feature comparison

Legend: ✅ broad support · ◐ partial or platform-limited · — absent

| Feature                  | xpra | html5 | vispra | rust | go |
|--------------------------|:----:|:-----:|:------:|:----:|:--:|
| Transports               | ✅    | ◐     | ◐      | ◐    | ◐  |
| Transport security       | ✅    | ✅     | ✅      | ◐    | ✅  |
| Authentication           | ✅    | ◐     | ◐      | ◐    | ◐  |
| Packet encoding          | ✅    | ✅     | ✅      | ◐    | ✅  |
| Packet compression       | ✅    | ◐     | ◐      | ◐    | ◐  |
| Packet types             | ✅    | ◐     | ◐      | ◐    | ◐  |
| Out-of-band chunks       | ✅    | ✅     | ✅      | ✅    | ✅  |
| Forwarded windows        | ✅    | ✅     | ✅      | ✅    | ✅  |
| Advanced window state    | ✅    | ◐     | ◐      | ◐    | ◐  |
| Override-redirect popups | ✅    | ✅     | ✅      | ◐    | ✅  |
| Picture encodings        | ✅    | ✅     | ✅      | ◐    | ✅  |
| Video encodings          | ✅    | ◐     | ◐      | ◐    | —  |
| Accelerated rendering    | ✅    | ◐     | ◐      | ◐    | ◐  |
| Speaker audio            | ✅    | ✅     | ◐      | ◐    | —  |
| Microphone               | ✅    | —     | —      | —    | —  |
| Clipboard                | ✅    | ◐     | ◐      | ◐    | —  |
| Keyboard                 | ✅    | ◐     | ◐      | ◐    | ◐  |
| Pointer / input          | ✅    | ◐     | ◐      | ◐    | ◐  |
| Server cursors           | ✅    | ◐     | ◐      | ◐    | ◐  |
| Window icons             | ✅    | ◐     | ◐      | ◐    | ◐  |
| Bell forwarding          | ✅    | ✅     | ◐      | ◐    | ◐  |
| Desktop notifications    | ✅    | ✅     | ✅      | ◐    | ◐  |
| Client tray / menu       | ✅    | ✅     | ◐      | ◐    | —  |
| Remote app system tray   | ✅    | ✅     | ◐      | —    | —  |
| File transfer / URLs     | ✅    | ✅     | ◐      | —    | —  |
| Printer forwarding       | ✅    | ✅     | ◐      | —    | —  |
| Webcam forwarding        | ✅    | —     | —      | —    | —  |
| Shared memory (mmap)     | ✅    | —     | —      | —    | —  |
| DPI / display sync       | ✅    | ◐     | ◐      | ◐    | ◐  |
| Remote logging / events  | ✅    | ✅     | ◐      | ◐    | ◐  |
| Bandwidth adaptation     | ✅    | ◐     | ◐      | —    | —  |

The sections below detail what each client actually implements.

### Native xpra client

The reference implementation and the only complete one: a production client packaged for Linux, MS Windows and MacOS.

| Feature                 | Notes                                                                                              |
|-------------------------|----------------------------------------------------------------------------------------------------|
| Transports              | TCP, SSL, SSH, WS/WSS, QUIC, Unix sockets, named pipes, vsock; VNC support                         |
| Transport security      | TLS verification / configuration, SSH, application-level AES                                       |
| Authentication          | Password, prompt, file, URI, SCRAM, Kerberos, GSS, U2F/FIDO2 and others                            |
| Packet encoding         | Rencodeplus and YAML                                                                               |
| Packet compression      | LZ4, Zstd, Brotli; bidirectional negotiation                                                       |
| Packet types            | Legacy and 6.5+ names, selected with `XPRA_BACKWARDS_COMPATIBLE`                                   |
| Advanced window state   | Shapes, workspaces, transient relationships, fullscreen, stacking, decorations, constraints, grabs |
| Picture encodings       | RGB, JPEG, PNG, WebP, AVIF and others depending on codecs                                          |
| Video encodings         | H.264, VP8/VP9, AV1, HEVC and others depending on decoder availability                             |
| Accelerated rendering   | OpenGL plus VAAPI, NVIDIA, Media Foundation, VideoToolbox and other optional paths                 |
| Speaker audio           | Multiple negotiated codecs through GStreamer                                                       |
| Clipboard               | Multiple selections / targets, direction controls and filtering                                    |
| Keyboard                | Full keymap upload / synchronization, layouts, shortcuts and lock-state handling                   |
| Pointer / input         | Pointer, buttons, wheel, focus, relative input, grabs and XI2 support                              |
| Server cursors          | Multiple cursor formats and scaling                                                                |
| Bell forwarding         | Native platform backend                                                                            |
| Desktop notifications   | Native notification backends on supported platforms                                                |
| Client tray / menu      | Extensive session controls                                                                         |
| Printer forwarding      | Optional platform dependencies                                                                     |
| Webcam forwarding       | Optional; client camera → Linux server                                                             |
| Shared memory (mmap)    | For local sessions                                                                                 |
| DPI / display sync      | DPI, scaling, monitor layout, workspaces and high bit depth                                        |
| Remote logging / events | Full diagnostics, session info and event handling                                                  |
| Bandwidth adaptation    | Detection, limits, codec adaptation and detailed latency metrics                                   |

### xpra-html5

Production client, widely deployed; runs in any modern browser.

| Feature                 | Notes                                                                                         |
|-------------------------|-----------------------------------------------------------------------------------------------|
| Transports              | WS/WSS, WebTransport (experimental)                                                           |
| Transport security      | HTTPS/WSS through the browser's TLS stack; application-level AES (CBC/CTR/CFB)                |
| Authentication          | HMAC-SHA256 password; refuses to send passwords over unencrypted remote links                 |
| Packet encoding         | Rencodeplus                                                                                   |
| Packet compression      | Inbound LZ4 and Brotli                                                                        |
| Packet types            | Legacy names, both directions                                                                 |
| Forwarded windows       | Create / destroy / draw / move / resize / raise                                               |
| Advanced window state   | Fullscreen, maximize/minimize, above/below, modal and opacity, confined to the browser canvas |
| Picture encodings       | RGB (lz4), JPEG, PNG, WebP, AVIF, `scroll` - subject to browser support                       |
| Video encodings         | H.264 and VP8 through `WebCodecs`, MPEG4 / VP8 through `MediaSource`                          |
| Accelerated rendering   | Browser-native decoding, offscreen canvas and decode workers; no GPU control                  |
| Speaker audio           | Opus, Vorbis, AAC, MP3, FLAC through `MediaSource`, with an `aurora` fallback                 |
| Clipboard               | Text and HTML, CLIPBOARD selection only, subject to browser permissions                       |
| Keyboard                | Layout selection and browser keycodes; no keymap upload                                       |
| Pointer / input         | Pointer, buttons, wheel, focus and pointer lock                                               |
| Server cursors          | PNG cursors                                                                                   |
| Window icons            | PNG icons                                                                                     |
| Bell forwarding         | Audio sample                                                                                  |
| Desktop notifications   | Browser notifications                                                                         |
| Client tray / menu      | Floating toolbar with session controls                                                        |
| File transfer / URLs    | Downloads and URL opening                                                                     |
| Printer forwarding      | Through the browser's print dialog                                                            |
| DPI / display sync      | DPI and screen size reported, resizes with the browser window                                 |
| Remote logging / events | Remote logging, session info and diagnostics                                                  |
| Bandwidth adaptation    | Bandwidth limit option, pings and latency metrics                                             |

### vispra

Early stage third party rewrite of the html5 client; runs in any modern browser.

| Feature                 | Notes                                                                   |
|-------------------------|-------------------------------------------------------------------------|
| Transports              | WS/WSS, WebTransport (experimental)                                     |
| Transport security      | HTTPS/WSS through the browser's TLS stack; application-level AES        |
| Authentication          | HMAC-SHA256 password                                                    |
| Packet encoding         | Rencodeplus                                                             |
| Packet compression      | Inbound LZ4 and Brotli                                                  |
| Packet types            | Legacy names, both directions                                           |
| Forwarded windows       | Create / destroy / draw / move / resize / raise                         |
| Advanced window state   | A subset of the html5 client's, also confined to the browser canvas     |
| Picture encodings       | RGB (lz4), JPEG, PNG, WebP, AVIF, `scroll` - subject to browser support |
| Video encodings         | H.264 and VP8 through `WebCodecs`                                       |
| Accelerated rendering   | Browser-native decoding, offscreen canvas and decode workers            |
| Speaker audio           | `MediaSource` and `aurora` codecs                                       |
| Clipboard               | Plain text, subject to browser permissions                              |
| Keyboard                | Layout selection and browser keycodes; no keymap upload                 |
| Pointer / input         | Pointer, buttons, wheel and focus                                       |
| Server cursors          | PNG cursors                                                             |
| Window icons            | PNG icons                                                               |
| Bell forwarding         | Tone generated with the Web Audio API                                   |
| Desktop notifications   | Browser notifications                                                   |
| Client tray / menu      | Taskbar and session info panel                                          |
| Remote app system tray  | Tray windows are received and rendered                                  |
| File transfer / URLs    | Basic file reception                                                    |
| Printer forwarding      | Present but disabled by default                                         |
| DPI / display sync      | DPI and screen size reported, resizes with the browser window           |
| Remote logging / events | Remote logging, session info and pings                                  |
| Bandwidth adaptation    | Bandwidth limit option and pings                                        |

### Rust client

Proof of concept - the README says it is not yet usable. Runs on MS Windows and on Linux, X11 or Wayland.

| Feature                  | Notes                                                                                        |
|--------------------------|----------------------------------------------------------------------------------------------|
| Transports               | TCP, SSL, WS/WSS, SSH subprocess                                                             |
| Transport security       | TLS supported, but certificate verification is currently disabled; SSH supported             |
| Authentication           | HMAC-SHA256 password via connection dialog, environment, pinentry or built-in dialog         |
| Packet encoding          | YAML                                                                                         |
| Packet compression       | Inbound LZ4 only                                                                             |
| Packet types             | Sends 6.5+ names, receives legacy: needs a 6.6+ server left in its backwards-compatible mode |
| Out-of-band chunks       | Received from the server                                                                     |
| Forwarded windows        | Create / destroy / draw / move / resize / raise                                              |
| Advanced window state    | Fullscreen, maximize/minimize, decorations, above/below, constraints and interactive moves   |
| Override-redirect popups | X11; degraded on native Wayland                                                              |
| Picture encodings        | JPEG, PNG, WebP; no raw RGB                                                                  |
| Video encodings          | H.264 on Windows through Media Foundation                                                    |
| Accelerated rendering    | Media Foundation H.264 on Windows; CPU softbuffer otherwise                                  |
| Speaker audio            | Bare Opus on Windows only, with jitter buffering and AV sync                                 |
| Clipboard                | Bidirectional plain text, CLIPBOARD selection only; X11/XWayland or Windows                  |
| Keyboard                 | Direct key events; no keymap upload, NumLock limitation on Wayland                           |
| Pointer / input          | Pointer, buttons, wheel, focus and server-requested grabs                                    |
| Server cursors           | PNG cursors                                                                                  |
| Window icons             | PNG icons                                                                                    |
| Bell forwarding          | Windows tone; terminal BEL on Linux                                                          |
| Desktop notifications    | Windows tray balloons; logged on Linux                                                       |
| Client tray / menu       | Windows only, with an Exit command                                                           |
| DPI / display sync       | Windows DPI-aware manifest; no server DPI / monitor synchronization                          |
| Remote logging / events  | Remote logging, lifecycle events and pings                                                   |
| Bandwidth adaptation     | Pings only                                                                                   |

### Go client

Minimal client, usable on three window systems: Linux X11, Linux Wayland and MS Windows.

| Feature                  | Notes                                                                                                                                                                |
|--------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Transports               | TCP, SSL, WS/WSS, SSH subprocess                                                                                                                                     |
| Transport security       | TLS certificate and hostname verification against the system trust store for `ssl`/`wss`, private CA option; SSH through the system client; no application-level AES |
| Authentication           | HMAC-SHA256 password via URL, connection dialog, `XPRA_PASSWORD`, pinentry or the Windows credentials dialog; SSH logins left to OpenSSH                             |
| Packet encoding          | Rencodeplus                                                                                                                                                          |
| Packet compression       | Inbound LZ4 only                                                                                                                                                     |
| Packet types             | Sends 6.5+ names; receives legacy unless `XPRA_BACKWARDS_COMPATIBLE=0`                                                                                               |
| Out-of-band chunks       | Received and spliced back in by index                                                                                                                                |
| Forwarded windows        | Create / destroy / draw / move / resize / raise / minimize                                                                                                           |
| Advanced window state    | Title, size constraints, raise and minimize/restore; no positioning or stacking on Wayland                                                                           |
| Override-redirect popups | X11, Windows, and Wayland `xdg_popup`                                                                                                                                |
| Picture encodings        | RGB24/RGB32, JPEG, PNG (including palette and grayscale), WebP                                                                                                       |
| Accelerated rendering    | X11 pixmap backing store, GDI blits on Windows, `wl_shm` buffers on Wayland; no video acceleration                                                                   |
| Keyboard                 | X11 keysym names, the compositor's own keymap on Wayland, printable ASCII only on Windows; no keymap upload                                                          |
| Pointer / input          | Pointer, buttons, wheel and focus                                                                                                                                    |
| Server cursors           | PNG cursors on all three backends                                                                                                                                    |
| Window icons             | PNG icons; on Wayland only with `xdg-toplevel-icon-v1`                                                                                                               |
| Bell forwarding          | Native X11 and Win32 sound; none on Wayland                                                                                                                          |
| Desktop notifications    | Logged only                                                                                                                                                          |
| DPI / display sync       | Windows per-monitor DPI awareness; nothing reported to the server                                                                                                    |
| Remote logging / events  | Server lifecycle events and pings; no client-side remote logging                                                                                                     |
| Bandwidth adaptation     | Pings only                                                                                                                                                           |

## See also

* [Xpra client](./Client.md) - the default client: launcher, session files, URL mapping and command line
* [Client OpenGL](./Client-OpenGL.md) - accelerated window rendering in the default client
* [xpra-html5 configuration](https://github.com/Xpra-org/xpra-html5/blob/master/docs/Configuration.md) - options and URL parameters for the html5 client
* [Network protocol](../Network/Protocol.md) - what a client implementation has to support
* [Subsystems](../Subsystems/README.md) - the feature modules found on both ends of the connection

## Defunct clients

These clients are no longer maintained and will not work with the
[currently supported versions](https://github.com/Xpra-org/xpra/wiki/Versions) of the xpra server.\
They are listed here for reference only:

| Client                                                                             | Platform      | Last activity | Notes                                                                                   |
|------------------------------------------------------------------------------------|---------------|---------------|-----------------------------------------------------------------------------------------|
| [Android client](https://xpra.org/vault/Android/)                                  | Android       | 2015          | The original Java client, also shipped as part of `winswitch` - archived APKs from 2012 to 2015 |
| [Xpra-client-android](https://github.com/sylvain121/Xpra-client-android)           | Android, Java | 2016          | Fork of `xpra-client` adding `h264` decoding (GPLv3)                                    |
| [xpra-client](https://github.com/jksiezni/xpra-client)                             | Android, Java | 2021          | Java client with Android and Swing frontends (GPLv3)                                    |
| [xpra-html5-client](https://github.com/andersevenrud/xpra-html5-client)            | Browser       | 2024          | TypeScript / React rewrite of the html5 client, designed to be embeddable (MPL-2.0)     |
