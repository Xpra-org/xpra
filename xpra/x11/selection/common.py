# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct
from enum import Enum
from typing import Sequence, Iterable

from xpra.util.str_fn import repr_ellipsized
from xpra.x11.error import xsync


sizeof_long = struct.calcsize(b'@L')


class AlreadyOwned(Exception):
    pass


class Ownership(Enum):
    # If the selection is already owned, then raise AlreadyOwned rather
    # than stealing it.
    IF_UNOWNED = 1
    # If the selection is already owned, then steal it, and then block until
    # the previous owner has signaled that they are done cleaning up.
    FORCE = 2
    # If the selection is already owned, then steal it and return immediately.
    # Created for the use of tests.
    FORCE_AND_RETURN = 3


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
