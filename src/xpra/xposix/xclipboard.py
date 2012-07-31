# This file is part of Parti.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct

from wimpiggy.lowlevel import (gdk_atom_objects_from_gdk_atom_array, #@UnresolvedImport
                               gdk_atom_array_from_gdk_atom_objects) #@UnresolvedImport

from xpra.platform.clipboard_base import ClipboardProtocolHelperBase, debug

class ClipboardProtocolHelper(ClipboardProtocolHelperBase):
    """ This clipboard helper adds the ability to parse raw X11 atoms
        to and from a form suitable for transport over the wire.
    """

    def __init__(self, send_packet_cb):
        ClipboardProtocolHelperBase.__init__(self, send_packet_cb, ["CLIPBOARD", "PRIMARY", "SECONDARY"])

    def _do_munge_raw_selection_to_wire(self, target, datatype, dataformat, data):
        if dataformat == 32 and datatype in ("ATOM", "ATOM_PAIR"):
            # Convert to strings and send that. Bizarrely, the atoms are
            # not actual X atoms, but an array of GdkAtom's reinterpreted
            # as a byte buffer.
            atoms = gdk_atom_objects_from_gdk_atom_array(data)
            atom_names = [str(atom) for atom in atoms]
            debug("_do_munge_raw_selection_to_wire(%s, %s, %s, %s:%s) atoms=%s, atom_names=%s", target, datatype, dataformat, type(data), len(data), atoms, atom_names)
            if target=="TARGET":
                atom_names.remove("SAVE_TARGETS")
                atom_names.remove("COMPOUND_TEXT")
            return "atoms", atom_names
        return ClipboardProtocolHelperBase._do_munge_raw_selection_to_wire(self, target, datatype, dataformat, data)

    def _munge_wire_selection_to_raw(self, encoding, datatype, dataformat, data):
        debug("_munge_wire_selection_to_raw(%s, %s, %s, %s:%s)", encoding, datatype, dataformat, type(data), len(data or ""))
        if encoding == "atoms":
            import gtk.gdk
            gdk_atoms = [gtk.gdk.atom_intern(a) for a in data]
            atom_array = gdk_atom_array_from_gdk_atom_objects(gdk_atoms)
            return struct.pack("=" + "L" * len(atom_array), *atom_array)
        return ClipboardProtocolHelperBase._munge_wire_selection_to_raw(self, encoding, datatype, dataformat, data)
