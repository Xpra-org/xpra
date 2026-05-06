#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Phase-A baseline-measurement helper for `docs/Usage/Memory.md`.

Run this on a host with an xpra X11 seamless server already running and
(optionally) a Python client connected. It samples and prints a fixed
table of memory counters for the server, the dummy X server, and any
connected client process.

Usage:
    tests/perf/memory_baseline.py --display :100
    tests/perf/memory_baseline.py --display :100 --client-pid <pid>
    tests/perf/memory_baseline.py --display :100 --label "encoding=rgb"

Output is intended to be pasted into the "Baseline numbers" or
"Tunables" tables of `docs/Usage/Memory.md`. Run multiple
configurations (with and without each tunable) and diff manually.

The script does NOT spawn or stop xpra — it just measures whatever is
already running. Keep that responsibility separate so this works
identically against system, packaged, or development builds.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any

# allow running from a checkout without installing:
sys.path.insert(0, ".")

from xpra.util.meminfo import get_mem_info  # noqa: E402


COLUMNS = (
    "rss", "vms", "pss", "uss",
    "rssanon", "rssfile", "rssshmem",
    "shared_clean", "shared_dirty",
    "private_clean", "private_dirty",
    "swap",
)


def fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    units = ("KB", "MB", "GB")
    v = float(n)
    for u in units:
        v /= 1024
        if v < 1024:
            return f"{v:.1f} {u}"
    return f"{v:.1f} TB"


def get_xpra_info(display: str) -> dict[str, Any]:
    proc = subprocess.run(
        ["xpra", "info", display],
        capture_output=True, text=True, check=False, timeout=15,
    )
    if proc.returncode != 0:
        raise SystemExit(f"xpra info {display} failed: {proc.stderr.strip()}")
    out: dict[str, Any] = {}
    for line in proc.stdout.splitlines():
        key, _, value = line.partition("=")
        if not key:
            continue
        out[key.strip()] = value.strip()
    return out


def find_server_pid(info: dict[str, Any]) -> int:
    # `server.pid` is reported by the daemon subsystem.
    for k in ("server.pid", "pid"):
        if k in info:
            try:
                return int(info[k])
            except ValueError:
                continue
    return 0


def find_vfb_pid(info: dict[str, Any]) -> int:
    for k in ("display.pid", "display.display.pid"):
        if k in info:
            try:
                return int(info[k])
            except ValueError:
                continue
    return 0


def find_child_pids(info: dict[str, Any]) -> dict[str, int]:
    """Return {label: pid} for every `child.N.pid` / `command.N.pid` and
    standalone `<service>.pid` (dbus, ibus, ...) reported by the server.
    Labels are derived from the matching `<prefix>.command` (basename
    of argv[0]) when available, otherwise from the key prefix."""
    out: dict[str, int] = {}
    seen: set[int] = set()
    standalone = {"dbus", "ibus", "pulseaudio"}
    for key, value in info.items():
        if not key.endswith(".pid"):
            continue
        prefix = key[:-len(".pid")]
        is_child = key.startswith("child.") or key.startswith("command.")
        is_standalone = "." not in prefix and prefix in standalone
        if not (is_child or is_standalone):
            continue
        try:
            pid = int(value)
        except ValueError:
            continue
        if pid <= 0 or pid in seen:
            continue
        seen.add(pid)
        cmd = info.get(f"{prefix}.command", "")
        label = prefix
        if cmd:
            # `command` values are tuple-ish strings: '/usr/bin/foo', '...'
            first = cmd.split(",", 1)[0].strip().strip("'\"")
            if first:
                base = first.rsplit("/", 1)[-1]
                if base.startswith("python") and "," in cmd:
                    second = cmd.split(",", 2)[1].strip().strip(" '\"")
                    if second:
                        base = second.rsplit("/", 1)[-1]
                label = f"{prefix}:{base}"
        out[label] = pid
    return out


def print_row(label: str, mem: dict[str, int]) -> None:
    cells = [label.ljust(20)]
    for col in COLUMNS:
        v = mem.get(col, 0)
        cells.append(fmt_bytes(v).rjust(10))
    print(" ".join(cells))


def print_header() -> None:
    cells = ["process".ljust(20)]
    for col in COLUMNS:
        cells.append(col.rjust(10))
    print(" ".join(cells))
    print("-" * len(" ".join(cells)))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--display", required=True, help="display, e.g. :100")
    p.add_argument("--client-pid", type=int, default=0,
                   help="optional Python client pid to also sample")
    p.add_argument("--label", default="", help="annotate the run (printed first)")
    p.add_argument("--json", action="store_true",
                   help="emit raw JSON instead of the table")
    p.add_argument("--no-children", action="store_true",
                   help="skip server-spawned child processes (xterm, dbus, ibus, ...)")
    args = p.parse_args()

    info = get_xpra_info(args.display)
    server_pid = find_server_pid(info)
    vfb_pid = find_vfb_pid(info)

    samples: dict[str, dict[str, int]] = {}
    seen: set[int] = set()
    if server_pid:
        samples["xpra-server"] = get_mem_info(server_pid)["proc"]
        seen.add(server_pid)
    if vfb_pid:
        samples["xorg-vfb"] = get_mem_info(vfb_pid)["proc"]
        seen.add(vfb_pid)
    if args.client_pid:
        samples["python-client"] = get_mem_info(args.client_pid)["proc"]
        seen.add(args.client_pid)
    if not args.no_children:
        for label, pid in find_child_pids(info).items():
            if pid in seen:
                continue
            seen.add(pid)
            try:
                samples[label] = get_mem_info(pid)["proc"]
            except Exception:
                continue

    if args.json:
        out = {
            "label": args.label,
            "display": args.display,
            "pids": {"server": server_pid, "vfb": vfb_pid, "client": args.client_pid},
            "samples": samples,
        }
        print(json.dumps(out, indent=2))
        return 0

    if args.label:
        print(f"# {args.label}")
    print(f"# display={args.display} server={server_pid or '?'} "
          f"vfb={vfb_pid or '?'} client={args.client_pid or '-'}")
    print_header()
    for name, mem in samples.items():
        print_row(name, mem)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
