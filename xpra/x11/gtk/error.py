# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def inject_gdk() -> None:
    from xpra.os_util import gi_import
    try:
        Gdk = gi_import("Gdk")
    except ImportError as e:
        from xpra.log import Logger
        Logger("gtk").warn("Warning: unable to import Gdk: %s", e)
        return

    from xpra.x11 import error
    error.Xenter = Gdk.error_trap_push

    def gdkXexit(flush=True):
        if flush:
            Gdk.flush()
        return Gdk.error_trap_pop()
    error.Xexit = gdkXexit
