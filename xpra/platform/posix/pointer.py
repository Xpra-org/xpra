# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def get_position() -> tuple[int, int]:
    from xpra.platform.posix.gui import x11_bindings
    if x11_bindings():
        from xpra.x11.bindings.core import X11CoreBindings
        return X11CoreBindings().query_pointer()
    from xpra.gtk.util import get_default_root_window
    return get_default_root_window().get_pointer()[-3:-1]


def get_pointer_device():
    return None
