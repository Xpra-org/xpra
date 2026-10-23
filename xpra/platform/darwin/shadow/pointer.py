# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.server.shadow.pointer import ShadowPointerManager


class DarwinShadowPointerManager(ShadowPointerManager):
    """
    macOS pointer subsystem for shadow servers.
    """

    # every move must reach the device so it records the position,
    # otherwise button clicks would be sent to the last known
    # position (0, 0 by default):
    SKIP_REDUNDANT_MOVES = False
