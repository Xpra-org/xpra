# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

import os
from typing import Any

from xpra.server.subsystem.stub import StubServerMixin
from xpra.util.debug import CPUINFO, init_leak_detection
from xpra.util.objects import typedict
from xpra.log import Logger

log = Logger("network")


class DebugServer(StubServerMixin):
    """
    Mixin for system state debugging, leak detection (file descriptors, memory)
    """

    def __init__(self):
        StubServerMixin.__init__(self)
        self.mem_bytes = 0
        self.cpu_info: dict = {}

    def init(self, opts) -> None:
        self.init_cpuinfo()

    def setup(self) -> None:
        def is_closed() -> bool:
            return getattr(self, "_closing", False)

        init_leak_detection(is_closed)
        from xpra.util.meminfo import maybe_start_memory_debug
        maybe_start_memory_debug()
        self.args_control(
            "debug-memory",
            "snapshot Python heap (gc + tracemalloc top sites). "
            "args: [top_n=20] [trim=no|yes]",
            max_args=2,
        )

    def get_info(self, _source=None) -> dict[str, Any]:
        info = {}
        if self.mem_bytes:
            info["total-memory"] = self.mem_bytes
        if self.cpu_info:
            info["cpuinfo"] = {k: v for k, v in self.cpu_info.items() if k != "python_version"}
        return info

    def control_command_debug_memory(self, top_n: str = "30", trim: str = "no") -> str:
        """Snapshot the Python heap and (optionally) call `malloc_trim(0)`.

        Heavy work runs in a background thread and the full report is
        written to `/tmp/xpra-debug-memory-<pid>-<ts>.txt`. The control
        command returns immediately with the path so the client doesn't
        time out while `tracemalloc.take_snapshot()` is computing.

        For full call-frame attribution start the server with
        `PYTHONTRACEMALLOC=10` (or higher).
        """
        try:
            n = max(1, min(200, int(top_n)))
        except (TypeError, ValueError):
            n = 30
        do_trim = str(trim).lower() in ("1", "yes", "true", "on")

        import time
        path = f"/tmp/xpra-debug-memory-{os.getpid()}-{int(time.time())}.txt"

        from xpra.util.thread import start_thread
        start_thread(
            self._debug_memory_snapshot, "debug-memory-snapshot",
            daemon=True, args=(path, n, do_trim),
        )
        return f"snapshotting heap to {path} (in background; tracemalloc may take ~10s)"

    def _debug_memory_snapshot(self, path: str, n: int, do_trim: bool) -> None:
        from xpra.util.meminfo import get_proc_mem
        lines: list[str] = [f"# memory snapshot for pid {os.getpid()}"]

        # 1. process memory
        try:
            m = get_proc_mem()
            for k in ("rss", "pss", "vms", "rssanon", "rssfile", "rssshmem"):
                if k in m:
                    lines.append(f"  {k:10s}={m[k] / 1024 / 1024:8.1f} MB")
        except Exception as e:
            lines.append(f"meminfo unavailable: {e}")

        # 2. gc stats + top object types
        import gc
        gc.collect()
        lines.append("")
        lines.append("# gc.get_stats():")
        for i, gen in enumerate(gc.get_stats()):
            lines.append(f"  gen{i}: collections={gen.get('collections', 0)} "
                         f"collected={gen.get('collected', 0)} "
                         f"uncollectable={gen.get('uncollectable', 0)}")
        try:
            objs = gc.get_objects()
        except Exception as e:
            objs = ()
            lines.append(f"# gc.get_objects() failed: {e}")
        lines.append(f"# gc.get_objects(): {len(objs)} live objects")
        if objs:
            counts: dict[str, int] = {}
            for o in objs:
                t = type(o).__name__
                counts[t] = counts.get(t, 0) + 1
            top = sorted(counts.items(), key=lambda kv: -kv[1])[:n]
            lines.append(f"# top {len(top)} types by count:")
            for name, c in top:
                lines.append(f"  {c:>10d}  {name}")

        # 3. tracemalloc top allocation sites
        try:
            import tracemalloc
            if tracemalloc.is_tracing():
                snap = tracemalloc.take_snapshot()
                all_stats = snap.statistics("lineno")
                total = sum(s.size for s in all_stats)
                stats = all_stats[:n]
                lines.append("")
                lines.append(f"# tracemalloc: total tracked={total / 1024 / 1024:.1f} MB "
                             f"in {len(all_stats)} sites "
                             f"(showing top {len(stats)})")
                for s in stats:
                    frame = s.traceback[0]
                    lines.append(f"  {s.size / 1024:>10.1f} KB  {s.count:>7d}x  "
                                 f"{frame.filename}:{frame.lineno}")
                # Also group by file (sum across all lines):
                lines.append("")
                lines.append(f"# tracemalloc: top {n} files by total size:")
                by_file: dict[str, tuple[int, int]] = {}
                for s in all_stats:
                    f = s.traceback[0].filename
                    sz, cnt = by_file.get(f, (0, 0))
                    by_file[f] = (sz + s.size, cnt + s.count)
                for fname, (sz, cnt) in sorted(by_file.items(), key=lambda kv: -kv[1][0])[:n]:
                    lines.append(f"  {sz / 1024 / 1024:>8.2f} MB  {cnt:>8d}x  {fname}")
            else:
                lines.append("")
                lines.append("# tracemalloc not active — start with PYTHONTRACEMALLOC=10")
        except ImportError:
            lines.append("# tracemalloc unavailable")

        # 4. optional malloc_trim
        if do_trim:
            lines.append("")
            try:
                import ctypes
                libc = ctypes.CDLL("libc.so.6")
                before = get_proc_mem().get("rss", 0)
                released = libc.malloc_trim(0)
                after = get_proc_mem().get("rss", 0)
                lines.append(
                    f"# malloc_trim(0) returned {released}; "
                    f"RSS {before / 1024 / 1024:.1f} -> {after / 1024 / 1024:.1f} MB "
                    f"(Δ {(before - after) / 1024 / 1024:+.1f} MB)"
                )
            except Exception as e:
                lines.append(f"# malloc_trim failed: {e}")

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
                f.write("\n")
            log.info("debug-memory snapshot written to %s", path)
        except OSError as e:
            log.error("failed to write debug-memory snapshot to %s: %s", path, e)

    def init_cpuinfo(self) -> None:
        if not CPUINFO:
            return
        # this crashes if not run from the UI thread!
        try:
            from cpuinfo import get_cpu_info
        except ImportError as e:
            log("no cpuinfo: %s", e)
            return
        self.cpu_info = get_cpu_info()
        if self.cpu_info:
            c = typedict(self.cpu_info)
            count = c.intget("count", 0)
            brand = c.strget("brand")
            if count > 0 and brand:
                log.info("%ix %s", count, brand)
