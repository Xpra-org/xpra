# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""All the goo needed to deal with X properties.

Everyone else should just use prop_set/prop_get with nice clean Python calling
conventions, and if you need more (un)marshalling smarts, add them here."""

import binascii
import struct
import cairo

from xpra.gtk_common.gobject_compat import import_gtk, import_gdk, is_gtk3
gtk = import_gtk()
gdk = import_gdk()
from xpra.gtk_common.gtk_util import get_xwindow

from xpra.log import Logger
log = Logger("x11", "window")

try:
    from xpra.x11.gtk2.gdk_bindings import (
                    get_pywindow,               #@UnresolvedImport
                    get_xvisual,                #@UnresolvedImport
                   )
except ImportError as e:
    #we should only ever be missing the gdk_bindings with GTK3 builds:
    log("cannot import gdk bindings", exc_info=True)
    if not is_gtk3():
        raise
    def missing_fn(*args):
        raise NotImplementedError()
    get_pywindow, get_xvisual = missing_fn, missing_fn

from xpra.x11.bindings.window_bindings import (
                constants,                      #@UnresolvedImport
                X11WindowBindings,          #@UnresolvedImport
                PropertyError)              #@UnresolvedImport
X11Window = X11WindowBindings()

from xpra.os_util import StringIOClass, PYTHON3
from xpra.gtk_common.error import xsync, XError
from xpra.codecs.argb.argb import premultiply_argb_in_place #@UnresolvedImport


if PYTHON3:
    long = int              #@ReservedAssignment
    unicode = str           #@ReservedAssignment


USPosition      = constants["USPosition"]
PPosition       = constants["PPosition"]
PMaxSize        = constants["PMaxSize"]
PMinSize        = constants["PMinSize"]
PBaseSize       = constants["PBaseSize"]
PResizeInc      = constants["PResizeInc"]
PAspect         = constants["PAspect"]
PWinGravity     = constants["PWinGravity"]
XUrgencyHint    = constants["XUrgencyHint"]
WindowGroupHint = constants["WindowGroupHint"]
StateHint       = constants["StateHint"]
IconicState     = constants["IconicState"]
InputHint       = constants["InputHint"]


def unsupported(*args):
    raise Exception("unsupported")

def _force_length(name, data, length, noerror_length=None):
    if len(data)==length:
        return data
    if len(data)!=noerror_length:
        log.warn("Odd-lengthed property %s: wanted %s bytes, got %s: %r"
                 % (name, length, len(data), data))
    # Zero-pad data
    data += "\0" * length
    return data[:length]


class NetWMStrut(object):
    def __init__(self, disp, data):
        # This eats both _NET_WM_STRUT and _NET_WM_STRUT_PARTIAL.  If we are
        # given a _NET_WM_STRUT instead of a _NET_WM_STRUT_PARTIAL, then it
        # will be only length 4 instead of 12, we just don't define the other values
        # and let the client deal with it appropriately
        if len(data)==16:
            self.left, self.right, self.top, self.bottom = struct.unpack("=IIII", data)
        else:
            data = _force_length("_NET_WM_STRUT or _NET_WM_STRUT_PARTIAL", data, 4 * 12)
            (self.left, self.right, self.top, self.bottom,
             self.left_start_y, self.left_end_y,
             self.right_start_y, self.right_end_y,
             self.top_start_x, self.top_end_x,
             self.bottom_start_x, self.bottom_stop_x,
             ) = struct.unpack("=" + "I" * 12, data)

    def todict(self):
        return self.__dict__

    def __str__(self):
        return "NetWMStrut(%s)" % self.todict()


class MotifWMHints(object):
    def __init__(self, disp, data):
        #some applications use the wrong size (ie: blender uses 16) so pad it:
        pdata = _force_length("_MOTIF_WM_HINTS", data, 20, 16)
        self.flags, self.functions, self.decorations, self.input_mode, self.status = \
            struct.unpack("=IIIiI", pdata)
        log("MotifWMHints(%s)=%s", binascii.hexlify(data), self)

    #found in mwmh.h:
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
    ALL_BIT         = 0
    BORDER_BIT      = 1
    RESIZEH_BIT     = 2
    TITLE_BIT       = 3
    MENU_BIT        = 4
    MINIMIZE_BIT    = 5
    MAXIMIZE_BIT    = 6
    #CLOSE_BIT                # non-standard close button
    #RESIZE_BIT               # non-standard resize button
    #SHADE_BIT,               # non-standard shade button
    #STICK_BIT,               # non-standard stick button
    #MAXIMUS_BIT              # non-standard maxim
    # "input":
    MODELESS        = 0
    PRIMARY_APPLICATION_MODAL = 1
    SYSTEM_MODAL    = 2
    FULL_APPLICATION_MODAL = 3

    FLAGS_STR = {
                 FUNCTIONS_BIT      : "functions",
                 DECORATIONS_BIT    : "decorations",
                 INPUT_MODE_BIT     : "input",
                 STATUS_BIT         : "status",
                 }
    FUNCTIONS_STR = {
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
    DECORATIONS_STR = {
                       ALL_BIT      : "all",
                       BORDER_BIT   : "border",
                       RESIZEH_BIT  : "resizeh",
                       TITLE_BIT    : "title",
                       MENU_BIT     : "menu",
                       MINIMIZE_BIT : "minimize",
                       MAXIMIZE_BIT : "maximize",
                       }
    INPUT_STR = {
                 MODELESS                   : "modeless",
                 PRIMARY_APPLICATION_MODAL  : "primary-application-modal",
                 SYSTEM_MODAL               : "system-modal",
                 FULL_APPLICATION_MODAL     : "full-application-modal",
                 }
    def bits_to_strs(self, int_val, dict_str):
        return [v for k,v in dict_str.items() if (int_val & (2**k))]
    def flags_strs(self):
        return self.bits_to_strs(self.flags, MotifWMHints.FLAGS_STR)
    def functions_strs(self):
        return self.bits_to_strs(self.flags, MotifWMHints.FUNCTIONS_STR)
    def decorations_strs(self):
        return self.bits_to_strs(self.flags, MotifWMHints.DECORATIONS_STR)
    def input_strs(self):
        return self.bits_to_strs(self.flags, MotifWMHints.INPUT_STR)
    def __str__(self):
        return "MotifWMHints(%s)" % {"flags"        : self.flags_strs(),
                                     "functions"    : self.functions_strs(),
                                     "decorations"  : self.decorations_strs(),
                                     "input_mode"   : self.input_strs(),
                                     "status"       : self.status}


def _read_image(disp, stream):
    try:
        header = stream.read(2 * 4)
        if not header:
            return None
        (width, height) = struct.unpack("=II", header)
        data = stream.read(width * height * 4)
        if len(data) < width * height * 4:
            log.warn("Corrupt _NET_WM_ICON")
            return None
    except Exception as e:
        log.warn("Weird corruption in _NET_WM_ICON: %s", e)
        return None
    # Cairo wants a native-endian array here, and since the icon is
    # transmitted as CARDINALs, that's what we get. It might seem more
    # sensible to use ImageSurface.create_for_data (at least it did to me!)
    # but then you end up with a surface that refers to the memory you pass in
    # directly, and also .get_data() doesn't work on it, and it breaks the
    # test suite and blah. This at least works, as odd as it is:
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    # old versions of cairo do not have this method, just ignore it
    if not hasattr(surf, "get_data"):
        log.warn("Your Cairo is too old! Carrying on as best I can, "
                 "but don't expect a miracle")
        return None
    surf.get_data()[:] = data
    # Cairo uses premultiplied alpha. EWMH actually doesn't specify what it
    # uses, but apparently the de-facto standard is non-premultiplied. (At
    # least that's what Compiz's sources say.)
    premultiply_argb_in_place(surf.get_data())
    return (width * height, surf)

# This returns a cairo ImageSurface which contains the largest icon defined in
# a _NET_WM_ICON property.
def NetWMIcons(disp, data):
    icons = []
    stream = StringIOClass(data)
    while True:
        size_image = _read_image(disp, stream)
        if size_image is None:
            break
        icons.append(size_image)
    if not icons:
        return None
    icons.sort()
    return icons[-1][1]

def _get_atom(disp, d):
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

def _to_latin1(disp, v):
    return v.encode("latin1")

def _from_latin1(disp, v):
    return v.decode("latin1")

def _to_utf8(disp, v):
    return v.encode("UTF-8")

def _from_utf8(disp, v):
    return v.decode("UTF-8")


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


def get_python_type(scalar_type):
    #ie: get_python_type("STRING") = "latin1"
    return {"UTF8_STRING"  : "utf8",
            "STRING"       : "latin1",
            "ATOM"         : "atom",
            "CARDINAL"     : "u32",
            "INTEGER"      : "integer",
            "VISUALID"     : "visual",
            "WINDOW"       : "window",
            }.get(scalar_type)

_prop_types = {
    # Python type, X type Atom, formatbits, serializer, deserializer, list
    # terminator
    "utf8": (unicode, "UTF8_STRING", 8, _to_utf8, _from_utf8, b"\0"),
    # In theory, there should be something clever about COMPOUND_TEXT here.  I
    # am not sufficiently clever to deal with COMPOUNT_TEXT.  Even knowing
    # that Xutf8TextPropertyToTextList exists.
    "latin1": (unicode, "STRING", 8, _to_latin1, _from_latin1, b"\0"),
    "atom": (str, "ATOM", 32,
             lambda disp, a: struct.pack("@I", _get_xatom(a)),
              _get_atom,
             b""),
    "state": ((int, long), "WM_STATE", 32,
            lambda disp, c: struct.pack("=I", c),
            lambda disp, d: struct.unpack("=I", d)[0],
            b""),
    "u32": ((int, long), "CARDINAL", 32,
            lambda disp, c: struct.pack("=I", c),
            lambda disp, d: struct.unpack("=I", d)[0],
            b""),
    "integer": ((int, long), "INTEGER", 32,
            lambda disp, c: struct.pack("=I", c),
            lambda disp, d: struct.unpack("=I", d)[0],
            b""),
    "visual": (gdk.Visual, "VISUALID", 32,
               lambda disp, c: struct.pack("=I", get_xvisual(c)),
               unsupported,
               b""),
    "window": (gdk.Window, "WINDOW", 32,
               lambda disp, c: struct.pack("=I", get_xwindow(c)),
               lambda disp, d: get_pywindow(disp, struct.unpack("=I", d)[0]),
               b""),
    "strut": (NetWMStrut, "CARDINAL", 32,
              unsupported, NetWMStrut, None),
    "strut-partial": (NetWMStrut, "CARDINAL", 32,
                      unsupported, NetWMStrut, None),
    "motif-hints": (MotifWMHints, "_MOTIF_WM_HINTS", 32,
              unsupported, MotifWMHints, None),
    "icon": (cairo.ImageSurface, "CARDINAL", 32,
             unsupported, NetWMIcons, None),
    "xsettings-settings": (tuple, "_XSETTINGS_SETTINGS", 8,
                           set_xsettings,
                           get_xsettings,
                           None),
    # For uploading ad-hoc instances of the above complex structures to the
    # server, so we can test reading them out again:
    "debug-CARDINAL": (str, "CARDINAL", 32,
                       lambda disp, c: c,
                       lambda disp, d: d,
                       None),
    # For fetching the extra information on a MULTIPLE clipboard conversion
    # request. The exciting thing about MULTIPLE is that it's not actually
    # specified what 'type' one should use; you just fetch with
    # AnyPropertyType and assume that what you get is a bunch of pairs of
    # atoms.
    "multiple-conversion": (str, 0, 32, unsupported, _get_multiple, None),
    }

def _prop_encode(disp, etype, value):
    if isinstance(etype, list):
        return _prop_encode_list(disp, etype[0], value)
    else:
        return _prop_encode_scalar(disp, etype, value)

def _prop_encode_scalar(disp, etype, value):
    (pytype, atom, formatbits, serialize, _, _) = _prop_types[etype]
    assert isinstance(value, pytype), "value for atom %s is not a %s: %s" % (atom, pytype, type(value))
    return (atom, formatbits, serialize(disp, value))

def _prop_encode_list(disp, etype, value):
    (_, atom, formatbits, _, _, terminator) = _prop_types[etype]
    value = list(value)
    serialized = [_prop_encode_scalar(disp, etype, v)[2] for v in value]
    no_none = [x for x in serialized if x is not None]
    # Strings in X really are null-separated, not null-terminated (ICCCM
    # 2.7.1, see also note in 4.1.2.5)
    return (atom, formatbits, terminator.join(no_none))


def prop_set(target, key, etype, value):
    with xsync:
        X11Window.XChangeProperty(get_xwindow(target), key,
                       _prop_encode(target, etype, value))

def _prop_decode(disp, etype, data):
    if isinstance(etype, list):
        return _prop_decode_list(disp, etype[0], data)
    else:
        return _prop_decode_scalar(disp, etype, data)

def _prop_decode_scalar(disp, etype, data):
    (pytype, _, _, _, deserialize, _) = _prop_types[etype]
    value = deserialize(disp, data)
    assert value is None or isinstance(value, pytype), "expected a %s but value is a %s" % (pytype, type(value))
    return value

def _prop_decode_list(disp, etype, data):
    (_, _, formatbits, _, _, terminator) = _prop_types[etype]
    if terminator:
        datums = data.split(terminator)
    else:
        datums = []
        nbytes = formatbits // 8
        while data:
            datums.append(data[:nbytes])
            data = data[nbytes:]
    props = [_prop_decode_scalar(disp, etype, datum) for datum in datums]
    #assert None not in props
    return [x for x in props if x is not None]

# May return None.
def prop_get(target, key, etype, ignore_errors=False, raise_xerrors=False):
    if isinstance(etype, list):
        scalar_type = etype[0]
    else:
        scalar_type = etype
    (_, atom, _, _, _, _) = _prop_types[scalar_type]
    try:
        with xsync:
            data = X11Window.XGetWindowProperty(get_xwindow(target), key, atom, etype)
        if data is None:
            if not ignore_errors:
                log("Missing property %s (%s)", key, etype)
            return None
    except XError:
        if raise_xerrors:
            raise
        log.info("Missing window %s or wrong property type %s (%s)", target, key, etype, exc_info=True)
        return None
    except PropertyError:
        if not ignore_errors:
            log.info("Missing property or wrong property type %s (%s)", key, etype, exc_info=True)
        return None
    try:
        return _prop_decode(target, etype, data)
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
