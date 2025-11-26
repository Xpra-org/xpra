# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Functions for converting to and from X11 properties.
    prop_encode
    prop_decode
"""

import struct
from io import BytesIO
from collections.abc import Callable, Sequence
from typing import Any, NoReturn, Final

from xpra.util.str_fn import hexstr
from xpra.x11.bindings.core import constants
from xpra.log import Logger

log = Logger("x11", "window")


USPosition: Final[int] = constants["USPosition"]
PPosition: Final[int] = constants["PPosition"]
PMaxSize: Final[int] = constants["PMaxSize"]
PMinSize: Final[int] = constants["PMinSize"]
PBaseSize: Final[int] = constants["PBaseSize"]
PResizeInc: Final[int] = constants["PResizeInc"]
PAspect: Final[int] = constants["PAspect"]
PWinGravity: Final[int] = constants["PWinGravity"]
XUrgencyHint: Final[int] = constants["XUrgencyHint"]
WindowGroupHint: Final[int] = constants["WindowGroupHint"]
StateHint: Final[int] = constants["StateHint"]
IconicState: Final[int] = constants["IconicState"]
InputHint: Final[int] = constants["InputHint"]

sizeof_long: Final[int] = struct.calcsize(b'@L')


def unsupported(*_args) -> NoReturn:
    raise RuntimeError("unsupported")


def _force_length(name: str, data: bytes, length: int, noerror_length: int = -1) -> bytes:
    if len(data) == length:
        return data
    if len(data) != noerror_length:
        log.warn("Odd-lengthed property %s: wanted %s bytes, got %s: %r"
                 % (name, length, len(data), data))
    # Zero-pad data
    data += b"\0" * length
    return data[:length]


class NetWMStrut:
    def __init__(self, data: bytes):
        # This eats both _NET_WM_STRUT and _NET_WM_STRUT_PARTIAL.  If we are
        # given a _NET_WM_STRUT instead of a _NET_WM_STRUT_PARTIAL, then it
        # will be only length 4 instead of 12, we just don't define the other values
        # and let the client deal with it appropriately
        if len(data) == 4 * sizeof_long:
            self.left, self.right, self.top, self.bottom = struct.unpack(b"@LLLL", data)
        else:

            data = _force_length("_NET_WM_STRUT or _NET_WM_STRUT_PARTIAL", data, 12 * sizeof_long)
            (
                self.left, self.right, self.top, self.bottom,
                self.left_start_y, self.left_end_y,
                self.right_start_y, self.right_end_y,
                self.top_start_x, self.top_end_x,
                self.bottom_start_x, self.bottom_stop_x,
            ) = struct.unpack(b"@" + b"L" * 12, data)

    def todict(self) -> dict:
        return self.__dict__

    def __str__(self):
        return "NetWMStrut(%s)" % self.todict()


class MotifWMHints:
    __slots__ = ("flags", "functions", "decorations", "input_mode", "status")

    def __init__(self, data: bytes):
        # some applications use the wrong size (ie: blender uses 16) so pad it:
        pdata = _force_length("_MOTIF_WM_HINTS", data, sizeof_long*5, sizeof_long*4)
        self.flags, self.functions, self.decorations, self.input_mode, self.status = \
            struct.unpack(b"@LLLlL", pdata)
        log("MotifWMHints(%s)=%s", hexstr(data), self)

    # found in mwmh.h:
    # "flags":
    FUNCTIONS_BIT   = 0
    DECORATIONS_BIT = 1
    INPUT_MODE_BIT  = 2
    STATUS_BIT      = 3
    # "functions":
    ALL_BIT         = 0
    RESIZE_BIT      = 1
    MOVE_BIT        = 2      # like _NET_WM_ACTION_MOVE
    MINIMIZE_BIT    = 3      # like _NET_WM_ACTION_MINIMIZE
    MAXIMIZE_BIT    = 4      # like _NET_WM_ACTION_(FULLSCREEN|MAXIMIZE_(HORZ|VERT))
    CLOSE_BIT       = 5      # like _NET_WM_ACTION_CLOSE
    SHADE_BIT       = 6      # like _NET_WM_ACTION_SHADE
    STICK_BIT       = 7      # like _NET_WM_ACTION_STICK
    FULLSCREEN_BIT  = 8      # like _NET_WM_ACTION_FULLSCREEN
    ABOVE_BIT       = 9      # like _NET_WM_ACTION_ABOVE
    BELOW_BIT       = 10     # like _NET_WM_ACTION_BELOW
    MAXIMUS_BIT     = 11     # like _NET_WM_ACTION_MAXIMUS_(LEFT|RIGHT|TOP|BOTTOM)
    # "decorations":
    # ALL_BIT         = 0 (same as above)
    BORDER_BIT      = 1
    RESIZEH_BIT     = 2
    TITLE_BIT       = 3
    MENU_BIT        = 4
    # MINIMIZE_BIT    = 5 (same as above)
    # MAXIMIZE_BIT    = 6 (same as above)
    # CLOSE_BIT                # non-standard close button
    # RESIZE_BIT               # non-standard resize button
    # SHADE_BIT,               # non-standard shade button
    # STICK_BIT,               # non-standard stick button
    # MAXIMUS_BIT              # non-standard maxim
    # "input":
    MODELESS        = 0
    PRIMARY_APPLICATION_MODAL = 1
    SYSTEM_MODAL    = 2
    FULL_APPLICATION_MODAL = 3
    # "status":
    TEAROFF_WINDOW  = 0

    FLAGS_STR: dict[int, str] = {
        FUNCTIONS_BIT      : "functions",
        DECORATIONS_BIT    : "decorations",
        INPUT_MODE_BIT     : "input",
        STATUS_BIT         : "status",
    }
    FUNCTIONS_STR: dict[int, str] = {
        ALL_BIT        : "all",
        RESIZE_BIT     : "resize",
        MOVE_BIT       : "move",
        MINIMIZE_BIT   : "minimize",
        MAXIMIZE_BIT   : "maximize",
        CLOSE_BIT      : "close",
        SHADE_BIT      : "shade",
        STICK_BIT      : "stick",
        FULLSCREEN_BIT : "fullscreen",
        ABOVE_BIT      : "above",
        BELOW_BIT      : "below",
        MAXIMUS_BIT    : "maximus",
    }
    DECORATIONS_STR: dict[int, str] = {
        ALL_BIT      : "all",
        BORDER_BIT   : "border",
        RESIZEH_BIT  : "resizeh",
        TITLE_BIT    : "title",
        MENU_BIT     : "menu",
        MINIMIZE_BIT : "minimize",
        MAXIMIZE_BIT : "maximize",
    }
    INPUT_STR: dict[int, str] = {
        MODELESS                   : "modeless",
        PRIMARY_APPLICATION_MODAL  : "primary-application-modal",
        SYSTEM_MODAL               : "system-modal",
        FULL_APPLICATION_MODAL     : "full-application-modal",
    }

    STATUS_STR: dict[int, str] = {
        TEAROFF_WINDOW : "tearoff",
    }

    def bits_to_strs(self, int_val: int, flag_bit: int, dict_str: dict) -> Sequence[str]:
        if flag_bit and not self.flags & (2**flag_bit):
            # the bit is not set, ignore this attribute
            return ()
        return tuple(v for k, v in dict_str.items() if int_val & (2**k))

    def flags_strs(self) -> Sequence[str]:
        return self.bits_to_strs(self.flags,
                                 0,
                                 MotifWMHints.FLAGS_STR)

    def functions_strs(self) -> Sequence[str]:
        return self.bits_to_strs(self.functions,
                                 MotifWMHints.FUNCTIONS_BIT,
                                 MotifWMHints.FUNCTIONS_STR)

    def decorations_strs(self) -> Sequence[str]:
        return self.bits_to_strs(self.decorations,
                                 MotifWMHints.DECORATIONS_BIT,
                                 MotifWMHints.DECORATIONS_STR)

    def input_strs(self) -> str:
        if self.flags & (2**MotifWMHints.INPUT_MODE_BIT):
            return MotifWMHints.INPUT_STR.get(self.input_mode, "unknown mode: %i" % self.input_mode)
        return "modeless"

    def status_strs(self) -> Sequence[str]:
        return self.bits_to_strs(self.input_mode,
                                 MotifWMHints.STATUS_BIT,
                                 MotifWMHints.STATUS_STR)

    def __str__(self):
        attrs = {
            "flags": self.flags_strs(),
            "functions": self.functions_strs(),
            "decorations": self.decorations_strs(),
            "input_mode": self.input_strs(),
            "status": self.status_strs(),
        }
        return f"MotifWMHints({attrs})"


def _read_image(stream) -> tuple[int, int, str, bytes] | None:
    try:
        int_size = struct.calcsize(b"@I")
        long_size = struct.calcsize(b"@L")
        header = stream.read(long_size*2)
        if not header:
            return None
        width, height = struct.unpack(b"@LL", header)
        data = stream.read(width * height * long_size)
        expected = width * height * long_size
        if len(data) < expected:
            log.warn("Warning: corrupt _NET_WM_ICON, expected %i bytes but got %i",
                     expected, len(data))
            return None
        if int_size != long_size:
            # long to ints (CARD32):
            longs = struct.unpack(b"@"+b"l"*(width*height), data)
            data = struct.pack(b"@"+b"i"*(width*height), *longs)
    except Exception:
        log.warn("Weird corruption in _NET_WM_ICON", exc_info=True)
        return None
    return width, height, "BGRA", data

# This returns a list of icons from a _NET_WM_ICON property.
# each icon is a tuple:
# (width, height, fmt, data)


def NetWMIcons(data) -> list | None:
    icons = []
    stream = BytesIO(data)
    while True:
        icon = _read_image(stream)
        if icon is None:
            break
        icons.append(icon)
    if not icons:
        return None
    return icons


def _to_latin1(v: str) -> bytes:
    return v.encode("latin1")


def _from_latin1(v: bytes) -> str:
    return v.decode("latin1")


def _to_utf8(v: str) -> bytes:
    return v.encode("UTF-8")


def _from_utf8(v: bytes) -> str:
    return v.decode("UTF-8")


def _to_u8(v: int) -> bytes:
    return struct.pack(b"@B", v)


def _from_u8(v: bytes) -> int:
    return struct.unpack(b"@B", v)[0]


def _to_u16(v: int) -> bytes:
    return struct.pack(b"@H", v)


def _from_u16(v: bytes) -> int:
    return struct.unpack(b"@H", v)[0]


def _to_long(v: int) -> bytes:
    return struct.pack(b"@L", v)


def _from_long(v: bytes) -> int:
    return struct.unpack(b"@L", v)[0]


def _to_state(v: int) -> bytes:
    return struct.pack(b"@LL", v, 0)


def _from_state(v: bytes) -> int:
    wm_state = _force_length("WM_STATE", v, sizeof_long*2, sizeof_long)
    return struct.unpack(b"@LL", wm_state)[0]


PROP_TYPES: dict[str, tuple[type, str, int, Callable[[Any], bytes], Callable[[bytes], Any], bytes | None]] = {
    # Python type, X type Atom, formatbits, serializer, deserializer, list terminator
    "utf8": (str, "UTF8_STRING", 8, _to_utf8, _from_utf8, b"\0"),
    # In theory, there should be something clever about COMPOUND_TEXT here.  I
    # am not sufficiently clever to deal with COMPOUNT_TEXT.  Even knowing
    # that Xutf8TextPropertyToTextlist exists.
    "latin1": (str, "STRING", 8, _to_latin1, _from_latin1, b"\0"),
    "state": (int, "WM_STATE", 32, _to_state, _from_state, b""),
    "u8": (int, "CARDINAL", 8, _to_u8, _from_u8, b""),
    "u16": (int, "CARDINAL", 16, _to_u16, _from_u16, b""),
    "u32": (int, "CARDINAL", 32, _to_long, _from_long, b""),
    "integer": (int, "INTEGER", 32, _to_long, _from_long, b""),
    "strut": (NetWMStrut, "CARDINAL", 32, unsupported, NetWMStrut, None),
    "strut-partial": (NetWMStrut, "CARDINAL", 32, unsupported, NetWMStrut, None),
    "motif-hints": (MotifWMHints, "_MOTIF_WM_HINTS", 32, unsupported, MotifWMHints, None),
    "icons": (list, "CARDINAL", 32, unsupported, NetWMIcons, None),
    "window": (int, "WINDOW", 32, _to_long, _from_long, b""),
}

PROP_SIZES = {
    "icons": 4*1024*1024,
}


def prop_encode(etype : list | tuple | str, value):
    if isinstance(etype, (list, tuple)):
        return _prop_encode_list(etype[0], value)
    return _prop_encode_scalar(etype, value)


def _prop_encode_scalar(etype: str, value) -> tuple[str, int, bytes]:
    pytype, atom, formatbits, serialize = PROP_TYPES[etype][:4]
    assert isinstance(value, pytype), "value for atom %s is not a %s: %s" % (atom, pytype, type(value))
    return atom, formatbits, serialize(value)


def _prop_encode_list(etype: str, value) -> tuple[str, int, bytes]:
    _, atom, formatbits, _, _, terminator = PROP_TYPES[etype]
    if terminator is None:
        raise ValueError(f"cannot encode lists of {etype!r}")
    value = tuple(value)
    serialized = tuple(_prop_encode_scalar(etype, v)[2] for v in value)
    # Strings in X really are null-separated, not null-terminated (ICCCM
    # 2.7.1, see also note in 4.1.2.5)
    return atom, formatbits, terminator.join(x for x in serialized if x is not None)


def prop_decode(etype: str | list | tuple, data: bytes):
    if isinstance(etype, (list, tuple)):
        return _prop_decode_list(etype[0], data)
    return _prop_decode_scalar(etype, data)


def _prop_decode_scalar(etype: str, data: bytes):
    pytype, _, _, _, deserialize, _ = PROP_TYPES[etype]
    value = deserialize(data)
    assert value is None or isinstance(value, pytype), "expected a %s but value is a %s" % (pytype, type(value))
    return value


def _prop_decode_list(etype: str, data) -> list:
    _, _, formatbits, _, _, terminator = PROP_TYPES[etype]
    if terminator:
        datums = data.split(terminator)
    else:
        datums = []
        if formatbits == 32:
            nbytes = struct.calcsize("@L")
        else:
            nbytes = formatbits // 8
        while data:
            datums.append(data[:nbytes])
            data = data[nbytes:]
    props = (_prop_decode_scalar(etype, datum) for datum in datums)
    return [x for x in props if x is not None]
