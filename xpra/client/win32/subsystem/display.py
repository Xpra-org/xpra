# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Sequence
from ctypes import WinDLL
from ctypes.wintypes import HDC, LPCSTR

from xpra.platform.win32 import constants as win32con
from xpra.platform.win32.common import (
    EnumDisplayMonitors, GetMonitorInfo,
    GetDeviceCaps, DeleteDC,
)
from xpra.platform.win32.displayconfig import get_display_config
from xpra.client.subsystem.display import DisplayClient
from xpra.log import Logger

log = Logger("win32", "screen")

# MONITORINFO.dwFlags:
MONITORINFOF_PRIMARY = 0x1

# CreateDCA declared locally so that `lpInitData` can be NULL
# (the shared binding in `common` expects a DEVMODE structure by value):
_gdi32 = WinDLL("gdi32", use_last_error=True)
_CreateDCA = _gdi32.CreateDCA
_CreateDCA.restype = HDC
_CreateDCA.argtypes = [LPCSTR, LPCSTR, LPCSTR, LPCSTR]


def _get_device_dc(device: str) -> int:
    # `device` is a name like "\\.\DISPLAY1" as returned by GetMonitorInfo:
    return _CreateDCA(b"DISPLAY", device.encode("latin1"), None, None)


def get_monitors_info(xscale: float = 1.0, yscale: float = 1.0) -> dict[int, Any]:
    """
    Native (non-GTK) enumeration of the monitors using the win32 API.
    Returns per-monitor dictionaries matching the layout used by the GTK backend.
    """
    def xs(v: int) -> int:
        return round(v / xscale)

    def ys(v: int) -> int:
        return round(v / yscale)

    # awareness-independent geometry / scanout data, keyed by GDI device name:
    try:
        display_config = get_display_config()
    except Exception:
        log("get_display_config() failed", exc_info=True)
        display_config = {}
    info: dict[int, Any] = {}
    for i, hmonitor in enumerate(EnumDisplayMonitors()):
        try:
            mi = GetMonitorInfo(hmonitor)
        except OSError:
            log("GetMonitorInfo(%#x) failed", hmonitor, exc_info=True)
            continue
        mleft, mtop, mright, mbottom = mi["Monitor"]
        wleft, wtop, wright, wbottom = mi["Work"]
        device = mi.get("Device", "")
        minfo: dict[str, Any] = {
            "primary": bool(mi.get("Flags", 0) & MONITORINFOF_PRIMARY),
            "geometry": (xs(mleft), ys(mtop), xs(mright - mleft), ys(mbottom - mtop)),
            "workarea": (xs(wleft), ys(wtop), xs(wright - wleft), ys(wbottom - wtop)),
        }
        # prefer the `QueryDisplayConfig` SOURCE mode for the geometry: it is the
        # true device-pixel desktop surface, reported independently of the process
        # DPI awareness (whereas `GetMonitorInfo` is only physical when PMv2-aware):
        dcfg = display_config.get(device, {})
        src = dcfg.get("source")
        if src:
            sx, sy = src["position"]
            sw, sh = src["width"], src["height"]
            minfo["geometry"] = (xs(sx), ys(sy), xs(sw), ys(sh))
            # rebase the workarea (which `GetMonitorInfo` reports in the awareness
            # space) onto the physical geometry, so both live in the same device-pixel
            # coordinate space. this is an identity transform under PMv2 awareness:
            mw, mh = mright - mleft, mbottom - mtop
            fx = sw / mw if mw else 1.0
            fy = sh / mh if mh else 1.0
            minfo["workarea"] = (
                xs(sx + round((wleft - mleft) * fx)),
                ys(sy + round((wtop - mtop) * fy)),
                xs(round((wright - wleft) * fx)),
                ys(round((wbottom - wtop) * fy)),
            )
        tgt = dcfg.get("target")
        if tgt:
            # the actual scanout raster of the panel, in true device pixels
            # (not subject to the client `xscale`/`yscale` - this is hardware):
            minfo["scanout"] = {
                "active-size": tgt["active-size"],
                "total-size": tgt["total-size"],
                "pixel-clock": tgt["pixel-clock"],
            }
            # a hardware/GPU scaler sits between the desktop surface and the panel:
            if "scaled" in dcfg:
                minfo["scaled"] = dcfg["scaled"]
        if device:
            minfo["name"] = device
            dc = _get_device_dc(device)
            if dc:
                try:
                    wmm = GetDeviceCaps(dc, win32con.HORZSIZE)
                    hmm = GetDeviceCaps(dc, win32con.VERTSIZE)
                    if wmm > 0 and hmm > 0:
                        minfo["width-mm"] = xs(wmm)
                        minfo["height-mm"] = ys(hmm)
                    refresh = GetDeviceCaps(dc, win32con.VREFRESH)
                    # 0 or 1 mean "hardware default" (i.e. unknown):
                    if refresh > 1:
                        minfo["refresh-rate"] = refresh * 1000
                    depth = GetDeviceCaps(dc, win32con.BITSPIXEL)
                    if depth > 0:
                        minfo["depth"] = depth
                finally:
                    DeleteDC(dc)
            else:
                log("failed to create a device context for %r", device)
        # prefer the exact scanout refresh rate (mHz) over the integer GetDeviceCaps
        # value, but ignore the 0/1 Hz "unknown" sentinel some drivers report:
        if tgt and tgt["refresh-rate"] > 1000:
            minfo["refresh-rate"] = tgt["refresh-rate"]
        info[i] = minfo
    log("get_monitors_info(%s, %s)=%s", xscale, yscale, info)
    return info


class Win32DisplayClient(DisplayClient):
    """
    win32-native (non-GTK) toolkit implementation of the display queries that
    need real window-system bindings.
    """

    def get_root_size(self) -> tuple[int, int]:
        from xpra.platform.win32.gui import get_display_size
        return get_display_size()

    def get_screen_sizes(self, xscale=1.0, yscale=1.0) -> Sequence[tuple[int, int]]:
        w, h = self.get_root_size()
        return ((round(w / xscale), round(h / yscale)), )

    def get_monitors_info(self) -> dict:
        return get_monitors_info(self.xscale, self.yscale)
