# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util.system import is_X11


def get_pointer_device():
    if is_X11():
        from xpra.x11.server.xtest_pointer import XTestPointerDevice
        return XTestPointerDevice()
    return None
