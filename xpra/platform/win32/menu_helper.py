# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import struct
from typing import Any
from collections.abc import Sequence

from xpra.platform.win32 import get_common_startmenu_dir, get_startmenu_dir
from xpra.log import Logger
from xpra.util.str_fn import print_nested_dict

log = Logger("exec")


def parse_link(content: bytes) -> str:
    # skip first 20 bytes (HeaderSize and LinkCLSID)
    # read the LinkFlags structure (4 bytes)
    lflags = struct.unpack('I', content[0x14:0x18])[0]
    position = 0x18
    # if the HasLinkTargetIDlist bit is set then skip the stored IDlist
    # structure and header
    if (lflags & 0x01) == 1:
        position = struct.unpack('H', content[0x4C:0x4E])[0] + 0x4E
    last_pos = position
    position += 0x04
    # get how long the file information is (LinkInfoSize)
    length = struct.unpack('I', content[last_pos:position])[0]
    # skip 12 bytes (LinkInfoHeaderSize, LinkInfoFlags, and VolumeIDOffset)
    position += 0x0C
    # go to the LocalBasePath position
    lbpos = struct.unpack('I', content[position:position + 0x04])[0]
    position = last_pos + lbpos
    # read the string at the given position of the determined length
    size = (length + last_pos) - position - 0x02
    temp = struct.unpack('c' * size, content[position:position + size])
    return ''.join([chr(ord(a)) for a in temp])


def read_link(path: str) -> str:
    try:
        with open(path, "rb") as stream:
            content = stream.read()
    except OSError:
        log(f"read_link({path!r})", exc_info=True)
        return ""
    try:
        return parse_link(content)
    except Exception as e:
        log("error parsing '%s': %s", path, e)
        return ""


def listdir(d) -> Sequence[str]:
    if not d:
        return ()
    try:
        return os.listdir(d)
    except PermissionError as e:
        log("listdir(%s)", d, exc_info=True)
        log.warn(f"Warning: cannot access directory {d!r}")
        log.warn(f" {e}")
        return ()


def load_subdir(d: str) -> dict[str, dict[str, str]]:
    # recurse down directories
    # and return a dictionary of entries
    menu = {}
    for x in listdir(d):
        if x.endswith(".ini"):
            continue
        name = os.path.join(d, x)
        if os.path.isdir(name):
            menu.update(load_subdir(name))
        elif name.endswith(".lnk"):
            exe = read_link(name)
            if exe:
                menu[x[:-4]] = {
                    "command": exe,
                }
    return menu


def load_dir(d: str) -> dict[str, dict[str, Any]]:
    log("load_dir(%s)", d)
    menu = {}
    for x in listdir(d):
        log(f" {x}")
        if x.endswith(".ini"):
            continue
        name = os.path.join(d, x)
        if os.path.isdir(name):
            subdirmenu = load_subdir(name)
            if subdirmenu:
                menu[x] = {
                    "Entries": subdirmenu,
                }
        elif name.endswith(".lnk"):
            # add them to the "Shortcuts" submenu:
            exe = read_link(name)
            if exe:
                menu.setdefault("Shortcuts", {}).setdefault("Entries", {})[x[:-4]] = {
                    "command": exe,
                }
    return menu


def load_menu() -> dict[str, dict[str, Any]]:
    menu = {}
    for menu_dir in (get_common_startmenu_dir(), get_startmenu_dir()):
        # ie: "C:\ProgramData\Microsoft\Windows\Start Menu"
        for x in listdir(menu_dir):
            subdir = os.path.join(menu_dir, x)
            if os.path.isdir(subdir):
                # ie: "C:\ProgramData\Microsoft\Windows\Start Menu\Programs"
                m = load_dir(subdir)
                if not m:
                    continue
                # TODO: recursive merge
                for k, v in m.items():
                    ev = menu.get(k)
                    if isinstance(ev, dict):
                        ev.update(v)
                    else:
                        menu[k] = v
    return menu


def main() -> None:
    # pylint: disable=import-outside-toplevel
    from xpra.platform import program_context
    with program_context("menu-helper", "Menu Helper"):
        menu = load_menu()
        print_nested_dict(menu)


if __name__ == "__main__":
    main()
