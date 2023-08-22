# This file is part of Xpra.
# Copyright (C) 2019-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Dict, Tuple, List

from xpra.util import envint, envbool, csv


RESOLUTION_ALIASES : Dict[str,Tuple[int,int]] = {
    "QVGA"  : (320, 240),
    "VGA"   : (640, 480),
    "SVGA"  : (800, 600),
    "XGA"   : (1024, 768),
    "1080P" : (1920, 1080),
    "FHD"   : (1920, 1080),
    "4K"    : (3840, 2160),
    "5K"    : (5120, 2880),
    "8K"    : (7680, 4320),
    }

def get_default_video_max_size() -> Tuple[int,int]:
    svalues = os.environ.get("XPRA_VIDEO_MAX_SIZE", "").replace("x", ",").split(",")
    if len(svalues)==2:
        try:
            return int(svalues[0]), int(svalues[0])
        except (TypeError, ValueError):
            pass
    return 4096, 4096


VIDEO_MAX_SIZE = get_default_video_max_size()

from enum import IntEnum

class Gravity(IntEnum):
    #X11 constants we use for gravity:
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

def GravityStr(v):
    try:
        return Gravity(v)
    except ValueError:
        return str(v)

CLOBBER_UPGRADE : int = 0x1
CLOBBER_USE_DISPLAY : int = 0x2

#if you want to use a virtual screen bigger than this
#you will need to change those values, but some broken toolkits
#will then misbehave (they use signed shorts instead of signed ints..)
MAX_WINDOW_SIZE : int = 2**15-2**13


GROUP : str = os.environ.get("XPRA_GROUP", "xpra")

FULL_INFO : int = envint("XPRA_FULL_INFO", 1)
assert FULL_INFO>=0
LOG_HELLO : bool = envbool("XPRA_LOG_HELLO", False)

SSH_AGENT_DISPATCH : bool = envbool("XPRA_SSH_AGENT_DISPATCH", os.name=="posix")

MIN_COMPRESS_SIZE : int = envint("XPRA_MIN_DECOMPRESSED_SIZE", -1)
MAX_DECOMPRESSED_SIZE : int = envint("XPRA_MAX_DECOMPRESSED_SIZE", 256*1024*1024)


MIN_DPI : int = envint("XPRA_MIN_DPI", 10)
MAX_DPI : int = envint("XPRA_MIN_DPI", 500)

SYNC_ICC : bool = envbool("XPRA_SYNC_ICC", True)

DEFAULT_REFRESH_RATE : int = envint("XPRA_DEFAULT_REFRESH_RATE", 50*1000)

SPLASH_EXIT_DELAY : int = envint("XPRA_SPLASH_EXIT_DELAY", 4)

DEFAULT_XDG_DATA_DIRS : str = ":".join(
        (
        "/usr/share",
        "/usr/local/share",
        "~/.local/share/applications",
        "~/.local/share/flatpak/exports/share",
        "/var/lib/flatpak/exports/share",
        )
    )

def noop(*_args) -> None:
    """ do nothing """


WINDOW_DECODE_SKIPPED : int = 0
WINDOW_DECODE_ERROR : int = -1
WINDOW_NOT_FOUND : int = -2


ScreenshotData = Tuple[int,int,str,int,bytes]


class KeyEvent:
    __slots__ = ("modifiers", "keyname", "keyval", "keycode", "group", "string", "pressed")

    def __init__(self):
        self.modifiers : List[str] = []
        self.keyname : str = ""
        self.keyval : int = 0
        self.keycode : int = 0
        self.group : int = 0
        self.string : str = ""
        self.pressed : bool = True

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
        #just honour whatever the client supplied:
        return i(invalue)
    v = i(refresh_rate_str)
    if v is not None:
        #server specifies an absolute value:
        if 0<v<1000:
            return v*1000
        if v>=1000:
            return v
    if refresh_rate_str.endswith("%"):
        #server specifies a percentage:
        mult = i(refresh_rate_str[:-1])  #ie: "80%" -> 80
        iv = i(invalue)
        if mult and iv:
            return iv*mult//100
    #fallback to client supplied value, if any:
    return i(invalue)


def adjust_monitor_refresh_rate(refresh_rate_str, mdef) -> Dict[int,Dict]:
    adjusted = {}
    for i, monitor in mdef.items():
        #make a copy, don't modify in place!
        #(as this may be called multiple times on the same input dict)
        mprops = dict(monitor)
        if refresh_rate_str!="auto":
            value = monitor.get("refresh-rate", DEFAULT_REFRESH_RATE)
            value = get_refresh_rate_for_value(refresh_rate_str, value)
            if value:
                mprops["refresh-rate"] = value
        adjusted[i] = mprops
    return adjusted
