# Threat model

## What this project does and where untrusted input enters

Xpra is a remote display system: a server runs X11 (or Wayland) applications on a virtual display,
or shadows an existing desktop, and forwards their windows, audio, clipboard, notifications, printers, files etc
to one or more clients over the network.
It is mostly Python, with the performance sensitive parts (pixel format conversions, codecs, packet encoding,
X11 and Wayland bindings) written in Cython and calling C libraries.

Both peers are untrusted, in both directions:

* **a malicious client attacking the server**:
  * before authentication: anything reachable from a listening socket - the connection upgrades
    (`tcp`, `ssl`, `ws`, `wss`, `http`, `ssh`, `quic` / `webtransport`, `rfb` / VNC, `rdp`, `vsock`, named pipes),
    the builtin http server, the packet header, the packet decoders (`rencodeplus`, `bencode`), decompression (`lz4`, `brotli`),
    the `hello` packet and the authentication modules (`xpra/auth/`).
    This is the most important attack surface.
  * after authentication: every packet handler, with the data the client sends -
    keyboard and pointer events, window configuration, clipboard contents, file transfers, printer definitions,
    webcam frames, audio, `mmap` areas, encoding options, control commands.
    An authenticated client is still not trusted to escape the restrictions the server applies to it
    (disabled features, `readonly`, `start-new-commands=no`, per-socket options, `--uid` / `--gid`, seccomp, landlock).
* **a malicious server attacking the client**: a compromised server, or a compromised application
  running in the session (ie: a browser), must not be able to compromise the client's machine.
  Window metadata (titles, icons, class, hints), cursors, screen updates (every picture and video decoder,
  `rgb`, `mmap`), clipboard data, notifications, system tray icons, file transfers and file / URL open requests,
  print jobs, audio streams, OpenGL paints, server-provided strings shown or logged by the client.
  `xpra://` URLs and connection strings passed to the client are also untrusted.
* **local peers**: other local users connecting to the server's unix domain sockets or abstract sockets,
  dbus (`--dbus-control`), the system tray, the proxy server and its sub-processes.

## Components that matter most / least

Most important:
* `xpra/net/`: protocol, packet encoding, compression, websocket / http / ssl / quic handling, `xpra/net/protocol/`
* `xpra/auth/` and the authentication / challenge handling in `xpra/server/core.py` and `xpra/client/base/`
* `xpra/codecs/`: all the Cython code (`.pyx`) - memory safety bugs there are the most serious,
  especially the decoders and pixel format converters which the client runs on server-supplied data:
  `argb`, `csc_cython`, `libyuv`, `vpx`, `jpeg`, `webp`, `avif`, `openh264`, `dav1d`, `de265`, `aom`, `pillow`, etc
* the client-side handling of server data (`xpra/client/`, `xpra/gtk/`, OpenGL paint code)
* the server-side packet handlers (`xpra/server/subsystem/`, `xpra/server/source/`)
* `mmap` (`xpra/net/mmap/`), file transfers (`xpra/net/file_transfer.py`), clipboard (`xpra/clipboard/`)
* the X11 bindings (`xpra/x11/bindings/`)

Less important, but still in scope:
* the proxy server, shadow servers, `xpra/platform/` (Linux / posix code is more important than MS Windows / MacOS)

Out of scope:
* `packaging/`, `docs/`, `tests/` and the build system (`setup.py`)
* the third-party libraries themselves (ffmpeg, libvpx, openh264, Pillow, GTK, ...),
  unless xpra misuses them or passes them unvalidated sizes / buffers
* the HTML5 client, which is a separate project: https://github.com/Xpra-org/xpra-html5
* issues which are already listed as known in `docs/SECURITY.md`

## How to exercise it

* the unit tests are in `tests/unittests/unit/`, mirroring the module tree, run them as the `xpra-test` user
  (some tests behave differently as root):
  `python3 setup.py unittests unit/codecs/argb_test.py` rebuilds and installs into `/src/dist/` before running the test,
  `cd tests/unittests && PYTHONPATH=. python3 unit/codecs/argb_test.py` runs it against the system wide installation
  (the source tree in `/src` has no compiled extensions, so do not put it on `PYTHONPATH`)
* already known to fail in this image: `unit/codecs/pillow_encoder_test.py` and `unit/server/window/windowicon_test.py`
  (also failing in the CI), and tests which need a desktop environment the image does not have (icon theme, dbus session bus,
  `XDG_RUNTIME_DIR`): `wayland_client_test`, `posix_security_test`, `portal_shadow_capture_test`, `icon_image_test`
* the image also has xpra installed system wide: `xpra start --bind-tcp=127.0.0.1:10000 --no-daemon --start=xterm`
  then `xpra attach tcp://127.0.0.1:10000/` or `xpra info tcp://127.0.0.1:10000/`
* use `Xvfb` on a high display number (ie: `:1000` and above), the way `tests/unittests/unit/server_test_util.py`
  does with `find_free_display()` and `start_Xvfb()`
* debug logging is enabled per category with `-d network,auth,...`, `xpra/net/protocol/` has the framing code
  which is the easiest place to inject crafted packets

## How you rate severity

* **critical**: remote code execution or memory corruption reachable before authentication, authentication bypass,
  and remote code execution in the client triggered by a server without any user interaction
* **high**: memory corruption (buffer overflow, use-after-free, double free) reachable after authentication or
  from a malicious server, even without a demonstrated exploit; reading or writing arbitrary files;
  escaping the restrictions applied to a client (disabled features, `readonly`, `start-new-commands=no`, sandboxing)
* **medium**: information leaks (heap memory, file contents, credentials in logs), denial of service of the server
  reachable before authentication, spoofing (window titles, notifications impersonating local applications,
  file names or extensions hidden with control or bidi characters)
* **low**: denial of service reachable only after authentication or from a malicious server (crashing or hanging the client),
  excessive resource usage, log injection
* anything which requires an unsafe configuration that is documented as such (ie: no authentication on a public socket,
  `--start-new-commands=yes` for an untrusted client) is at most low

## Anything to leave alone

* features that are intentionally powerful for an authenticated user who is allowed to use them:
  starting commands, the control channel, the xpra shell, file transfers and opening files once accepted, printing,
  `uinput`, shadowing a desktop - these are only bugs if they can be used when disabled, or beyond the configured restrictions
* a local user who already owns the session (same uid) controlling it
* weak legacy options kept for compatibility (ie: AES-CBC encryption, plain-text password authentication over
  unencrypted connections) when they are explicitly enabled
* missing features of a third-party library, and bugs only present in outdated distribution packages
