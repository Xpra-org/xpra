# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
from ctypes import CDLL, c_char_p
from tempfile import gettempdir

from xpra.util.io import info, warn


def init_exchndl() -> None:
    """
    Load Dr. MinGW's crash handler, which writes a native stack trace of every thread
    to a `.RPT` report file when the process crashes.
    """
    try:
        exchndl = CDLL("exchndl.dll")
    except OSError as e:
        warn(f"Warning: failed to load exchndl.dll: {e}")
        return
    exchndl.ExcHndlInit()
    # the default report location is beside the executable, which may not be writable:
    exe_name = os.path.splitext(os.path.basename(sys.executable))[0]
    report = os.environ.get("XPRA_EXCHNDL_REPORT", os.path.join(gettempdir(), f"{exe_name}-{os.getpid()}.RPT"))
    exchndl.ExcHndlSetLogFileNameA.argtypes = [c_char_p]
    exchndl.ExcHndlSetLogFileNameA(report.encode())
    info(f"crash reports will be written to {report!r}")
