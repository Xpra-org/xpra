# This file is part of Xpra.
# Copyright (C) 2023 Chris Marchetti <adamnew123456@gmail.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

try:
    from xpra.platform.xposix.proc_libproc import get_parent_pid
except ImportError:
    try:
        from xpra.platform.xposix.proc_procps import get_parent_pid
    except ImportError:
        get_parent_pid = None
