#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os
from typing import Any
from types import ModuleType
from collections.abc import Sequence

from xpra.os_util import gi_import
from xpra.util.str_fn import csv
from xpra.log import Logger, consume_verbose_argv

log = Logger("audio", "gstreamer")
# pylint: disable=import-outside-toplevel
GST_FLOW_OK: int = 0  # Gst.FlowReturn.OK

GST_FORMAT_BYTES: int = 2
GST_FORMAT_TIME: int = 3
GST_FORMAT_BUFFERS: int = 4
BUFFER_FORMAT: int = GST_FORMAT_BUFFERS

GST_APP_STREAM_TYPE_STREAM: int = 0
STREAM_TYPE: int = GST_APP_STREAM_TYPE_STREAM

Gst: ModuleType | None = None


def get_gst_version() -> tuple[int, ...]:
    if not Gst:
        return ()
    return tuple(Gst.version())


def import_gst() -> ModuleType | None:
    log("import_gst()")
    global Gst
    if Gst is not None:
        return Gst
    log("GStreamer 1.x environment: %s",
        {k: v for k, v in os.environ.items() if (k.startswith("GST") or k.startswith("GI") or k == "PATH")})
    log("GStreamer 1.x sys.path=%s", csv(sys.path))
    try:
        Gst = gi_import("Gst")
        log("Gst=%s", Gst)
        Gst.init(None)
    except Exception as e:
        log("Warning failed to import GStreamer 1.x", exc_info=True)
        log.warn("Warning: failed to import GStreamer 1.x:")
        log.warn(" %s", e)
        return None
    return Gst


def get_default_appsink_attributes() -> dict[str, Any]:
    return {
        "name": "sink",
        "emit-signals": True,
        "max-buffers": 1,
        "drop": False,
        "sync": False,
        "async": False,
        "qos": False,
    }


def get_default_appsrc_attributes() -> dict[str, Any]:
    return {
        "name": "src",
        "emit-signals": False,
        "block": False,
        "is-live": False,
        "stream-type": STREAM_TYPE,
    }


def make_buffer(data):
    buf = Gst.Buffer.new_allocate(None, len(data), None)
    buf.fill(0, data)
    return buf


def normv(v: int) -> int:
    if v == 2 ** 64 - 1:
        return -1
    return int(v)


all_plugin_names: Sequence[str] = ()


def get_all_plugin_names() -> Sequence[str]:
    global all_plugin_names
    if not all_plugin_names and Gst:
        registry = Gst.Registry.get()
        apn = [el.get_name() for el in registry.get_feature_list(Gst.ElementFactory)]
        apn.sort()
        all_plugin_names = tuple(apn)
        log("found the following plugins: %s", all_plugin_names)
    return all_plugin_names


def has_plugins(*names: str) -> bool:
    allp = get_all_plugin_names()
    # support names that contain a gstreamer chain, ie: "flacparse ! flacdec"
    snames = []
    for x in names:
        if not x:
            continue
        snames += [v.strip() for v in x.split("!")]
    missing = [name for name in snames if (name is not None and name not in allp)]
    if missing:
        log("missing %s from %s", missing, names)
    return len(missing) == 0


def get_caps_str(ctype: str = "video/x-raw", caps=None) -> str:
    if not caps:
        return ctype

    def s(v) -> str:
        if isinstance(v, str):
            return f"(string){v}"
        if isinstance(v, tuple):
            return "/".join(str(x) for x in v)  # ie: "60/1"
        return str(v)

    els = [ctype]
    for k, v in caps.items():
        els.append(f"{k}={s(v)}")
    return ",".join(els)


def get_element_str(element: str, eopts=None) -> str:
    s = element
    if eopts:
        s += " " + " ".join(f"{k}={v}" for k, v in eopts.items())
    return s


def format_element_options(options) -> str:
    return csv(f"{k}={v}" for k, v in options.items())


def plugin_str(plugin, options: dict) -> str:
    assert plugin is not None
    s = str(plugin)

    def qstr(v):
        # only quote strings
        if isinstance(v, str):
            return f'"{v}"'
        return v

    if options:
        s += " "
        s += " ".join([f"{k}={qstr(v)}" for k, v in options.items()])
    return s


def main():
    from xpra.platform import program_context
    from xpra.log import enable_color
    with program_context("GStreamer-Info", "GStreamer Information"):
        enable_color()
        consume_verbose_argv(sys.argv, "gstreamer")
        import_gst()
        v = get_gst_version()
        if not v:
            print("no gstreamer version information")
        else:
            if v[-1] == 0:
                v = v[:-1]
            gst_vinfo = ".".join(str(x) for x in v)
            print("Loaded Python GStreamer version %s for Python %s.%s" % (
                gst_vinfo, sys.version_info[0], sys.version_info[1])
            )
        apn = get_all_plugin_names()
        print("GStreamer plugins found: " + csv(apn))
        print("")
        print("GStreamer version: " + ".".join([str(x) for x in get_gst_version()]))
        print("")


if __name__ == "__main__":
    main()
