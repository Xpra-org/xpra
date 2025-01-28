# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
The goo needed to deal with X properties.

Everyone else should just use prop_set/prop_get with nice clean Python calling
conventions, and if you need more (un)marshalling smarts, add them here.

This module adds GTK / GDK specific conversions,
the conversions for plain python types is found in prop_conv.py
"""

import struct

from xpra.x11.prop_conv import prop_encode, prop_decode, PROP_TYPES, PROP_SIZES
from xpra.x11.bindings.window import X11WindowBindings, PropertyError
from xpra.gtk.error import xsync, XError, XSyncContext
from xpra.util.str_fn import repr_ellipsized
from xpra.log import Logger

log = Logger("x11", "window")


def _get_atom(d) -> str | None:
    unpacked = struct.unpack(b"@L", d)[0]
    if unpacked == 0:
        log.warn("Warning: invalid zero atom value")
        return None
    with xsync:
        name = X11WindowBindings().get_atom_name(unpacked)
    if not name:
        log.error("invalid atom: %s - %s", repr(d), repr(unpacked))
        return None
    return name


def _get_xatom(str_or_int):
    with xsync:
        return X11WindowBindings().get_xatom(str_or_int)


PYTHON_TYPES: dict[str, str] = {
    "UTF8_STRING": "utf8",
    "STRING": "latin1",
    "ATOM": "atom",
    "CARDINAL": "u32",
    "INTEGER": "integer",
    "VISUALID": "visual",
    "WINDOW": "window",
}


def get_python_type(scalar_type: str) -> str:
    # ie: get_python_type("STRING") = "latin1"
    return PYTHON_TYPES.get(scalar_type, scalar_type)


def _to_atom(a) -> bytes:
    return struct.pack(b"@L", _get_xatom(a))


# add the GTK / GDK types to the conversion function list:
PROP_TYPES["atom"] = (str, "ATOM", 32, _to_atom, _get_atom, b"")


def prop_set(xid: int, key: str, etype: list | tuple | str, value) -> None:
    dtype, dformat, data = prop_encode(etype, value)
    raw_prop_set(xid, key, dtype, dformat, data)


def raw_prop_set(xid: int, key: str, dtype: str, dformat: int, data) -> None:
    if not isinstance(xid, int):
        raise TypeError(f"xid must be an int, not a {type(xid)}")
    with xsync:
        X11WindowBindings().XChangeProperty(xid, key, dtype, dformat, data)


def prop_type_get(xid: int, key: str):
    try:
        return X11WindowBindings().GetWindowPropertyType(xid, key)
    except XError:
        log("prop_type_get%s", (xid, key), exc_info=True)
        return None


# May return None.
def prop_get(xid: int, key: str, etype, ignore_errors: bool = False, raise_xerrors: bool = False):
    # ie: 0x4000, "_NET_WM_PID", "u32"
    if isinstance(etype, (list, tuple)):
        scalar_type = etype[0]
    else:
        scalar_type = etype  # ie: "u32"
    type_atom = PROP_TYPES[scalar_type][1]  # ie: "CARDINAL"
    buffer_size = PROP_SIZES.get(scalar_type, 65536)
    data = raw_prop_get(xid, key, type_atom, buffer_size, ignore_errors, raise_xerrors)
    if data is None:
        return None
    return do_prop_decode(key, etype, data, ignore_errors)


def raw_prop_get(xid: int, key: str, type_atom: str, buffer_size: int = 65536,
                 ignore_errors: bool = False, raise_xerrors: bool = False):
    if not isinstance(xid, int):
        raise TypeError(f"xid must be an int, not a {type(xid)}")
    try:
        with XSyncContext():
            data = X11WindowBindings().XGetWindowProperty(xid, key, type_atom, buffer_size)
        if data is None:
            if not ignore_errors:
                log("Missing property %s (%s)", key, type_atom)
            return None
    except XError:
        log("raw_prop_get%s", (xid, key, type_atom, ignore_errors, raise_xerrors), exc_info=True)
        if raise_xerrors:
            raise
        log.info(f"Missing window {xid:x} or wrong property type {key} ({type_atom})")
        return None
    except PropertyError as e:
        log("raw_prop_get%s", (xid, key, type_atom, ignore_errors, raise_xerrors), exc_info=True)
        if not ignore_errors:
            log.info(f"Missing property or wrong property type {key} ({type_atom})")
            log.info(f" on window {xid:x}")
            log.info(" %s", str(e) or type(e))
        return None
    return data


def _etypestr(etype) -> str:
    if isinstance(etype, (list, tuple)):
        scalar_type = etype[0]
        return f"array of {scalar_type}"
    return str(etype)


def do_prop_decode(key: str, etype, data, ignore_errors=False):
    try:
        with XSyncContext():
            return prop_decode(etype, data)
    except Exception:
        if ignore_errors:
            log("prop_get%s", (key, etype, ignore_errors), exc_info=True)
            return None
        log.warn("Error parsing property '%s' (%s)", key, _etypestr(etype))
        log.warn(" this may be a misbehaving application, or bug in Xpra")
        try:
            log.warn(" data length=%i", len(data))
        except TypeError:
            pass
        log.warn(" data: %r", repr_ellipsized(str(data)), exc_info=True)
        raise


def prop_del(xid: int, key: str):
    if not isinstance(xid, int):
        raise TypeError(f"xid must be an int, not a {type(xid)}")
    with xsync:
        X11WindowBindings().XDeleteProperty(xid, key)
