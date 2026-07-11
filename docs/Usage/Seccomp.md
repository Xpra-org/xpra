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
| `draw` | picture / video decoding | compressed image and video frames |
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
| `default` | enable all three filters with a **non-fatal** action: a blocked syscall fails with a permission error instead of killing anything |
| `strict` | enable all three filters with a **fatal** action: a blocked syscall kills the whole process |
| a list | enable only the listed threads, ie `draw`, `parse`, `rfb` |

The list form lets you pick individual filters and, optionally, an action per
filter (see [actions](#actions) below):

```shell
# only sandbox the image decoding thread:
xpra attach ... --seccomp=draw

# sandbox decoding and network parsing:
xpra attach ... --seccomp=draw,parse

# decoding is fatal on violation, network parsing only fails the call:
xpra attach ... --seccomp=draw:kill,parse:errno
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

* **Debug image dumping** (`XPRA_SAVE_TO_FILE`) writes frames to disk from the
  decoding thread, so it is automatically turned off (with a warning) whenever
  seccomp is enabled.

* **Codec self-test** must stay enabled (it is, by default). Xpra pre-loads and
  pre-warms every decoder at startup *before* the sandbox is installed; running
  with `XPRA_CODEC_SELFTEST=0` removes that step and is incompatible with the
  `draw` filter.

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
| `XPRA_SECCOMP_DRAW` | enable/disable the decoding filter |
| `XPRA_SECCOMP_PARSE` | enable/disable the network parse filter |
| `XPRA_SECCOMP_RFB` | enable/disable the VNC client filter |
| `XPRA_SECCOMP_DRAW_ACTION` | action for the decoding filter |
| `XPRA_SECCOMP_PARSE_ACTION` | action for the parse filter |
| `XPRA_SECCOMP_RFB_ACTION` | action for the VNC client filter |

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
`xpra/seccomp/_native`. The primitive `install_filter(syscalls, action)` sets
`PR_SET_NO_NEW_PRIVS`, initialises the filter with the chosen default action, adds
one `SCMP_ACT_ALLOW` rule per allowed syscall, and loads it. The Python side lives
in `xpra/seccomp/`:

* `xpra/seccomp/draw.py` - decoding thread, installed at the top of the draw loop
  (`xpra/client/subsystem/window/draw.py`).
* `xpra/seccomp/parse.py` - network parse thread, installed at the top of
  `_read_parse_thread_loop` (`xpra/net/protocol/socket_handler.py`), and only for
  real network sockets.
* `xpra/seccomp/rfb.py` - RFB client read thread, installed once the handshake
  reaches steady state (`xpra/client/base/rfb_protocol.py`).

The `--seccomp` option is turned into the `XPRA_SECCOMP*` environment variables by
`parse_seccomp_option()` / `configure_seccomp()` in `xpra/scripts/main.py`. This
runs in `run_mode` right after `configure_env`, before the client / server object
and its threads are created, and only sets variables that are not already defined.
The list form deliberately does **not** set the global `XPRA_SECCOMP` flag: the
draw filter reads it as its primary gate, so setting it would override the
per-thread flags.

**Thread inheritance.** A seccomp filter is inherited by every thread created
*after* it is loaded, so a filter also covers any worker thread its host thread
spawns. To keep a handler *out* of the sandbox it must run on a thread that is not
a descendant of the filtered thread - in practice, register its packet handler
with `main_thread=True` so it is dispatched on the GLib main loop (which predates
the parse thread's filter). This is how the `challenge` handler stays unsandboxed:
auth backends may `fork`/`exec` a helper (kerberos/gss/exec/u2f/pinentry) or read
files, so `_process_challenge` runs on the main thread.

## Syscall lists

`xpra/seccomp/draw.py` defines a permissive `BASE_SYSCALLS` baseline. From it:

* the **draw** allow-list (`DRAW_SYSCALLS`) removes the file-namespace syscalls
  (`FILE_SYSCALLS`: `open`, `openat`, `unlink`, `unlinkat`, `mkdir`, `rename`,
  `renameat*`, `ftruncate`, `fallocate`). The draw thread only decodes images that
  are already in memory, so it never needs to open, create or delete a file -
  *provided* its decoders are already loaded and pre-warmed. That pre-warming is
  the codec self-test (`XPRA_CODEC_SELFTEST`, on by default), which runs a real
  decode of each codec on the loader thread at startup, triggering PIL's lazy
  plugin imports and any `dlopen` of codec libraries *before* the draw thread
  starts. Hardware decoders (which would `dlopen` CUDA etc. on the draw thread) are
  separately disabled under seccomp via `xpra/client/subsystem/encoding.py`.
* the **parse** and **rfb** allow-lists keep the full `BASE_SYSCALLS` (including
  `open`/`openat`) plus a few socket-introspection syscalls (`recvfrom`,
  `getsockname`, `getsockopt`, `sysinfo`). They dispatch many packet handlers
  inline with a much larger lazy-import surface, so tightening them is deferred
  (validate in `log` mode first).

**`kill_process` caveat:** a blocked lazy `import` or `dlopen` is a `SIGSYS`
process kill, not a catchable exception - `log.trap_error` cannot recover from it.
This is why the pre-warm above matters, and why the debug file-dump
(`get_save_to_file()` in `xpra/codecs/debug.py`) is disabled under seccomp.

## Thread coverage

Two threads carry a filter today - **draw** and **parse** - plus the client-side
**rfb** thread. The rest of the thread inventory, and why each is or is not
sandboxed:

| Thread | Untrusted input? | Decision |
|---|---|---|
| **draw / decode** | Yes: compressed images/video | **Sandboxed** (`seccomp/draw.py`) |
| **network parse** | Yes: raw socket bytes | **Sandboxed**, network sockets only (`seccomp/parse.py`) |
| **RFB read** (client) | Yes: framebuffer parsing | **Sandboxed** at steady state (`seccomp/rfb.py`) |
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
`clipboard-token`: jpeg goes to the already-sandboxed draw thread, `challenge` is
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
| `open-url` | may spawn an opener via `subprocess.Popen` | Blocker under a fatal action |
| `file-send`, `file-send-chunk`, `file-data-response` | open/write/unlink download files, may start a print/open worker | Blockers under a fatal action |
| `challenge` | starts the auth worker (may fork/exec, read files) | Kept off-thread (`main_thread=True`) |
| `audio-data` / keepalive | sequencing + delegation to the audio subprocess | Safe on the parse thread |
| `encoding-set`, `server-event`, `logging-event` | update client state / log | Safe on the parse thread |
| `ping` | immediate `ping_echo` response | Kept on the parse thread deliberately |

Handlers already moved off the parse thread (onto the UI/main thread) include
`notification-*`, `file-data-request`, and the command-client `display-*` /
`shell-reply` handlers.

## Future work

* Draw thread: initialise video decoders from the draw thread so decoder worker
  threads and the filter have a well-defined ordering.
* Parse thread: walk the remaining inline handlers with
  `XPRA_SECCOMP_PARSE_ACTION=errno` and, per handler, either allow a benign
  read-only syscall or move privileged work (subprocess/file I/O, ie `open-url`,
  `file-send`) off-thread with `main_thread=True`. `ping` and the file data-plane
  handlers stay on the parse thread to avoid contention.
* Tighten the parse / rfb allow-lists to drop file access, once their lazy-import
  surface has been validated in `log` mode.
