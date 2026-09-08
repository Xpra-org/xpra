# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct
from typing import Sequence, Iterable

from xpra.util.str_fn import repr_ellipsized
from xpra.x11.error import xsync
from xpra.log import Logger

log = Logger("x11", "util")


sizeof_long = struct.calcsize(b'@L')


class AlreadyOwned(Exception):
    pass


def x11_event_loop_running() -> bool:
    """ True when the X11 event loop is already routing events - see `x11.subsystem.x11init` """
    try:
        from xpra.x11.bindings import loop
    except ImportError:
        return False
    return bool(loop.loop)


def gtk_event_window(xid: int):
    """
        gtk's wrapper for one of our event windows, or None when gtk is not the one
        routing our X11 events. Servers pump them from `x11.bindings.loop` instead,
        and must not load the gtk bindings at all.
        Nothing ever uses the value: it exists so that gtk's own lookup of the window
        keeps working for the events it processes after ours - see the callers.
    """
    if x11_event_loop_running():
        return None
    try:
        # `gtk_get_pywindow` only loads the gtk bindings when it is called, so the call has
        # to be guarded too; and importing the package runs its `__init__`, which injects
        # gtk's lookup into `xpra.x11.common` - neither may happen on a server:
        from xpra.x11.gtk import gtk_get_pywindow
        return gtk_get_pywindow(xid)
    except ImportError:
        # a process which cannot load the gtk bindings is not using them for routing
        log("gtk_event_window(%#x)", xid, exc_info=True)
        return None


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
