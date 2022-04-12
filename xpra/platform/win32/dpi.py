# This file is part of Xpra.
# Copyright (C) 2011-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.platform.win32.common import (
    GetSystemMetrics, user32,
    )
from xpra.util import envint, envbool
from xpra.log import Logger


log = Logger("win32", "screen")

DPI_AWARE = envbool("XPRA_DPI_AWARE", True)
DPI_AWARENESS = envint("XPRA_DPI_AWARENESS", 2)


DPI_SCALING = 1
def init_dpi():
    log("init_dpi() DPI_AWARE=%s, DPI_AWARENESS=%s", DPI_AWARE, DPI_AWARENESS)
    #tell win32 we handle dpi
    if not DPI_AWARE:
        log.warn("SetProcessDPIAware not set due to environment override")
        return
    w, h = GetSystemMetrics(0), GetSystemMetrics(1)
    try:
        SetProcessDPIAware = user32.SetProcessDPIAware
        dpiaware = SetProcessDPIAware()
        log("SetProcessDPIAware: %s()=%s", SetProcessDPIAware, dpiaware)
        assert dpiaware!=0
    except Exception as e:
        log.warn("SetProcessDPIAware() failed: %s", e)
    if DPI_AWARENESS<=0:
        log.warn("SetProcessDPIAwareness not set due to environment override")
        return
    try:
        Process_System_DPI_Aware        = 1
        Process_DPI_Unaware             = 0
        Process_Per_Monitor_DPI_Aware   = 2
        assert DPI_AWARENESS in (Process_System_DPI_Aware, Process_DPI_Unaware, Process_Per_Monitor_DPI_Aware)
        SetProcessDpiAwarenessInternal = user32.SetProcessDpiAwarenessInternal
        dpiawareness = SetProcessDpiAwarenessInternal(DPI_AWARENESS)
        log("SetProcessDPIAwareness: %s(%s)=%s", SetProcessDpiAwarenessInternal, DPI_AWARENESS, dpiawareness)
        assert dpiawareness==0
    except Exception as e:
        log("SetProcessDpiAwarenessInternal(%s) failed: %s", DPI_AWARENESS, e)
        log(" (not available on MS Windows before version 8.1)")
    actual_w, actual_h = GetSystemMetrics(0), GetSystemMetrics(1)
    if actual_w!=w or actual_h!=h:
        #MS Windows is going to lie to us..
        global DPI_SCALING
        DPI_SCALING = round(100*((actual_w/w) + (actual_h/h)))/200
        log("DPI_SCALING=%s", DPI_SCALING)
