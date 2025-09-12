#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import ctypes
from weakref import WeakValueDictionary
from typing import Any
from collections.abc import Callable, Sequence

import Quartz
import Quartz.CoreGraphics as CG
from AppKit import NSScreen, NSBeep, NSApp

from xpra.os_util import gi_import
from xpra.common import roundup
from xpra.util.env import envint, envbool
from xpra.util.io import CaptureStdErr
from xpra.platform.darwin import get_OSXApplication
from xpra.log import Logger

log = Logger("osx", "events")
workspacelog = Logger("osx", "events", "workspace")
pointerlog = Logger("osx", "events", "pointer")

SLEEP_HANDLER = envbool("XPRA_OSX_SLEEP_HANDLER", True)
OSX_WHEEL_MULTIPLIER = envint("XPRA_OSX_WHEEL_MULTIPLIER", 100)
OSX_WHEEL_PRECISE_MULTIPLIER = envint("XPRA_OSX_WHEEL_PRECISE_MULTIPLIER", 1)
OSX_WHEEL_DIVISOR = envint("XPRA_OSX_WHEEL_DIVISOR", 10)
WHEEL = envbool("XPRA_WHEEL", True)
SUBPROCESS_NOTIFIER = envbool("XPRA_OSX_SUBPROCESS_NOTIFIER", False)

ALPHA = {
    CG.kCGImageAlphaNone: "AlphaNone",
    CG.kCGImageAlphaPremultipliedLast: "PremultipliedLast",
    CG.kCGImageAlphaPremultipliedFirst: "PremultipliedFirst",
    CG.kCGImageAlphaLast: "Last",
    CG.kCGImageAlphaFirst: "First",
    CG.kCGImageAlphaNoneSkipLast: "SkipLast",
    CG.kCGImageAlphaNoneSkipFirst: "SkipFirst",
}


# if there is an easier way of doing this, I couldn't find it:
def nodbltime() -> float:
    return -1


GetDblTime: Callable = nodbltime
try:
    Carbon_ctypes = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
    GetDblTime = Carbon_ctypes.GetDblTime
except Exception:
    log("GetDblTime not found", exc_info=True)


def do_init() -> None:
    osxapp = get_OSXApplication()
    log("do_init() osxapp=%s", osxapp)
    if not osxapp:
        return  # not much else we can do here
    from xpra.platform.paths import get_icon
    from xpra.platform.gui import get_default_icon
    filename = get_default_icon()
    icon = get_icon(filename)
    log("do_init() icon=%s", icon)
    if icon:
        osxapp.set_dock_icon_pixbuf(icon)
    from xpra.platform.darwin.menu import getOSXMenuHelper
    mh = getOSXMenuHelper(None)
    log("do_init() menu helper=%s", mh)
    osxapp.set_dock_menu(mh.build_dock_menu())
    import warnings
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*invalid cast from 'GtkMenuBar'")
        with CaptureStdErr():
            osxapp.set_menu_bar(mh.rebuild())


def do_ready() -> None:
    osxapp = get_OSXApplication()
    if osxapp:
        log("%s()", osxapp.ready)
        osxapp.ready()


def get_backends() -> list[type]:
    if get_OSXApplication():
        from xpra.platform.darwin.tray import OSXTray
        return [OSXTray]
    return []


def system_bell(*_args) -> bool:
    NSBeep()
    return True


def _sizetotuple(s) -> tuple[int, int]:
    return int(s.width), int(s.height)


def _recttotuple(r) -> tuple[int, int, int, int]:
    return int(r.origin.x), int(r.origin.y), int(r.size.width), int(r.size.height)


def get_double_click_time() -> int:
    try:
        # what are ticks? just an Apple retarded way of measuring elapsed time.
        # They must have considered gigaparsecs divided by teapot too, which is just as useful.
        # (but still call it "Time" you see)
        MS_PER_TICK = 1000.0 / 60
        v = GetDblTime()
        if v > 0:
            return int(v * MS_PER_TICK)
    except Exception:
        pass
    return -1


def get_window_min_size() -> tuple[int, int]:
    # roughly enough to see the window buttons:
    return 120, 1


# def get_window_max_size():
#    return 2**15-1, 2**15-1


def get_window_frame_sizes() -> dict[str, Any]:
    # use a hard-coded window position and size:
    return get_window_frame_size(20, 20, 100, 100)


def get_window_frame_size(x: int, y: int, w: int, h: int) -> dict[str, Any]:
    try:
        cr = Quartz.NSMakeRect(x, y, w, h)
        mask = Quartz.NSTitledWindowMask | Quartz.NSClosableWindowMask | Quartz.NSMiniaturizableWindowMask | Quartz.NSResizableWindowMask
        wr = Quartz.NSWindow.pyobjc_classMethods.frameRectForContentRect_styleMask_(cr, mask)
        dx = int(wr[0][0] - cr[0][0])
        dy = int(wr[0][1] - cr[0][1])
        dw = int(wr[1][0] - cr[1][0])
        dh = int(wr[1][1] - cr[1][1])
        # note: we assume that the title bar is at the top
        # dx, dy and dw are usually 0
        # dh is usually 22 on my 10.5.x system
        return {
            "offset": (dx + dw // 2, dy + dh),
            "frame": (dx + dw // 2, dx + dw // 2, dy + dh, dy),
        }
    except Exception:
        log("failed to query frame size using Quartz, using hardcoded value", exc_info=True)
        return {  # left, right, top, bottom:
            "offset": (0, 22),
            "frame": (0, 0, 22, 0),
        }


def get_workarea() -> tuple[int, int, int, int] | None:
    w = get_workareas()
    if w and len(w) == 1:
        return w[0]
    return None


# per monitor workareas (assuming a single screen)
def get_workareas() -> Sequence[tuple[int, int, int, int]]:
    workareas = []
    screens = NSScreen.screens()
    for screen in screens:
        log("get_workareas() testing screen %s", screen)
        frame = screen.frame()
        visibleFrame = screen.visibleFrame()
        log(" frame=%s, visibleFrame=%s", frame, visibleFrame)
        log(" backingScaleFactor=%s", screen.backingScaleFactor())
        x = int(visibleFrame.origin.x - frame.origin.x)
        y = int((frame.size.height - visibleFrame.size.height) - (visibleFrame.origin.y - frame.origin.y))
        w = int(visibleFrame.size.width)
        h = int(visibleFrame.size.height)
        workareas.append((x, y, w, h))
    log("get_workareas()=%s", workareas)
    return workareas


def get_display_size() -> tuple[int, int]:
    Gdk = gi_import("Gdk")
    screen = Gdk.Screen.get_default
    if not screen:
        raise RuntimeError("unable to access the screen via Gdk")
    return screen.get_width(), screen.get_height()


def get_vrefresh() -> int:
    vrefresh = []
    try:
        err, active_displays, no = CG.CGGetActiveDisplayList(99, None, None)
        log("get_vrefresh() %i active displays: %s (err=%i)", no, active_displays, err)
        if err == 0 and no > 0:
            for adid in active_displays:
                mode = CG.CGDisplayCopyDisplayMode(adid)
                v = int(CG.CGDisplayModeGetRefreshRate(mode))
                log("get_vrefresh() refresh-rate(%#x)=%i", adid, v)
                if v > 0:
                    vrefresh.append(v)
    except Exception:
        log("failed to query vrefresh for active displays: %s", exc_info=True)
    log("get_vrefresh() found %s", vrefresh)
    if len(vrefresh) > 0:
        return min(vrefresh)
    return -1


def get_display_icc_info() -> dict[Any, dict]:
    info = {}
    try:
        err, active_displays, no = CG.CGGetActiveDisplayList(99, None, None)
        if err == 0 and no > 0:
            for i, adid in enumerate(active_displays):
                info[i] = get_colorspace_info(CG.CGDisplayCopyColorSpace(adid))
    except Exception as e:
        log("failed to query colorspace for active displays: %s", e)
    return info


def get_icc_info() -> dict:
    # maybe we shouldn't return anything if there's more than one display?
    info = {}
    try:
        did = CG.CGMainDisplayID()
        info = get_colorspace_info(CG.CGDisplayCopyColorSpace(did))
    except Exception as e:
        log("failed to query colorspace for main display: %s", e)
    return info


def get_colorspace_info(cs) -> dict[str, Any]:
    MODELS: dict[Any, str] = {
        CG.kCGColorSpaceModelUnknown: "unknown",
        CG.kCGColorSpaceModelMonochrome: "monochrome",
        CG.kCGColorSpaceModelRGB: "RGB",
        CG.kCGColorSpaceModelCMYK: "CMYK",
        CG.kCGColorSpaceModelLab: "lab",
        CG.kCGColorSpaceModelDeviceN: "DeviceN",
        CG.kCGColorSpaceModelIndexed: "indexed",
        CG.kCGColorSpaceModelPattern: "pattern",
    }

    # base = CGColorSpaceGetBaseColorSpace(cs)
    # color_table = CGColorSpaceGetColorTable(cs)

    def tomodelstr(v) -> str:
        return MODELS.get(v, "unknown")

    defs = (
        ("name", "CGColorSpaceCopyName", str),
        ("icc-profile", "CGColorSpaceCopyICCProfile", str),
        ("icc-data", "CGColorSpaceCopyICCData", str),
        ("components", "CGColorSpaceGetNumberOfComponents", int),
        ("supports-output", "CGColorSpaceSupportsOutput", bool),
        ("model", "CGColorSpaceGetModel", tomodelstr),
        ("wide-gamut", "CGColorSpaceIsWideGamutRGB", bool),
        ("color-table-count", "CGColorSpaceGetColorTableCount", int),
    )
    return _call_CG_conv(defs, cs)


def get_display_mode_info(mode) -> dict[str, Any]:
    defs = (
        ("width", "CGDisplayModeGetWidth", int),
        ("height", "CGDisplayModeGetHeight", int),
        ("pixel-encoding", "CGDisplayModeCopyPixelEncoding", str),
        ("vrefresh", "CGDisplayModeGetRefreshRate", int),
        ("io-flags", "CGDisplayModeGetIOFlags", int),
        ("id", "CGDisplayModeGetIODisplayModeID", int),
        ("usable-for-desktop", "CGDisplayModeIsUsableForDesktopGUI", bool),
    )
    return _call_CG_conv(defs, mode)


def get_display_modes_info(modes) -> dict[int, Any]:
    return {i: get_display_mode_info(mode) for i, mode in enumerate(modes)}


def _call_CG_conv(defs: Sequence[tuple[str, str, Callable]], argument) -> dict[str, Any]:
    # utility for calling functions on CG with an argument,
    # then convert the return value using another function
    # missing functions are ignored, and None values are skipped
    info = {}
    for prop_name, fn_name, conv in defs:
        fn = getattr(CG, fn_name, None)
        if fn:
            try:
                v = fn(argument)
            except Exception as e:
                log("function %s failed: %s", fn_name, e)
                del e
                continue
            if v is not None:
                info[prop_name] = conv(v)
            else:
                log("%s is not set", prop_name)
        else:
            log("function %s does not exist", fn_name)
    return info


def get_display_info(did) -> dict[str, Any]:
    defs = (
        ("height", "CGDisplayPixelsHigh", int),
        ("width", "CGDisplayPixelsWide", int),
        ("bounds", "CGDisplayBounds", _recttotuple),
        ("active", "CGDisplayIsActive", bool),
        ("asleep", "CGDisplayIsAsleep", bool),
        ("online", "CGDisplayIsOnline", bool),
        ("main", "CGDisplayIsMain", bool),
        ("builtin", "CGDisplayIsBuiltin", bool),
        ("in-mirror-set", "CGDisplayIsInMirrorSet", bool),
        ("always-in-mirror-set", "CGDisplayIsAlwaysInMirrorSet", bool),
        ("in-hw-mirror-set", "CGDisplayIsInHWMirrorSet", bool),
        ("mirrors-display", "CGDisplayMirrorsDisplay", int),
        ("stereo", "CGDisplayIsStereo", bool),
        ("primary", "CGDisplayPrimaryDisplay", bool),
        ("unit-number", "CGDisplayUnitNumber", int),
        ("vendor", "CGDisplayVendorNumber", int),
        ("model", "CGDisplayModelNumber", int),
        ("serial", "CGDisplaySerialNumber", int),
        ("service-port", "CGDisplayIOServicePort", int),
        ("size", "CGDisplayScreenSize", _sizetotuple),
        ("rotation", "CGDisplayRotation", int),
        ("colorspace", "CGDisplayCopyColorSpace", get_colorspace_info),
        ("opengl-acceleration", "CGDisplayUsesOpenGLAcceleration", bool),
        ("mode", "CGDisplayCopyDisplayMode", get_display_mode_info),
    )
    info = _call_CG_conv(defs, did)
    try:
        modes = CG.CGDisplayCopyAllDisplayModes(did, None)
        info["modes"] = get_display_modes_info(modes)
    except Exception as e:
        log("failed to query display modes: %s", e)
    return info


def get_displays_info() -> dict[str, Any]:
    did = CG.CGMainDisplayID()
    info: dict[str, Any] = {
        "main": get_display_info(did),
    }
    err, active_displays, no = CG.CGGetActiveDisplayList(99, None, None)
    if err == 0 and no > 0:
        for i, adid in enumerate(active_displays):
            info.setdefault("active", {})[i] = get_display_info(adid)
    err, online_displays, no = CG.CGGetOnlineDisplayList(99, None, None)
    if err == 0 and no > 0:
        for i, odid in enumerate(online_displays):
            info.setdefault("online", {})[i] = get_display_info(odid)
    return info


def get_info() -> dict[str, Any]:
    from xpra.platform.gui import get_info_base
    i = get_info_base()
    with log.trap_error("Error: OSX get_display_info failed"):
        i["displays"] = get_displays_info()
    return i


# keep track of the window object for each view
VIEW_TO_WINDOW: WeakValueDictionary[int, Any] = WeakValueDictionary()


def get_nsview(window) -> int:
    try:
        from xpra.platform.darwin.gdk3_bindings import get_nsview_ptr
    except ImportError:
        return 0
    try:
        return get_nsview_ptr(window.get_window())
    except Exception:
        return 0


def add_window_hooks(window) -> None:
    if WHEEL:
        nsview = get_nsview(window)
        if nsview:
            VIEW_TO_WINDOW[nsview] = window


def remove_window_hooks(window) -> None:
    if WHEEL:
        nsview = get_nsview(window)
        if nsview:
            VIEW_TO_WINDOW.pop(nsview, None)


def get_CG_imagewrapper(rect=None):
    from xpra.codecs.image import ImageWrapper
    assert CG, "cannot capture without Quartz.CoreGraphics"
    if rect is None:
        x = 0
        y = 0
        region = CG.CGRectInfinite
    else:
        x, y, w, h = rect
        region = CG.CGRectMake(x, y, roundup(w, 2), roundup(h, 2))
    image = CG.CGWindowListCreateImage(region,
                                       CG.kCGWindowListOptionOnScreenOnly,
                                       CG.kCGNullWindowID,
                                       CG.kCGWindowImageNominalResolution)  # CG.kCGWindowImageDefault)
    width = CG.CGImageGetWidth(image)
    height = CG.CGImageGetHeight(image)
    bpc = CG.CGImageGetBitsPerComponent(image)
    bpp = CG.CGImageGetBitsPerPixel(image)
    rowstride = CG.CGImageGetBytesPerRow(image)
    alpha = CG.CGImageGetAlphaInfo(image)
    alpha_str = ALPHA.get(alpha, alpha)
    log("get_CG_imagewrapper(..) image size: %sx%s, bpc=%s, bpp=%s, rowstride=%s, alpha=%s", width, height, bpc, bpp,
        rowstride, alpha_str)
    prov = CG.CGImageGetDataProvider(image)
    argb = CG.CGDataProviderCopyData(prov)
    return ImageWrapper(x, y, width, height, argb, "BGRX", 24, rowstride)


def take_screenshot() -> tuple[int, int, str, int, bytes]:
    log("grabbing screenshot")
    from PIL import Image
    from io import BytesIO
    image = get_CG_imagewrapper()
    w = image.get_width()
    h = image.get_height()
    img = Image.frombuffer("RGB", (w, h), image.get_pixels(), "raw", image.get_pixel_format(), image.get_rowstride())
    buf = BytesIO()
    img.save(buf, "PNG")
    data = buf.getvalue()
    buf.close()
    return w, h, "png", image.get_rowstride(), data


def force_focus(duration=2000) -> None:
    enable_focus_workaround()
    GLib = gi_import("GLib")
    GLib.timeout_add(duration, disable_focus_workaround)


__osx_open_signal = False
# We have to wait for the main loop to be running
# to get the NSApplicationOpenFile signal,
# or the GURLHandler.
OPEN_SIGNAL_WAIT = envint("XPRA_OSX_OPEN_SIGNAL_WAIT", 500)


def wait_for_open_handlers(show_cb: Callable[[], None],
                           open_file_cb: Callable[[str], None],
                           open_url_cb: Callable[[str], None],
                           delay: int = OPEN_SIGNAL_WAIT) -> None:
    GLib = gi_import("GLib")

    def open_url(url: str) -> None:
        global __osx_open_signal
        if __osx_open_signal:
            log.warn("Warning: open signal already handled, ignoring url %r", url)
            return
        __osx_open_signal = True
        log("open_url(%s) will call %s", url, open_url_cb)
        GLib.idle_add(open_url_cb, url)

    def open_file(filename: str) -> None:
        global __osx_open_signal
        if __osx_open_signal:
            log.warn("Warning: open signal already handled, ignoring file %r", filename)
            return
        __osx_open_signal = True
        log("open_file(%s) will call %s", filename, open_file_cb)
        GLib.idle_add(open_file_cb, filename)

    from xpra.platform.darwin.events import get_app_delegate
    get_app_delegate().set_url_handler(open_url)
    get_app_delegate().set_file_handler(open_file)

    def may_show() -> None:
        global __osx_open_signal
        log("may_show() osx open signal=%s", __osx_open_signal)
        if not __osx_open_signal:
            __osx_open_signal = True
            force_focus()
            show_cb()

    log("waiting for open handlers or timeout in %ims", delay)
    GLib.timeout_add(delay, may_show)


def disable_focus_workaround() -> None:
    NSApp.activateIgnoringOtherApps_(False)


def enable_focus_workaround() -> None:
    NSApp.activateIgnoringOtherApps_(True)


def can_access_display() -> bool:
    # see: https://stackoverflow.com/a/11511419/428751
    d = Quartz.CGSessionCopyCurrentDictionary()
    if not d:
        return False
    kCGSSessionOnConsoleKey = d.get("kCGSSessionOnConsoleKey", 0)
    log("kCGSSessionOnConsoleKey=%s", kCGSSessionOnConsoleKey)
    if kCGSSessionOnConsoleKey == 0:
        # GUI session doesn't own the console, or the console's screens are asleep
        return False
    CGSSessionScreenIsLocked = d.get("CGSSessionScreenIsLocked", 0)
    log("CGSSessionScreenIsLocked=%s", CGSSessionScreenIsLocked)
    if CGSSessionScreenIsLocked:
        # screen is locked
        return False
    return True
