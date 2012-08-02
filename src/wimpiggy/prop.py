# This file is part of Parti.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""All the goo needed to deal with X properties.

Everyone else should just use prop_set/prop_get with nice clean Python calling
conventions, and if you need more (un)marshalling smarts, add them here."""

import traceback
import struct
try:
    from StringIO import StringIO   #@UnresolvedImport @UnusedImport
except:
    from io import StringIO         #@Reimport
import gtk.gdk
import cairo
from wimpiggy.lowlevel import (
                XGetWindowProperty,         #@UnresolvedImport
                XChangeProperty,            #@UnresolvedImport
                NoSuchProperty,             #@UnresolvedImport
                PropertyError,              #@UnresolvedImport
                get_xatom, get_pyatom,      #@UnresolvedImport
                get_xwindow, get_pywindow,  #@UnresolvedImport
                const,                      #@UnresolvedImport
                premultiply_argb_in_place   #@UnresolvedImport
               )
from wimpiggy.error import trap, XError
from wimpiggy.log import Logger
log = Logger()

import sys
if sys.version > '3':
    long = int              #@ReservedAssignment
    unicode = str           #@ReservedAssignment


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

class WMSizeHints(object):
    def __init__(self, disp, data):
        # pre-ICCCM size is 15
        data = _force_length("WM_SIZE_HINTS", data, 18*4, noerror_length=15*4)
        (flags,
         pad1, pad2, pad3, pad4,            #@UnusedVariable
         min_width, min_height,
         max_width, max_height,
         width_inc, height_inc,
         min_aspect_num, min_aspect_denom,
         max_aspect_num, max_aspect_denom,
         base_width, base_height,
         win_gravity) = struct.unpack("=" + "I" * 18, data) #@UnusedVariable
        #print(repr(data))
        #print(struct.unpack("@" + "i" * 18, data))
        # We only extract the pieces we care about:
        if flags & const["PMaxSize"]:
            self.max_size = (max_width, max_height)
        else:
            self.max_size = None
        if flags & const["PMinSize"]:
            self.min_size = (min_width, min_height)
        else:
            self.min_size = None
        if flags & const["PBaseSize"]:
            self.base_size = (base_width, base_height)
        else:
            self.base_size = None
        if flags & const["PResizeInc"]:
            self.resize_inc = (width_inc, height_inc)
        else:
            self.resize_inc = None
        if flags & const["PAspect"]:
            self.min_aspect = min_aspect_num * 1.0 / min_aspect_denom
            self.min_aspect_ratio = (min_aspect_num, min_aspect_denom)
            self.max_aspect = max_aspect_num * 1.0 / max_aspect_denom
            self.max_aspect_ratio = (max_aspect_num,  max_aspect_denom)
        else:
            self.min_aspect, self.max_aspect = (None, None)
            self.min_aspect_ratio, self.max_aspect_ratio = (None, None)

class WMHints(object):
    def __init__(self, disp, data):
        data = _force_length("WM_HINTS", data, 9 * 4)
        (flags, _input, initial_state,  #@UnusedVariable
         icon_pixmap, icon_window,      #@UnusedVariable
         icon_x, icon_y, icon_mask,     #@UnusedVariable
         window_group) = struct.unpack("=" + "i" * 9, data)
        # NB the last field is missing from at least some ICCCM 2.0's (typo).
        # FIXME: extract icon stuff too
        self.urgency = bool(flags & const["XUrgencyHint"])
        if flags & const["WindowGroupHint"]:
            self.group_leader = window_group
        else:
            self.group_leader = None
        if flags & const["StateHint"]:
            self.start_iconic = (initial_state == const["IconicState"])
        else:
            self.start_iconic = None
        if flags & const["InputHint"]:
            self.input = input
        else:
            self.input = None

class NetWMStrut(object):
    def __init__(self, disp, data):
        # This eats both _NET_WM_STRUT and _NET_WM_STRUT_PARTIAL.  If we are
        # given a _NET_WM_STRUT instead of a _NET_WM_STRUT_PARTIAL, then it
        # will be only length 4 instead of 12, but _force_length will zero-pad
        # and _NET_WM_STRUT is *defined* as a _NET_WM_STRUT_PARTIAL where the
        # extra fields are zero... so it all works out.
        data = _force_length("_NET_WM_STRUT or _NET_WM_STRUT_PARTIAL", data, 4 * 12)
        (self.left, self.right, self.top, self.bottom,
         self.left_start_y, self.left_end_y,
         self.right_start_y, self.right_end_y,
         self.top_start_x, self.top_end_x,
         self.bottom_start_x, self.bottom_stop_x,
         ) = struct.unpack("=" + "I" * 12, data)

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
    except Exception, e:
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
    stream = StringIO(data)
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
    unpacked = struct.unpack("=I", d)[0]
    pyatom = get_pyatom(disp, unpacked)
    if not pyatom:
        log.error("invalid atom: %s - %s", repr(d), repr(unpacked))
        return  None
    return str(pyatom)

def _get_multiple(disp, d):
    uint_struct = struct.Struct("=I")
    log("get_multiple struct size=%s, len(%s)=%s", uint_struct.size, d, len(d))
    if len(d)!=uint_struct.size and False:
        log.info("get_multiple value is not an atom: %s", d)
        return  str(d)
    return _get_atom(disp, d)

#undocumented XSETTINGS values:
LITTLE_ENDIAN = 0
BIG_ENDIAN    = 1
def get_local_byteorder():
    if sys.byteorder=="little":
        return  LITTLE_ENDIAN
    else:
        return  BIG_ENDIAN

def parse_xsettings(d):
    #parse xsettings according to
    #http://standards.freedesktop.org/xsettings-spec/xsettings-spec-0.5.html
    assert len(d)>=12, "_XSETTINGS_SETTINGS property is too small: %s" % len(d)
    log("parse_xsettings(%s)", list(d))    
    byte_order, _, _, _, serial, n_settings = struct.unpack("=BBBBII", d[:12])
    log("parse_xsettings(..) found byte_order=%s (local is %s), serial=%s, n_settings=%s", byte_order, get_local_byteorder(), serial, n_settings)
    settings = []
    pos = 12
    while n_settings>len(settings) and len(d)>0:
        istart = pos
        #parse header:
        setting_type, _, name_len = struct.unpack("=BBH", d[pos:pos+4])
        pos += 4
        #extract property name:
        prop_name = d[pos:pos+name_len]
        pos += (name_len + 0x3) & ~0x3
        #serial:
        last_change_serial = struct.unpack("=I", d[pos:pos+4])[0]
        pos += 4
        log("parse_xsettings(..) found property %s of type %s, serial=%s", prop_name, setting_type, last_change_serial)
        #extract value:
        if setting_type==0:     #XSettingsTypeInteger
            value = struct.unpack("=I", d[pos:pos+4])[0]
            pos += 4
        elif setting_type==1:   #XSettingsTypeString
            value_len = struct.unpack("=I", d[pos:pos+4])[0]
            value = d[pos+4:pos+4+value_len]
            pos += 4 + ((value_len + 0x3) & ~0x3)
        elif setting_type==2:   #XSettingsTypeColor
            red, blue, green, alpha = struct.unpack("=HHHH", d[pos:pos+8])
            value = (red, blue, green, alpha)
            pos += 8
        else:
            log.error("invalid setting type: %s, cannot continue parsing XSETTINGS!", setting_type)
            break
        setting = setting_type, prop_name, value, last_change_serial
        log("parse_xsettings(..) %s -> %s", list(d[istart:pos]), setting)
        settings.append(setting)
    log("parse_xsettings(..) settings=%s", settings)
    return  serial, settings

def format_xsettings(d):
    #TODO: detect old clients
    assert len(d)==2, "invalid format for XSETTINGS: %s" % str(d)
    serial, settings = d
    log("format_xsettings(%s) serial=%s, %s settings", d, serial, len(settings))
    a = struct.pack("=BBBBII", get_local_byteorder(), 0, 0, 0, serial, len(settings))
    for setting in settings:
        setting_type, prop_name, value, last_change_serial = setting
        x = b''
        x += struct.pack("=BBH", setting_type, 0, len(prop_name))
        x += struct.pack("="+"s"*len(prop_name), *list(prop_name))
        pad_len = ((len(prop_name) + 0x3) & ~0x3) - len(prop_name)
        x += '\0'*pad_len
        x += struct.pack("=I", last_change_serial)
        if setting_type==0:     #XSettingsTypeInteger
            assert type(value)==int
            x += struct.pack("=I", value)
        elif setting_type==1:   #XSettingsTypeString
            assert type(value)==str
            x += struct.pack("=I", len(value))
            x += struct.pack("="+"s"*len(value), *list(value))
            pad_len = ((len(value) + 0x3) & ~0x3) - len(value)
            x += '\0'*pad_len
        elif setting_type==2:   #XSettingsTypeColor
            red, blue, green, alpha = value
            x = struct.pack("=HHHH", red, blue, green, alpha)
        else:
            log.error("invalid xsetting type: %s, cannot continue parsing XSETTINGS!", setting_type)
            break
        log("format_xsettings(..) %s -> %s", setting, list(x))
        a += x
    a += '\0'
    log("format_xsettings(%s)=%s", d, list(a))
    return  a

def set_xsettings_format(use_tuple=True):
    log("set_xsettings_format(%s)", use_tuple)
    global _prop_types
    if use_tuple:
        _prop_types["xsettings-settings"] = (tuple, "_XSETTINGS_SETTINGS", 8,
                           lambda disp, c: format_xsettings(c),
                           lambda disp, d: parse_xsettings(d),
                           None)
    else:
        #for old clients that rely on the old string format:
        _prop_types["xsettings-settings"] = (str, "_XSETTINGS_SETTINGS", 8,
                           lambda disp, c: c,
                           lambda disp, d: d,
                           None)


_prop_types = {
    # Python type, X type Atom, formatbits, serializer, deserializer, list
    # terminator
    "utf8": (unicode, "UTF8_STRING", 8,
             lambda disp, u: u.encode("UTF-8"),
             lambda disp, d: d.decode("UTF-8"),
             "\0"),
    # In theory, there should be something clever about COMPOUND_TEXT here.  I
    # am not sufficiently clever to deal with COMPOUNT_TEXT.  Even knowing
    # that Xutf8TextPropertyToTextList exists.
    "latin1": (unicode, "STRING", 8,
               lambda disp, u: u.encode("latin1"),
               lambda disp, d: d.decode("latin1"),
               "\0"),
    "atom": (str, "ATOM", 32,
             lambda disp, a: struct.pack("=I", get_xatom(a)),
              _get_atom,
             ""),
    "u32": ((int, long), "CARDINAL", 32,
            lambda disp, c: struct.pack("=I", c),
            lambda disp, d: struct.unpack("=I", d)[0],
            ""),
    "window": (gtk.gdk.Window, "WINDOW", 32,
               lambda disp, c: struct.pack("=I", get_xwindow(c)),
               lambda disp, d: get_pywindow(disp, struct.unpack("=I", d)[0]),
               ""),
    "wm-size-hints": (WMSizeHints, "WM_SIZE_HINTS", 32,
                      unsupported,
                      WMSizeHints,
                      None),
    "wm-hints": (WMHints, "WM_HINTS", 32,
                 unsupported,
                 WMHints,
                 None),
    "strut": (NetWMStrut, "CARDINAL", 32,
              unsupported, NetWMStrut, None),
    "strut-partial": (NetWMStrut, "CARDINAL", 32,
                      unsupported, NetWMStrut, None),
    "icon": (cairo.ImageSurface, "CARDINAL", 32,
             unsupported, NetWMIcons, None),
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
set_xsettings_format(True)

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
    trap.call_unsynced(XChangeProperty, target, key,
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
def prop_get(target, key, etype, ignore_errors=False):
    if isinstance(etype, list):
        scalar_type = etype[0]
    else:
        scalar_type = etype
    (_, atom, _, _, _, _) = _prop_types[scalar_type]
    try:
        #print(atom)
        data = trap.call_synced(XGetWindowProperty, target, key, atom)
        #print(atom, repr(data[:100]))
    except NoSuchProperty:
        log.debug("Missing property %s (%s)", key, etype)
        return None
    except (XError, PropertyError):
        if not ignore_errors:
            log.info("Missing window or missing property or wrong property type %s (%s)", key, etype)
            traceback.print_exc()
        return None
    try:
        return _prop_decode(target, etype, data)
    except:
        log.warn("Error parsing property %s (type %s); this may be a"
                 + " misbehaving application, or bug in Wimpiggy\n"
                 + "  Data: %r[...?]",
                 key, etype, data[:160])
        if not ignore_errors:
            traceback.print_exc()
        raise
