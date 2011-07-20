# This file is part of Parti.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct
import gobject
import gtk

from wimpiggy.util import n_arg_signal
from wimpiggy.prop import prop_get
from wimpiggy.error import trap
from wimpiggy.lowlevel import (get_xatom, get_pywindow, #@UnresolvedImport
                               gdk_atom_objects_from_gdk_atom_array) #@UnresolvedImport

from wimpiggy.log import Logger
log = Logger()

from xpra.nested_main import NestedMainLoop

class ClipboardProtocolHelper(object):
    def __init__(self, send_packet_cb):
        self.send = send_packet_cb
        self._clipboard_proxies = {}
        for clipboard in ("CLIPBOARD", "PRIMARY", "SECONDARY"):
            proxy = ClipboardProxy(clipboard)
            proxy.connect("send-clipboard-token",
                          self._send_clipboard_token_handler)
            proxy.connect("get-clipboard-from-remote",
                          self._get_clipboard_from_remote_handler)
            proxy.show()
            self._clipboard_proxies[clipboard] = proxy
        self._clipboard_request_counter = 0
        self._clipboard_outstanding_requests = {}

    # Used by the client during startup:
    def send_all_tokens(self):
        for selection in self._clipboard_proxies:
            self.send(["clipboard-token", selection])

    def _process_clipboard_token(self, packet):
        (_, selection) = packet
        if selection in self._clipboard_proxies:
            self._clipboard_proxies[selection].got_token()

    def _get_clipboard_from_remote_handler(self, proxy, selection, target):
        request_id = self._clipboard_request_counter
        self._clipboard_request_counter += 1
        loop = NestedMainLoop()
        self._clipboard_outstanding_requests[request_id] = loop
        self.send(["clipboard-request", request_id, selection, target])
        result = loop.main(1 * 1000, 2 * 1000)
        del self._clipboard_outstanding_requests[request_id]
        return result

    def _clipboard_got_contents(self, request_id, type, format, data):
        if request_id in self._clipboard_outstanding_requests:
            loop = self._clipboard_outstanding_requests[request_id]
            loop.done({"type": type, "format": format, "data": data})
        else:
            log("got unexpected response to clipboard request %s", request_id)

    def _send_clipboard_token_handler(self, proxy, selection):
        self.send(["clipboard-token", selection])

    def _munge_raw_selection_to_wire(self, type, format, data):
        # Some types just cannot be marshalled:
        if type in ("WINDOW", "PIXMAP", "BITMAP", "DRAWABLE",
                    "PIXEL", "COLORMAP"):
            return (None, None)
        # Other types need special handling, and all types need to be
        # converting into an endian-neutral format:
        if format == 32:
            if type in ("ATOM", "ATOM_PAIR"):
                # Convert to strings and send that. Bizarrely, the atoms are
                # not actual X atoms, but an array of GdkAtom's reinterpreted
                # as a byte buffer.
                atoms = gdk_atom_objects_from_gdk_atom_array(data)
                return ("atoms", [str(atom) for atom in atoms])
            else:
                sizeof_long = struct.calcsize("@L")
                format = "@" + "L" * (len(data) // sizeof_long)
                ints = struct.unpack(format, data)
                return ("integers", ints)
        elif format == 16:
            sizeof_short = struct.calcsize("@H")
            assert sizeof_short == 16
            format = "@" + "H" * (len(data) // sizeof_short)
            return ("integers", struct.unpack(format, data))
        elif format == 8:
            return ("bytes", data)
        else:
            log("unhandled format %s for clipboard data type %s" % (format, type))
            return (None, None)

    def _munge_wire_selection_to_raw(self, encoding, type, format, data):
        if encoding == "bytes":
            return data
        elif encoding == "atoms":
            d = gtk.gdk.display_get_default()
            ints = [get_xatom(d, a) for a in data]
            return struct.pack("@" + "L" * len(ints), *ints)
        elif encoding == "integers":
            if format == 32:
                format_char = "L"
            elif format == 16:
                format_char = "H"
            elif format == 8:
                format_char = "B"
            else:
                assert False
            return struct.pack("@" + format_char * len(data), *data)
        else:
            assert False

    def _process_clipboard_request(self, packet):
        (_, request_id, selection, target) = packet
        if selection in self._clipboard_proxies:
            proxy = self._clipboard_proxies[selection]
            def got_contents(type, format, data):
                if type is not None:
                    munged = self._munge_raw_selection_to_wire(type,
                                                               format,
                                                               data)
                    (wire_encoding, wire_data) = munged
                    log("clipboard raw -> wire: %r -> %r",
                        (type, format, data), munged)
                    if wire_encoding is not None:
                        self.send(["clipboard-contents", request_id, selection,
                                   type, format, wire_encoding, wire_data])
                        return
                self.send(["clipboard-contents-none", request_id, selection])
            proxy.get_contents(target, got_contents)
        else:
            self.send(["clipboard-contents-none", request_id, selection])

    def _process_clipboard_contents(self, packet):
        (_, request_id, selection,
         type, format, wire_encoding, wire_data) = packet
        raw_data = self._munge_wire_selection_to_raw(wire_encoding, type,
                                                     format, wire_data)
        log("clipboard wire -> raw: %r -> %r",
            (type, format, wire_encoding, wire_data), raw_data)
        self._clipboard_got_contents(request_id, type, format, raw_data)

    def _process_clipboard_contents_none(self, packet):
        (_, request_id, selection) = packet
        self._clipboard_got_contents(request_id, None, None, None)

    _packet_handlers = {
        "clipboard-token": _process_clipboard_token,
        "clipboard-request": _process_clipboard_request,
        "clipboard-contents": _process_clipboard_contents,
        "clipboard-contents-none": _process_clipboard_contents_none,
        }

    def process_clipboard_packet(self, packet):
        packet_type = packet[0]
        self._packet_handlers[packet_type](self, packet)

class ClipboardProxy(gtk.Invisible):
    __gsignals__ = {
        # arguments: (selection, target)
        "get-clipboard-from-remote": (gobject.SIGNAL_RUN_LAST,
                                      gobject.TYPE_PYOBJECT,
                                      (gobject.TYPE_PYOBJECT,) * 2,
                                      ),
        # arguments: (selection,)
        "send-clipboard-token": n_arg_signal(1),
        }

    def __init__(self, selection):
        gtk.Invisible.__init__(self)
        self.add_events(gtk.gdk.PROPERTY_CHANGE_MASK)
        self._selection = selection
        self._clipboard = gtk.Clipboard(selection=selection)
        self._have_token = False

    def do_selection_request_event(self, event):
        # Black magic: the superclass default handler for this signal
        # implements all the hards parts of selection handling, occasionally
        # calling back to the do_selection_get handler (below) to actually get
        # the data to be sent.  However, it only does this for targets that
        # have been registered ahead of time; other targets fall through to a
        # default implementation that cannot be overridden.  So, we swoop in
        # ahead of time and add whatever target was requested to the list of
        # targets we want to handle!
        #
        # Special cases (magic targets defined by ICCCM):
        #   TIMESTAMP: the remote side has a different timeline than us, so
        #     sending TIMESTAMPS across the wire doesn't make any sense. We
        #     ignore TIMESTAMP requests, and let them fall through to GTK+'s
        #     default handler.
        #   TARGET: GTK+ has default handling for this, but we don't want to
        #     use it. Fortunately, if we tell GTK+ that we can handle TARGET
        #     requests, then it will pass them on to us rather than fall
        #     through to the default handler.
        #   MULTIPLE: Ugh. To handle this properly, we need to go out
        #     ourselves and fetch the magic property off the requesting window
        #     (with proper error trapping and all), and interpret its
        #     contents. Probably doable (FIXME), just a pain.
        #
        # Another special case is that if an app requests the contents of a
        # clipboard that it currently owns, then GTK+ will short-circuit the
        # normal logic and request the contents directly (i.e. it calls
        # gtk_selection_invoke_handler) -- without giving us a chance to
        # assert that we can handle the requested sort of target. Fortunately,
        # Xpra never needs to request the clipboard when it owns it, so that's
        # okay.
        assert str(event.selection) == self._selection
        target = str(event.target)
        if target == "TIMESTAMP":
            pass
        elif target == "MULTIPLE":
            targets = []
            def get_targets():
                win = get_pywindow(event.requestor)
                atoms = prop_get(win, event.property, ["multiple-conversion"])
                log("MULTIPLE clipboard atoms: %r", atoms)
                targets += atoms[::2]
            trap.swallow(get_targets)
            log("MULTIPLE clipboard targets: %r", atoms)
            for target in targets:
                self.selection_add_target(self._selection, target, 0)
        else:
            self.selection_add_target(self._selection, target, 0)
        gtk.Invisible.do_selection_request_event(self, event)

    # This function is called by GTK+ when we own the clipboard and a local
    # app is requesting its contents:
    def do_selection_get(self, selection_data, info, time):
        # Either call selection_data.set() or don't, and then return.
        # In practice, send a call across the wire, then block in a recursive
        # main loop.
        assert self._selection == str(selection_data.selection)
        target = str(selection_data.target)
        result = self.emit("get-clipboard-from-remote", self._selection, target)
        if result is not None and result["type"] is not None:
            selection_data.set(result["type"],
                               result["format"],
                               result["data"])
        else:
            log("remote selection fetch timed out")

    def do_selection_clear_event(self, event):
        # Someone else on our side has the selection
        self._have_token = False

        # Emit a signal -> send a note to the other side saying "hey its
        # ours now"
        # Send off the anti-token.
        self.emit("send-clipboard-token", self._selection)
        gtk.Invisible.do_selection_clear_event(self, event)

    def got_token(self):
        # We got the anti-token.
        self._have_token = True
        if not self.selection_owner_set(self._selection):
            # I don't know how this can actually fail, given that we pass
            # CurrentTime, but just in case:
            log.warn("Failed to acquire local clipboard %s; "
                     % (self._selection,)
                     + "will not be able to pass local apps "
                     + "contents of remote clipboard")

    # This function is called by the xpra core when the peer has requested the
    # contents of this clipboard:
    def get_contents(self, target, cb):
        if self._have_token:
            log.warn("Our peer requested the contents of the clipboard, but "
                     + "*I* thought *they* had it... weird.")
            cb(None, None, None)
        def unpack(clipboard, selection_data, data):
            if selection_data is None:
                cb(None, None, None)
            else:
                cb(str(selection_data.type),
                   selection_data.format,
                   selection_data.data)
        self._clipboard.request_contents(target, unpack)

gobject.type_register(ClipboardProxy)
