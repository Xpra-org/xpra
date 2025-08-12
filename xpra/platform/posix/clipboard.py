# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def get_backend_module() -> str:
    from xpra.platform.posix.gui import x11_bindings
    if x11_bindings():
        try:
            from xpra import x11
            assert x11
            return "xpra.x11.selection.clipboard.X11Clipboard"
        except ImportError:
            pass
    return "xpra.gtk.clipboard.GTK_Clipboard"
