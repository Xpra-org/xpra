# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2009 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import binascii
from enum import IntEnum
from typing import Final


XPRA_APP_ID: Final[int] = 0
XPRA_GUID1: Final[int] = 0x67b3efa2
XPRA_GUID2: Final[int] = 0xe470
XPRA_GUID3: Final[int] = 0x4a5f
XPRA_GUID4: Final[tuple[int, int, int, int, int, int, int, int]] = (0xb6, 0x53, 0x6f, 0x6f, 0x98, 0xfe, 0x60, 0x81)
XPRA_GUID_STR: Final[str] = "67B3EFA2-E470-4A5F-B653-6F6F98FE6081"
XPRA_GUID_BYTES: Final[bytes] = binascii.unhexlify(XPRA_GUID_STR.replace("-", ""))
XPRA_NOTIFICATIONS_OFFSET: Final[int] = 2**24

# noinspection PyPep8
RESOLUTION_ALIASES: dict[str, tuple[int, int]] = {
    "QVGA"  : (320, 240),
    "VGA"   : (640, 480),
    "SVGA"  : (800, 600),
    "XGA"   : (1024, 768),
    "720P"  : (1280, 720),
    "1080P" : (1920, 1080),
    "FHD"   : (1920, 1080),
    "WQHD"  : (2560, 1440),
    "4K"    : (3840, 2160),
    "5K"    : (5120, 2880),
    "6K"    : (6144, 3456),
    "8K"    : (7680, 4320),
}

# if you want to use a virtual screen bigger than this
# you will need to change those values, but some broken toolkits
# will then misbehave (they use signed shorts instead of signed ints..)
MAX_WINDOW_SIZE: int = 2**15-2**13


# noinspection PyPep8
class NotificationID(IntEnum):
    BANDWIDTH       = XPRA_NOTIFICATIONS_OFFSET + 1
    IDLE            = XPRA_NOTIFICATIONS_OFFSET + 2
    WEBCAM          = XPRA_NOTIFICATIONS_OFFSET + 3
    AUDIO           = XPRA_NOTIFICATIONS_OFFSET + 4
    OPENGL          = XPRA_NOTIFICATIONS_OFFSET + 5
    SCALING         = XPRA_NOTIFICATIONS_OFFSET + 6
    NEW_USER        = XPRA_NOTIFICATIONS_OFFSET + 7
    CLIPBOARD       = XPRA_NOTIFICATIONS_OFFSET + 8
    FAILURE         = XPRA_NOTIFICATIONS_OFFSET + 9
    DPI             = XPRA_NOTIFICATIONS_OFFSET + 10
    DISCONNECT      = XPRA_NOTIFICATIONS_OFFSET + 11
    DISPLAY         = XPRA_NOTIFICATIONS_OFFSET + 12
    STARTUP         = XPRA_NOTIFICATIONS_OFFSET + 13
    FILETRANSFER    = XPRA_NOTIFICATIONS_OFFSET + 14
    SHADOWWAYLAND   = XPRA_NOTIFICATIONS_OFFSET + 15


# noinspection PyPep8
class Gravity(IntEnum):
    # X11 constants we use for gravity:
    NorthWest   = 1
    North       = 2
    NorthEast   = 3
    West        = 4
    Center      = 5
    East        = 6
    SouthWest   = 7
    South       = 8
    SouthEast   = 9
    Static      = 10


# initiate-moveresize X11 constants
# noinspection PyPep8
class MoveResize(IntEnum):
    SIZE_TOPLEFT      = 0
    SIZE_TOP          = 1
    SIZE_TOPRIGHT     = 2
    SIZE_RIGHT        = 3
    SIZE_BOTTOMRIGHT  = 4
    SIZE_BOTTOM       = 5
    SIZE_BOTTOMLEFT   = 6
    SIZE_LEFT         = 7
    MOVE              = 8
    SIZE_KEYBOARD     = 9
    MOVE_KEYBOARD     = 10
    CANCEL            = 11


# noinspection PyPep8
MOVERESIZE_DIRECTION_STRING = {
    MoveResize.SIZE_TOPLEFT      : "SIZE_TOPLEFT",
    MoveResize.SIZE_TOP          : "SIZE_TOP",
    MoveResize.SIZE_TOPRIGHT     : "SIZE_TOPRIGHT",
    MoveResize.SIZE_RIGHT        : "SIZE_RIGHT",
    MoveResize.SIZE_BOTTOMRIGHT  : "SIZE_BOTTOMRIGHT",
    MoveResize.SIZE_BOTTOM       : "SIZE_BOTTOM",
    MoveResize.SIZE_BOTTOMLEFT   : "SIZE_BOTTOMLEFT",
    MoveResize.SIZE_LEFT         : "SIZE_LEFT",
    MoveResize.MOVE              : "MOVE",
    MoveResize.SIZE_KEYBOARD     : "SIZE_KEYBOARD",
    MoveResize.MOVE_KEYBOARD     : "MOVE_KEYBOARD",
    MoveResize.CANCEL            : "CANCEL",
}
SOURCE_INDICATION_UNSET: Final[int] = 0
SOURCE_INDICATION_NORMAL: Final[int] = 1
SOURCE_INDICATION_PAGER: Final[int] = 2
# noinspection PyPep8
SOURCE_INDICATION_STRING: Final[dict[int, str]] = {
    SOURCE_INDICATION_UNSET      : "UNSET",
    SOURCE_INDICATION_NORMAL     : "NORMAL",
    SOURCE_INDICATION_PAGER      : "PAGER",
}

# magic value for "workspace" window property, means unset
WORKSPACE_UNSET: Final[int] = 65535
WORKSPACE_ALL: Final[int] = 0xffffffff
WORKSPACE_NAMES: dict[int, str] = {
    WORKSPACE_UNSET: "unset",
    WORKSPACE_ALL: "all",
}
WINDOW_DECODE_SKIPPED: Final[int] = 0
WINDOW_DECODE_ERROR: Final[int] = -1
WINDOW_NOT_FOUND: Final[int] = -2

# clients should provide the `metadata.supported` capability instead
DEFAULT_METADATA_SUPPORTED = (
    "title", "icon-title", "pid", "iconic",
    "size-constraints", "class-instance", "client-machine",
    "transient-for", "window-type",
    "fullscreen", "maximized", "decorations", "skip-taskbar", "skip-pager",
    "has-alpha", "override-redirect", "tray", "modal",
    "role", "opacity", "xid", "group-leader",
    "opaque-region",
    "command", "workspace", "above", "below", "sticky",
    "set-initial-position", "requested-position",
    "content-type", "content-types",
    "parent", "relative-position",
    "actions",
)
DEFAULT_XDG_DATA_DIRS: str = ":".join(
    (
        "/usr/share",
        "/usr/local/share",
        "~/.local/share/applications",
        "~/.local/share/flatpak/exports/share",
        "/var/lib/flatpak/exports/share",
    )
)
