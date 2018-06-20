# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct

from xpra.util import envbool
from xpra.gtk_common.gobject_compat import is_gtk3
from xpra.clipboard.clipboard_base import ClipboardProtocolHelperBase, _filter_targets, log

try:
    if is_gtk3():
        from xpra.gtk_common.gtk3 import gdk_atoms  #@UnresolvedImport, @UnusedImport
    else:
        from xpra.gtk_common.gtk2 import gdk_atoms  #@UnresolvedImport, @Reimport
except ImportError as e:
    log.error("Error: gdk atoms library not found:")
    log.error(" %s", e)
    del e
    gdk_atoms = None
SANITIZE_GTKSELECTIONDATA = envbool("XPRA_SANITIZE_GTKSELECTIONDATA", True)
if not is_gtk3() and SANITIZE_GTKSELECTIONDATA:
    try:
        from xpra.gtk_common.gtk2.gdk_bindings import sanitize_gtkselectiondata
        from xpra.clipboard import clipboard_base
        clipboard_base.sanitize_gtkselectiondata = sanitize_gtkselectiondata
    except ImportError as e:
        log.error("Error: sanitize_gtkselectiondata not found:")
        log.error(" %s", e)
        del e


class GDKClipboardProtocolHelper(ClipboardProtocolHelperBase):
    """ This clipboard helper adds the ability to parse raw X11 atoms
        to and from a form suitable for transport over the wire.
    """

    def __repr__(self):
        return "GDKClipboardProtocolHelper"


    def _do_munge_raw_selection_to_wire(self, target, datatype, dataformat, data):
        if dataformat==32 and datatype in (b"ATOM", b"ATOM_PAIR") and gdk_atoms:
            # Convert to strings and send that. Bizarrely, the atoms are
            # not actual X atoms, but an array of GdkAtom's reinterpreted
            # as a byte buffer.
            atoms = gdk_atoms.gdk_atom_objects_from_gdk_atom_array(data)
            log("_do_munge_raw_selection_to_wire(%s, %s, %s, %s:%s) atoms=%s", target, datatype, dataformat, type(data), len(data), tuple(atoms))
            atom_names = [str(atom) for atom in atoms]
            if target==b"TARGETS":
                atom_names = _filter_targets(atom_names)
            return "atoms", atom_names
        return ClipboardProtocolHelperBase._do_munge_raw_selection_to_wire(self, target, datatype, dataformat, data)

    def _munge_wire_selection_to_raw(self, encoding, datatype, dataformat, data):
        if encoding==b"atoms" and gdk_atoms:
            atom_array = gdk_atoms.gdk_atom_array_from_atoms(data)
            bdata = struct.pack("@" + "L" * len(atom_array), *atom_array)
            log("_munge_wire_selection_to_raw(%s, %s, %s, %s:%s)=%s=%s=%s", encoding, datatype, dataformat, type(data), len(data or ""), data, atom_array, tuple(bdata))
            return bdata
        return ClipboardProtocolHelperBase._munge_wire_selection_to_raw(self, encoding, datatype, dataformat, data)
