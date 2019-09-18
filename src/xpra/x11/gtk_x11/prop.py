# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2019 Antoine Martin <antoine@xpra.org>
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
from gi.repository import Gdk

from xpra.x11.prop_conv import prop_encode, prop_decode, unsupported, PROP_TYPES, PROP_SIZES
from xpra.x11.gtk_x11.gdk_bindings import (
    get_pywindow,               #@UnresolvedImport
    get_xvisual,                #@UnresolvedImport
    )
from xpra.x11.bindings.window_bindings import ( #@UnresolvedImport
    X11WindowBindings,
    PropertyError,
    )
from xpra.gtk_common.error import xsync, XError, XSyncContext
from xpra.util import repr_ellipsized
from xpra.log import Logger

log = Logger("x11", "window")


def _get_atom(_disp, d):
    unpacked = struct.unpack(b"@L", d)[0]
    if unpacked==0:
        log.warn("Warning: invalid zero atom value")
        return None
    with xsync:
        pyatom = X11WindowBindings().XGetAtomName(unpacked)
    if not pyatom:
        log.error("invalid atom: %s - %s", repr(d), repr(unpacked))
        return  None
    if not isinstance(pyatom, str):
        #py3k:
        return pyatom.decode()
    return pyatom

def _get_xatom(str_or_int):
    with xsync:
        return X11WindowBindings().get_xatom(str_or_int)

def _get_multiple(disp, d):
    uint_struct = struct.Struct(b"@L")
    log("get_multiple struct size=%s, len(%s)=%s", uint_struct.size, d, len(d))
    if len(d)!=uint_struct.size and False:
        log.info("get_multiple value is not an atom: %s", d)
        return  str(d)
    return _get_atom(disp, d)


def _get_display_name(disp):
    try:
        return disp.get_display().get_name()
    except Exception:
        return None

def set_xsettings(disp, v):
    from xpra.x11.xsettings_prop import set_settings
    return set_settings(_get_display_name(disp), v)

def get_xsettings(disp, v):
    from xpra.x11.xsettings_prop import get_settings
    return get_settings(_get_display_name(disp), v)


PYTHON_TYPES = {
    "UTF8_STRING"   : "utf8",
    "STRING"        : "latin1",
    "ATOM"          : "atom",
    "CARDINAL"      : "u32",
    "INTEGER"       : "integer",
    "VISUALID"      : "visual",
    "WINDOW"        : "window",
    }
def get_python_type(scalar_type):
    #ie: get_python_type("STRING") = "latin1"
    return PYTHON_TYPES.get(scalar_type)

def _to_atom(_disp, a):
    return struct.pack(b"@L", _get_xatom(a))

def _to_visual(disp, c):
    return struct.pack(b"@L", get_xvisual(disp, c))

def _to_window(_disp, w):
    return struct.pack(b"@L", w.get_xid())

def get_window(disp, w):
    return get_pywindow(disp, struct.unpack(b"@L", w)[0])

#add the GTK / GDK types to the conversion function list:
PROP_TYPES.update({
    "atom": (str, "ATOM", 32, _to_atom, _get_atom, b""),
    "visual": (Gdk.Visual, "VISUALID", 32, _to_visual, unsupported, b""),
    "window": (Gdk.Window, "WINDOW", 32, _to_window, get_window, b""),
    "xsettings-settings": (tuple, "_XSETTINGS_SETTINGS", 8,
                           set_xsettings,
                           get_xsettings,
                           None),
    # For fetching the extra information on a MULTIPLE clipboard conversion
    # request. The exciting thing about MULTIPLE is that it's not actually
    # specified what 'type' one should use; you just fetch with
    # AnyPropertyType and assume that what you get is a bunch of pairs of
    # atoms.
    "multiple-conversion": (str, 0, 32, unsupported, _get_multiple, None),
    })


def prop_set(target, key, etype, value):
    with xsync:
        dtype, dformat, data = prop_encode(target, etype, value)
        X11WindowBindings().XChangeProperty(target.get_xid(), key, dtype, dformat, data)


def prop_type_get(target, key):
    try:
        return X11WindowBindings().GetWindowPropertyType(target.get_xid(), key)
    except XError:
        return None


# May return None.
def prop_get(target, key, etype, ignore_errors=False, raise_xerrors=False):
    if isinstance(etype, (list, tuple)):
        scalar_type = etype[0]
        def etypestr():
            return "array of %s" % scalar_type
    else:
        scalar_type = etype
        def etypestr():
            return "%s" % etype
    atom = PROP_TYPES[scalar_type][1]
    try:
        buffer_size = PROP_SIZES.get(scalar_type, 64*1024)
        with XSyncContext():
            data = X11WindowBindings().XGetWindowProperty(target.get_xid(), key, atom, etype, buffer_size)
        if data is None:
            if not ignore_errors:
                log("Missing property %s (%s)", key, etype)
            return None
    except XError:
        log("prop_get%s", (target, key, etype, ignore_errors, raise_xerrors), exc_info=True)
        if raise_xerrors:
            raise
        log.info("Missing window %s or wrong property type %s (%s)", target, key, etypestr())
        return None
    except PropertyError as e:
        log("prop_get%s", (target, key, etype, ignore_errors, raise_xerrors), exc_info=True)
        if not ignore_errors:
            log.info("Missing property or wrong property type %s (%s)", key, etypestr())
            log.info(" %s", e)
        return None
    try:
        with XSyncContext():
            return prop_decode(target, etype, data)
    except :
        if ignore_errors:
            log("prop_get%s", (target, key, etype, ignore_errors, raise_xerrors), exc_info=True)
            return None
        log.warn("Error parsing property '%s' (%s)", key, etypestr())
        log.warn(" this may be a misbehaving application, or bug in Xpra")
        try:
            log.warn(" data length=%i", len(data))
        except TypeError:
            pass
        log.warn(" data: %r", repr_ellipsized(str(data)), exc_info=True)
        raise

def prop_del(target, key):
    with xsync:
        X11WindowBindings().XDeleteProperty(target.get_xid(), key)
