# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from ctypes import POINTER, byref, get_last_error
from ctypes.wintypes import BOOL, HANDLE, POINT

from xpra.platform.win32.common import GetSystemMetrics, user32
from xpra.util.env import envint, envbool
from xpra.log import Logger

log = Logger("win32", "screen")

# master switch: leave this alone unless you specifically want the OS to
# virtualize ("cook") the coordinates for testing - see `init_dpi()`:
DPI_AWARE = envbool("XPRA_DPI_AWARE", True)
# debug-only escape hatch to pin a *specific* awareness level instead of the
# strongest available. 0 (the default) means "force the strongest available".
# Any other value maps to a `DPI_AWARENESS_CONTEXT` (see `DEBUG_CONTEXTS` below).
# This can only ever *lower* accuracy, so it exists purely for debugging:
DPI_AWARENESS = envint("XPRA_DPI_AWARENESS", 0)

DPI_SCALING = 1

# `DPI_AWARENESS_CONTEXT` pseudo-handle values (win32 `windef.h`).
# these are passed *by value* to `SetProcessDpiAwarenessContext`:
DPI_AWARENESS_CONTEXT_UNAWARE = -1
DPI_AWARENESS_CONTEXT_SYSTEM_AWARE = -2
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE = -3
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4

# `GetLastError` value returned when the awareness was already set
# (ie: via the process manifest) and so cannot be changed at runtime:
ERROR_ACCESS_DENIED = 5

# debug-only mapping for `XPRA_DPI_AWARENESS`:
DEBUG_CONTEXTS: dict[int, int] = {
    -1: DPI_AWARENESS_CONTEXT_UNAWARE,
    1: DPI_AWARENESS_CONTEXT_SYSTEM_AWARE,
    2: DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE,
    3: DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2,
}


def _set_dpi_awareness_context(context: int) -> bool:
    # modern api: `user32.SetProcessDpiAwarenessContext` (win10 1703+).
    # this is the *only* api that can request Per-Monitor v2, which is what
    # gives us true physical-pixel coordinates on every monitor:
    try:
        fn = user32.SetProcessDpiAwarenessContext  # @UndefinedVariable
    except AttributeError:
        log("SetProcessDpiAwarenessContext is not available (requires Windows 10 1703+)")
        return False
    fn.argtypes = [HANDLE]
    fn.restype = BOOL
    if fn(context):
        log("SetProcessDpiAwarenessContext(%i) succeeded", context)
        return True
    err = get_last_error()
    log("SetProcessDpiAwarenessContext(%i) failed, GetLastError()=%i", context, err)
    if err == ERROR_ACCESS_DENIED:
        # awareness was already set (typically via the exe manifest, which is
        # the preferred, immutable mechanism) - nothing to do, and nothing wrong:
        log(" awareness already set (most likely via the application manifest)")
        return True
    return False


def init_dpi() -> None:
    log("init_dpi() DPI_AWARE=%s, DPI_AWARENESS=%s", DPI_AWARE, DPI_AWARENESS)
    if not DPI_AWARE:
        # debug-only: let the OS virtualize the coordinates
        log.warn("Warning: DPI awareness is disabled via XPRA_DPI_AWARE")
        log.warn(" pixel coordinates and monitor geometry may be virtualized by the OS")
        return
    w, h = GetSystemMetrics(0), GetSystemMetrics(1)
    if DPI_AWARENESS in DEBUG_CONTEXTS:
        # debug-only: pin a specific (usually weaker) awareness level.
        # note: the exe manifest may already have set an immutable level,
        # in which case this request is quietly ignored by the OS:
        context = DEBUG_CONTEXTS[DPI_AWARENESS]
        log.warn("Warning: forcing DPI awareness context %i via XPRA_DPI_AWARENESS", context)
        ok = _set_dpi_awareness_context(context)
    else:
        # normal path: request Per-Monitor v2 (Windows 10 1703+) so that the
        # coordinates we receive are true physical pixels, irrespective of the
        # system's per-monitor scaling factors. this is a no-op (access-denied,
        # treated as success) when the manifest already declared `PerMonitorV2`:
        ok = _set_dpi_awareness_context(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
    if not ok:
        log.warn("Warning: unable to set DPI awareness context")
        log.warn(" pixel coordinates and monitor geometry may be virtualized by the OS")
    actual_w, actual_h = GetSystemMetrics(0), GetSystemMetrics(1)
    if actual_w != w or actual_h != h:
        # the reported screen size changed, which means the OS was previously
        # lying to us (virtualized metrics). record the scaling factor for
        # diagnostics - this should stay at 1 under full (v2) awareness:
        global DPI_SCALING
        DPI_SCALING = round(100 * ((actual_w / w) + (actual_h / h))) / 200
        log("DPI_SCALING=%s (screen size changed from %s to %s after enabling DPI awareness)",
            DPI_SCALING, (w, h), (actual_w, actual_h))


def _load_logical_to_physical():
    # `LogicalToPhysicalPointForPerMonitorDPI` (win10 1607+) is the per-monitor,
    # awareness-independent point conversion. Resolve it lazily so that a missing
    # symbol on an older OS cannot break the import of this module:
    try:
        fn = user32.LogicalToPhysicalPointForPerMonitorDPI  # @UndefinedVariable
    except AttributeError:
        log("LogicalToPhysicalPointForPerMonitorDPI is not available (requires Windows 10 1607+)")
        return None
    fn.argtypes = [HANDLE, POINTER(POINT)]
    fn.restype = BOOL
    return fn


_logical_to_physical = _load_logical_to_physical()


def physical_point(hwnd: int, x: int, y: int) -> tuple[int, int]:
    """
    Convert a *screen* point from the window's logical (DPI-awareness dependent)
    coordinate space into true physical device pixels, irrespective of the
    process / thread / window DPI awareness.

    This is a no-op when the process is already Per-Monitor-v2 aware (see
    `init_dpi`), but it guarantees physical-pixel accuracy even if a lower
    awareness level somehow ended up in effect (Layer 2 - belt and braces).

    Note: the conversion uses the DPI of the monitor `hwnd` is on, so a pointer
    that has crossed onto a monitor with a different scaling factor while the
    process is *not* fully aware would use the window's monitor DPI. Under the
    enforced Per-Monitor-v2 awareness this never matters (identity transform).
    """
    if not hwnd or not callable(_logical_to_physical):
        return x, y
    pt = POINT(x, y)
    # noinspection calling-non-callable
    if _logical_to_physical(hwnd, byref(pt)):
        return int(pt.x), int(pt.y)
    return x, y
