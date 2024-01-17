# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2013-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import re
import sys
import binascii
import traceback
from itertools import chain
from threading import RLock
from enum import Enum, IntEnum
try:
    #Python 3.11 and later:
    from enum import StrEnum
except ImportError:
    StrEnum = Enum      # type: ignore
from typing import Dict, Tuple, Optional, Any, List, Set, Callable, Iterable, Union

# this is imported in a lot of places,
# so don't import too much at the top:
# pylint: disable=import-outside-toplevel

XPRA_APP_ID = 0

XPRA_GUID1 = 0x67b3efa2
XPRA_GUID2 = 0xe470
XPRA_GUID3 = 0x4a5f
XPRA_GUID4 = (0xb6, 0x53, 0x6f, 0x6f, 0x98, 0xfe, 0x60, 0x81)
XPRA_GUID_STR = "67B3EFA2-E470-4A5F-B653-6F6F98FE6081"
XPRA_GUID_BYTES = binascii.unhexlify(XPRA_GUID_STR.replace("-",""))


XPRA_NOTIFICATIONS_OFFSET = 2**24
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


#constants shared between client and server:
#(do not modify the values, see also disconnect_is_an_error)
#timeouts:
class ConnectionMessage(StrEnum):
    CLIENT_PING_TIMEOUT     = "client ping timeout"
    LOGIN_TIMEOUT           = "login timeout"
    CLIENT_EXIT_TIMEOUT     = "client exit timeout"
    #errors:
    PROTOCOL_ERROR          = "protocol error"
    VERSION_ERROR           = "version error"
    CONTROL_COMMAND_ERROR   = "control command error"
    AUTHENTICATION_FAILED   = "authentication failed"
    AUTHENTICATION_ERROR    = "authentication error"
    PERMISSION_ERROR        = "permission error"
    SERVER_ERROR            = "server error"
    CONNECTION_ERROR        = "connection error"
    SESSION_NOT_FOUND       = "session not found error"
    #informational (not a problem):
    DONE                    = "done"
    SERVER_EXIT             = "server exit"
    SERVER_UPGRADE          = "server upgrade"
    SERVER_SHUTDOWN         = "server shutdown"
    CLIENT_REQUEST          = "client request"
    DETACH_REQUEST          = "detach request"
    NEW_CLIENT              = "new client"
    IDLE_TIMEOUT            = "idle timeout"
    SESSION_BUSY            = "session busy"
    #client telling the server:
    CLIENT_EXIT             = "client exit"


#magic value for "workspace" window property, means unset
WORKSPACE_UNSET = 65535
WORKSPACE_ALL = 0xffffffff

WORKSPACE_NAMES = {
                   WORKSPACE_UNSET  : "unset",
                   WORKSPACE_ALL    : "all",
                   }

#this default value is based on 0.15.x clients,
#later clients should provide the `metadata.supported` capability instead
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
    #4.4:
    #"parent", "relative-position",
    )


#initiate-moveresize X11 constants
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


util_logger = None
def get_util_logger():
    global util_logger
    if not util_logger:
        from xpra.log import Logger
        util_logger = Logger("util")
    return util_logger


#convenience method based on the strings above:
def disconnect_is_an_error(reason) -> bool:
    return reason.find("error")>=0 or (reason.find("timeout")>=0 and reason!=ConnectionMessage.IDLE_TIMEOUT)


def dump_exc():
    """Call this from an except: clause to print a nice traceback."""
    print("".join(traceback.format_exception(*sys.exc_info())))

def noerr(fn, *args):
    try:
        return fn(*args)
    except Exception:
        return None

def stderr_print(msg:str= "") -> bool:
    stderr = sys.stderr
    if stderr:
        try:
            noerr(stderr.write, msg+"\n")
            noerr(stderr.flush)
            return True
        except (OSError, AttributeError):
            pass
    return False


def nicestr(obj):
    """ Python 3.10 and older don't give us a nice string representation for enums """
    if isinstance(obj, Enum):
        return str(obj.value)
    return str(obj)


def net_utf8(value) -> str:
    """
    Given a value received by the network layer,
    convert it to a string.
    Gymnastics are involved if:
    - we get a memoryview from lz4
    - the rencode packet encoder is used
      as it ends up giving us a string which is actually utf8 bytes.
    """
    #with 'rencodeplus' or 'bencode', we just get the unicode string directly:
    if isinstance(value, str):
        return value
    if isinstance(value, memoryview):
        value = value.tobytes()
    #with rencode v1, we have to decode the value:
    #(after converting it to 'bytes' if necessary)
    return u(strtobytes(value))


def u(v) -> str:
    if isinstance(v, str):
        return v
    try:
        return v.decode("utf8")
    except (AttributeError, UnicodeDecodeError):
        return bytestostr(v)


# A simple little class whose instances we can stick random bags of attributes
# on.
class AdHocStruct:
    def __repr__(self):
        return ("<%s object, contents: %r>"
                % (type(self).__name__, self.__dict__))


def remove_dupes(seq:Iterable[Any]) -> List[Any]:
    seen : Set[Any] = set()
    seen_add : Callable = seen.add
    return [x for x in seq if not (x in seen or seen_add(x))]

def merge_dicts(a : Dict[str,Any], b : Dict[str,Any], path:Optional[List[str]]=None) -> Dict[str,Any]:
    """ merges b into a """
    if path is None:
        path = []
    for key in b:
        if key in a:
            if isinstance(a[key], dict) and isinstance(b[key], dict):
                merge_dicts(a[key], b[key], path + [str(key)])
            elif a[key] == b[key]:
                pass # same leaf value
            else:
                raise ValueError('Conflict at %s: existing value is %s, new value is %s' % (
                    '.'.join(path + [str(key)]), a[key], b[key]))
        else:
            a[key] = b[key]
    return a

def make_instance(class_options, *args):
    log = get_util_logger()
    log("make_instance%s", tuple([class_options]+list(args)))
    for c in class_options:
        if c is None:
            continue
        try:
            v = c(*args)
            log(f"make_instance(..) {c}()={v}")
            if v:
                return v
        except Exception:
            log.error("make_instance(%s, %s)", class_options, args, exc_info=True)
            log.error("Error: cannot instantiate %s:", c)
            log.error(" with arguments %s", tuple(args))
    return None


def roundup(n : int, m : int) -> int:
    return (n + m - 1) & ~(m - 1)


class AtomicInteger:
    __slots__ = ("counter", "lock")
    def __init__(self, integer : int = 0):
        self.counter : int = integer
        from threading import RLock
        self.lock : RLock = RLock()

    def increase(self, inc = 1) -> int:
        with self.lock:
            self.counter = self.counter + inc
            return self.counter

    def decrease(self, dec = 1) -> int:
        with self.lock:
            self.counter = self.counter - dec
            return self.counter

    def get(self) -> int:
        return self.counter

    def __str__(self) -> str:
        return str(self.counter)

    def __repr__(self) -> str:
        return f"AtomicInteger({self.counter})"


    def __int__(self) -> int:
        return self.counter

    def __eq__(self, other) -> bool:
        try:
            return self.counter==int(other)
        except ValueError:
            return False

    def __cmp__(self, other) -> int:
        try:
            return self.counter-int(other)
        except ValueError:
            return -1


class MutableInteger(object):
    __slots__ = ("counter", )
    def __init__(self, integer : int = 0):
        self.counter : int = integer

    def increase(self, inc = 1) -> int:
        self.counter = self.counter + inc
        return self.counter

    def decrease(self, dec = 1) -> int:
        self.counter = self.counter - dec
        return self.counter

    def get(self) -> int:
        return self.counter

    def __str__(self) -> str:
        return str(self.counter)

    def __repr__(self) -> str:
        return f"MutableInteger({self.counter})"


    def __int__(self) -> int:
        return self.counter

    def __eq__(self, other) -> bool:
        return self.counter==int(other)
    def __ne__(self, other) -> bool:
        return self.counter!=int(other)
    def __lt__(self, other) -> bool:
        return self.counter<int(other)
    def __le__(self, other) -> bool:
        return self.counter<=int(other)
    def __gt__(self, other) -> bool:
        return self.counter>int(other)
    def __ge__(self, other) -> bool:
        return self.counter>=int(other)
    def __cmp__(self, other) -> int:
        return self.counter-int(other)


def strtobytes(x) -> bytes:
    if isinstance(x, bytes):
        return x
    return str(x).encode("latin1")
def bytestostr(x) -> str:
    if isinstance(x, (bytes, bytearray)):
        return x.decode("latin1")
    return str(x)

def decode_str(x, try_encoding="utf8"):
    """
    When we want to decode something (usually a byte string) no matter what.
    Try with utf8 first then fallback to just bytestostr().
    """
    try:
        return x.decode(try_encoding)
    except (AttributeError, UnicodeDecodeError):
        return bytestostr(x)


_RaiseKeyError = object()

def checkdict(v):
    assert isinstance(v, dict)
    return v

class typedict(dict):
    __slots__ = ("warn", ) # no __dict__ - that would be redundant
    @staticmethod # because this doesn't make sense as a global function.
    def _process_args(mapping=(), **kwargs) -> Dict[str,Any]:
        if hasattr(mapping, "items"):
            mapping = getattr(mapping, "items")()
        return dict((bytestostr(k), v) for k, v in chain(mapping, getattr(kwargs, "items")()))
    def __init__(self, mapping=(), **kwargs):
        super().__init__(self._process_args(mapping, **kwargs))
        self.warn = self._warn
    def __getitem__(self, k):
        return super().__getitem__(bytestostr(k))
    def __setitem__(self, k, v):
        return super().__setitem__(bytestostr(k), v)
    def __delitem__(self, k):
        return super().__delitem__(bytestostr(k))
    def get(self, k, default=None):
        kstr = bytestostr(k)
        if kstr in self:
            return super().get(kstr, default)
        #try to locate this value in a nested dictionary:
        if kstr.find(".")>0:
            prefix, k = kstr.split(".", 1)
            if prefix in self:
                v = super().get(prefix)
                if isinstance(v, dict):
                    return typedict(v).get(k, default)
        return default
    def setdefault(self, k, default=None):
        return super().setdefault(bytestostr(k), default)
    def pop(self, k, v=_RaiseKeyError):
        if v is _RaiseKeyError:
            return super().pop(bytestostr(k))
        return super().pop(bytestostr(k), v)
    def update(self, mapping=(), **kwargs):
        super().update(self._process_args(mapping, **kwargs))
    def __contains__(self, k):
        return super().__contains__(bytestostr(k))
    @classmethod
    def fromkeys(cls, keys, v=None):
        return super().fromkeys((bytestostr(k) for k in keys), v)
    def __repr__(self):
        return '{0}({1})'.format(type(self).__name__, super().__repr__())

    def _warn(self, msg, *args):
        get_util_logger().warn(msg, *args)

    def conv_get(self, k, default=None, conv=None):
        strkey = bytestostr(k)
        if strkey in self:
            v = super().get(strkey)
        else:
            #try harder by recursing:
            d = self
            while strkey.find(".")>0:
                prefix, k = strkey.split(".", 1)
                if prefix not in d:
                    return default
                v = d[prefix]
                if not isinstance(v, dict):
                    return default
                d = v
                strkey = k
            if strkey not in d:
                return default
            v = dict.get(d, strkey)
        if isinstance(v, dict) and conv and conv in (bytestostr, strtobytes, int, bool):
            d = typedict(v)
            if "" in d:
                v = d[""]
        try:
            return conv(v)
        except (TypeError, ValueError, AssertionError) as e:
            self._warn(f"Warning: failed to convert {k}")
            self._warn(f" from {type(v)} using {conv}: {e}")
            return default

    def uget(self, k, default=None):
        return self.conv_get(k, default, u)

    def strget(self, k, default:Optional[str]=None) -> str:
        return self.conv_get(k, default, bytestostr)

    def bytesget(self, k : str, default:Optional[bytes]=None) -> bytes:
        return self.conv_get(k, default, strtobytes)

    def intget(self, k : str, default:Optional[int]=0) -> int:
        return self.conv_get(k, default, int)

    def boolget(self, k : str, default:Optional[bool]=False) -> bool:
        return self.conv_get(k, default, bool)

    def dictget(self, k : str, default:Optional[dict]=None) -> Dict:
        return self.conv_get(k, default, checkdict)

    def intpair(self, k : str, default_value:Optional[Tuple[int,int]]=None) -> Optional[Tuple[int, int]]:
        v = self.inttupleget(k, default_value)
        if v is None:
            return default_value
        if len(v)!=2:
            #"%s is not a pair of numbers: %s" % (k, len(v))
            return default_value
        try:
            return int(v[0]), int(v[1])
        except ValueError:
            return default_value

    def strtupleget(self, k : str, default_value=(), min_items:Optional[int]=None, max_items:Optional[int]=None) -> Tuple[str, ...]:
        return self.tupleget(k, default_value, str, min_items, max_items)

    def inttupleget(self, k : str, default_value=(), min_items:Optional[int]=None, max_items:Optional[int]=None) -> Tuple[int, ...]:
        return self.tupleget(k, default_value, int, min_items, max_items)

    def tupleget(self, k : str, default_value=(), item_type=None, min_items:Optional[int]=None, max_items:Optional[int]=None) -> Tuple[Any, ...]:
        v = self._listget(k, default_value, item_type, min_items, max_items)
        return tuple(v or ())

    def _listget(self, k : str, default_value, item_type=None, min_items:Optional[int]=None, max_items:Optional[int]=None) -> List[Any]:
        v = self.get(k)
        if v is None:
            return default_value
        if isinstance(v, dict) and "" in v:
            v = v.get("")
        if not isinstance(v, (list, tuple)):
            self._warn("listget%s", (k, default_value, item_type, max_items))
            self._warn("expected a list or tuple value for %s but got %s", k, type(v))
            return default_value
        if min_items is not None and len(v)<min_items:
            self._warn("too few items in %s %s: minimum %s allowed, but got %s", type(v), k, max_items, len(v))
            return default_value
        if max_items is not None and len(v)>max_items:
            self._warn("too many items in %s %s: maximum %s allowed, but got %s", type(v), k, max_items, len(v))
            return default_value
        aslist = list(v)
        if item_type:
            for i, x in enumerate(aslist):
                if isinstance(x, bytes) and item_type==str:
                    x = bytestostr(x)
                    aslist[i] = x
                elif isinstance(x, str) and item_type==str:
                    x = str(x)
                    aslist[i] = x
                if not isinstance(x, item_type):
                    if callable(item_type):
                        try:
                            return item_type(x)
                        except Exception:
                            self._warn("invalid item type for %s %s: %s cannot be used with %s",
                                       type(v), k, item_type, type(x))
                            return default_value
                    self._warn("invalid item type for %s %s: expected %s but got %s",
                               type(v), k, item_type, type(x))
                    return default_value
        return aslist


def parse_scaling_value(v) -> Optional[Tuple[int,int]]:
    if not v:
        return None
    if v.endswith("%"):
        return float(v[:1]).as_integer_ratio()
    values = v.replace("/", ":").replace(",", ":").split(":", 1)
    values = [int(x) for x in values]
    for x in values:
        assert x>0, f"invalid scaling value {x}"
    if len(values)==1:
        ret = 1, values[0]
    else:
        assert values[0]<=values[1], "cannot upscale"
        ret = values[0], values[1]
    return ret

def from0to100(v):
    return intrangevalidator(v, 0, 100)

def intrangevalidator(v, min_value=None, max_value=None):
    v = int(v)
    if min_value is not None and v<min_value:
        raise ValueError(f"value must be greater than {min_value}")
    if max_value is not None and v>max_value:
        raise ValueError(f"value must be lower than {max_value}")
    return v


def log_screen_sizes(root_w, root_h, sizes):
    try:
        do_log_screen_sizes(root_w, root_h, sizes)
    except Exception as e:
        get_util_logger().warn("failed to parse screen size information: %s", e, exc_info=True)

def prettify_plug_name(s, default="") -> str:
    if not s:
        return default
    try:
        s = s.decode("utf8")
    except (AttributeError, UnicodeDecodeError):
        pass
    #prettify strings on win32
    s = re.sub(r"[0-9\.]*\\", "-", s).lstrip("-")
    if s.startswith("WinSta-"):
        s = s[len("WinSta-"):]
    #ie: "(Standard monitor types) DELL ..."
    if s.startswith("(") and s.lower().find("standard")<s.find(") "):
        s = s.split(") ", 1)[1]
    if s=="0":
        s = default
    return s

def do_log_screen_sizes(root_w, root_h, sizes):
    from xpra.log import Logger
    log = Logger("screen")
    #old format, used by some clients (android):
    if not isinstance(sizes, (tuple, list)):
        return
    if any(True for x in sizes if not isinstance(x, (tuple, list))):
        return
    def dpi(size_pixels, size_mm):
        if size_mm==0:
            return 0
        return round(size_pixels * 254 / size_mm / 10)
    def add_workarea(info, wx, wy, ww, wh):
        info.append("workarea: %4ix%-4i" % (ww, wh))
        if wx!=0 or wy!=0:
            #log position if not (0, 0)
            info.append("at %4ix%-4i" % (wx, wy))
    if len(sizes)!=1:
        log.warn("Warning: more than one screen found")
        log.warn(" this is not supported")
        log("do_log_screen_sizes(%i, %i, %s)", root_w, root_h, sizes)
        return
    s = sizes[0]
    if len(s)<10:
        log.info(" %s", s)
        return
    #more detailed output:
    display_name, width, height, width_mm, height_mm, \
    monitors, work_x, work_y, work_width, work_height = s[:10]
    #always log plug name:
    info = ["%s" % prettify_plug_name(display_name)]
    if width!=root_w or height!=root_h:
        #log plug dimensions if not the same as display (root):
        info.append("%ix%i" % (width, height))
    sdpix = dpi(width, width_mm)
    sdpiy = dpi(height, height_mm)
    info.append("(%ix%i mm - DPI: %ix%i)" % (width_mm, height_mm, sdpix, sdpiy))

    if work_width!=width or work_height!=height or work_x!=0 or work_y!=0:
        add_workarea(info, work_x, work_y, work_width, work_height)
    log.info("  "+" ".join(info))
    #sort monitors from left to right, top to bottom:
    monitors_distances = []
    for m in monitors:
        plug_x, plug_y = m[1:3]
        monitors_distances.append((plug_x+plug_y*width, m))
    sorted_monitors = [x[1] for x in sorted(monitors_distances)]
    for i, m in enumerate(sorted_monitors, start=1):
        if len(m)<7:
            log.info("    %s", m)
            continue
        plug_name, plug_x, plug_y, plug_width, plug_height, plug_width_mm, plug_height_mm = m[:7]
        default_name = "monitor %i" % i
        info = ['%-16s' % prettify_plug_name(plug_name, default_name)]
        if plug_width!=width or plug_height!=height or plug_x!=0 or plug_y!=0:
            info.append("%4ix%-4i" % (plug_width, plug_height))
            if plug_x!=0 or plug_y!=0 or len(sorted_monitors)>1:
                info.append("at %4ix%-4i" % (plug_x, plug_y))
        if (plug_width_mm!=width_mm or plug_height_mm!=height_mm) and (plug_width_mm>0 or plug_height_mm>0):
            dpix = dpi(plug_width, plug_width_mm)
            dpiy = dpi(plug_height, plug_height_mm)
            dpistr = ""
            if sdpix!=dpix or sdpiy!=dpiy or len(sorted_monitors)>1:
                dpistr = " - DPI: %ix%i" % (dpix, dpiy)
            info.append("(%3ix%-3i mm%s)" % (plug_width_mm, plug_height_mm, dpistr))
        if len(m)>=11:
            dwork_x, dwork_y, dwork_width, dwork_height = m[7:11]
            #only show it again if different from the screen workarea
            if dwork_x!=work_x or dwork_y!=work_y or dwork_width!=work_width or dwork_height!=work_height:
                add_workarea(info, dwork_x, dwork_y, dwork_width, dwork_height)
        if len(sorted_monitors)==1 and len(info)==1 and info[0].strip() in ("Canvas", "DUMMY0"):
            #no point in logging just `Canvas` on its own
            continue
        istr = (" ".join(info)).rstrip(" ")
        if len(monitors)==1 and istr.lower() in ("unknown unknown", "0", "1", default_name, "screen", "monitor"):
            #a single monitor with no real name,
            #so don't bother showing it:
            continue
        log.info("    "+istr)

def get_screen_info(screen_sizes) -> Dict[int, Dict[str, Any]]:
    #same format as above
    if not screen_sizes:
        return {}
    info : Dict[int, Dict[str, Any]] = {}
    for i, x in enumerate(screen_sizes):
        if not isinstance(x, (tuple, list)):
            continue
        sinfo : Dict[str,Any] = info.setdefault(i, {})
        sinfo["display"] = x[0]
        if len(x)>=3:
            sinfo["size"] = x[1], x[2]
        if len(x)>=5:
            sinfo["size_mm"] = x[3], x[4]
        if len(x)>=6:
            monitors = x[5]
            for j, monitor in enumerate(monitors):
                if len(monitor)>=7:
                    minfo : Dict[str,Any] = sinfo.setdefault("monitor", {}).setdefault(j, {})
                    for k,v in {
                                "name"      : monitor[0],
                                "geometry"  : monitor[1:5],
                                "size_mm"   : monitor[5:7],
                                }.items():
                        minfo[k] = v
        if len(x)>=10:
            sinfo["workarea"] = x[6:10]
    return info

def dump_all_frames(logger=None) -> None:
    try:
        frames = sys._current_frames()      #pylint: disable=protected-access
    except AttributeError:
        return
    else:
        dump_frames(frames.items(), logger)

def dump_gc_frames(logger=None) -> None:
    import gc
    import inspect
    gc.collect()
    frames = tuple((None, x) for x in gc.get_objects() if inspect.isframe(x))
    dump_frames(frames, logger)

def dump_frames(frames, logger=None) -> None:
    if not logger:
        logger = get_util_logger()
    logger("found %s frames:", len(frames))
    for i,(fid,frame) in enumerate(frames):
        fidstr = ""
        if fid is not None:
            try:
                fidstr = hex(fid)
            except TypeError:
                fidstr = str(fid)
        logger("%i: %s %s:", i, fidstr, frame)
        for x in traceback.format_stack(frame):
            for l in x.splitlines():
                logger("%s", l)


def detect_leaks() -> Callable[[], None]:
    import tracemalloc
    tracemalloc.start()
    last_snapshot = [tracemalloc.take_snapshot()]
    def print_leaks():
        s1 = last_snapshot[0]
        s2 = tracemalloc.take_snapshot()
        last_snapshot[0] = s2
        top_stats = s2.compare_to(s1, 'lineno')
        print("[ Top 20 differences ]")
        for stat in top_stats[:20]:
            print(stat)
        for i, stat in enumerate(top_stats[:20]):
            print()
            print("top %i:" % i)
            print("%s memory blocks: %.1f KiB" % (stat.count, stat.size / 1024))
            for line in stat.traceback.format():
                print(line)
        return True
    return print_leaks

def start_mem_watcher(ms) -> None:
    from xpra.make_thread import start_thread
    start_thread(mem_watcher, name="mem-watcher", daemon=True, args=(ms,))

def mem_watcher(ms, pid:int=os.getpid()) -> None:
    import time
    import psutil
    process = psutil.Process(pid)
    while True:
        mem = process.memory_full_info()
        #get_util_logger().info("memory usage: %s", mem.mem//1024//1024)
        get_util_logger().info("memory usage for %s: %s", pid, mem)
        time.sleep(ms/1000.0)

def log_mem_info(prefix="memory usage: ", pid=os.getpid()) -> None:
    import psutil
    process = psutil.Process(pid)
    mem = process.memory_full_info()
    print("%i %s%s" % (pid, prefix, mem))


class ellipsizer:
    __slots__ = ("obj", "limit")
    def __init__(self, obj, limit=100):
        self.obj = obj
        self.limit = limit
    def __str__(self):
        return self.__repr__()
    def __repr__(self):
        if self.obj is None:
            return "None"
        return repr_ellipsized(self.obj, self.limit)

def repr_ellipsized(obj, limit=100) -> str:
    if isinstance(obj, str):
        if len(obj)>limit>6:
            return nonl(obj[:limit//2-2]+" .. "+obj[2-limit//2:])
        return nonl(obj)
    if isinstance(obj, memoryview):
        obj = obj.tobytes()
    if isinstance(obj, bytes):
        try:
            s = nonl(repr(obj))
        except Exception:
            s = binascii.hexlify(obj).decode()
        if len(s)>limit>6:
            return nonl(s[:limit//2-2]+" .. "+s[2-limit//2:])
        return s
    return repr_ellipsized(repr(obj), limit)


def rindex(alist:Union[List,Tuple], avalue:Any) -> int:
    return len(alist) - alist[::-1].index(avalue) - 1


def notypedict(d:Dict) -> Dict:
    for k in list(d.keys()):
        v = d[k]
        if isinstance(v, dict):
            d[k] = notypedict(v)
    return dict(d)

def flatten_dict(info:Dict[str,Any], sep:str=".") -> Dict[str,Any]:
    to : Dict[str, Any] = {}
    _flatten_dict(to, sep, "", info)
    return to

def _flatten_dict(to:Dict[str, Any], sep:str, path:str, d:Dict[str,Any]):
    for k,v in d.items():
        if path:
            if k:
                npath = path+sep+bytestostr(k)
            else:
                npath = path
        else:
            npath = bytestostr(k)
        if isinstance(v, dict):
            _flatten_dict(to, sep, npath, v)
        elif v is not None:
            to[npath] = v

def parse_simple_dict(s:str="", sep:str=",") -> Dict[str, Union[str,List[str]]]:
    #parse the options string and add the pairs:
    d : Dict[str, Union[str,List[str]]] = {}
    for el in s.split(sep):
        if not el:
            continue
        try:
            k, v = el.split("=", 1)
            def may_add() -> Union[str,List[str]]:
                cur = d.get(k)
                if cur is None:
                    return v
                if not isinstance(cur, list):
                    cur = [cur]
                cur.append(v)
                return cur
            d[k] = may_add()
        except Exception as e:
            log = get_util_logger()
            log.warn("Warning: failed to parse dictionary option '%s':", s)
            log.warn(" %s", e)
    return d

#used for merging dicts with a prefix and suffix
#non-None values get added to <todict> with a prefix and optional suffix
def updict(todict:Dict, prefix:str, d:Dict, suffix:str="", flatten_dicts:bool=False) -> Dict:
    if not d:
        return todict
    for k,v in d.items():
        if v is not None:
            if k:
                k = prefix+"."+str(k)
            else:
                k = prefix
            if suffix:
                k = k+"."+suffix
            if flatten_dicts and isinstance(v, dict):
                updict(todict, k, v)
            else:
                todict[k] = v
    return todict

def pver(v, numsep:str=".", strsep:str=", ") -> str:
    #print for lists with version numbers, or CSV strings
    if isinstance(v, (list, tuple)):
        types = list(set(type(x) for x in v))
        if len(types)==1:
            if types[0]==int:
                return numsep.join(str(x) for x in v)
            if types[0]==str:
                return strsep.join(str(x) for x in v)
            if types[0]==bytes:
                def s(x):
                    try:
                        return x.decode("utf8")
                    except UnicodeDecodeError:
                        return bytestostr(x)
                return strsep.join(s(x) for x in v)
    return bytestostr(v)

def sorted_nicely(l:Iterable):
    """ Sort the given iterable in the way that humans expect."""
    def convert(text):
        if text.isdigit():
            return int(text)
        return text
    alphanum_key = lambda key: [convert(c) for c in re.split(r"(\d+)", bytestostr(key))]
    return sorted(l, key = alphanum_key)

def print_nested_dict(d:Dict, prefix:str="", lchar:str="*", pad:int=32, vformat=None, print_fn:Optional[Callable]=None,
                      version_keys=("version", "revision"), hex_keys=("data", )):
    #"smart" value formatting function:
    def sprint(arg):
        if print_fn:
            print_fn(arg)
        else:
            print(arg)
    def vf(k, v):
        if vformat:
            fmt = vformat
            if isinstance(vformat, dict):
                fmt = vformat.get(k)
            if fmt is not None:
                return nonl(fmt(v))
        try:
            if any(k.find(x)>=0 for x in version_keys):
                return nonl(pver(v)).lstrip("v")
            if any(k.find(x)>=0 for x in hex_keys):
                return binascii.hexlify(v)
        except Exception:
            pass
        return nonl(pver(v, ", ", ", "))
    l = pad-len(prefix)-len(lchar)
    for k in sorted_nicely(d.keys()):
        v = d[k]
        if isinstance(v, dict):
            nokey = v.get("", (v.get(None)))
            if nokey is not None:
                sprint("%s%s %s : %s" % (prefix, lchar, bytestostr(k).ljust(l), vf(k, nokey)))
                for x in ("", None):
                    v.pop(x, None)
            else:
                sprint("%s%s %s" % (prefix, lchar, bytestostr(k)))
            print_nested_dict(v, prefix+"  ", "-", vformat=vformat, print_fn=print_fn,
                              version_keys=version_keys, hex_keys=hex_keys)
        else:
            sprint("%s%s %s : %s" % (prefix, lchar, bytestostr(k).ljust(l), vf(k, v)))

def reverse_dict(d:Dict) -> Dict:
    reversed_d = {}
    for k,v in d.items():
        reversed_d[v] = k
    return reversed_d


def std(s, extras:str="-,./: ") -> str:
    s = s or ""
    try:
        s = s.decode("latin1")
    except Exception:
        pass
    def c(v):
        try:
            return chr(v)
        except Exception:
            return str(v)
    def f(v):
        return str.isalnum(c(v)) or v in extras
    return "".join(filter(f, s))

def alnum(s) -> str:
    try:
        s = s.encode("latin1")
    except Exception:
        pass
    def c(v):
        try:
            return chr(v)
        except Exception:
            return str(v)
    def f(v):
        return str.isalnum(c(v))
    return "".join(c(v) for v in filter(f, s))

def nonl(x) -> str:
    if not x:
        return ""
    return str(x).replace("\n", "\\n").replace("\r", "\\r")

def engs(v) -> str:
    if isinstance(v, int):
        l = v
    else:
        try:
            l = len(v)
        except TypeError:
            return ""
    return "s" if l!=1 else ""


def obsc(v) -> str:
    OBSCURE_PASSWORDS = envbool("XPRA_OBSCURE_PASSWORDS", True)
    if OBSCURE_PASSWORDS:
        return "".join("*" for _ in (bytestostr(v) or ""))
    return v


def csv(v) -> str:
    try:
        return ", ".join(str(x) for x in v)
    except Exception:
        return str(v)


def unsetenv(*varnames) -> None:
    for x in varnames:
        os.environ.pop(x, None)

def hasenv(name : str) -> bool:
    return os.environ.get(name) is not None

def envint(name : str, d:int=0) -> int:
    try:
        return int(os.environ.get(name, d))
    except ValueError:
        return d

def envbool(name : str, d:bool=False) -> bool:
    try:
        v = os.environ.get(name, "").lower()
        if v is None:
            return d
        if v in ("yes", "true", "on"):
            return True
        if v in ("no", "false", "off"):
            return False
        return bool(int(v))
    except ValueError:
        return d

def envfloat(name : str, d:float=0) -> float:
    try:
        return float(os.environ.get(name, d))
    except ValueError:
        return d


#give warning message just once per key then ignore:
_once_only = set()
def first_time(key:str) -> bool:
    if key not in _once_only:
        _once_only.add(key)
        return True
    return False

numpy_import_lock = RLock()

