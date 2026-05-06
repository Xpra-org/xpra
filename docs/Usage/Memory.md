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

> *Numbers below are placeholders — to be filled in once the Phase A
> measurement run is complete on a known reference machine. They are
> indicative; absolute values vary substantially with distribution,
> kernel, GLIBC malloc tuning, and codec set installed.*

Test rig: X11 seamless server, packaged `xorg.conf`, GTK3 Python
client on the same host, single `xterm` open, idle 30 s.

| Process | RSS | VSZ | PSS |
| --- | --- | --- | --- |
| `Xorg` (Xdummy) | _TBD_ | _TBD_ | _TBD_ |
| `xpra` server | _TBD_ | _TBD_ | _TBD_ |
| Python GTK3 client | _TBD_ | _TBD_ | _TBD_ |

## Tunables

Each row is one option, toggled in isolation against the baseline. ΔRSS
columns show the saving (or cost) on the relevant process.

### Subsystems

Most of these default to `yes` (or `auto`). Disabling a subsystem
removes its mixin from the assembled server class
(`xpra/server/features.py`, `xpra/server/factory.py`).

| Option | Default | ΔRSS server | ΔRSS client | Notes |
| --- | --- | --- | --- | --- |
| `--audio=no` | yes | _TBD_ | _TBD_ | Skips GStreamer initialization |
| `--gstreamer=no` | yes | _TBD_ | — | Implies `--audio=no` and disables webcam GStreamer pipelines |
| `--clipboard=no` | yes | _TBD_ | _TBD_ | |
| `--notifications=no` | yes | _TBD_ | — | |
| `--bell=no` | yes | _TBD_ | — | |
| `--cursors=no` | yes | _TBD_ | — | |
| `--dbus=no` | yes (POSIX) | _TBD_ | — | Also disables power, idle-timeout, suspend glue |
| `--mdns=no` | yes (POSIX) | _TBD_ | — | |
| `--http=no` | yes | _TBD_ | — | |
| `--webcam=no` | yes | _TBD_ | — | |
| `--printing=no` | yes | _TBD_ | — | |
| `--file-transfer=no` | yes | _TBD_ | — | |
| `--readonly` | no | _TBD_ | — | Disables keyboard *and* pointer subsystems |

### Encodings and codecs

Codecs eagerly imported by `xpra/server/subsystem/encoding.py` are the
biggest *constant-cost* memory contributors after GStreamer. Restricting
the encoding set skips imports.

| Option | Default | ΔRSS server | Notes |
| --- | --- | --- | --- |
| `--encoding=rgb` | auto | _TBD_ | Forces lossless; skips JPEG/WebP/AVIF and video codecs |
| `--encodings=rgb,png` | all | _TBD_ | Same as above but allows PNG fallbacks |
| `--video=no` | yes | _TBD_ | Disables the video pipeline; skips x264/vpx/NVENC |
| `--video-encoders=none` | all | _TBD_ | Finer-grained version of the above |
| `--csc-modules=none` | all | _TBD_ | Skips colorspace conversion modules |

`XPRA_TARGET_LATENCY_TOLERANCE` and similar performance tuning knobs
do **not** affect RSS — don't chase phantom savings there.

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

| Test | ΔRSS Xorg | ΔRSS client app | Notes |
| --- | --- | --- | --- |
| `glxgears` (software GL) vs. `vglrun glxgears` | _TBD_ | _TBD_ | VirtualGL adds its own per-app overhead but moves the bulk off Xdummy |

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
