# Xpra Clients

Any application that speaks the [xpra network protocol](../Network/Protocol.md) can be used as an xpra client,
see the [porting guide](../Porting/README.md) to write one.\
The reference implementation is the [xpra client](./Client.md) shipped with the xpra server itself, but a number of
alternative clients exist, with varying degrees of completeness.

Servers negotiate their capabilities with each client during the `hello` handshake, so features that a client does not
implement are simply not enabled for that connection.

<div class="docs-section-heading" markdown="1">

## Client implementations

</div>

| Client                                                     | Maintained by                                   | License |
|------------------------------------------------------------|-------------------------------------------------|---------|
| [xpra](./Client.md)                                        | [Xpra-org](https://github.com/Xpra-org/xpra)    | GPLv2   |
| [xpra-html5](https://github.com/Xpra-org/xpra-html5)       | [Xpra-org](https://github.com/Xpra-org)         | MPL-2.0 |
| [vispra](https://github.com/MajidNajafi/vispra)            | third party                                     | MIT     |
| [rust-xpra](https://github.com/Xpra-org/rust-xpra)         | [Xpra-org](https://github.com/Xpra-org)         | GPLv3   |
| [go-xpra](https://github.com/Xpra-org/go-xpra)             | [Xpra-org](https://github.com/Xpra-org)         | GPLv3   |
| [c-xpra](https://github.com/Xpra-org/c-xpra)               | [Xpra-org](https://github.com/Xpra-org)         | MIT     |
| [kotlin-xpra](https://github.com/Xpra-org/kotlin-xpra)     | [Xpra-org](https://github.com/Xpra-org)         | GPLv3   |
| [xpra-client](https://github.com/lukaszsobala/xpra-client) | [lukaszsobala](https://github.com/lukaszsobala) | GPLv3   |

The [xpra client](./Client.md) is the default client: it is the only one that implements the complete feature set, and
the only one available as a native package for Linux, MS Windows and MacOS.\
The two browser based clients, `xpra-html5` and `vispra`, are served over `ws` / `wss` connections - the xpra server's
builtin web server will pick up `xpra-html5` automatically when it is installed.\
The `rust` and `go` clients are smaller native implementations with a deliberately limited feature set, also used
for validating the protocol.\
`c-xpra` is smaller still: a C client that only needs libc, libX11 and libXfixes (libpng, libwebp, libturbojpeg and
libXcursor are used when installed), written clean-room from the protocol documentation alone, to show that the documentation is enough to write a client.\
`kotlin-xpra` is an Android client in Kotlin and Jetpack Compose: it shows one top-level window at a time, fullscreen,
with touch input, a soft-keyboard bridge and a window switcher.\
`xpra-client` is a Java / Kotlin Android client, with a Swing frontend also in the repository. It is a fork of
`jksiezni/xpra-client`, updated for current Android versions and Xpra servers.

<div class="docs-section-heading" markdown="1">

## Project size and build

</div>

These are not the same kind of project, and what it costs to build and ship them differs by two orders of magnitude:

| Client      | Languages                        | Source               | Binaries                                                 | Build time                               | Time to first window |
|-------------|----------------------------------|----------------------|----------------------------------------------------------|------------------------------------------|----------------------|
| xpra        | Python 3, Cython, C, CUDA - GTK3 | 1888 files, 407 kloc | 4-9 MB packages, 112 MB `.exe`, 71-92 MB `.dmg` / `.pkg` | 4 minutes, over 10 on MS Windows / MacOS | 1 second             |
| xpra-html5  | JavaScript, no framework         | 33 files, 19 kloc    | 1.4-2.1 MB package, 2.3 MB served to the browser         | 20 seconds                               | 0.4 seconds          |
| vispra      | TypeScript, SolidJS, Vite        | 117 files, 24 kloc   | 2.8 MB served to the browser, no packages                | 10 seconds                               | -                    |
| rust-xpra   | Rust, `winit` / `softbuffer`     | 38 files, 13 kloc    | 2.4-2.8 MB package, 2.8 MB executable, 2.5 MB `.exe`     | 75 seconds                               | 60 ms                |
| go-xpra     | Go, no `cgo`, no toolkit         | 121 files, 21 kloc   | 4.0-4.3 MB package, 8.1 MB executable, 11 MB `.exe`      | 10 seconds                               | 60 ms                |
| c-xpra      | C99, Xlib                        | 24 files, 4.4 kloc   | 25-40 KB package, 44 KB executable, 23 KB with UPX       | 1 second                                 | 15 ms                |
| kotlin-xpra | Kotlin, Jetpack Compose          | 34 files, 4.5 kloc   | 1.5 MB `.apk`                                            | 100 seconds                              | -                    |
| xpra-client | Java, Kotlin, Android / Swing    | 141 files, 16.6 kloc | 2.2 MB `.apk`, 8.3 MB debug `.apk`                       | 100 seconds, 50 for a debug build        | -                    |

Source counts tracked files in each project's own languages, tests included and vendored libraries excluded - the
`xpra-html5` figure leaves out some 70 kloc of bundled jquery and audio decoders, whereas `vispra` gets the equivalent
from `npm` and never commits it. Of xpra's 407 kloc, 341 are Python, 53 Cython and 13 C and CUDA.
`c-xpra` builds its own LZ4 decoder, rencodeplus codec and SHA-256 rather than linking libraries for them, and only
ships for Linux.\
The `xpra-client` count includes the Swing frontend and excludes the bundled Grafika library.\
The package sizes are what the xpra repositories serve, and they only look small because a distribution package leans
on the distribution's own Python, GTK and codec libraries; the MS Windows installer and the MacOS `.dmg` / `.pkg` carry
all of that themselves, which is the whole difference between 4 MB and 112 MB.\
The `go-xpra` `.exe` the repositories serve is not stripped, unlike its Linux packages and the executable measured here.\
Build times are wall clock, from cold, on one 8 thread x86_64 desktop, with the dependencies already installed. Only
xpra's is long enough to matter, and it is much longer on the two platforms that also build the toolchain, the
bundled libraries and an installer.
The time to first window is how long it takes from executing the client until the server's `xterm` window is mapped on
the client's display, measured on the same machine against a local xpra 8.0 server over `tcp`, as the median of 8 to
10 runs. The browser clients start from a browser that is already running, in a new browsing context with an empty cache.
The xpra client was measured with OpenGL disabled: probing it adds to the startup time.
`vispra` cannot connect to an xpra 8.0 server: it does not send the packet `encoders` list that xpra servers require
since they dropped compatibility with versions older than 7.0.
The two Android clients were not measured.

Build `xpra-client` with `./gradlew assembleDebug`, using JDK 17 or later and the Android SDK.
APKs are available as [CI artifacts](https://github.com/lukaszsobala/xpra-client/actions/workflows/main.yml).
Its first size and build time in the table are for the release APK, shrunk by R8 like `kotlin-xpra`'s.

<div class="docs-section-heading" markdown="1">

## Feature comparison

</div>

This comparison should be correct as of **2026-11-10 17:07 +0700**, the last time it was checked
against each client's repository.

Legend: 🟢 supported · 🟠 partial, platform-limited or degraded · 🔴 absent

Rows that name their options carry one marker per option, in that order: `ws` also covers `wss`, and `quic` also
covers the browsers' `WebTransport`.

| Feature                                    | xpra  | html5 | vispra | rust  | go    | c     |
|--------------------------------------------|:-----:|:-----:|:------:|:-----:|:-----:|:-----:|
| Transports (tcp/ssl/ssh/ws/quic)           | 🟢🟢🟢🟢🟢 | 🔴🔴🔴🟢🟠 | 🔴🔴🔴🟢🟠  | 🟢🟢🟢🟢🔴 | 🟢🟢🟢🟢🔴 | 🟢🔴🔴🔴🔴 |
| Transport security (tls/ssh/aes)           | 🟢🟢🟢   | 🟢🔴🟢   | 🟢🔴🟢    | 🟢🟢🔴   | 🟢🟢🔴   | 🔴🔴🔴   |
| Authentication                             | 🟢     | 🟠     | 🟠      | 🟠     | 🟠     | 🟠     |
| Packet encoding (rencodeplus/yaml)         | 🟢🟢    | 🟢🔴    | 🟢🔴     | 🔴🟢    | 🟢🔴    | 🟢🔴    |
| Compression in (lz4/zstd/brotli)           | 🟢🟢🟢   | 🟢🔴🟢   | 🟢🔴🟢    | 🟢🔴🔴   | 🟢🔴🔴   | 🟢🔴🔴   |
| Compression out (lz4/zstd/brotli)          | 🟢🟢🟢   | 🔴🔴🔴   | 🔴🔴🔴    | 🔴🔴🔴   | 🔴🔴🔴   | 🔴🔴🔴   |
| Out-of-band chunks                         | 🟢     | 🟢     | 🟢      | 🟢     | 🟢     | 🟢     |
| Forwarded windows                          | 🟢     | 🟢     | 🟢      | 🟢     | 🟢     | 🟢     |
| Advanced window state                      | 🟢     | 🟠     | 🟠      | 🟠     | 🟠     | 🟠     |
| Override-redirect popups                   | 🟢     | 🟢     | 🟢      | 🟠     | 🟢     | 🟢     |
| Picture encodings (rgb/jpeg/png/webp/avif) | 🟢🟢🟢🟢🟢 | 🟢🟢🟢🟢🟠 | 🟢🟢🟢🟢🟠  | 🔴🟢🟢🟢🔴 | 🟢🟢🟢🟢🔴 | 🟢🟢🟢🟢🔴 |
| Video encodings (h264/vp8/vp9/av1)         | 🟢🟢🟢🟢  | 🟢🟢🔴🔴  | 🟢🟢🔴🔴   | 🟠🔴🔴🔴  | 🔴🔴🔴🔴  | 🔴🔴🔴🔴  |
| Accelerated rendering                      | 🟢     | 🟠     | 🟠      | 🟠     | 🟠     | 🟠     |
| Speaker audio (opus/vorbis/mp3/flac/aac)   | 🟢🟢🟢🟢🟢 | 🟢🟢🟢🟢🟢 | 🟢🟢🟢🟢🟢  | 🟠🔴🔴🔴🔴 | 🔴🔴🔴🔴🔴 | 🔴🔴🔴🔴🔴 |
| Microphone                                 | 🟢     | 🔴     | 🔴      | 🔴     | 🔴     | 🔴     |
| Clipboard                                  | 🟢     | 🟠     | 🟠      | 🟠     | 🟠     | 🟠     |
| Keyboard                                   | 🟢     | 🟠     | 🟠      | 🟠     | 🟠     | 🟠     |
| Pointer / input                            | 🟢     | 🟠     | 🟠      | 🟠     | 🟠     | 🟠     |
| Server cursors                             | 🟢     | 🟠     | 🟠      | 🟠     | 🟠     | 🟠     |
| Window icons                               | 🟢     | 🟢     | 🔴      | 🟠     | 🟢     | 🟢     |
| Bell forwarding                            | 🟢     | 🟢     | 🟠      | 🟠     | 🟠     | 🟢     |
| Desktop notifications                      | 🟢     | 🟢     | 🟢      | 🟠     | 🟠     | 🟠     |
| Client tray / menu                         | 🟢     | 🟢     | 🟠      | 🟠     | 🟠     | 🔴     |
| Remote app system tray                     | 🟢     | 🟢     | 🟠      | 🔴     | 🔴     | 🔴     |
| File transfer / URLs                       | 🟢     | 🟢     | 🟠      | 🔴     | 🔴     | 🔴     |
| Printer forwarding                         | 🟢     | 🟢     | 🟠      | 🔴     | 🔴     | 🔴     |
| Webcam forwarding                          | 🟢     | 🔴     | 🔴      | 🔴     | 🔴     | 🔴     |
| Shared memory                              | 🟢     | 🔴     | 🔴      | 🟠     | 🟠     | 🔴     |
| DPI / display sync                         | 🟢     | 🟠     | 🟠      | 🟠     | 🟠     | 🟠     |
| Remote logging / events                    | 🟢     | 🟢     | 🟠      | 🟠     | 🟠     | 🟠     |
| Bandwidth adaptation                       | 🟢     | 🟠     | 🟠      | 🔴     | 🔴     | 🔴     |

The sections below detail what each client actually implements.

### Native xpra client

The reference implementation and the only complete one: a production client packaged for Linux, MS Windows and MacOS.

| Feature                 | Notes                                                                                              |
|-------------------------|----------------------------------------------------------------------------------------------------|
| Transports              | Also Unix sockets, named pipes and vsock; VNC support                                              |
| Authentication          | Password, prompt, file, URI, SCRAM, Kerberos, GSS, U2F/FIDO2 and others                            |
| Advanced window state   | Shapes, workspaces, transient relationships, fullscreen, stacking, decorations, constraints, grabs |
| Picture encodings       | Also `scroll`, and others depending on the codecs installed                                        |
| Video encodings         | HEVC and others too, depending on decoder availability                                             |
| Accelerated rendering   | OpenGL plus VAAPI, NVIDIA, Media Foundation, VideoToolbox and other optional paths                 |
| Speaker audio           | Negotiated through GStreamer, in a choice of containers                                            |
| Clipboard               | Multiple selections / targets, direction controls and filtering                                    |
| Keyboard                | Full keymap upload / synchronization, layouts, shortcuts and lock-state handling                   |
| Pointer / input         | Pointer, buttons, wheel, focus, relative input, grabs and XI2 support                              |
| Server cursors          | `raw` and `png`, local themed cursors by name, desktop scaling and size negotiation                |
| Bell forwarding         | Native platform backend                                                                            |
| Desktop notifications   | Native notification backends on supported platforms                                                |
| Client tray / menu      | Extensive session controls                                                                         |
| Printer forwarding      | Optional platform dependencies                                                                     |
| Webcam forwarding       | Optional; client camera → Linux server                                                             |
| Shared memory           | `mmap`, in both directions, for sessions on the same host                                          |
| DPI / display sync      | DPI, scaling, monitor layout, workspaces and high bit depth                                        |
| Remote logging / events | Full diagnostics, session info and event handling                                                  |
| Bandwidth adaptation    | Detection, limits, codec adaptation and detailed latency metrics                                   |

### xpra-html5

Production client, widely deployed; runs in any modern browser and requires an xpra 7.0 or later server.

| Feature                 | Notes                                                                                                                             |
|-------------------------|-----------------------------------------------------------------------------------------------------------------------------------|
| Transports              | The `quic` marker is `WebTransport`, still experimental                                                                           |
| Transport security      | HTTPS/WSS through the browser's TLS stack; application-level AES (CBC/CTR/CFB)                                                    |
| Authentication          | HMAC-SHA256 password; refuses to send passwords over unencrypted remote links                                                     |
| Forwarded windows       | Create / destroy / draw / move / resize / raise                                                                                   |
| Advanced window state   | Fullscreen, maximize/minimize, above/below, modal, opacity and the server's window border, confined to the browser canvas         |
| Picture encodings       | Also `scroll`; RGB is lz4 compressed, and WebP and AVIF are validated in a decode worker first                                    |
| Video encodings         | H.264 and VP8 through `WebCodecs`, decoded offscreen - Safari 26 and later included                                               |
| Accelerated rendering   | Browser-native decoding, offscreen canvas and decode workers; no GPU control                                                      |
| Speaker audio           | Through `MediaSource`, with an `aurora` fallback                                                                                  |
| Clipboard               | Text, HTML and PNG images, CLIPBOARD selection only (PRIMARY too without the async clipboard API), subject to browser permissions |
| Keyboard                | Layout selection and browser keycodes; no keymap upload                                                                           |
| Pointer / input         | Pointer, buttons, wheel, focus and pointer lock                                                                                   |
| Server cursors          | PNG only, rescaled for the browser zoom; no cursor names, no size negotiation                                                     |
| Window icons            | PNG icons, in the title bar, the window list and the page favicon                                                                 |
| Bell forwarding         | Audio sample                                                                                                                      |
| Desktop notifications   | Browser notifications                                                                                                             |
| Client tray / menu      | Floating toolbar with session controls                                                                                            |
| File transfer / URLs    | Downloads and URL opening                                                                                                         |
| Printer forwarding      | Through the browser's print dialog                                                                                                |
| DPI / display sync      | DPI and screen size reported, resizes with the browser window                                                                     |
| Remote logging / events | Remote logging, session info and diagnostics                                                                                      |
| Bandwidth adaptation    | Bandwidth limit option, pings and latency metrics                                                                                 |

### vispra

Early stage third party rewrite of the html5 client; runs in any modern browser, against a server left in its default
backwards-compatible mode since it only knows the packet names from before xpra 6.5.

| Feature                 | Notes                                                                 |
|-------------------------|-----------------------------------------------------------------------|
| Transports              | The `quic` marker is `WebTransport`, still experimental               |
| Transport security      | HTTPS/WSS through the browser's TLS stack; application-level AES      |
| Authentication          | HMAC-SHA256 password                                                  |
| Forwarded windows       | Create / destroy / draw / move / resize / raise                       |
| Advanced window state   | A subset of the html5 client's, also confined to the browser canvas   |
| Picture encodings       | Also `scroll`; RGB is lz4 compressed, AVIF subject to browser support |
| Video encodings         | H.264 and VP8 through `WebCodecs`                                     |
| Accelerated rendering   | Browser-native decoding, offscreen canvas and decode workers          |
| Speaker audio           | Through `MediaSource`, with an `aurora` fallback                      |
| Clipboard               | Plain text, subject to browser permissions                            |
| Keyboard                | Layout selection and browser keycodes; no keymap upload               |
| Pointer / input         | Pointer, buttons, wheel and focus                                     |
| Server cursors          | PNG only, at the size the server sends; no cursor names, no scaling   |
| Window icons            | Decoded and dropped: every window shows the same branding icon        |
| Bell forwarding         | Tone generated with the Web Audio API                                 |
| Desktop notifications   | Browser notifications                                                 |
| Client tray / menu      | Taskbar and session info panel                                        |
| Remote app system tray  | Tray windows are received and rendered                                |
| File transfer / URLs    | Basic file reception                                                  |
| Printer forwarding      | Present but disabled by default                                       |
| DPI / display sync      | DPI and screen size reported, resizes with the browser window         |
| Remote logging / events | Remote logging, session info and pings                                |
| Bandwidth adaptation    | Bandwidth limit option and pings                                      |

### Rust client

Runs on MS Windows, on Linux, X11 or Wayland, and on MacOS (Apple silicon binaries); requires an xpra 7.0 or later server, with or without
`XPRA_BACKWARDS_COMPATIBLE`.

| Feature                  | Notes                                                                                                                                                                                                            |
|--------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Transports               | Also Unix domain sockets on Linux and MacOS; `ssh` shells out to the system client, or to the `--ssh` command (PuTTY's `plink` included)                                                                         |
| Transport security       | Certificate and hostname verification against the system trust store, `--ssl-insecure` opts out; no private CA option, no application-level AES                                                                  |
| Authentication           | HMAC-SHA256 password via connection dialog, environment, pinentry or built-in dialog                                                                                                                             |
| Out-of-band chunks       | Received from the server                                                                                                                                                                                         |
| Forwarded windows        | Create / destroy / draw / move / resize / raise                                                                                                                                                                  |
| Advanced window state    | Fullscreen, maximize/minimize, decorations, above/below, modal, constraints and interactive moves; on X11 also sticky, shaded, opacity, workspace, window type, skip-taskbar / skip-pager and attention requests |
| Override-redirect popups | Real override-redirect on X11 only: undecorated but focus-stealing toplevels on MS Windows, managed windows on MacOS, placed by the compositor on Wayland                                                        |
| Video encodings          | H.264 on Windows through Media Foundation                                                                                                                                                                        |
| Accelerated rendering    | Media Foundation H.264 on Windows; CPU softbuffer otherwise                                                                                                                                                      |
| Speaker audio            | Bare Opus on Windows only, with jitter buffering and AV sync                                                                                                                                                     |
| Clipboard                | Bidirectional plain text, CLIPBOARD selection only; X11/XWayland, MS Windows and MacOS                                                                                                                           |
| Keyboard                 | Direct key events, sending the keyboard layout and using the server's modifier names; no keymap upload, NumLock limitation on Wayland                                                                            |
| Pointer / input          | Pointer, buttons, wheel, focus and server-requested grabs                                                                                                                                                        |
| Server cursors           | PNG only, at the size the server sends; no cursor names, no scaling                                                                                                                                              |
| Window icons             | PNG icons on X11 and MS Windows; `winit` ignores them on Wayland and MacOS                                                                                                                                       |
| Bell forwarding          | Windows tone; terminal BEL on Linux and MacOS                                                                                                                                                                    |
| Desktop notifications    | Windows tray balloons; logged on Linux and MacOS                                                                                                                                                                 |
| Client tray / menu       | Windows only, with an Exit command                                                                                                                                                                               |
| Shared memory            | `mmap` on Linux and MacOS, server → client only, on by default; not on MS Windows                                                                                                                                |
| DPI / display sync       | Desktop size and per-monitor layout reported, with monitor-relative coordinates; HiDPI displays run in logical pixels, scaled up locally; no DPI value sent                                                      |
| Remote logging / events  | Remote logging, lifecycle events and pings                                                                                                                                                                       |
| Bandwidth adaptation     | Pings only                                                                                                                                                                                                       |

### Go client

Minimal client, usable on four window systems: Linux X11, Linux Wayland, MS Windows and MacOS; requires an xpra 7.0 or
later server.

| Feature                  | Notes                                                                                                                                                                                                                         |
|--------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Transports               | Also Unix domain sockets on Unix-like systems; `ssh` shells out to the system client                                                                                                                                          |
| Transport security       | TLS certificate and hostname verification against the system trust store for `ssl`/`wss`, private CA option; SSH through the system client; no application-level AES                                                          |
| Authentication           | HMAC-SHA256 password via URL, connection dialog, `XPRA_PASSWORD`, pinentry or the Windows credentials dialog; SSH logins left to OpenSSH                                                                                      |
| Out-of-band chunks       | Received and spliced back in by index                                                                                                                                                                                         |
| Forwarded windows        | Create / destroy / draw / move / resize / raise / minimize                                                                                                                                                                    |
| Advanced window state    | Title, size constraints, raise, focus and minimize/restore; maximized, fullscreen, above/below, sticky, shaded and skip-taskbar / skip-pager on X11, maximized and above on MS Windows; no positioning or stacking on Wayland |
| Override-redirect popups | X11, MS Windows, MacOS, and Wayland `xdg_popup`                                                                                                                                                                               |
| Picture encodings        | RGB24 and RGB32; PNG includes palette and grayscale                                                                                                                                                                           |
| Accelerated rendering    | X11 pixmap backing store, GDI blits on Windows, `wl_shm` buffers on Wayland, a `CALayer` repainted whole on MacOS; no video acceleration                                                                                      |
| Clipboard                | Bidirectional UTF-8 text, CLIPBOARD selection only, up to 16 MiB; X11, Wayland, MS Windows and MacOS                                                                                                                          |
| Keyboard                 | X11 keysym names, the compositor's own keymap on Wayland, printable ASCII only on Windows, Option and Command as Alt and Super on MacOS; no keymap upload                                                                     |
| Pointer / input          | Pointer, buttons, wheel and focus                                                                                                                                                                                             |
| Server cursors           | PNG only on all four backends, at the size the server sends; no cursor names, no scaling                                                                                                                                      |
| Window icons             | PNG icons; on Wayland through `xdg-toplevel-icon-v1`, which the compositor is free to ignore; the Dock icon on MacOS, which has no per-window icon                                                                            |
| Bell forwarding          | Native X11, Win32 and MacOS sound; none on Wayland                                                                                                                                                                            |
| Desktop notifications    | Logged only                                                                                                                                                                                                                   |
| Client tray / menu       | MS Windows notification area and MacOS menu bar icon, with an Exit command                                                                                                                                                    |
| Shared memory            | `mmap` for Unix domain socket connections, on Linux only, server → client only                                                                                                                                                |
| DPI / display sync       | Desktop size and per-monitor layout reported, with monitor-relative coordinates; Windows per-monitor DPI awareness; no DPI value sent                                                                                         |
| Remote logging / events  | Server lifecycle events and pings; no client-side remote logging                                                                                                                                                              |
| Bandwidth adaptation     | Pings only                                                                                                                                                                                                                    |

### C client

Minimal Linux X11 client, written clean-room from the protocol documentation; it speaks protocol 8.0 only, so it
needs an xpra 8.0 development series server.

| Feature                 | Notes                                                                                                                                                                                     |
|-------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Transports              | Also Unix domain sockets, including local `:N` displays                                                                                                                                   |
| Authentication          | HMAC-SHA256 password via `XPRA_PASSWORD`, a password file or a terminal prompt                                                                                                            |
| Out-of-band chunks      | Received and substituted back in, up to three per packet                                                                                                                                  |
| Forwarded windows       | Create / destroy / draw / move / resize / raise / close                                                                                                                                   |
| Advanced window state   | Title, transient-for and size constraints only                                                                                                                                            |
| Picture encodings       | `rgb24` and `rgb32` in any channel order, raw or LZ4 compressed; `png` (also palette and grayscale), `webp` and `jpeg` only when libpng / libwebp / libturbojpeg can be loaded at runtime |
| Accelerated rendering   | `XPutImage` from a client-side image; no `XShm`, no video acceleration                                                                                                                    |
| Clipboard               | Text only, `CLIPBOARD` and `PRIMARY` selections, both directions, at most 1 MiB; no images, no other targets                                                                              |
| Keyboard                | X11 keysym names and modifiers; no keymap upload                                                                                                                                          |
| Pointer / input         | Pointer, buttons, wheel and focus                                                                                                                                                         |
| Window icons            | PNG icons up to 256x256 as `_NET_WM_ICON`, only when libpng can be loaded                                                                                                                 |
| Server cursors          | `raw` RGBA up to 256x256, in colour through libXcursor when installed, black and white otherwise; no cursor names, no scaling                                                             |
| Bell forwarding         | X11 keyboard extension bell, on the window it belongs to                                                                                                                                  |
| Desktop notifications   | Printed on stdout                                                                                                                                                                         |
| DPI / display sync      | Screen size reported as a single monitor; no DPI                                                                                                                                          |
| Remote logging / events | Server events printed on stdout and pings; no client-side remote logging                                                                                                                  |

<div class="docs-section-heading" markdown="1">

## See also

</div>

* [Xpra client](./Client.md) - the default client: launcher, session files, URL mapping and command line
* [Client OpenGL](./Client-OpenGL.md) - accelerated window rendering in the default client
* [xpra-html5 configuration](https://github.com/Xpra-org/xpra-html5/blob/master/docs/Configuration.md) - options and URL parameters for the html5 client
* [Porting guide](../Porting/README.md) - how to implement a new client
* [Network protocol](../Network/Protocol.md) - what a client implementation has to support
* [Subsystems](../Subsystems/README.md) - the feature modules found on both ends of the connection

<div class="docs-section-heading" markdown="1">

## Defunct clients

</div>

These clients are no longer maintained and will not work with the
[currently supported versions](https://github.com/Xpra-org/xpra/wiki/Versions) of the xpra server.\
They are listed here for reference only:

| Client                                                                   | Platform      | Last activity | Notes                                                                                           |
|--------------------------------------------------------------------------|---------------|---------------|-------------------------------------------------------------------------------------------------|
| [Android client](https://xpra.org/vault/Android/)                        | Android       | 2015          | The original Java client, also shipped as part of `winswitch` - archived APKs from 2012 to 2015 |
| [Xpra-client-android](https://github.com/sylvain121/Xpra-client-android) | Android, Java | 2016          | Fork of `xpra-client` adding `h264` decoding (GPLv3)                                            |
| [xpra-client](https://github.com/jksiezni/xpra-client)                   | Android, Java | 2021          | Java client with Android and Swing frontends (GPLv3)                                            |
| [xpra-html5-client](https://github.com/andersevenrud/xpra-html5-client)  | Browser       | 2024          | TypeScript / React rewrite of the html5 client, designed to be embeddable (MPL-2.0)             |
