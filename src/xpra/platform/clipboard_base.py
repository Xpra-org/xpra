# This file is part of Parti.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import struct

from wimpiggy.gobject_compat import import_gobject, import_gtk, import_gdk, is_gtk3
gobject = import_gobject()
gtk = import_gtk()
gdk = import_gdk()
if is_gtk3():
    PROPERTY_CHANGE_MASK = gdk.EventMask.PROPERTY_CHANGE_MASK
else:
    PROPERTY_CHANGE_MASK = gdk.PROPERTY_CHANGE_MASK


from wimpiggy.util import n_arg_signal
from wimpiggy.log import Logger
log = Logger()

from xpra.nested_main import NestedMainLoop
from xpra.protocol import zlib_compress

#debug = log.info
debug = log.debug

class ClipboardProtocolHelperBase(object):
    def __init__(self, send_packet_cb, clipboards=["CLIPBOARD"]):
        self.send = send_packet_cb
        self.max_clipboard_packet_size = 32*1024 - 1024
        self._clipboard_proxies = {}
        for clipboard in clipboards:
            proxy = ClipboardProxy(clipboard)
            proxy.connect("send-clipboard-token", self._send_clipboard_token_handler)
            proxy.connect("get-clipboard-from-remote", self._get_clipboard_from_remote_handler)
            proxy.show()
            self._clipboard_proxies[clipboard] = proxy
        self._clipboard_request_counter = 0
        self._clipboard_outstanding_requests = {}

    def local_to_remote(self, selection):
        return  selection
    def remote_to_local(self, selection):
        return  selection

    # Used by the client during startup:
    def send_all_tokens(self):
        for selection in self._clipboard_proxies:
            name = self.local_to_remote(selection)
            debug("send_all_tokens selection=%s, exported as=%s", selection, name)
            self.send("clipboard-token", name)

    def _process_clipboard_token(self, packet):
        selection = packet[1]
        name = self.remote_to_local(selection)
        debug("process clipboard token selection=%s, local clipboard name=%s", selection, name)
        if name in self._clipboard_proxies:
            self._clipboard_proxies[name].got_token()

    def _get_clipboard_from_remote_handler(self, proxy, selection, target):
        request_id = self._clipboard_request_counter
        self._clipboard_request_counter += 1
        debug("get clipboard from remote handler id=%s", request_id)
        loop = NestedMainLoop()
        self._clipboard_outstanding_requests[request_id] = loop
        self.send("clipboard-request", request_id, self.local_to_remote(selection), target)
        result = loop.main(1 * 1000, 2 * 1000)
        debug("get clipboard from remote result(%s)=%s", request_id, result)
        del self._clipboard_outstanding_requests[request_id]
        return result

    def _clipboard_got_contents(self, request_id, dtype, dformat, data):
        debug("got clipboard contents(%s)=%s (type=%s, format=%s)", request_id, len(data or []), dtype, dformat)
        if request_id in self._clipboard_outstanding_requests:
            loop = self._clipboard_outstanding_requests[request_id]
            loop.done({"type": dtype, "format": dformat, "data": data})
        else:
            debug("got unexpected response to clipboard request %s", request_id)

    def _send_clipboard_token_handler(self, proxy, selection):
        debug("send clipboard token: %s", selection)
        self.send("clipboard-token", self.local_to_remote(selection))

    def _munge_raw_selection_to_wire(self, target, dtype, dformat, data):
        # Some types just cannot be marshalled:
        if type in ("WINDOW", "PIXMAP", "BITMAP", "DRAWABLE",
                    "PIXEL", "COLORMAP"):
            debug("skipping clipboard data of type: %s, format=%s, len(data)=%s", dtype, dformat, len(data))
            return None, None
        return self._do_munge_raw_selection_to_wire(target, dtype, dformat, data)

    def _do_munge_raw_selection_to_wire(self, target, dtype, dformat, data):
        """ this method is overriden in xclipboard to parse X11 atoms """
        # Other types need special handling, and all types need to be
        # converting into an endian-neutral format:
        debug("_do_munge_raw_selection_to_wire(%s, %s, %s, %s:%s)", target, dtype, dformat, type(data), len(data or ""))
        if dformat == 32:
            #you should be using gdk_clipboard for atom support!
            if dtype in ("ATOM", "ATOM_PAIR") and os.name=="posix":
                #we cannot handle gdk atoms here (but gdk_clipboard does)
                return None, None
            #important note: on 64 bits, format=32 means 8 bytes, not 4
            #that's just the way it is...
            sizeof_long = struct.calcsize('@L')
            assert sizeof_long in (4, 8), "struct.calcsize('@L')=%s" % sizeof_long
            binfmt = "@" + "L" * (len(data) // sizeof_long)
            ints = struct.unpack(binfmt, data)
            return "integers", ints
        elif dformat == 16:
            sizeof_short = struct.calcsize('=H')
            assert sizeof_short == 2, "struct.calcsize('=H')=%s" % sizeof_short
            binfmt = "=" + "H" * (len(data) // sizeof_short)
            ints = struct.unpack(binfmt, data)
            return "integers", ints
        elif dformat == 8:
            return "bytes", data
        else:
            log.error("unhandled format %s for clipboard data type %s" % (dformat, dtype))
            return None, None

    def _munge_wire_selection_to_raw(self, encoding, dtype, dformat, data):
        debug("wire selection to raw, encoding=%s, type=%s, format=%s, len(data)=%s", encoding, dtype, dformat, len(data))
        if encoding == "bytes":
            return data
        elif encoding == "integers":
            if dformat == 32:
                format_char = "L"
            elif dformat == 16:
                format_char = "H"
            elif dformat == 8:
                format_char = "B"
            else:
                raise Exception("unknown encoding format: %s" % dformat)
            fstr = "@" + format_char * len(data)
            debug("struct.pack(%s, %s)", fstr, data)
            return struct.pack(fstr, *data)
        else:
            raise Exception("unhanled encoding: %s" % encoding)

    def _process_clipboard_request(self, packet):
        request_id, selection, target = packet[1:4]
        name = self.remote_to_local(selection)
        debug("process clipboard request, request_id=%s, selection=%s, local name=%s, target=%s", request_id, selection, name, target)
        if name in self._clipboard_proxies:
            proxy = self._clipboard_proxies[name]
            def got_contents(dtype, dformat, data):
                debug("got_contents(%s, %s, %s:%s) data=%s, str(data)=%s", dtype, dformat, type(data), len(data or ""), list(bytearray(data or "")[:200]), str(data)[:200])
                def no_contents():
                    self.send("clipboard-contents-none", request_id, selection)
                if dtype is None or data is None:
                    no_contents()
                    return
                munged = self._munge_raw_selection_to_wire(target, dtype, dformat, data)
                wire_encoding, wire_data = munged
                debug("clipboard raw -> wire: %r -> %r", (dtype, dformat, data), munged)
                if wire_encoding is None:
                    no_contents()
                    return
                if len(wire_data)>256:
                    wire_data = zlib_compress("clipboard: %s / %s" % (dtype, dformat), wire_data)
                    if len(wire_data)>self.max_clipboard_packet_size:
                        log.warn("even compressed, clipboard contents are too big and have not been sent: %s compressed bytes dropped" % len(wire_data))
                        no_contents()
                        return
                self.send("clipboard-contents", request_id, selection,
                           dtype, dformat, wire_encoding, wire_data)
            proxy.get_contents(target, got_contents)
        else:
            self.send("clipboard-contents-none", request_id, selection)

    def _process_clipboard_contents(self, packet):
        request_id, selection, dtype, dformat, wire_encoding, wire_data = packet[1:8]
        debug("process clipboard contents, selection=%s, type=%s, format=%s", selection, dtype, dformat)
        raw_data = self._munge_wire_selection_to_raw(wire_encoding, dtype, dformat, wire_data)
        debug("clipboard wire -> raw: %r -> %r", (dtype, dformat, wire_encoding, wire_data), raw_data)
        self._clipboard_got_contents(request_id, dtype, dformat, raw_data)

    def _process_clipboard_contents_none(self, packet):
        debug("process clipboard contents none")
        request_id = packet[1]
        self._clipboard_got_contents(request_id, None, None, None)

    _packet_handlers = {
        "clipboard-token": _process_clipboard_token,
        "clipboard-request": _process_clipboard_request,
        "clipboard-contents": _process_clipboard_contents,
        "clipboard-contents-none": _process_clipboard_contents_none,
        }

    def process_clipboard_packet(self, packet):
        packet_type = packet[0]
        debug("process clipboard packet type=%s", packet_type)
        self._packet_handlers[packet_type](self, packet)


class DefaultClipboardProtocolHelper(ClipboardProtocolHelperBase):
    """
        Default clipboard implementation with all 3 selections.
        But without gdk atom support, see gdk_clipboard for a better one!
    """

    def __init__(self, send_packet_cb):
        ClipboardProtocolHelperBase.__init__(self, send_packet_cb, ["CLIPBOARD", "PRIMARY", "SECONDARY"])


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
        self.add_events(PROPERTY_CHANGE_MASK)
        self._selection = selection
        self._clipboard = gtk.Clipboard(selection=selection)
        self._have_token = False

    def do_selection_request_event(self, event):
        debug("do_selection_request_event(%s)", event)
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
            try:
                from wimpiggy.prop import prop_get
                from wimpiggy.error import trap
            except ImportError:
                debug("MULTIPLE for property '%s' not handled due to missing wimpiggy bindings", event.property)
                gtk.Invisible.do_selection_request_event(self, event)
                return
            def get_targets(targets):
                atoms = prop_get(event.window, event.property, ["multiple-conversion"])
                debug("MULTIPLE clipboard atoms: %r", atoms)
                targets += atoms[::2]
            targets = []
            trap.swallow(get_targets, targets)
            debug("MULTIPLE clipboard targets: %r", targets)
            for target in targets:
                self.selection_add_target(self._selection, target, 0)
        else:
            debug("target for %s: %r", self._selection, target)
            self.selection_add_target(self._selection, target, 0)
        debug("do_selection_request_event(%s) target=%s, selection=%s", event, target, self._selection)
        gtk.Invisible.do_selection_request_event(self, event)

    # This function is called by GTK+ when we own the clipboard and a local
    # app is requesting its contents:
    def do_selection_get(self, selection_data, info, time):
        # Either call selection_data.set() or don't, and then return.
        # In practice, send a call across the wire, then block in a recursive
        # main loop.
        debug("do_selection_get(%s, %s, %s)", selection_data, info, time)
        assert self._selection == str(selection_data.selection)
        target = str(selection_data.target)
        result = self.emit("get-clipboard-from-remote", self._selection, target)
        if result is not None and result["type"] is not None:
            data = result["data"]
            dformat = result["format"]
            dtype = result["type"]
            debug("do_selection_get(%s,%s,%s) calling selection_data.set(%s, %s, %s:%s)", selection_data, info, time, dtype, dformat, type(data), len(data or ""))
            selection_data.set(dtype, dformat, data)
        else:
            debug("remote selection fetch timed out")

    def do_selection_clear_event(self, event):
        # Someone else on our side has the selection
        debug("do_selection_clear_event(%s) selection=%s", event, self._selection)
        self._have_token = False

        # Emit a signal -> send a note to the other side saying "hey its
        # ours now"
        # Send off the anti-token.
        self.emit("send-clipboard-token", self._selection)
        gtk.Invisible.do_selection_clear_event(self, event)

    def got_token(self):
        # We got the anti-token.
        debug("got token, selection=%s", self._selection)
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
        debug("get_contents(%s,%s)", target, cb)
        if self._have_token:
            log.warn("Our peer requested the contents of the clipboard, but "
                     + "*I* thought *they* had it... weird.")
            cb(None, None, None)
        def unpack(clipboard, selection_data, data):
            debug("unpack(%s, %s, %s:%s)", clipboard, selection_data, type(data), len(data or ""))
            if selection_data is None:
                cb(None, None, None)
            else:
                debug("unpack(..) type=%s, format=%s, data=%s:%s", selection_data.type, selection_data.format,
                            type(selection_data.data), len(selection_data.data or ""))
                cb(str(selection_data.type),
                   selection_data.format,
                   selection_data.data)
        self._clipboard.request_contents(target, unpack)

gobject.type_register(ClipboardProxy)
