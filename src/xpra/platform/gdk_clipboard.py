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

from xpra.platform.clipboard_base import ClipboardProtocolHelperBase, debug


class GDKClipboardProtocolHelper(ClipboardProtocolHelperBase):
    """ This clipboard helper adds the ability to parse raw X11 atoms
        to and from a form suitable for transport over the wire.
    """

    def __init__(self, send_packet_cb):
        ClipboardProtocolHelperBase.__init__(self, send_packet_cb, ["CLIPBOARD", "PRIMARY", "SECONDARY"])

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
                otargets = list(atom_names)
                discard_targets = ("SAVE_TARGETS", "COMPOUND_TEXT")
                for x in discard_targets:
                    if x in atom_names:
                        atom_names.remove(x)
                debug("_do_munge_raw_selection_to_wire(%s, %s, %s, %s:%s) filtered targets(%s)=%s", target, datatype, dataformat, type(data), len(data), otargets, atom_names)
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


class TranslatedClipboardProtocolHelper(GDKClipboardProtocolHelper):
    """
        This implementation of the clipboard helper only has one
        type (aka "selection") of clipboard ("CLIPBOARD" by default)
        and it can convert it to another clipboard name ("PRIMARY")
        when conversing with the other end.
        This is because the server implementation always uses the 3 X11
        clipboards whereas some clients (MS Windows) only have "CLIPBOARD"
        and we generally want to map it to X11's "PRIMARY"...
    """

    def __init__(self, send_packet_cb, local_clipboard="CLIPBOARD", remote_clipboard="PRIMARY"):
        self.local_clipboard = local_clipboard
        self.remote_clipboard = remote_clipboard
        ClipboardProtocolHelperBase.__init__(self, send_packet_cb, [local_clipboard])

    def local_to_remote(self, selection):
        debug("local_to_remote(%s) local_clipboard=%s, remote_clipboard=%s", selection, self.local_clipboard, self.remote_clipboard)
        if selection==self.local_clipboard:
            return  self.remote_clipboard
        return  selection

    def remote_to_local(self, selection):
        debug("remote_to_local(%s) local_clipboard=%s, remote_clipboard=%s", selection, self.local_clipboard, self.remote_clipboard)
        if selection==self.remote_clipboard:
            return  self.local_clipboard
        return  selection
