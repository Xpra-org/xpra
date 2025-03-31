# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# noinspection PyPep8

import os
import sys
import binascii
from enum import Enum, IntEnum
from typing import Final, Protocol, TypeAlias, Any
from collections.abc import Callable, Sized, MutableSequence, Iterable, Sequence

from xpra.util.env import envint, envbool


try:
    # Python 3.11 and later:
    from enum import StrEnum
    from typing import Self
except ImportError:     # pragma: no cover
    StrEnum = Enum      # type: ignore
    Self = Any

try:
    # Python 3.12 and later:
    from collections.abc import Buffer

    class SizedBuffer(Buffer, Sized, Protocol):
        pass
except ImportError:
    class SizedBuffer(Sized, Protocol):
        def __buffer__(self):
            raise NotImplementedError()


PaintCallback: TypeAlias = Callable[[int | bool, str], None]
PaintCallbacks: TypeAlias = MutableSequence[PaintCallback]


ALL_CLIPBOARDS: Final[Sequence[str]] = ("CLIPBOARD", "PRIMARY", "SECONDARY")


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


def get_default_video_max_size() -> tuple[int, int]:
    svalues = os.environ.get("XPRA_VIDEO_MAX_SIZE", "").replace("x", ",").split(",")
    if len(svalues) == 2:
        try:
            return int(svalues[0]), int(svalues[0])
        except (TypeError, ValueError):
            pass
    return 4096, 4096


def force_size_constraint(width: int, height: int) -> dict[str, dict[str, Any]]:
    size = width, height
    return {
        "size-constraints": {
            "maximum-size": size,
            "minimum-size": size,
            "base-size": size,
        },
    }


VIDEO_MAX_SIZE = get_default_video_max_size()


XPRA_APP_ID: Final[int] = 0
XPRA_GUID1: Final[int] = 0x67b3efa2
XPRA_GUID2: Final[int] = 0xe470
XPRA_GUID3: Final[int] = 0x4a5f
XPRA_GUID4: Final[tuple[int, int, int, int, int, int, int, int]] = (0xb6, 0x53, 0x6f, 0x6f, 0x98, 0xfe, 0x60, 0x81)
XPRA_GUID_STR: Final[str] = "67B3EFA2-E470-4A5F-B653-6F6F98FE6081"
XPRA_GUID_BYTES: Final[bytes] = binascii.unhexlify(XPRA_GUID_STR.replace("-", ""))
XPRA_NOTIFICATIONS_OFFSET: Final[int] = 2**24


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
    from xpra.util.str_fn import nicestr
    rstr = nicestr(reason)
    return rstr.find("error") >= 0 or (rstr.find("timeout") >= 0 and rstr != ConnectionMessage.IDLE_TIMEOUT.value)


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


def gravity_str(v) -> str:
    try:
        return Gravity(v).name
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
SOURCE_INDICATION_UNSET: Final[int] = 0
SOURCE_INDICATION_NORMAL: Final[int] = 1
SOURCE_INDICATION_PAGER: Final[int] = 2
SOURCE_INDICATION_STRING: Final[dict[int, str]] = {
    SOURCE_INDICATION_UNSET      : "UNSET",
    SOURCE_INDICATION_NORMAL     : "NORMAL",
    SOURCE_INDICATION_PAGER      : "PAGER",
}


# magic value for "workspace" window property, means unset
WORKSPACE_UNSET: Final[int] = 65535
WORKSPACE_ALL: Final[int] = 0xffffffff
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

SSH_AGENT_DISPATCH: bool = envbool("XPRA_SSH_AGENT_DISPATCH", os.name == "posix")

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


WINDOW_DECODE_SKIPPED: Final[int] = 0
WINDOW_DECODE_ERROR: Final[int] = -1
WINDOW_NOT_FOUND: Final[int] = -2


ScreenshotData = tuple[int, int, str, int, bytes]


MIN_VREFRESH = envint("XPRA_MIN_VREFRESH", 5)
MAX_VREFRESH = envint("XPRA_MAX_VREFRESH", 144)


def i(value, default: int) -> int:
    try:
        return int(value)
    except ValueError:
        return default


def get_refresh_rate_for_value(refresh_rate: str, invalue: int, multiplier=1) -> int:
    if refresh_rate.lower() in ("none", "auto"):
        # just leave it unchanged:
        return invalue
    # refresh rate can be a value (ie: 40), or a range (10-50)
    parts = refresh_rate.split("-", 1)
    if len(parts) > 1:
        minvr = i(parts[0], MIN_VREFRESH) * multiplier
        maxvr = i(parts[1], MAX_VREFRESH) * multiplier
        if minvr > maxvr:
            raise ValueError("the minimum refresh rate cannot be greater than the maximum")
        return min(maxvr, max(minvr, invalue))

    minvr = MIN_VREFRESH * multiplier
    maxvr = MAX_VREFRESH * multiplier
    if refresh_rate.endswith("%") > 0:
        mult = int(refresh_rate[:-1])  # ie: "80%" -> 80
        value = round(invalue * mult / 100)
        return min(maxvr, max(minvr, value))

    try:
        value = int(refresh_rate) * multiplier
        return min(maxvr, max(minvr, value))
    except ValueError:
        pass
    # fallback to client supplied value:
    return invalue


def adjust_monitor_refresh_rate(refresh_rate: str, mdef) -> dict[int, dict]:
    adjusted = {}
    for i, monitor in mdef.items():
        # make a copy, don't modify in place!
        # (as this may be called multiple times on the same input dict)
        mprops = dict(monitor)
        if refresh_rate != "auto":
            value = int(monitor.get("refresh-rate", DEFAULT_REFRESH_RATE))
            value = get_refresh_rate_for_value(refresh_rate, value, 1000)
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
    # noinspection PyBroadException
    try:
        return fn(*args)
    except Exception:
        return None


def roundup(n: int, m: int) -> int:
    return (n + m - 1) & ~(m - 1)


def uniq(seq: Iterable) -> list:
    seen = set()
    return [x for x in seq if not (x in seen or seen.add(x))]


def get_run_info(subcommand="server") -> Sequence[str]:
    from xpra.os_util import POSIX
    from xpra.util.version import full_version_str, get_platform_info
    from xpra.util.system import platform_name
    from xpra.log import Logger
    log = Logger("util")
    run_info = [f"xpra {subcommand} version {full_version_str()}"]
    try:
        pinfo = get_platform_info()
        osinfo = " on " + platform_name(sys.platform,
                                        pinfo.get("linux_distribution") or pinfo.get("sysrelease", ""))
    except OSError:
        log("platform name error:", exc_info=True)
        osinfo = ""
    if POSIX:
        uid = os.getuid()
        gid = os.getgid()
        try:
            import pwd
            import grp

            user = pwd.getpwuid(uid)[0]
            group = grp.getgrgid(gid)[0]
            run_info.append(f" {uid=} ({user}), {gid=} ({group})")
        except (TypeError, KeyError):
            log("failed to get user and group information", exc_info=True)
            run_info.append(f" {uid=}, {gid=}")
    run_info.append(" running with pid %s%s" % (os.getpid(), osinfo))
    vinfo = ".".join(str(x) for x in sys.version_info[:FULL_INFO + 1])
    run_info.append(f" {sys.implementation.name} {vinfo}")
    return run_info
