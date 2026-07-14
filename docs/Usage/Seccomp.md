# Seccomp sandboxing

`seccomp` is a Linux kernel feature that restricts the set of system calls a
thread is allowed to make. Xpra can use it to lock down the threads that are the
first to process data coming from the network, so that a bug in a picture / video
decoder or in the packet parser cannot easily be turned into something worse -
executing a command, opening or deleting files, or opening new network
connections.

This is a defence-in-depth measure: it does not replace [authentication](Authentication.md)
or [encryption](../Network/Encryption.md), it limits the *damage* a successful
exploit of one of those threads could do.

**Linux only** (it has no effect on other platforms) and **disabled by default**.


## What it protects

Xpra installs a separate, thread-local filter on each of the threads that handle
untrusted input:

| Filter | Thread | What it processes |
|---|---|---|
| `decode` | picture decoding | compressed image and video frames, window icons, cursors |
| `parse` | network read | raw socket bytes: decrypt → decompress → decode packets |
| `rfb` | VNC client read | RFB / VNC framebuffer updates (when connecting to a VNC server) |

Each filter only affects the thread it is installed on - the rest of xpra keeps
running normally. The same filters are available whether xpra is running as a
client, a server or a [proxy](Proxy-Server.md).


## Enabling it

Use the `--seccomp` command line option:

```shell
xpra attach ssl://HOST:PORT/ --seccomp=default
```

| `--seccomp=` | Effect |
|---|---|
| `no` | *(default)* no filtering |
| `default` | enable all four filters with a **non-fatal** action: a blocked syscall fails with a permission error instead of killing anything |
| `strict` | enable all four filters with a **fatal** action: a blocked syscall kills the whole process |
| a list | enable only the listed threads, ie `decode`, `parse`, `rfb`, `menu` |

The list form lets you pick individual filters and, optionally, an action per
filter (see [actions](#actions) below):

```shell
# only sandbox the image decoding thread:
xpra attach ... --seccomp=decode

# sandbox decoding and network parsing:
xpra attach ... --seccomp=decode,parse

# decoding is fatal on violation, network parsing only fails the call:
xpra attach ... --seccomp=decode:kill,parse:errno
```

The recommended approach is to start with `--seccomp=default` (nothing is killed,
violations simply fail) to confirm your normal workflow is unaffected, and only
then switch to `--seccomp=strict` for full enforcement.


## Actions

The *action* decides what happens when a sandboxed thread attempts a syscall that
is not on its allow-list:

| Action | Behaviour |
|---|---|
| `errno` | the call fails with a permission error - **non-fatal**, the safest to try first |
| `kill` | the offending thread is killed |
| `kill_process` | the whole xpra process is killed - the strongest enforcement |
| `log` | the call is **allowed** but recorded in the kernel audit log - useful for tuning (see [diagnosing](#diagnosing-and-tuning)) |
| `allow` | the call is allowed - effectively disables the filter, for testing |

`--seccomp=default` uses `errno`, `--seccomp=strict` uses `kill_process`.


## Things to be aware of

* **File transfers and URL opening.** When a *fatal* action is used (`strict`,
  `kill`, `kill_process`), receiving a file or an [`open-url`](../Features/File-Transfers.md)
  request on a sandboxed network thread will kill the process, because those
  handlers legitimately open files or launch commands. If you enable strict
  filtering, also disable those features (`--file-transfer=no --open-url=no`) or
  keep them on a non-fatal action. With `--seccomp=default` (`errno`) the transfer
  simply fails instead.

* **Debug image dumping** writes to disk from the decoding thread, so it is
  automatically turned off (with a warning) whenever seccomp is enabled - this covers
  `XPRA_SAVE_TO_FILE` (frames), `XPRA_SAVE_WINDOW_ICONS` and `XPRA_SAVE_CURSORS`.

* **Codec self-test** must stay enabled (it is, by default). Xpra pre-loads and
  pre-warms every decoder at startup *before* the sandbox is installed; running
  with `XPRA_CODEC_SELFTEST=0` removes that step and is incompatible with the
  `decode` filter.

* **QUIC** connections read from the socket on a separate event-loop thread that
  is not sandboxed; the packet decoding they feed into *is* covered by the `parse`
  filter. See the [technical details](#quic).

* **VNC servers.** Only the *client* side RFB thread is sandboxed; an xpra server
  accepting VNC clients is not covered by the `rfb` filter.


## Diagnosing and tuning

Different transports (TLS, QUIC, WebSocket) and platforms may need a slightly
different set of syscalls. If a filter is too strict for your setup, two modes
help you find the missing syscall:

* **`log` action** - the syscall is allowed but recorded. Note that this goes to
  the **kernel audit log, not** xpra's own `-d seccomp` logging. Find the records
  with:
  ```shell
  sudo ausearch -m SECCOMP -ts recent
  sudo journalctl -k --grep=seccomp
  sudo dmesg | grep -i seccomp
  ```
  The syscall shows up as a number (`syscall=NN`); resolve it with `ausyscall NN`
  or `scmp_sys_resolver -a x86_64 NN`.

* **`errno` action** - the syscall fails with a permission error, which usually
  produces an ordinary Python `PermissionError` traceback in xpra's log pointing
  straight at the call site. This is often the quickest way to identify the
  culprit (but, unlike `log`, it changes behaviour, so the session may misbehave
  after the first blocked call).

To turn on xpra's own logging of the filter installation, add `-d seccomp`.


## Environment variables

The `--seccomp` option is a convenience wrapper: it sets a handful of environment
variables early enough for the threads to pick them up. You can also set them
directly for finer control - **an explicit environment variable always takes
precedence over the option**:

| Variable | Purpose |
|---|---|
| `XPRA_SECCOMP` | global on/off, enables all filters |
| `XPRA_SECCOMP_DECODE` | enable/disable the decoding filter |
| `XPRA_SECCOMP_PARSE` | enable/disable the network parse filter |
| `XPRA_SECCOMP_RFB` | enable/disable the VNC client filter |
| `XPRA_SECCOMP_MENU` | enable/disable the menu loading filter |
| `XPRA_SECCOMP_DECODE_ACTION` | action for the decoding filter |
| `XPRA_SECCOMP_PARSE_ACTION` | action for the parse filter |
| `XPRA_SECCOMP_RFB_ACTION` | action for the VNC client filter |
| `XPRA_SECCOMP_MENU_ACTION` | action for the menu loading filter |

Each `*_ACTION` accepts `errno`, `kill`, `kill_thread`, `kill_process`, `log` or
`allow` (default: `kill_process`).

---

# Technical details

The rest of this document describes how the filters are implemented and how the
threads were audited. It is only relevant if you want to understand or extend the
sandboxing - end users can stop reading here.

## How it works

Each filter is a per-thread [`seccomp`](https://www.kernel.org/doc/html/latest/userspace-api/seccomp_filter.html)
BPF allow-list, built with `libseccomp` in the native helper
`xpra/seccomp/_native`. The primitive `install_filter(syscalls, action, masked_rules)` sets
`PR_SET_NO_NEW_PRIVS`, initialises the filter with the chosen default action, adds
one `SCMP_ACT_ALLOW` rule per allowed syscall (optionally constrained by masked
argument comparisons), and loads it. The Python side lives
in `xpra/seccomp/`:

* `xpra/seccomp/draw.py` - the `decode` filter, installed at the top of the decode loop
  (`xpra/client/subsystem/decode.py`). The module keeps its original file name, from when
  the only sandboxed decoding thread was the draw loop.
* `xpra/seccomp/parse.py` - network parse thread, installed at the top of
  `_read_parse_thread_loop` (`xpra/net/protocol/socket_handler.py`), and only for
  real network sockets.
* `xpra/seccomp/rfb.py` - RFB client read thread, installed once the handshake
  reaches steady state (`xpra/client/base/rfb_protocol.py`).
* `xpra/seccomp/menu.py` - XDG menu loading thread, installed before importing or
  parsing platform menu data (`xpra/server/menu_provider.py`).

The `--seccomp` option is turned into the `XPRA_SECCOMP*` environment variables by
`parse_seccomp_option()` / `configure_seccomp()` in `xpra/scripts/main.py`. This
runs in `run_mode` right after `configure_env`, before the client / server object
and its threads are created, and only sets variables that are not already defined.
The list form deliberately does **not** set the global `XPRA_SECCOMP` flag: the
decode filter reads it as its primary gate, so setting it would override the
per-thread flags.

**Thread inheritance.** A seccomp filter is inherited by every thread created
*after* it is loaded, so a filter also covers any worker thread its host thread
spawns. To keep a handler *out* of the sandbox it must run on a thread that is not
a descendant of the filtered thread - in practice, register its packet handler
with `main_thread=True` so it is dispatched on the GLib main loop (which predates
the parse thread's filter). This is how the `challenge` handler stays unsandboxed:
auth backends may `fork`/`exec` a helper (kerberos/gss/exec/u2f/pinentry) or read
files, so `_process_challenge` runs on the main thread.

The server also starts its shared background worker during `ServerCore.init()`,
before subsystem setup. Menu loading posts completion callbacks to this worker;
creating it lazily from the filtered menu thread would make unrelated work inherit
the menu policy.

## Syscall lists

`xpra/seccomp/draw.py` defines a permissive `BASE_SYSCALLS` baseline. From it:

* the **decode** allow-list (`DECODE_SYSCALLS`) removes the file-namespace syscalls
  (`FILE_SYSCALLS`: `open`, `openat`, `unlink`, `unlinkat`, `mkdir`, `rename`,
  `renameat*`, `ftruncate`, `fallocate`). The decode thread only decodes images that
  are already in memory, so it never needs to open, create or delete a file -
  *provided* everything it will import is already loaded. To guarantee that
  ordering, the decode thread is made the **sole initializer** of the codecs: from
  `Decode.preload()` it loads and self-tests all of them *itself*, before
  it installs the filter. Loading runs the codec self-test (`XPRA_CODEC_SELFTEST`,
  on by default), which does a real decode of each codec, triggering PIL's lazy
  plugin imports, any `dlopen` of codec libraries and any transient decoder worker
  threads, all while the decode thread is still unfiltered. Every other consumer that
  needs the codecs (the `encoding-config` packet, and - in backwards-compatible
  mode - the encoding capabilities in the hello) calls
  `Encodings.ensure_codecs_loaded()`, which *waits* for the decode thread rather than
  loading anything itself; only when there is no decode thread does it load them
  directly. This is safe because the decode thread is started (in the client's `run`)
  before the main loop builds the hello. Hardware decoders (which would `dlopen`
  CUDA etc. on the decode thread) are separately disabled under seccomp via
  `xpra/client/subsystem/encoding.py`.
* the **parse** allow-list (`PARSE_SYSCALLS`) is the same tightened `DECODE_SYSCALLS`
  (no file access) plus the socket syscalls the reader needs (`SOCKET_SYSCALLS`:
  `recvfrom`, `getsockname`, `getsockopt`, `sysinfo`). This is possible because
  every inline packet handler that spawned a subprocess or did file I/O has been
  moved off the parse thread (file transfers and printing to the file worker thread;
  `open-url`, `start-command` and `control-request` to the main thread - see the
  handler audit below). The residual risk is a handler that lazily imports a module
  for the *first time* on the parse thread (an `openat`); the parse action defaults
  to `errno` (non-fatal) for this reason, so validate a deployment with
  `XPRA_SECCOMP_PARSE_ACTION=log` and pre-compiled bytecode before using `strict`.
* the **rfb** allow-list (`RFB_SYSCALLS`) still keeps the full `BASE_SYSCALLS`
  (including `open`/`openat`) plus `SOCKET_SYSCALLS`. Its inline handlers have not
  been walked to move their file I/O off-thread, so tightening it is deferred.
* the **menu** allow-list (`MENU_SYSCALLS`) keeps the read-side filesystem calls
  needed to traverse XDG configuration and load XML, desktop files and icons.
  `open` and `openat` use masked argument rules which reject write, create,
  truncate, append and temporary-file flags. Namespace mutations, new descendants
  and socket operations are not allowed, and writes are limited to the standard
  output/error descriptors used for logging. Use `--seccomp=menu:errno` when
  auditing menu and icon variants before enabling a fatal action. pyxdg's
  `KDELegacyDirs` helper is skipped because it would execute `kde-config`, and
  runtime bytecode writes are disabled before the loader's lazy imports.

**`gi_import` caveat:** pygobject's `require_version()` enumerates the typelib
directories *on disk* on every call, even for a namespace that is already loaded.
Any lazy `gi_import("GLib")` made from a handler (`xpra/util/background_worker.py`,
`xpra/notification/base.py`, `xpra/codecs/loader.py`, ...) would therefore hit
`openat` on the parse thread and fail with `Namespace GLib not available`.
`gi_import` (`xpra/os_util.py`) now skips `require_version` when that exact version
has already been required, so the module comes from the import cache without
touching the filesystem.

**`kill_process` caveat:** a blocked lazy `import` or `dlopen` is a `SIGSYS`
process kill, not a catchable exception - `log.trap_error` cannot recover from it.
This is why the pre-warm above matters, and why the debug file-dumps
(`get_save_to_file()` in `xpra/codecs/debug.py`, `get_save_window_icons()` in
`xpra/client/subsystem/window/window_icon.py`, `get_save_cursors()` in
`xpra/client/subsystem/cursor.py`) are disabled under seccomp.

## The decode thread

The sandboxed decoding thread is not draw-specific: it is a shared worker owned by the
`decode` subsystem (`xpra/client/subsystem/decode.py`), and any client subsystem can post
work to it with `add_decode_work(method, *args)` (`StubClientSubsystem`). Its queue holds
`(callable, args)` pairs, so the producer stays a trivial packet handler and the decoding
itself happens on the filtered thread. Three consumers use it today:

| Packet | Enqueues | Decodes |
|---|---|---|
| `window-draw` / `eos` | `WindowDraw._process_window_draw` | `_do_draw` → `window.draw_region()` |
| `window-icon` | `WindowIcon._process_window_icon` | `_decode_window_icon` → Pillow |
| `cursor` / `cursor-data` | `CursorClient._process_cursor_data` | `_decode_cursor_data` → Pillow |

Two rules bind a new consumer:

* **Import from `preload_decode()`, not from the work item.** `Decode.preload()` loads the
  codecs and then calls `preload_decode()` on every subsystem, all while the thread is still
  unfiltered. A module imported for the first time *after* the filter is installed hits
  `openat` and, under a fatal action, kills the process. (This is why the window-icon and
  cursor subsystems import `PIL` / `xpra.codecs.pillow.decoder` from that hook: with
  `--encodings=rgb`, `dec_pillow` is never loaded, so nothing else would have imported them.)
* **Keep the packet handler on `main_thread=True`.** All three producers are UI packets, and
  so is `new-window`. That shared UI-thread hop is what orders a draw or an icon *after* the
  window it refers to has been created; dispatching them straight from the parse thread would
  race window creation. The handler only enqueues, so it costs nothing to leave it there.

The result is bounced back to the UI thread with `idle_add`, and the target window is looked
up *then*, not before enqueuing - a window destroyed mid-decode simply drops its icon.

## Thread coverage

Four thread roles carry filters today: **decode**, **parse**, client-side **rfb** and
**menu loading**. The rest of the thread inventory, and why each is or is not sandboxed:

| Thread | Untrusted input? | Decision |
|---|---|---|
| **decode** | Yes: compressed images/video, window icons, cursors | **Sandboxed** (`seccomp/draw.py`) |
| **network parse** | Yes: raw socket bytes | **Sandboxed**, network sockets only (`seccomp/parse.py`) |
| **RFB read** (client) | Yes: framebuffer parsing | **Sandboxed** at steady state (`seccomp/rfb.py`) |
| **menu loading** | Local XDG metadata and icons | **Sandboxed**, read-only filesystem access (`seccomp/menu.py`) |
| **QUIC/WebTransport asyncio** | Yes: UDP recv + TLS/HTTP3 | Mostly covered indirectly - see below |
| **RFB read** (server) | Yes: client input | Out of scope - handlers drive the display server |
| **HTTP handler** | Websocket upgrade only | Left - see below |
| **write / format** | No: outgoing packets only | Not worth sandboxing |
| **verify_auth** | Reads the hello packet | Auth backends fork/exec helpers and read files by design - sandboxing would break authentication |
| **handle-new-connection** | Sniffs a few bytes | Setup-only, may go on to spawn (ssl/ssh upgrade) - low value |

### QUIC

For QUIC, the socket `recvfrom` + TLS decrypt + HTTP/3 demux happen in the aioquic
event-loop thread (`asyncio-thread`), which pushes already-decoded stream bytes
into `read_queue` (`xpra/net/quic/connection.py`). The parse thread then reads that
queue and runs the normal decode/dispatch path - so the packet decode surface *is*
covered by the parse filter. Only the UDP read and the QUIC/TLS framing run
unfiltered. That thread also runs the whole aioquic/asyncio machinery (timers,
crypto, cert access), so sandboxing it is not practical; the residual gap is narrow
and documented rather than closed.

### RFB read thread (client)

`RFBClientProtocol` reads the socket and does all the tight/zlib/gradient/
depalette/cursor byte-crunching inline, dispatching `draw`/`challenge`/
`clipboard-token`: jpeg goes to the already-sandboxed decode thread, `challenge` is
`main_thread=True` (and dispatched before client-init anyway), and the heavy
parsing is pure-Python + `zlib.decompress`.

The filter is *not* installed from thread-start: the RFB handshake and the VeNCrypt
inline TLS upgrade (`_upgrade_to_tls`) run on this same read thread. Rather than
audit every syscall OpenSSL's handshake and the auth path might make, the filter is
installed once we reach steady-state framebuffer parsing, in `_parse_client_init`
just before `self._packet_parser = self._parse_rfb_packet`. By then TLS is up and
auth is done; the write thread was already created on the first handshake `send()`,
so it predates the filter and is unaffected.

### Websocket upgrade

The HTTP/websocket upgrade is handled by Python's stdlib
`http.server.BaseHTTPRequestHandler` - text header parsing, no bespoke binary
parser. Once upgraded, WS frames are unmasked and fed into the filtered parse
thread, so the websocket data plane is already covered. The handler also serves the
HTML5 client from disk (needs `openat`), so it could not be sandboxed anyway.

## Packet handler audit

The parse thread runs packet handlers inline, so the filter also covers them.
Handlers that do file I/O or spawn subprocesses are the ones that trip a fatal
filter:

| Handler(s) | What it does | Seccomp impact |
|---|---|---|
| `open-url` | may spawn an opener via `subprocess.Popen` | Moved to the UI/main thread (`main_thread=True`) |
| `file-send`, `file-send-chunk` | open/write/unlink download files | Moved to the file worker thread (see below) |
| `file-ack-chunk` | compresses and sends the next outgoing chunk | Moved to the file worker thread |
| `file-data-response` | ACCEPT: hash/compress and send; OPEN: open a file/URL locally via `subprocess.Popen` | Hash/compress → worker thread; OPEN's `subprocess.Popen` → main thread |
| `file-request` (server) | reads a requested file from disk, then sends it | Moved to the file worker thread |
| `print-file` (server) | forwards a print job to clients (hash/compress) | Per-client send moved to the file worker thread |
| `print-devices` (server) | configures virtual printers, spawns `lpadmin` | Moved to the main thread (`main_thread=True`) |
| `command-start` (server) | starts a new command via `subprocess.Popen` | Moved to the main thread (`main_thread=True`) |
| `control-request` (server) | runs a control command (may fork/exec, do file I/O) | Moved to the main thread (`main_thread=True`) |
| `shell-exec` (server) | runs arbitrary Python (`exec`) - gated by `--shell` | Off by default; grants RCE when enabled (see below) |
| `challenge` | starts the auth worker (may fork/exec, read files) | Kept off-thread (`main_thread=True`) |
| `audio-data` / keepalive | sequencing + delegation to the audio subprocess | Safe on the parse thread |
| `encoding-set`, `server-event`, `logging-event` | update client state / log | Safe on the parse thread |
| `ping` | immediate `ping_echo` response | Kept on the parse thread deliberately |

Handlers already moved off the parse thread (onto the UI/main thread) include
`open-url`, `notification-*`, `file-data-request`, and the command-client
`display-*` / `shell-reply` handlers. With these moves, no handler that spawns a
subprocess or does file I/O runs inline on the parse thread - except `shell-exec`,
which is off by default and, when enabled with `--shell=yes`, hands the client
arbitrary code execution anyway (a far larger hole than any parse-thread syscall
gap): do not enable it on a sandboxed deployment.

### File worker thread

File transfers run their disk I/O (writing received files, reading files to send)
and CPU-heavy work (compression, hashing) on a dedicated daemon thread (`file-io`,
`xpra.net.file_transfer.FileTransferHandler`) rather than inline on the parse
thread. The handlers hand their work to `schedule_file_io()`, which queues it for
that thread:

* `file-send` / `file-send-chunk` - write received files to disk (`openat` /
  `write` / `unlink`);
* `file-ack-chunk` and `file-data-response` (ACCEPT) - compress / hash the
  outgoing data;
* `file-request` (server) - read the requested file from disk before sending it;
* `print-file` (server) - forward a print job to each client (hash / compress),
  scheduled on that client's worker.

The `file-data-response` OPEN fallback (open a file/URL at this end) instead uses
`GLib.idle_add` to run its `subprocess.Popen` on the main thread, mirroring
`open-url` - the worker thread stays a minimal disk/compression consumer and never
spawns subprocesses.

Together this keeps `openat` / `write` / `unlink` / `execve` off the parse thread,
which is what lets the parse allow-list drop file access (`PARSE_SYSCALLS`, above).

The thread is **started on demand** (on the first transfer that needs it) and,
crucially, **from the main thread** via `GLib.idle_add` - never from the parse
thread - because a thread inherits the seccomp filter of the thread that creates
it, so a worker spawned by a filtered parse thread would itself be unable to touch
the filesystem. On disconnect, `stop_file_io_thread()` queues an exit marker and
joins the thread, so any in-flight write completes before teardown
(`XPRA_FILE_IO_JOIN_TIMEOUT`, default 5s). Set `XPRA_FILE_IO_THREAD=0` to run the
work inline on the parse thread instead (the previous behaviour).

## Future work

* The parse allow-list now drops file access, but this has only been reasoned
  through statically - validate a real deployment in `log` mode
  (`XPRA_SECCOMP_PARSE_ACTION=log`) exercising all features (clipboard, mmap setup,
  audio, encodings), watch the audit log for any `openat` a first-time lazy import
  or mmap file setup still needs on the parse thread, and either pre-warm it or add
  it back. Only switch to `strict` (`kill_process`) after that. Two opt-in features
  must stay disabled under a fatal parse filter: `--shell` (arbitrary code
  execution) and `XPRA_SAVE_PRINT_JOBS` (debug write, still on the calling thread).
* The `rfb` read thread still keeps file access; its inline handlers have not been
  walked to move their file I/O off-thread. Lower priority than the main parse path.
