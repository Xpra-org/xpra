# ![Memory](../images/icons/server.png) Memory Usage

This document covers how much RAM an xpra session consumes, which
subsystems and codecs dominate the footprint, and the tunables that
trim it. It also explains how XShm shared memory is accounted for, so
you don't double-count it when comparing the X11 server (`Xorg`/Xdummy)
and the xpra server side by side.

For sizing the dummy X server's `VideoRam`, see [Xdummy](Xdummy.md).
For OpenGL applications, see also [OpenGL](OpenGL.md) — `vglrun` has a
significant memory impact on the X11 server side.

## Quick reference

- Resident set size (`RSS`) of the xpra server and `Xorg` is the
  primary metric.
- XShm segments are counted in **both** `Xorg` and `xpra` `RSS` (that's
  what shared memory means). Use `Pss` from
  `/proc/<pid>/smaps_rollup` — or subtract `RssShmem` from one side —
  to avoid double-counting.
- The biggest contributors, in rough order:
  1. The dummy X server framebuffer (sized by `VideoRam`,
     [Xdummy](Xdummy.md)).
  2. Software-GL backing pixmaps (Mesa under Xdummy) — eliminate with
     `vglrun`.
  3. GStreamer pipelines (audio/webcam).
  4. Loaded video codecs (NVENC, x264, vpx, …).
  5. Per-window XShm segments (≈ `width × height × bytes_per_pixel`
     each).

## Measuring a session

Every running xpra server now reports the data needed to size and
diagnose its own memory use through `xpra info`. No extra setup, no
authentication, no env vars.

```sh
xpra info :100 | grep -E '^(sys\.memory|display\.memory|display\.xshm|window\..*\.xshm)'
```

Key entries:

| Path | Meaning |
| --- | --- |
| `sys.memory.server.proc.rss` | RSS of the xpra server process |
| `sys.memory.server.proc.pss` | proportional set size (XShm-corrected) |
| `sys.memory.server.proc.rssanon` | anonymous heap (unique to this process) |
| `sys.memory.server.proc.rssshmem` | shared-memory pages (XShm + others) |
| `sys.memory.server.sysv_shm.bytes` | total SysV shared memory attached |
| `sys.memory.server.rusage.maxrss` | peak RSS (only with full auth) |
| `display.pid` | the dummy X server (`Xdummy`/`Xvfb`) pid |
| `display.memory.proc.rss` | RSS of the X server process |
| `display.memory.sysv_shm.bytes` | shared memory attached by the X server |
| `display.xshm-attached.bytes` | XShm bytes the xpra server has currently attached |
| `window.<wid>.xshm.bytes` | XShm bytes for a specific window |

The `display.xshm-attached` and `display.memory.sysv_shm` totals are
two views of the *same* segments — one counted in-process, one read
from `/proc/sysvipc/shm`. They should match.

### Leak hunting

Repeatedly poll `xpra info` and diff the relevant counters:

```sh
while true; do
    xpra info :100 |
        grep -E '^(sys\.memory\.server\.proc\.(rss|rssanon)|display\.xshm-attached\.bytes)'
    sleep 30
done
```

`rssanon` growth that isn't matched by visible UI activity is a
heap-side leak in the xpra server itself. Growth in
`display.xshm-attached.bytes` without matching window churn points at
an XShm wrapper that isn't being released.

`damage.ack-pending` and `damage.encoding-pending` per-window counters
already log warnings when they grow — but they're now also surfaced in
`xpra info` if you want to track them programmatically.

## Baseline numbers

Test rig: X11 seamless server (Fedora 43, Python 3.14, glibc malloc),
packaged `xorg.conf`, GTK3 Python client on the same host, single
`xterm` open, idle 30 s after connect, with
`XPRA_XDG=0 XPRA_IBUS=0` set on the server (see *Environment
variables* below). Absolute values vary substantially with
distribution, kernel, GLIBC malloc tuning, and the codec set
installed; treat these as indicative, not absolute.

| Process | RSS | VSZ | PSS |
| --- | --- | --- | --- |
| `Xorg` (Xdummy) | 107 MB | 998 MB | 79 MB |
| `xpra` server (idle, client connected) | **104 MB** | 2.3 GB | **78 MB** |
| `xpra` server (after `malloc_trim`) | 97 MB | 2.3 GB | — |
| Python GTK3 client | 220 MB | 4.2 GB | 138 MB |
| `xterm` | 13 MB | 241 MB | 7 MB |
| `pulseaudio` | 4 MB | 227 MB | <1 MB |
| `dbus` | 3 MB | 8 MB | <1 MB |
| `ibus-daemon` (only if `XPRA_IBUS!=0`) | 14 MB | 678 MB | 6 MB |

Notes:
- `xpra` server `rss_anon` is 60 MB (heap), `rss_file` 41 MB
  (shared library code mostly attributable elsewhere — `pss` is
  78 MB).
- The 220 MB client RSS is dominated by GTK + Pango + Cairo + Mesa
  shared libraries; `pss` of 138 MB is the more honest figure.
- If you compare `xpra` + `Xorg` `rss` naively (211 MB) you over-count
  XShm — see [XShm accounting](#xshm-accounting).
- Without `XPRA_XDG=0 XPRA_IBUS=0` the server-side `rss` rises by
  ~6 MB (freedesktop menu cache + IBus keymap), with no functional
  impact on a basic `xterm` session.

## Tunables

Each row is one option, toggled in isolation against the baseline. ΔRSS
columns show the saving (or cost) on the relevant process.

### Subsystems

Most of these default to `yes` (or `auto`). Disabling a subsystem
removes its mixin from the assembled server class
(`xpra/server/features.py`, `xpra/server/factory.py`).

Measured against an idle no-client baseline of **96 MB** server RSS
(with `XPRA_XDG=0 XPRA_IBUS=0`). Each flag is toggled in isolation;
deltas are not strictly additive (some subsystems share imports). One
sweep, ±0.5 MB noise floor on this host.

| Option                              | Default     | ΔRSS server | Notes                                                                |
|-------------------------------------|-------------|-------------|----------------------------------------------------------------------|
| `--audio=no`                        | yes         | −2 MB       | Skips GStreamer audio probe                                          |
| `--gstreamer=no`                    | yes         | −2 MB       | Implies `--audio=no`; also disables GStreamer video codecs           |
| `--clipboard=no`                    | yes         | ~0 MB       | Noise — the clipboard server itself is tiny at idle                  |
| `--notifications=no`                | yes         | −1 MB       |                                                                      |
| `--bell=no`                         | yes         | −4 MB       | Skips XFixes bell listener + dbus glue                               |
| `--cursors=no`                      | yes         | −1 MB       |                                                                      |
| `--dbus-control=no --dbus-launch=`  | yes (POSIX) | −6 MB       | Disables D-Bus control bus and the `--dbus-launch` daemon spawn      |
| `--mdns=no`                         | yes (POSIX) | −4 MB       | Skips Avahi/zeroconf service registration                            |
| `--http=no`                         | yes         | −6 MB       | Skips the embedded HTTP server (websocket upgrade path)              |
| `--webcam=no`                       | yes         | −6 MB       |                                                                      |
| `--printing=no`                     | yes         | −1 MB       |                                                                      |
| `--file-transfer=no`                | yes         | ~0 MB       | Noise                                                                |
| `--readonly`                        | no          | −7 MB       | Disables keyboard *and* pointer subsystems (skips IBus probing etc.) |
| **all of the above combined**       | —           | **−28 MB**  | "minimal-stack" — about a 30 % cut on top of the env-var savings     |

### Encodings and codecs

Codecs eagerly imported by `xpra/server/subsystem/encoding.py` are the
biggest *constant-cost* memory contributors after GStreamer. Restricting
the encoding set skips imports.

Same baseline conditions as the subsystems table above.

| Option                  | Default | ΔRSS server | Notes                                                                                  |
|-------------------------|---------|-------------|----------------------------------------------------------------------------------------|
| `--encoding=rgb`        | auto    | −2 MB       | Forces lossless; runtime selection only. The codec modules are still loaded.           |
| `--encodings=rgb,png`   | all     | −3 MB       | Restricts the encoder set; saves a little vs. defaults.                                |
| `--video=no`            | yes     | **−17 MB**  | Disables the video pipeline; skips x264/vpx/NVENC/AV1 imports entirely. Biggest win.   |
| `--video-encoders=none` | all     | −16 MB     | Finer-grained version of `--video=no` — almost identical effect.                       |
| `--csc-modules=none`    | all     | −6 MB      | Skips libyuv / swscale colorspace conversion modules. Useful with `--video-encoders=`. |

`XPRA_TARGET_LATENCY_TOLERANCE` and similar performance tuning knobs
do **not** affect RSS — don't chase phantom savings there.

### Environment variables

A few server-side env vars trim memory before any subsystem
loads — useful when you want a minimal session without changing
config files:

| Variable      | Effect                                                                                                                                                                   | ΔRSS server (measured)      |
|---------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------------|
| `XPRA_XDG=0`  | Skips freedesktop menu generation: no `xdg.IniFile` / `xdg.IconTheme` parsing, no per-app icon byte cache (~270 icons × ~10 KB held resident on default-config systems). | ~5 MB                       |
| `XPRA_IBUS=0` | Skips IBus keyboard mapping import + the `ibus-daemon` child process (which itself takes ~14 MB RSS)                                                                     | ~1 MB server + ~14 MB child |

Both are safe to set when the client doesn't need the application
menu and isn't using complex IME (CJK) input. They were used to
collect the [baseline numbers](#baseline-numbers) above.

### VirtualGL / `vglrun`

OpenGL applications under Xdummy use Mesa's `llvmpipe` software
rasterizer, which allocates large pixmaps on the X server side
(charged to Xdummy `VideoRam`). Wrapping the application in `vglrun`
moves the GL context to the host GPU and eliminates those pixmaps:

```sh
xpra start --start="vglrun glxgears"
# or:
xpra start --exec-wrapper=vglrun --start=glxgears
```

xpra recognizes `vglrun` as a command wrapper
(`xpra/server/subsystem/command.py:97`) so child-pid bookkeeping still
works.

| Test                                           | ΔRSS Xorg | ΔRSS client app | Notes                                                                 |
|------------------------------------------------|-----------|-----------------|-----------------------------------------------------------------------|
| `glxgears` (software GL) vs. `vglrun glxgears` | _TBD_     | _TBD_           | VirtualGL adds its own per-app overhead but moves the bulk off Xdummy |

See [OpenGL](OpenGL.md) for VirtualGL setup and caveats.

## XShm accounting

XShm (`MIT-SHM`) is a SysV shared memory segment created by xpra and
attached to **both** xpra (so the encoder reads pixels) and Xorg (so
the X server writes them). Size is approximately
`bytes_per_line × (height + 1)` per window.

Consequences:

- Naively summing `RSS(xpra) + RSS(Xorg)` overstates real memory
  consumption by the size of all attached XShm segments.
- The right comparison metric is `Pss` (proportional set size), which
  attributes each shared page proportionally. Both
  `sys.memory.server.proc.pss` and `display.memory.proc.pss` come from
  `/proc/<pid>/smaps_rollup`.
- Alternatively, subtract `rssshmem` from one side before summing.

Worked example: a 1920×1080 window at 32 bpp uses
`1920 × 4 × (1080 + 1) = 8 305 920` bytes of XShm. With XShm enabled,
that ~8 MB will appear in **both** Xorg's and xpra's `RSS`. A naive
`RSS(xpra) + RSS(Xorg)` count adds 16 MB; reality is 8 MB. Use:

```sh
xpra info :100 | grep -E '\.(pss|sysv_shm\.bytes)$'
```

## X11 server (`Xorg` / Xdummy) memory behaviour

- **The vfb's RSS stays high even after a client application
  terminates.** When an X11 client (Firefox, a game, …) exits, its
  pixmaps are freed back to the dummy driver's *internal* pool — not
  to the kernel. Subsequent clients reuse that pool, but the
  process's RSS does not shrink until you restart the X server.
  Plan `VideoRam` for *peak* observed pixmap usage, not steady-state.
- **That inflated RSS is swappable.** The dummy driver does not
  `mlock`/`mlock2` anything (verify with
  `cat /proc/<vfb-pid>/status | grep VmLck` — should be `0 kB`), and
  the kernel will page out idle Xdummy pages under memory pressure
  exactly like any other anonymous allocation. So if you're sizing
  `VideoRam` for a host without much physical RAM, the cost of the
  inflated steady-state is mostly *swap + latency on reconnect*, not
  RAM. A first damage event after a long idle may be slow as the
  kernel pages pixmaps back in, but capacity-wise the host doesn't
  need to keep all of `VideoRam` resident.

## References / further reading

- The Linux `proc(5)` manual page documents
  `/proc/<pid>/status` (`VmRSS`, `RssAnon`, `RssShmem`, …) and
  `/proc/<pid>/smaps_rollup` (`Pss`, `Shared_*`, `Private_*`, `Swap`).
- `/proc/sysvipc/shm` lists every SysV shared memory segment on the
  host with creator/last-attach pids. xpra parses this for
  `sysv_shm` accounting.
- [`xf86-video-dummy`](https://github.com/Xpra-org/xf86-video-dummy)
  README describes the semantics of `VideoRam` in the dummy driver.
- [VirtualGL documentation](https://github.com/VirtualGL/virtualgl/tree/master/doc)
  for `vglrun` setup.
- [OpenGL.md](OpenGL.md) — xpra's OpenGL configuration matrix.
- [Xdummy.md](Xdummy.md) — sizing the dummy X server's framebuffer.

## Developer notes

`XPRA_MEMORY_DEBUG=1` (with optional `XPRA_MEMORY_DEBUG_INTERVAL=<ms>`,
default 5000) on the server starts a background thread that logs
psutil `memory_full_info()` deltas at INFO level. Intended for leak
hunting during development; not a CLI option on purpose.
