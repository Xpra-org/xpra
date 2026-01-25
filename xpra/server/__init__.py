# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from enum import IntEnum


class ServerExitMode(IntEnum):
    UNSET = -1
    NORMAL = 0
    UPGRADE = 1
    EXIT = 2


CLOBBER_UPGRADE: int = 0x1
CLOBBER_USE_DISPLAY: int = 0x2
