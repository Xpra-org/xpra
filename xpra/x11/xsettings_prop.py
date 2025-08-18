# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
XSETTINGS

This code deals with:
* extracting data from XSETTINGS into nice python data structures
and
* converting those structures back into XSETTINGS format
"""

import sys
import struct
from enum import IntEnum
from typing import Any

from xpra.log import Logger, consume_verbose_argv
from xpra.util.env import envbool
from xpra.util.str_fn import strtobytes, bytestostr, hexstr

log: Logger = Logger("x11", "xsettings")


# undocumented XSETTINGS endianness values:
LITTLE_ENDIAN: int = 0
BIG_ENDIAN: int = 1


def get_local_byteorder() -> int:
    if sys.byteorder == "little":
        return LITTLE_ENDIAN
    return BIG_ENDIAN   # pragma: no cover

# the 3 types of settings supported:


class XSettingsType(IntEnum):
    Integer = 0
    String = 1
    Color = 2


XSettingsNames: dict[int, str] = {
    XSettingsType.Integer: "Integer",
    XSettingsType.String: "String",
    XSettingsType.Color: "Color",
}


XSETTINGS_CACHE: tuple[int, list[tuple]] = (0, [])


def bytes_to_xsettings(d: bytes) -> tuple[int, list[tuple[int, str, Any, int]]]:
    global XSETTINGS_CACHE
    DEBUG_XSETTINGS = envbool("XPRA_XSETTINGS_DEBUG", False)
    # parse xsettings according to
    # http://standards.freedesktop.org/xsettings-spec/xsettings-spec-0.5.html
    assert len(d) >= 12, "_XSETTINGS_SETTINGS property is too small: %s" % len(d)
    if DEBUG_XSETTINGS:
        log("bytes_to_xsettings(%s)", tuple(d))
    byte_order, _, _, _, serial, n_settings = struct.unpack(b"=BBBBII", d[:12])
    cache = XSETTINGS_CACHE
    log("bytes_to_xsettings(..) found byte_order=%s (local is %s), serial=%s, n_settings=%s, cache=%s",
        byte_order, get_local_byteorder(), serial, n_settings, cache)
    if cache and cache[0] == serial:
        log("bytes_to_xsettings(..) returning value from cache")
        return cache
    settings: list[tuple] = []
    pos = 12

    def req(what="int", nbytes=4):
        remain = len(d) - pos
        if remain < nbytes:
            raise ValueError(f"not enough data ({remain} bytes) to extract {what} ({nbytes} bytes needed)")

    while n_settings > len(settings):
        log("bytes_to_xsettings(..) pos=%i (len=%i), data=%s", pos, len(d), hexstr(d[pos:]))
        istart = pos
        # parse header:
        req("setting", 4)
        setting_type, _, name_len = struct.unpack(b"=BBH", d[pos:pos+4])
        pos += 4
        # extract property name:
        prop_name = d[pos:pos+name_len]
        pos += (name_len + 0x3) & ~0x3
        # serial:
        req("serial", 4)
        last_change_serial = struct.unpack(b"=I", d[pos:pos+4])[0]
        pos += 4
        if DEBUG_XSETTINGS:
            log("bytes_to_xsettings(..) found property %s of type %s, serial=%s",
                prop_name, XSettingsNames.get(setting_type, "INVALID!"), last_change_serial)
        # extract value:

        def add(value):
            setting = setting_type, prop_name, value, last_change_serial
            if DEBUG_XSETTINGS:
                log("bytes_to_xsettings(..) %s -> %s", tuple(d[istart:pos]), setting)
            settings.append(setting)
        if setting_type == XSettingsType.Integer:
            req("int", 4)
            add(int(struct.unpack(b"=I", d[pos:pos+4])[0]))
            pos += 4
        elif setting_type == XSettingsType.String:
            req("string length", 4)
            value_len = struct.unpack(b"=I", d[pos:pos+4])[0]
            pos += 4
            req("string", value_len)
            add(d[pos:pos+value_len])
            pos += (value_len + 0x3) & ~0x3
        elif setting_type == XSettingsType.Color:
            req("color", 8)
            red, blue, green, alpha = struct.unpack(b"=HHHH", d[pos:pos+8])
            add((red, blue, green, alpha))
            pos += 8
        else:
            log.error("invalid setting type: %s, cannot continue parsing XSETTINGS!", setting_type)
            break
    log(f"bytes_to_xsettings(..) {serial=} ,{settings=}")
    XSETTINGS_CACHE = (serial, settings)
    return serial, settings


def xsettings_to_bytes(d: tuple[int, list[tuple[int, str, Any, int]]]) -> bytes:
    if len(d) != 2:
        raise ValueError(f"invalid format for XSETTINGS: {d!r}")
    serial, settings = d
    log("xsettings_to_bytes(%s) serial=%s, %s settings", d, serial, len(settings))
    all_bin_settings = []
    for setting in settings:
        setting_type, prop_name, value, last_change_serial = setting
        prop_name = strtobytes(prop_name)
        try:
            log("xsettings_to_bytes(..) processing property %r of type %s",
                prop_name, XSettingsNames.get(setting_type, "INVALID!"))
            x = struct.pack(b"=BBH", setting_type, 0, len(prop_name))
            x += prop_name
            pad_len = ((len(prop_name) + 0x3) & ~0x3) - len(prop_name)
            x += b'\0'*pad_len
            x += struct.pack(b"=I", last_change_serial)
            if setting_type == XSettingsType.Integer:
                assert isinstance(value, int), f"invalid value type: integer wanted, not {type(value)}"
                x += struct.pack(b"=I", int(value))
            elif setting_type == XSettingsType.String:
                value = strtobytes(value)
                x += struct.pack(b"=I", len(value))
                x += value
                pad_len = ((len(value) + 0x3) & ~0x3) - len(value)
                x += b'\0'*pad_len
            elif setting_type == XSettingsType.Color:
                red, blue, green, alpha = value
                x += struct.pack(b"=HHHH", red, blue, green, alpha)
            else:
                log.error("Error: invalid type %i for xsetting property '%s'", setting_type, bytestostr(prop_name))
                continue
            log("xsettings_to_bytes(..) %s -> %s", setting, tuple(x))
            all_bin_settings.append(x)
        except Exception as e:
            log("xsettings_to_bytes(%s)", d, exc_info=True)
            log.error("Error processing XSettings property %s:", bytestostr(prop_name))
            log.error(" type=%s, value=%s", XSettingsNames.get(setting_type, "INVALID!"), value)
            log.estr(e)
    # header
    v = struct.pack(b"=BBBBII", get_local_byteorder(), 0, 0, 0, serial, len(all_bin_settings))
    v += b"".join(all_bin_settings)  # values
    v += b'\0'                       # null terminated
    log("xsettings_to_bytes(%s)=%s", d, tuple(v))
    return v


def main() -> int:  # pragma: no cover
    # pylint: disable=import-outside-toplevel
    from xpra.platform.gui import init as gui_init
    from xpra.os_util import POSIX
    from xpra.platform import program_context
    from xpra.x11.error import xsync
    with program_context("XSettings"):
        gui_init()
        consume_verbose_argv(sys.argv, "all")

        # naughty, but how else can I hook this up?
        if not POSIX:
            print("xsettings require a posix OS")
            return 1

        with xsync:
            from xpra.x11.bindings.display_source import init_display_source
            init_display_source()
            from xpra.x11.bindings.window import X11WindowBindings
            window_bindings = X11WindowBindings()
            selection = "_XSETTINGS_S0"
            owner = window_bindings.XGetSelectionOwner(selection)
            print(f"owner({selection})={owner:x}")
            XSETTINGS = "_XSETTINGS_SETTINGS"
            if owner:
                data = window_bindings.XGetWindowProperty(owner, XSETTINGS, XSETTINGS)
                serial, settings = bytes_to_xsettings(data)
                print(f"serial={serial}")
                print(f"{len(settings)} settings:")
                for s in settings:
                    print(s)
            return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
