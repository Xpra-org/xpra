# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Process memory and SysV shared memory accounting helpers.

Used to populate the `memory.*` keys of `xpra info` so users can size
sessions and chase leaks without having to attach a debugger or scrape
`/proc` by hand. Linux is the primary target; on other platforms we
fall back to whatever `psutil` exposes.
"""

import os

from xpra.util.io import get_util_logger

PROC_STATUS_KEYS = (
    "VmPeak", "VmSize", "VmHWM", "VmRSS",
    "VmData", "VmStk", "VmExe", "VmLib", "VmPTE", "VmSwap",
    "RssAnon", "RssFile", "RssShmem",
)


def _parse_kb_field(value: str) -> int:
    # `/proc/<pid>/status` reports memory in kB:  "1234 kB"
    parts = value.strip().split()
    if not parts:
        return 0
    try:
        n = int(parts[0])
    except ValueError:
        return 0
    if len(parts) > 1 and parts[1].lower() == "kb":
        return n * 1024
    return n


def _read_proc_status(pid: int) -> dict[str, int]:
    out: dict[str, int] = {}
    try:
        with open(f"/proc/{pid}/status", "r", encoding="utf-8") as f:
            for line in f:
                key, _, rest = line.partition(":")
                if key in PROC_STATUS_KEYS:
                    out[key] = _parse_kb_field(rest)
    except OSError:
        pass
    return out


def _read_smaps_rollup(pid: int) -> dict[str, int]:
    # Linux 4.14+. Cheap aggregate; no per-mapping iteration.
    keys = ("Rss", "Pss", "Shared_Clean", "Shared_Dirty",
            "Private_Clean", "Private_Dirty", "Swap")
    out: dict[str, int] = {}
    try:
        with open(f"/proc/{pid}/smaps_rollup", "r", encoding="utf-8") as f:
            for line in f:
                key, _, rest = line.partition(":")
                if key in keys:
                    out[key.lower()] = _parse_kb_field(rest)
    except OSError:
        pass
    return out


def get_proc_mem(pid: int = 0) -> dict[str, int]:
    """
    Return a flat dict of memory counters in bytes for the given pid
    (defaults to the current process). Combines `psutil.memory_full_info`
    with `/proc/<pid>/status` and `/proc/<pid>/smaps_rollup` so callers
    can disentangle anonymous heap (`rss_anon`) from XShm-style shared
    pages (`rss_shmem`) without parsing anything themselves.
    """
    if pid <= 0:
        pid = os.getpid()
    info: dict[str, int] = {}
    try:
        import psutil
        try:
            mem = psutil.Process(pid).memory_full_info()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            mem = None
        if mem is not None:
            for attr in ("rss", "vms", "shared", "text", "data",
                         "lib", "dirty", "uss", "pss", "swap"):
                value = getattr(mem, attr, None)
                if value is not None:
                    info[attr] = int(value)
    except ImportError:
        pass
    # Linux-specific fields psutil doesn't expose:
    for k, v in _read_proc_status(pid).items():
        info[k.lower()] = v
    for k, v in _read_smaps_rollup(pid).items():
        # may overwrite psutil's "pss"/"swap"; smaps_rollup wins (more accurate)
        info[k] = v
    return info


def get_sysv_shm(pid: int = 0) -> dict[str, int]:
    """
    Sum all SysV shared-memory segments either created or last attached
    by `pid` (`cpid`/`lpid` in `/proc/sysvipc/shm`). Used for XShm
    accounting — psutil does not expose this.
    """
    if pid <= 0:
        pid = os.getpid()
    segments = 0
    total = 0
    try:
        with open("/proc/sysvipc/shm", "r", encoding="utf-8") as f:
            header = f.readline().split()
            try:
                size_idx = header.index("size")
                cpid_idx = header.index("cpid")
                lpid_idx = header.index("lpid")
            except ValueError:
                return {"segments": 0, "bytes": 0}
            for line in f:
                fields = line.split()
                if len(fields) <= max(size_idx, cpid_idx, lpid_idx):
                    continue
                try:
                    cpid = int(fields[cpid_idx])
                    lpid = int(fields[lpid_idx])
                    if cpid != pid and lpid != pid:
                        continue
                    total += int(fields[size_idx])
                    segments += 1
                except ValueError:
                    continue
    except OSError:
        pass
    return {"segments": segments, "bytes": total}


def get_mem_info(pid: int = 0) -> dict[str, dict[str, int]]:
    """Convenience wrapper combining proc and sysv shm under one dict."""
    return {
        "proc": get_proc_mem(pid),
        "sysv_shm": get_sysv_shm(pid),
    }


def maybe_start_memory_debug() -> None:
    """If `XPRA_MEMORY_DEBUG` is set, start the periodic mem watcher.

    The interval is `XPRA_MEMORY_DEBUG_INTERVAL` ms (default 5000).
    Developer-targeted; intentionally not exposed as a CLI option.
    """
    from xpra.util.env import envint, envbool
    if not envbool("XPRA_MEMORY_DEBUG", False):
        return
    interval = envint("XPRA_MEMORY_DEBUG_INTERVAL", 5000)
    try:
        from xpra.util.pysystem import start_mem_watcher
        start_mem_watcher(interval)
    except Exception:
        get_util_logger().error("failed to start memory debug watcher", exc_info=True)
