#!/usr/bin/env python3
# ABOUTME: Ranks xpra functions by how much a type annotation would pay off,
# ABOUTME: for Cython runtime validation (--with-cythonize_more) and downstream strictness.

# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Find the highest-value places to add type annotations.

Two payoffs are scored (see the strategy in the commit that adds this file):

* payoff A - *runtime* validation: in a module compiled with
  ``--with-cythonize_more`` (see the ``ax()``/``ace()`` block in setup.py),
  Cython's ``annotation_typing`` (default True) turns a ``def`` argument
  annotated with a *concrete builtin* type (str/bytes/int/float/bool/dict/
  list/tuple/set/bytearray) into a real runtime ``TypeError`` guard. Only
  concrete builtins enforce; generics, ``X | None`` and custom classes stay
  ``object``. So payoff A only exists for modules in the cythonize_more set,
  and only for concrete-builtin *argument* annotations.

* payoff B - downstream strictness: tightening a loose return type
  (``Any``, bare ``dict``/``list``/``tuple``, ``X | None`` that is never None)
  lets callers drop defensive ``.get()``/``is None`` scaffolding. Works for any
  module, cythonized or not.

The tool never edits anything; it emits a ranked list to drive the work.

Usage:
    python3 tests/scripts/find_annotation_candidates.py            # ranked summary
    python3 tests/scripts/find_annotation_candidates.py --top 40   # top N functions
    python3 tests/scripts/find_annotation_candidates.py --package xpra/net/protocol
    python3 tests/scripts/find_annotation_candidates.py --csv > candidates.csv
"""

import ast
import os
import sys
import argparse
from collections import defaultdict

# Repo root = two levels up from tests/scripts/
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# --- cythonize_more membership -------------------------------------------------
# Mirror of the ax()/ace() calls in setup.py's `if cythonize_more_ENABLED:` block.
# ax("pkg") compiles pkg/*.py NON-recursively; ace("mod") compiles a single module.
# Keep this list in sync with setup.py (grep: 'ax("' / 'ace("' under cythonize_more).
CYTHONIZE_MORE_PACKAGES = {
    "xpra.auth", "xpra.cairo", "xpra.challenge",
    "xpra.client.base", "xpra.client.gtk3", "xpra.client.gtk3.opengl",
    "xpra.client.gtk3.subsystem", "xpra.client.gtk3.window", "xpra.client.gui",
    "xpra.client.gui.window", "xpra.client.pyglet", "xpra.client.qt6",
    "xpra.client.subsystem", "xpra.client.subsystem.window", "xpra.client.tk",
    "xpra.client.win32", "xpra.client.win32.subsystem",
    "xpra.clipboard", "xpra.codecs", "xpra.codecs.dmabuf", "xpra.codecs.pillow",
    "xpra.codecs.pillow.decoder", "xpra.codecs.pillow.encoder", "xpra.codecs.remote",
    "xpra.gstreamer", "xpra.gtk", "xpra.gtk.configure", "xpra.gtk.dialogs",
    "xpra.gtk.examples", "xpra.keyboard", "xpra.net", "xpra.net.ayncio",
    "xpra.net.control", "xpra.net.http", "xpra.net.mdns", "xpra.net.mmap",
    "xpra.net.protocol", "xpra.net.quic", "xpra.net.rdp", "xpra.net.rfb",
    "xpra.net.ssh", "xpra.net.ssh.paramiko", "xpra.net.tls", "xpra.net.websockets",
    "xpra.net.websockets.headers", "xpra.notification", "xpra.opengl", "xpra.scripts",
    "xpra.server", "xpra.server.dbus", "xpra.server.encoder", "xpra.server.proxy",
    "xpra.server.rdp", "xpra.server.rfb", "xpra.server.runner", "xpra.server.shadow",
    "xpra.server.source", "xpra.server.subsystem", "xpra.server.window",
    "xpra.uinput", "xpra.util", "xpra.wayland.client", "xpra.wayland.server",
    "xpra.x11", "xpra.x11.desktop", "xpra.x11.gtk",
    "xpra.x11.models", "xpra.x11.server", "xpra.x11.subsystem", "xpra.x11.uinput",
}
CYTHONIZE_MORE_MODULES = {
    "xpra.common", "xpra.exit_codes", "xpra.gtk.dialogs.qrcode", "xpra.log",
    "xpra.os_util", "xpra.platform.dotxpra_common", "xpra.platform.paths",
    "xpra.platform.posix.shadow_server", "xpra.platform.win32.service",
    "xpra.platform.win32.shadow", "xpra.util.ui_thread_watcher",
}


def module_dotted(relpath: str) -> str:
    return relpath[:-3].replace(os.path.sep, ".")


def in_cythonize_more(relpath: str) -> bool:
    mod = module_dotted(relpath)
    if mod in CYTHONIZE_MORE_MODULES:
        return True
    parent = mod.rsplit(".", 1)[0]          # ax() is non-recursive: only direct parent counts
    return parent in CYTHONIZE_MORE_PACKAGES


# --- concrete-builtin inference from default values ----------------------------
CONCRETE_BUILTINS = {"int", "str", "bytes", "bytearray", "bool", "float", "dict", "list", "tuple", "set"}


def builtin_from_default(node) -> str:
    """If a default value literal reveals a concrete builtin type, return its name."""
    if node is None:
        return ""
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bool):     # bool before int: bool is a subclass of int
            return "bool"
        if isinstance(v, int):
            return "int"
        if isinstance(v, float):
            return "float"
        if isinstance(v, str):
            return "str"
        if isinstance(v, bytes):
            return "bytes"
        return ""
    if isinstance(node, ast.Dict):
        return "dict"
    if isinstance(node, (ast.List, ast.ListComp)):
        return "list"
    if isinstance(node, ast.Tuple):
        return "tuple"
    if isinstance(node, (ast.Set, ast.SetComp)):
        return "set"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in CONCRETE_BUILTINS:
        return node.func.id
    return ""


# lower-confidence: argument name strongly suggests a concrete builtin
NAME_HINTS = {
    "int": {"wid", "width", "height", "stride", "depth", "bpp", "size", "count", "length", "port",
            "timeout", "index", "rowstride", "quality", "speed", "x", "y", "w", "h", "n", "fd"},
    "str": {"name", "title", "text", "path", "mode", "encoding", "filename", "message", "msg",
            "key", "hostname", "username", "display", "codec", "csc", "prompt"},
    "bytes": {"data", "pixels", "payload", "buf", "buffer", "raw"},
}


def name_hint(argname: str) -> str:
    for t, names in NAME_HINTS.items():
        if argname in names:
            return t
    return ""


# --- return-type looseness -----------------------------------------------------
def is_none(node) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def return_looseness(ret) -> tuple[str, int]:
    """Return (label, payoff-B weight) for a return annotation."""
    if ret is None:
        return ("", 0)          # missing return annotation: tracked as coverage, not a B target here
    if isinstance(ret, ast.Name):
        if ret.id == "Any":
            return ("Any", 2)
        if ret.id in ("dict", "list", "tuple", "set", "Dict", "List", "Tuple", "Set"):
            return (f"bare-{ret.id}", 2)
    if isinstance(ret, ast.Attribute) and ret.attr == "Any":
        return ("Any", 2)
    if isinstance(ret, ast.Subscript) and isinstance(ret.value, ast.Name) and ret.value.id == "Optional":
        return ("Optional", 1)
    if isinstance(ret, ast.BinOp) and isinstance(ret.op, ast.BitOr):
        if is_none(ret.left) or is_none(ret.right):
            return ("Optional", 1)
    return ("", 0)


# --- scoring weights -----------------------------------------------------------
# Boundary is a *location importance* multiplier: it only amplifies real remaining
# work (unannotated args / loose return / unannotated packet). A boundary function
# that is already fully annotated has zero work, so it scores zero and drops out.
W_BOUNDARY = 4
W_CONCRETE = 3       # unannotated arg whose default proves a concrete builtin
W_HEURISTIC = 1      # unannotated arg whose name suggests a concrete builtin
W_PACKET = 3         # unannotated `packet` arg -> annotate as Packet (unlocks get_* accessors)
CYTH_MULT = 1.5      # boost for modules that actually get runtime validation

BOUNDARY_PKG_HINTS = ("xpra/net/protocol", "xpra/net/rfb", "xpra/net/quic",
                      "xpra/net/websockets", "xpra/codecs", "xpra/clipboard")
BOUNDARY_NAME_HINTS = ("decode", "encode", "parse", "unpack", "load", "read_", "process_")


def boundary_location(relpath: str, funcname: str) -> int:
    """How much this is a trust/IO boundary (amplifies remaining work only)."""
    s = 0
    if funcname.startswith("_process_"):
        s += 2
    if any(relpath.replace(os.path.sep, "/").startswith(p) for p in BOUNDARY_PKG_HINTS):
        s += 1
    if any(h in funcname for h in BOUNDARY_NAME_HINTS):
        s += 1
    return s


class FuncRow:
    __slots__ = ("path", "line", "name", "cyth", "boundary", "concrete_args",
                 "heuristic_args", "missing_args", "ret_label", "ret_w", "score", "detail")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


def analyse_func(node, relpath, cyth) -> FuncRow:
    a = node.args
    positional = a.posonlyargs + a.args
    # map defaults onto the tail of positional args:
    defaults = dict(zip([arg.arg for arg in positional[len(positional) - len(a.defaults):]], a.defaults))
    for arg, dflt in zip(a.kwonlyargs, a.kw_defaults):
        defaults[arg.arg] = dflt

    concrete = []
    heuristic = []
    packet_unann = False
    missing = 0
    for arg in positional + a.kwonlyargs:
        if arg.arg in ("self", "cls"):
            continue
        if arg.annotation is not None:
            continue
        missing += 1
        if arg.arg == "packet":
            packet_unann = True
            continue
        t = builtin_from_default(defaults.get(arg.arg))
        if t:
            concrete.append(f"{arg.arg}:{t}")
            continue
        h = name_hint(arg.arg)
        if h:
            heuristic.append(f"{arg.arg}~{h}")

    ret_label, ret_w = return_looseness(node.returns)

    # actual annotation work available here; no work -> not a candidate
    work = W_CONCRETE * len(concrete) + W_HEURISTIC * len(heuristic) + ret_w + (W_PACKET if packet_unann else 0)
    if work <= 0:
        loc, score = 0, 0.0
    else:
        loc = boundary_location(relpath, node.name)
        score = (work + W_BOUNDARY * loc) * (CYTH_MULT if cyth else 1.0)

    detail = []
    if loc:
        detail.append(f"boundary+{loc}")
    if packet_unann:
        detail.append("packet:unannotated")
    if concrete:
        detail.append("concrete[" + ",".join(concrete) + "]")
    if heuristic:
        detail.append("hint[" + ",".join(heuristic) + "]")
    if ret_label:
        detail.append(f"ret={ret_label}")

    return FuncRow(path=relpath, line=node.lineno, name=node.name, cyth=cyth,
                   boundary=loc, concrete_args=len(concrete), heuristic_args=len(heuristic),
                   missing_args=missing, ret_label=ret_label, ret_w=ret_w,
                   score=round(score, 1), detail=" ".join(detail))


def scan() -> list[FuncRow]:
    rows = []
    for dirpath, _, files in os.walk(os.path.join(ROOT, "xpra")):
        for f in files:
            if not f.endswith(".py") or f == "__init__.py":
                continue
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, ROOT)
            cyth = in_cythonize_more(rel)
            try:
                tree = ast.parse(open(full, encoding="utf-8").read())
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    row = analyse_func(node, rel, cyth)
                    if row.score > 0:
                        rows.append(row)
    return rows


def print_functions(rows, top):
    rows = sorted(rows, key=lambda r: -r.score)[:top]
    print(f"\nTop {len(rows)} functions by annotation payoff:\n")
    print(f"{'score':>6}  {'cy':>2}  {'location':52}  {'function':32}  signals")
    print("-" * 130)
    for r in rows:
        loc = f"{r.path}:{r.line}"
        print(f"{r.score:6.1f}  {'Y' if r.cyth else '.':>2}  {loc:52}  {r.name:32}  {r.detail}")


def print_packages(rows):
    pkg = defaultdict(lambda: {"funcs": 0, "score": 0.0, "concrete": 0, "loose_ret": 0, "cyth": False})
    for r in rows:
        # group by the parent package directory (mirrors ax() granularity)
        key = os.path.dirname(r.path)
        d = pkg[key]
        d["funcs"] += 1
        d["score"] += r.score
        d["concrete"] += r.concrete_args
        d["loose_ret"] += 1 if r.ret_w else 0
        d["cyth"] = d["cyth"] or r.cyth
    print("\nPackages by total payoff (only funcs with score>0 counted):\n")
    print(f"{'score':>8}  {'cy':>2}  {'package':40}  {'funcs':>5}  {'concrete-args':>13}  {'loose-returns':>13}")
    print("-" * 100)
    for key, d in sorted(pkg.items(), key=lambda kv: -kv[1]["score"])[:30]:
        print(f"{d['score']:8.1f}  {'Y' if d['cyth'] else '.':>2}  {key:40}  {d['funcs']:5d}  "
              f"{d['concrete']:13d}  {d['loose_ret']:13d}")


def print_csv(rows):
    import csv
    w = csv.writer(sys.stdout)
    w.writerow(["score", "cythonize_more", "path", "line", "function", "boundary",
                "concrete_args", "heuristic_args", "missing_args", "return", "signals"])
    for r in sorted(rows, key=lambda r: -r.score):
        w.writerow([r.score, int(r.cyth), r.path, r.line, r.name, r.boundary,
                    r.concrete_args, r.heuristic_args, r.missing_args, r.ret_label, r.detail])


def main() -> int:
    ap = argparse.ArgumentParser(description="Rank xpra functions by type-annotation payoff.")
    ap.add_argument("--top", type=int, default=30, help="how many top functions to list")
    ap.add_argument("--package", default="", help="only include paths starting with this prefix")
    ap.add_argument("--cythonize-more-only", action="store_true",
                    help="only functions in modules that get runtime validation")
    ap.add_argument("--csv", action="store_true", help="dump every row as CSV")
    args = ap.parse_args()

    rows = scan()
    if args.package:
        rows = [r for r in rows if r.path.replace(os.path.sep, "/").startswith(args.package.rstrip("/"))]
    if args.cythonize_more_only:
        rows = [r for r in rows if r.cyth]

    if args.csv:
        print_csv(rows)
        return 0

    print(f"scanned {len(rows)} functions with a non-zero annotation payoff "
          f"({sum(1 for r in rows if r.cyth)} in cythonize_more modules)")
    print_packages(rows)
    print_functions(rows, args.top)
    return 0


if __name__ == "__main__":
    sys.exit(main())
