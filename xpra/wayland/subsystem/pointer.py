# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.server.subsystem.pointer import PointerManager


class WaylandPointerManager(PointerManager):

    def make_pointer_device(self):
        return self.server.compositor.get_pointer_device()
