#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2010-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os

from xpra.os_util import WIN32, OSX
from xpra.util import csv
from xpra.log import Logger

log = Logger("sound", "gstreamer")
# pylint: disable=import-outside-toplevel
GST_FLOW_OK = 0     #Gst.FlowReturn.OK

GST_FORMAT_BYTES = 2
GST_FORMAT_TIME = 3
GST_FORMAT_BUFFERS = 4
BUFFER_FORMAT = GST_FORMAT_BUFFERS

GST_APP_STREAM_TYPE_STREAM = 0
STREAM_TYPE = GST_APP_STREAM_TYPE_STREAM


Gst = None
def get_gst_version():
    if not Gst:
        return ()
    return Gst.version()


def import_gst():
    global Gst
    if Gst is not None:
        return Gst

    #hacks to locate gstreamer plugins on win32 and osx:
    if WIN32:
        frozen = getattr(sys, "frozen", None) in ("windows_exe", "console_exe", True)
        log("gstreamer_util: frozen=%s", frozen)
        if frozen:
            from xpra.platform.paths import get_app_dir
            gst_dir = os.path.join(get_app_dir(), "lib", "gstreamer-1.0")   #ie: C:\Program Files\Xpra\lib\gstreamer-1.0
            os.environ["GST_PLUGIN_PATH"] = gst_dir
    elif OSX:
        bundle_contents = os.environ.get("GST_BUNDLE_CONTENTS")
        log("OSX: GST_BUNDLE_CONTENTS=%s", bundle_contents)
        if bundle_contents:
            rsc_dir = os.path.join(bundle_contents, "Resources")
            os.environ["GST_PLUGIN_PATH"]       = os.path.join(rsc_dir, "lib", "gstreamer-1.0")
            os.environ["GST_PLUGIN_SCANNER"]    = os.path.join(rsc_dir, "bin", "gst-plugin-scanner-1.0")
    log("GStreamer 1.x environment: %s",
        dict((k,v) for k,v in os.environ.items() if (k.startswith("GST") or k.startswith("GI") or k=="PATH")))
    log("GStreamer 1.x sys.path=%s", csv(sys.path))

    try:
        log("import gi")
        import gi
        gi.require_version('Gst', '1.0')  # @UndefinedVariable
        from gi.repository import Gst           #@UnresolvedImport
        log("Gst=%s", Gst)
        Gst.init(None)
    except Exception as e:
        log("Warning failed to import GStreamer 1.x", exc_info=True)
        log.warn("Warning: failed to import GStreamer 1.x:")
        log.warn(" %s", e)
        return None
    return Gst


def get_default_appsink_attributes():
    return {
        "name"          : "sink",
        "emit-signals"  : True,
        "max-buffers"   : 1,
        "drop"          : False,
        "sync"          : False,
        "async"         : False,
        "qos"           : False,
        }

def get_default_appsrc_attributes():
    return {
        "name"          : "src",
        "emit-signals"  : False,
        "block"         : False,
        "is-live"       : False,
        "stream-type"   : STREAM_TYPE,
        }


def wrap_buffer(data):
    mf = Gst.MemoryFlags
    return Gst.Buffer.new_wrapped_full(
        mf.PHYSICALLY_CONTIGUOUS | mf.READONLY,
        data, len(data),
        0, None, None)

def make_buffer(data):
    buf = Gst.Buffer.new_allocate(None, len(data), None)
    buf.fill(0, data)
    return buf


def normv(v) -> int:
    if v==2**64-1:
        return -1
    return int(v)


all_plugin_names = []
def get_all_plugin_names() -> list:
    global all_plugin_names
    if not all_plugin_names and Gst:
        registry = Gst.Registry.get()
        all_plugin_names = [el.get_name() for el in registry.get_feature_list(Gst.ElementFactory)]
        all_plugin_names.sort()
        log("found the following plugins: %s", all_plugin_names)
    return all_plugin_names

def has_plugins(*names) -> bool:
    allp = get_all_plugin_names()
    #support names that contain a gstreamer chain, ie: "flacparse ! flacdec"
    snames = []
    for x in names:
        if not x:
            continue
        snames += [v.strip() for v in x.split("!")]
    missing = [name for name in snames if (name is not None and name not in allp)]
    if missing:
        log("missing %s from %s", missing, names)
    return len(missing)==0


def get_caps_str(ctype:str="video/x-raw", caps=None) -> str:
    if not caps:
        return ctype
    def s(v):
        if isinstance(v, str):
            return f"(string){v}"
        if isinstance(v, tuple):
            return "/".join(str(x) for x in v)      #ie: "60/1"
        return str(v)
    els = [ctype]
    for k,v in caps.items():
        els.append(f"{k}={s(v)}")
    return ",".join(els)

def get_element_str(element:str, eopts=None):
    s = element
    if eopts:
        s += " "+" ".join(f"{k}={v}" for k,v in eopts.items())
    return s


def format_element_options(options):
    return csv(f"{k}={v}" for k,v in options.items())

def plugin_str(plugin, options):
    if plugin is None:
        return None
    s = str(plugin)
    def qstr(v):
        #only quote strings
        if isinstance(v, str):
            return f'"{v}"'
        return v
    if options:
        s += " "
        s += " ".join([f"{k}={qstr(v)}" for k,v in options.items()])
    return s


def main():
    from xpra.platform import program_context
    from xpra.log import enable_color
    with program_context("GStreamer-Info", "GStreamer Information"):
        enable_color()
        if "-v" in sys.argv or "--verbose" in sys.argv:
            log.enable_debug()
        import_gst()
        v = get_gst_version()
        if not v:
            print("no gstreamer version information")
        else:
            if v[-1]==0:
                v = v[:-1]
            gst_vinfo = ".".join((str(x) for x in v))
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
