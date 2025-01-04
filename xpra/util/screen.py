# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import re
from typing import Any

from xpra.util.io import get_util_logger


def log_screen_sizes(root_w, root_h, sizes):
    try:
        do_log_screen_sizes(root_w, root_h, sizes)
    except Exception as e:
        get_util_logger().warn("failed to parse screen size information: %s", e, exc_info=True)


def prettify_plug_name(s, default="") -> str:
    if not s:
        return default
    try:
        s = s.decode("utf8")
    except (AttributeError, UnicodeDecodeError):
        pass
    # prettify strings on win32
    s = re.sub(r"[0-9\.]*\\", "-", s).lstrip("-")
    if s.startswith("WinSta-"):
        s = s[len("WinSta-"):]
    # ie: "(Standard monitor types) DELL ..."
    if s.startswith("(") and s.lower().find("standard") < s.find(") "):
        s = s.split(") ", 1)[1]
    if s == "0":
        s = default
    return s


def do_log_screen_sizes(root_w, root_h, sizes):
    from xpra.log import Logger
    log = Logger("screen")
    # old format, used by some clients (android):
    if not isinstance(sizes, (tuple, list)):
        return
    if any(True for x in sizes if not isinstance(x, (tuple, list))):
        return

    def dpi(size_pixels, size_mm):
        if size_mm == 0:
            return 0
        return round(size_pixels * 254 / size_mm / 10)

    def add_workarea(info, wx, wy, ww, wh):
        info.append("workarea: %4ix%-4i" % (ww, wh))
        if wx != 0 or wy != 0:
            # log position if not (0, 0)
            info.append("at %4ix%-4i" % (wx, wy))

    if len(sizes) != 1:
        log.warn("Warning: more than one screen found")
        log.warn(" this is not supported")
        log("do_log_screen_sizes(%i, %i, %s)", root_w, root_h, sizes)
        return
    s = sizes[0]
    if len(s) < 10:
        log.info(" %s", s)
        return
    # more detailed output:
    display_name, width, height, width_mm, height_mm, monitors, work_x, work_y, work_width, work_height = s[:10]
    # always log plug name:
    info = ["%s" % prettify_plug_name(display_name)]
    if width != root_w or height != root_h:
        # log plug dimensions if not the same as display (root):
        info.append("%ix%i" % (width, height))
    sdpix = dpi(width, width_mm)
    sdpiy = dpi(height, height_mm)
    info.append("(%ix%i mm - DPI: %ix%i)" % (width_mm, height_mm, sdpix, sdpiy))

    if work_width != width or work_height != height or work_x != 0 or work_y != 0:
        add_workarea(info, work_x, work_y, work_width, work_height)
    log.info("  " + " ".join(info))
    # sort monitors from left to right, top to bottom:
    monitors_distances = []
    for m in monitors:
        plug_x, plug_y = m[1:3]
        monitors_distances.append((plug_x + plug_y * width, m))
    sorted_monitors = [x[1] for x in sorted(monitors_distances)]
    for i, m in enumerate(sorted_monitors, start=1):
        if len(m) < 7:
            log.info("    %s", m)
            continue
        plug_name, plug_x, plug_y, plug_width, plug_height, plug_width_mm, plug_height_mm = m[:7]
        default_name = "monitor %i" % i
        info = ['%-16s' % prettify_plug_name(plug_name, default_name)]
        if plug_width != width or plug_height != height or plug_x != 0 or plug_y != 0:
            info.append("%4ix%-4i" % (plug_width, plug_height))
            if plug_x != 0 or plug_y != 0 or len(sorted_monitors) > 1:
                info.append("at %4ix%-4i" % (plug_x, plug_y))
        if (plug_width_mm != width_mm or plug_height_mm != height_mm) and (plug_width_mm > 0 or plug_height_mm > 0):
            dpix = dpi(plug_width, plug_width_mm)
            dpiy = dpi(plug_height, plug_height_mm)
            dpistr = ""
            if sdpix != dpix or sdpiy != dpiy or len(sorted_monitors) > 1:
                dpistr = " - DPI: %ix%i" % (dpix, dpiy)
            info.append("(%3ix%-3i mm%s)" % (plug_width_mm, plug_height_mm, dpistr))
        if len(m) >= 11:
            dwork_x, dwork_y, dwork_width, dwork_height = m[7:11]
            # only show it again if different from the screen workarea
            if dwork_x != work_x or dwork_y != work_y or dwork_width != work_width or dwork_height != work_height:
                add_workarea(info, dwork_x, dwork_y, dwork_width, dwork_height)
        if len(sorted_monitors) == 1 and len(info) == 1 and info[0].strip() in ("Canvas", "DUMMY0"):
            # no point in logging just `Canvas` on its own
            continue
        istr = (" ".join(info)).rstrip(" ")
        if len(monitors) == 1 and istr.lower() in ("unknown unknown", "0", "1", default_name, "screen", "monitor"):
            # a single monitor with no real name,
            # so don't bother showing it:
            continue
        log.info("    " + istr)


def get_screen_info(screen_sizes) -> dict[int, dict[str, Any]]:
    # same format as above
    if not screen_sizes:
        return {}
    info: dict[int, dict[str, Any]] = {}
    for i, x in enumerate(screen_sizes):
        if not isinstance(x, (tuple, list)):
            continue
        sinfo: dict[str, Any] = info.setdefault(i, {})
        sinfo["display"] = x[0]
        if len(x) >= 3:
            sinfo["size"] = x[1], x[2]
        if len(x) >= 5:
            sinfo["size_mm"] = x[3], x[4]
        if len(x) >= 6:
            monitors = x[5]
            for j, monitor in enumerate(monitors):
                if len(monitor) >= 7:
                    minfo: dict[str, Any] = sinfo.setdefault("monitor", {}).setdefault(j, {})
                    for k, v in {
                        "name": monitor[0],
                        "geometry": monitor[1:5],
                        "size_mm": monitor[5:7],
                    }.items():
                        minfo[k] = v
        if len(x) >= 10:
            sinfo["workarea"] = x[6:10]
    return info
