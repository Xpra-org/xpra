# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2017 Antoine Martin <antoine@devloop.org.uk>
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

from xpra.x11.prop_conv import prop_encode, prop_decode, unsupported, PROP_TYPES
from xpra.gtk_common.gobject_compat import import_gtk, import_gdk, is_gtk3, try_import_GdkX11
gtk = import_gtk()
gdk = import_gdk()
from xpra.gtk_common.gtk_util import get_xwindow

from xpra.log import Logger
log = Logger("x11", "window")


if is_gtk3():
    gdkx11 = try_import_GdkX11()
    def get_pywindow(disp_source, xid):
        try:
            disp = disp_source.get_display()
        except:
            disp = gdk.Display.get_default()
        return gdkx11.foreign_new_for_display(disp, xid)
    def get_xvisual(disp_source, xid):
        try:
            disp = disp_source.get_display()
        except:
            disp = gdk.Display.get_default()
        return disp.get_default_screen().lookup_visual(xid)
else:
    from xpra.x11.gtk2.gdk_bindings import (
                    get_pywindow,               #@UnresolvedImport
                    get_xvisual,                #@UnresolvedImport
                   )

from xpra.x11.bindings.window_bindings import (
                X11WindowBindings,          #@UnresolvedImport
                PropertyError)              #@UnresolvedImport
X11Window = X11WindowBindings()

from xpra.gtk_common.error import xsync, XError


def _get_atom(_disp, d):
    unpacked = struct.unpack("@I", d)[0]
    with xsync:
        pyatom = X11Window.XGetAtomName(unpacked)
    if not pyatom:
        log.error("invalid atom: %s - %s", repr(d), repr(unpacked))
        return  None
    if type(pyatom)!=str:
        #py3k:
        return pyatom.decode()
    return pyatom

def _get_xatom(str_or_int):
    with xsync:
        return X11Window.get_xatom(str_or_int)

def _get_multiple(disp, d):
    uint_struct = struct.Struct("@I")
    log("get_multiple struct size=%s, len(%s)=%s", uint_struct.size, d, len(d))
    if len(d)!=uint_struct.size and False:
        log.info("get_multiple value is not an atom: %s", d)
        return  str(d)
    return _get_atom(disp, d)


def _get_display_name(disp):
    try:
        return disp.get_display().get_name()
    except:
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
    return struct.pack("@I", _get_xatom(a))

def _to_visual(_disp, c):
    return struct.pack("=I", get_xvisual(c))

def _to_window(_disp, w):
    return struct.pack("=I", get_xwindow(w))

def get_window(disp, w):
    return get_pywindow(disp, struct.unpack("=I", d)[0])

#add the GTK / GDK types to the conversion function list:
PROP_TYPES.update({
    "atom": (str, "ATOM", 32, _to_atom, _get_atom, b""),
    "visual": (gdk.Visual, "VISUALID", 32, _to_visual, unsupported, b""),
    "window": (gdk.Window, "WINDOW", 32, _to_window, get_window, b""),
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
        X11Window.XChangeProperty(get_xwindow(target), key,
                       prop_encode(target, etype, value))

# May return None.
def prop_get(target, key, etype, ignore_errors=False, raise_xerrors=False):
    if isinstance(etype, list):
        scalar_type = etype[0]
    else:
        scalar_type = etype
    (_, atom, _, _, _, _) = PROP_TYPES[scalar_type]
    try:
        with xsync:
            data = X11Window.XGetWindowProperty(get_xwindow(target), key, atom, etype)
        if data is None:
            if not ignore_errors:
                log("Missing property %s (%s)", key, etype)
            return None
    except XError:
        log("prop_get%s", (target, key, etype, ignore_errors, raise_xerrors), exc_info=True)
        if raise_xerrors:
            raise
        log.info("Missing window %s or wrong property type %s (%s)", target, key, etype)
        return None
    except PropertyError:
        log("prop_get%s", (target, key, etype, ignore_errors, raise_xerrors), exc_info=True)
        if not ignore_errors:
            log.info("Missing property or wrong property type %s (%s)", key, etype)
        return None
    try:
        return prop_decode(target, etype, data)
    except:
        if not ignore_errors:
            log.warn("Error parsing property %s (type %s); this may be a"
                     + " misbehaving application, or bug in Xpra\n"
                     + "  Data: %r[...?]",
                     key, etype, data[:160], exc_info=True)
        raise

def prop_del(target, key):
    with xsync:
        X11Window.XDeleteProperty(get_xwindow(target), key)
