# This file is part of Parti.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct

from wimpiggy.gdk.gdk_atoms import (
                gdk_atom_objects_from_gdk_atom_array,   #@UnresolvedImport
                gdk_atom_array_from_gdk_atom_objects    #@UnresolvedImport
                )

from xpra.platform.clipboard_base import ClipboardProtocolHelperBase, CLIPBOARDS, debug


class GDKClipboardProtocolHelper(ClipboardProtocolHelperBase):
    """ This clipboard helper adds the ability to parse raw X11 atoms
        to and from a form suitable for transport over the wire.
    """

    def __init__(self, send_packet_cb, progress_cb=None, clipboards=CLIPBOARDS, filter_res=None):
        ClipboardProtocolHelperBase.__init__(self, send_packet_cb, progress_cb, clipboards, filter_res)

    def _do_munge_raw_selection_to_wire(self, target, datatype, dataformat, data):
        if dataformat == 32 and datatype in ("ATOM", "ATOM_PAIR"):
            debug("_do_munge_raw_selection_to_wire(%s, %s, %s, %s:%s:%s) using gdk atom code", target, datatype, dataformat, type(data), len(data), list(data))
            # Convert to strings and send that. Bizarrely, the atoms are
            # not actual X atoms, but an array of GdkAtom's reinterpreted
            # as a byte buffer.
            atoms = gdk_atom_objects_from_gdk_atom_array(data)
            debug("_do_munge_raw_selection_to_wire(%s, %s, %s, %s:%s) atoms=%s", target, datatype, dataformat, type(data), len(data), list(atoms))
            atom_names = [str(atom) for atom in atoms]
            debug("_do_munge_raw_selection_to_wire(%s, %s, %s, %s:%s) atom_names=%s", target, datatype, dataformat, type(data), len(data), atom_names)
            if target=="TARGETS":
                atom_names = self._filter_targets(atom_names)
            return "atoms", atom_names
        return ClipboardProtocolHelperBase._do_munge_raw_selection_to_wire(self, target, datatype, dataformat, data)

    def _munge_wire_selection_to_raw(self, encoding, datatype, dataformat, data):
        debug("_munge_wire_selection_to_raw(%s, %s, %s, %s:%s:%s)", encoding, datatype, dataformat, type(data), len(data or ""), list(data or ""))
        if encoding == "atoms":
            import gtk.gdk
            gdk_atoms = [gtk.gdk.atom_intern(a) for a in data]
            atom_array = gdk_atom_array_from_gdk_atom_objects(gdk_atoms)
            bdata = struct.pack("=" + "Q" * len(atom_array), *atom_array)
            debug("_munge_wire_selection_to_raw(%s, %s, %s, %s:%s)=%s=%s=%s", encoding, datatype, dataformat, type(data), len(data or ""), gdk_atoms, atom_array, list(bdata))
            return bdata
        return ClipboardProtocolHelperBase._munge_wire_selection_to_raw(self, encoding, datatype, dataformat, data)
