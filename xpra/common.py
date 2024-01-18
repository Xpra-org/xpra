# This file is part of Xpra.
# Copyright (C) 2019-2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import binascii
import os
from enum import Enum, IntEnum
from collections.abc import Callable

try:
    # Python 3.11 and later:
    from enum import StrEnum
except ImportError:     # pragma: no cover
    StrEnum = Enum      # type: ignore

from xpra.util.str_fn import csv
from xpra.util.env import envint, envbool

RESOLUTION_ALIASES: dict[str, tuple[int, int]] = {
    "QVGA"  : (320, 240),
    "VGA"   : (640, 480),
    "SVGA"  : (800, 600),
    "XGA"   : (1024, 768),
    "1080P" : (1920, 1080),
    "FHD"   : (1920, 1080),
    "4K"    : (3840, 2160),
    "5K"    : (5120, 2880),
    "6K"    : (6144, 3456),
    "8K"    : (7680, 4320),
}


def get_default_video_max_size() -> tuple[int, int]:
    svalues = os.environ.get("XPRA_VIDEO_MAX_SIZE", "").replace("x", ",").split(",")
    if len(svalues) == 2:
        try:
            return int(svalues[0]), int(svalues[0])
        except (TypeError, ValueError):
            pass
    return 4096, 4096


VIDEO_MAX_SIZE = get_default_video_max_size()


XPRA_APP_ID = 0
XPRA_GUID1 = 0x67b3efa2
XPRA_GUID2 = 0xe470
XPRA_GUID3 = 0x4a5f
XPRA_GUID4 = (0xb6, 0x53, 0x6f, 0x6f, 0x98, 0xfe, 0x60, 0x81)
XPRA_GUID_STR = "67B3EFA2-E470-4A5F-B653-6F6F98FE6081"
XPRA_GUID_BYTES = binascii.unhexlify(XPRA_GUID_STR.replace("-",""))
XPRA_NOTIFICATIONS_OFFSET = 2**24


class SocketState(StrEnum):
    LIVE = "LIVE"
    DEAD = "DEAD"
    UNKNOWN = "UNKNOWN"
    INACCESSIBLE = "INACCESSIBLE"


# constants shared between client and server:
# (do not modify the values, see also disconnect_is_an_error)
# timeouts:
class ConnectionMessage(StrEnum):
    CLIENT_PING_TIMEOUT     = "client ping timeout"
    LOGIN_TIMEOUT           = "login timeout"
    CLIENT_EXIT_TIMEOUT     = "client exit timeout"
    # errors:
    PROTOCOL_ERROR          = "protocol error"
    VERSION_ERROR           = "version error"
    CONTROL_COMMAND_ERROR   = "control command error"
    AUTHENTICATION_FAILED   = "authentication failed"
    AUTHENTICATION_ERROR    = "authentication error"
    PERMISSION_ERROR        = "permission error"
    SERVER_ERROR            = "server error"
    CONNECTION_ERROR        = "connection error"
    SESSION_NOT_FOUND       = "session not found error"
    # informational (not a problem):
    DONE                    = "done"
    SERVER_EXIT             = "server exit"
    SERVER_UPGRADE          = "server upgrade"
    SERVER_SHUTDOWN         = "server shutdown"
    CLIENT_REQUEST          = "client request"
    DETACH_REQUEST          = "detach request"
    NEW_CLIENT              = "new client"
    IDLE_TIMEOUT            = "idle timeout"
    SESSION_BUSY            = "session busy"
    # client telling the server:
    CLIENT_EXIT             = "client exit"


# convenience method based on the strings above:
def disconnect_is_an_error(reason) -> bool:
    return reason.find("error") >= 0 or (reason.find("timeout") >= 0 and reason != ConnectionMessage.IDLE_TIMEOUT)


class NotificationID(IntEnum):
    BANDWIDTH   = XPRA_NOTIFICATIONS_OFFSET+1
    IDLE        = XPRA_NOTIFICATIONS_OFFSET+2
    WEBCAM      = XPRA_NOTIFICATIONS_OFFSET+3
    AUDIO       = XPRA_NOTIFICATIONS_OFFSET+4
    OPENGL      = XPRA_NOTIFICATIONS_OFFSET+5
    SCALING     = XPRA_NOTIFICATIONS_OFFSET+6
    NEW_USER    = XPRA_NOTIFICATIONS_OFFSET+7
    CLIPBOARD   = XPRA_NOTIFICATIONS_OFFSET+8
    FAILURE     = XPRA_NOTIFICATIONS_OFFSET+9
    DPI         = XPRA_NOTIFICATIONS_OFFSET+10
    DISCONNECT  = XPRA_NOTIFICATIONS_OFFSET+11
    DISPLAY     = XPRA_NOTIFICATIONS_OFFSET+12
    STARTUP     = XPRA_NOTIFICATIONS_OFFSET+13
    FILETRANSFER    = XPRA_NOTIFICATIONS_OFFSET+14
    SHADOWWAYLAND   = XPRA_NOTIFICATIONS_OFFSET+15


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


def GravityStr(v) -> str:
    try:
        return str(Gravity(v))
    except ValueError:
        return str(v)


# initiate-moveresize X11 constants
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
SOURCE_INDICATION_UNSET     = 0
SOURCE_INDICATION_NORMAL    = 1
SOURCE_INDICATION_PAGER     = 2
SOURCE_INDICATION_STRING    = {
    SOURCE_INDICATION_UNSET      : "UNSET",
    SOURCE_INDICATION_NORMAL     : "NORMAL",
    SOURCE_INDICATION_PAGER      : "PAGER",
}


# magic value for "workspace" window property, means unset
WORKSPACE_UNSET = 65535
WORKSPACE_ALL = 0xffffffff
WORKSPACE_NAMES = {
    WORKSPACE_UNSET  : "unset",
    WORKSPACE_ALL    : "all",
}


CLOBBER_UPGRADE: int = 0x1
CLOBBER_USE_DISPLAY: int = 0x2

# if you want to use a virtual screen bigger than this
# you will need to change those values, but some broken toolkits
# will then misbehave (they use signed shorts instead of signed ints..)
MAX_WINDOW_SIZE: int = 2**15-2**13


GROUP: str = os.environ.get("XPRA_GROUP", "xpra")

FULL_INFO: int = envint("XPRA_FULL_INFO", 1)
assert FULL_INFO >= 0
LOG_HELLO: bool = envbool("XPRA_LOG_HELLO", False)

SSH_AGENT_DISPATCH: bool = envbool("XPRA_SSH_AGENT_DISPATCH", os.name=="posix")

MIN_COMPRESS_SIZE: int = envint("XPRA_MIN_DECOMPRESSED_SIZE", -1)
MAX_DECOMPRESSED_SIZE: int = envint("XPRA_MAX_DECOMPRESSED_SIZE", 256*1024*1024)


MIN_DPI: int = envint("XPRA_MIN_DPI", 10)
MAX_DPI: int = envint("XPRA_MIN_DPI", 500)

SYNC_ICC: bool = envbool("XPRA_SYNC_ICC", True)

DEFAULT_REFRESH_RATE: int = envint("XPRA_DEFAULT_REFRESH_RATE", 50*1000)

SPLASH_EXIT_DELAY: int = envint("XPRA_SPLASH_EXIT_DELAY", 4)

DEFAULT_XDG_DATA_DIRS: str = ":".join(
    (
        "/usr/share",
        "/usr/local/share",
        "~/.local/share/applications",
        "~/.local/share/flatpak/exports/share",
        "/var/lib/flatpak/exports/share",
    )
)


def noop(*_args, **_kwargs) -> None:
    """ do nothing """


WINDOW_DECODE_SKIPPED: int = 0
WINDOW_DECODE_ERROR: int = -1
WINDOW_NOT_FOUND: int = -2


ScreenshotData = tuple[int,int,str,int,bytes]


class KeyEvent:
    __slots__ = ("modifiers", "keyname", "keyval", "keycode", "group", "string", "pressed")

    def __init__(self):
        self.modifiers: list[str] = []
        self.keyname: str = ""
        self.keyval: int = 0
        self.keycode: int = 0
        self.group: int = 0
        self.string: str = ""
        self.pressed: bool = True

    def __repr__(self):
        strattrs = csv(f"{k}="+str(getattr(self, k)) for k in KeyEvent.__slots__)
        return f"KeyEvent({strattrs})"


def get_refresh_rate_for_value(refresh_rate_str, invalue) -> int:
    def i(v):
        try:
            return int(v)
        except ValueError:
            return invalue
    if refresh_rate_str.lower() in ("none", "auto"):
        # just honour whatever the client supplied:
        return i(invalue)
    v = i(refresh_rate_str)
    if v is not None:
        # server specifies an absolute value:
        if 0 < v < 1000:
            return v*1000
        if v >= 1000:
            return v
    if refresh_rate_str.endswith("%"):
        # server specifies a percentage:
        mult = i(refresh_rate_str[:-1])  # ie: "80%" -> 80
        iv = i(invalue)
        if mult and iv:
            return iv*mult//100
    # fallback to client supplied value, if any:
    return i(invalue)


def adjust_monitor_refresh_rate(refresh_rate_str, mdef) -> dict[int,dict]:
    adjusted = {}
    for i, monitor in mdef.items():
        # make a copy, don't modify in place!
        # (as this may be called multiple times on the same input dict)
        mprops = dict(monitor)
        if refresh_rate_str!="auto":
            value = monitor.get("refresh-rate", DEFAULT_REFRESH_RATE)
            value = get_refresh_rate_for_value(refresh_rate_str, value)
            if value:
                mprops["refresh-rate"] = value
        adjusted[i] = mprops
    return adjusted


# this default value is based on 0.15.x clients,
# later clients should provide the `metadata.supported` capability instead
DEFAULT_METADATA_SUPPORTED = (
    "title", "icon-title", "pid", "iconic",
    "size-hints", "class-instance", "client-machine",
    "transient-for", "window-type",
    "fullscreen", "maximized", "decorations", "skip-taskbar", "skip-pager",
    "has-alpha", "override-redirect", "tray", "modal",
    "role", "opacity", "xid", "group-leader",
    "opaque-region",
    "command", "workspace", "above", "below", "sticky",
    "set-initial-position", "requested-position",
    "content-type",
    # 4.4:
    # "parent", "relative-position",
)


def noerr(fn: Callable, *args):
    try:
        return fn(*args)
    except Exception:
        return None


def roundup(n: int, m: int) -> int:
    return (n + m - 1) & ~(m - 1)
