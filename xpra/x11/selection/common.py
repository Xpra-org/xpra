# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct
from typing import Sequence, Iterable

from xpra.util.str_fn import repr_ellipsized
from xpra.x11.error import xsync


sizeof_long = struct.calcsize(b'@L')


class AlreadyOwned(Exception):
    pass


def xatoms_to_strings(data: bytes) -> Sequence[str]:
    length = len(data)
    if length % sizeof_long != 0:
        raise ValueError(f"invalid length for atom array: {length}, value={repr_ellipsized(data)}")
    natoms = length // sizeof_long
    atoms = struct.unpack(b"@" + b"L" * natoms, data)
    with xsync:
        from xpra.x11.bindings.window import X11WindowBindings
        X11Window = X11WindowBindings()
        return tuple(name for name in (X11Window.get_atom_name(atom) for atom in atoms if atom) if name)


def strings_to_xatoms(data: Iterable[str]) -> bytes:
    with xsync:
        from xpra.x11.bindings.window import X11WindowBindings
        X11Window = X11WindowBindings()
        atom_array = tuple(X11Window.get_xatom(atom) for atom in data if atom)
    return struct.pack(b"@" + b"L" * len(atom_array), *atom_array)


def log_xfixes_error(msg: str) -> None:
    from xpra.util.env import first_time
    from xpra.log import Logger
    log = Logger("x11")
    log("xfixes_error(%s)", msg, exc_info=True)
    if first_time("xfixes"):
        log.warn("Warning: the XFixes extension is not available:")
        log.warn(f" {msg!r}")
        log.warn(" some selection features will be degraded")


def xfixes_selection_input(xid: int, selection: str) -> bool:
    try:
        from xpra.x11.bindings.fixes import XFixesBindings, init_xfixes_events
    except ImportError as e:
        log_xfixes_error(str(e))
        return False
    with xsync:
        xfixes = XFixesBindings()
        if not xfixes.hasXFixes():
            log_xfixes_error("not available")
            return False
        init_xfixes_events()
        xfixes.selectXFSelectionInput(xid, selection)
    return True
