# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import struct

from xpra.gtk_common.error import xsync, xswallow
from xpra.gtk_common.gobject_util import one_arg_signal, n_arg_signal
from xpra.gtk_common.gobject_compat import import_gdk, import_gobject, import_glib
from xpra.gtk_common.gtk_util import (
    get_default_root_window, get_xwindow, GDKWindow,
    PROPERTY_CHANGE_MASK, CLASS_INPUT_ONLY,
    )
from xpra.x11.gtk_x11.gdk_bindings import (
    add_event_receiver,                          #@UnresolvedImport
    remove_event_receiver,                       #@UnresolvedImport
    )
from xpra.clipboard.clipboard_core import (
    ClipboardProtocolHelperCore, ClipboardProxyCore, TEXT_TARGETS,
    must_discard, must_discard_extra, _filter_targets,
    )
from xpra.clipboard.clipboard_timeout_helper import ClipboardTimeoutHelper, CONVERT_TIMEOUT
from xpra.x11.bindings.window_bindings import ( #@UnresolvedImport
    constants, PropertyError,                   #@UnresolvedImport
    X11WindowBindings,                          #@UnresolvedImport
    )
from xpra.os_util import bytestostr
from xpra.util import csv, repr_ellipsized, first_time
from xpra.log import Logger

gdk = import_gdk()
gobject = import_gobject()
glib = import_glib()

X11Window = X11WindowBindings()

log = Logger("x11", "clipboard")


CurrentTime = constants["CurrentTime"]
StructureNotifyMask = constants["StructureNotifyMask"]

sizeof_long = struct.calcsize(b'@L')

BLACKLISTED_CLIPBOARD_CLIENTS = os.environ.get("XPRA_BLACKLISTED_CLIPBOARD_CLIENTS", "clipit").split(",")


def xatoms_to_strings(data):
    l = len(data)
    if l%sizeof_long!=0:
        raise Exception("invalid length for atom array: %i, value=%s" % (l, repr_ellipsized(str(data))))
    natoms = l//sizeof_long
    atoms = struct.unpack(b"@"+b"L"*natoms, data)
    with xsync:
        return tuple(bytestostr(name) for name in (X11Window.XGetAtomName(atom)
                                                   for atom in atoms if atom) if name is not None)

def strings_to_xatoms(data):
    with xsync:
        atom_array = tuple(X11Window.get_xatom(atom) for atom in data if atom)
    return struct.pack(b"@"+b"L"*len(atom_array), *atom_array)


class X11Clipboard(ClipboardTimeoutHelper, gobject.GObject):

    #handle signals from the X11 bindings,
    #and dispatch them to the proxy handling the selection specified:
    __gsignals__ = {
        "xpra-client-message-event"             : one_arg_signal,
        "xpra-selection-request"                : one_arg_signal,
        "xpra-selection-clear"                  : one_arg_signal,
        "xpra-property-notify-event"            : one_arg_signal,
        "xpra-xfixes-selection-notify-event"    : one_arg_signal,
        }

    def __init__(self, send_packet_cb, progress_cb=None, **kwargs):
        gobject.GObject.__init__(self)
        self.init_window()
        ClipboardTimeoutHelper.__init__(self, send_packet_cb, progress_cb)

    def __repr__(self):
        return "X11Clipboard"

    def init_window(self):
        root = get_default_root_window()
        self.window = GDKWindow(root, width=1, height=1, title="Xpra-Clipboard", wclass=CLASS_INPUT_ONLY)
        self.window.set_events(PROPERTY_CHANGE_MASK | self.window.get_events())
        xid = get_xwindow(self.window)
        with xsync:
            X11Window.selectSelectionInput(xid)
        add_event_receiver(self.window, self)

    def cleanup_window(self):
        w = self.window
        if w:
            self.window = None
            remove_event_receiver(w, self)
            w.destroy()

    def cleanup(self):
        ClipboardTimeoutHelper.cleanup(self)
        self.cleanup_window()

    def make_proxy(self, selection):
        xid = get_xwindow(self.window)
        proxy = ClipboardProxy(xid, selection)
        proxy.set_want_targets(self._want_targets)
        proxy.set_direction(self.can_send, self.can_receive)
        proxy.connect("send-clipboard-token", self._send_clipboard_token_handler)
        proxy.connect("send-clipboard-request", self._send_clipboard_request_handler)
        with xsync:
            X11Window.selectXFSelectionInput(xid, selection)
        return proxy


    ############################################################################
    # X11 event handlers:
    # we dispatch them to the proxy handling the selection specified
    ############################################################################
    def do_xpra_selection_request(self, event):
        log("do_xpra_selection_request(%s)", event)
        proxy = self._get_proxy(event.selection)
        if proxy:
            proxy.do_selection_request_event(event)

    def do_xpra_selection_clear(self, event):
        log("do_xpra_selection_clear(%s)", event)
        proxy = self._get_proxy(event.selection)
        if proxy:
            proxy.do_selection_clear_event(event)

    def do_xpra_xfixes_selection_notify_event(self, event):
        log("do_xpra_xfixes_selection_notify_event(%s)", event)
        proxy = self._get_proxy(event.selection)
        if proxy:
            proxy.do_selection_notify_event(event)

    def do_xpra_client_message_event(self, event):
        message_type = event.message_type
        if message_type=="_GTK_LOAD_ICONTHEMES":
            log("ignored clipboard client message: %s", message_type)
            return
        log.info("clipboard X11 window %#x received a client message", get_xwindow(self.window))
        log.info(" %s", event)

    def do_xpra_property_notify_event(self, event):
        if event.atom in (
            "_NET_WM_NAME", "WM_NAME", "_NET_WM_ICON_NAME", "WM_ICON_NAME",
            "WM_PROTOCOLS", "WM_NORMAL_HINTS", "WM_CLIENT_MACHINE", "WM_LOCALE_NAME",
            "_NET_WM_PID", "WM_CLIENT_LEADER", "_NET_WM_USER_TIME_WINDOW"):
            #these properties are populated by GTK when we create the window,
            #no need to log them:
            return
        log("do_xpra_property_notify_event(%s)", event)
        #ie: atom=PRIMARY-TARGETS
        #ie: atom=PRIMARY-VALUE
        parts = event.atom.split("-", 1)
        if len(parts)!=2:
            return
        selection = parts[0]        #ie: PRIMARY
        #target = parts[1]           #ie: VALUE
        proxy = self._get_proxy(selection)
        if proxy:
            proxy.do_property_notify(event)


    ############################################################################
    # x11 specific munging support:
    ############################################################################

    def _munge_raw_selection_to_wire(self, target, dtype, dformat, data):
        if dformat==32 and dtype in ("ATOM", "ATOM_PAIR"):
            return "atoms", _filter_targets(xatoms_to_strings(data))
        return ClipboardProtocolHelperCore._munge_raw_selection_to_wire(self, target, dtype, dformat, data)

    def _munge_wire_selection_to_raw(self, encoding, dtype, dformat, data):
        if encoding=="atoms":
            return strings_to_xatoms(_filter_targets(data))
        return ClipboardProtocolHelperCore._munge_wire_selection_to_raw(self, encoding, dtype, dformat, data)

gobject.type_register(X11Clipboard)


class ClipboardProxy(ClipboardProxyCore, gobject.GObject):

    __gsignals__ = {
        "xpra-client-message-event"             : one_arg_signal,
        "xpra-selection-request"                : one_arg_signal,
        "xpra-selection-clear"                  : one_arg_signal,
        "xpra-property-notify-event"            : one_arg_signal,
        "xpra-xfixes-selection-notify-event"    : one_arg_signal,
        #
        "send-clipboard-token"                  : one_arg_signal,
        "send-clipboard-request"                : n_arg_signal(2),
        }

    def __init__(self, xid, selection="CLIPBOARD"):
        ClipboardProxyCore.__init__(self, selection)
        gobject.GObject.__init__(self)
        self.xid = xid
        self.owned = False
        self._want_targets = False
        self.remote_requests = {}
        self.local_requests = {}
        self.local_request_counter = 0
        self.targets = ()
        self.target_data = {}

    def __repr__(self):
        return  "X11ClipboardProxy(%s)" % self._selection

    def cleanup(self):
        log("%s.cleanup()", self)
        #give up selection:
        #(disabled because this crashes GTK3 on exit)
        #if self.owned:
        #    self.owned = False
        #    with xswallow:
        #        X11Window.XSetSelectionOwner(0, self._selection)
        #empty replies for all pending requests,
        #this will also cancel any pending timers:
        rr = self.remote_requests
        self.remote_requests = {}
        for target in rr:
            self.got_contents(target)
        lr = self.local_requests
        self.local_requests = {}
        for target in lr:
            self.got_local_contents(target)

    def init_uuid(self):
        ClipboardProxyCore.init_uuid(self)
        self.claim()

    def set_want_targets(self, want_targets):
        self._want_targets = want_targets


    def got_token(self, targets, target_data=None, claim=True, synchronous_client=False):
        # the remote end now owns the clipboard
        self.cancel_emit_token()
        if not self._enabled:
            return
        self._got_token_events += 1
        log("got token, selection=%s, targets=%s, target data=%s, claim=%s, can-receive=%s",
            self._selection, targets, target_data, claim, self._can_receive)
        if claim:
            self._have_token = True
        if self._can_receive:
            self.targets = tuple(bytestostr(x) for x in (targets or ()))
            self.target_data = target_data or {}
            if targets and claim:
                xatoms = strings_to_xatoms(targets)
                self.got_contents("TARGETS", "ATOM", 32, xatoms)
            if target_data and synchronous_client and claim:
                targets = target_data.keys()
                text_targets = tuple(x for x in targets if x in TEXT_TARGETS)
                if text_targets:
                    target = text_targets[0]
                    dtype, dformat, data = target_data.get(target)
                    dtype = bytestostr(dtype)
                    self.got_contents(target, dtype, dformat, data)
        if self._can_receive and claim:
            self.claim()

    def claim(self, time=0):
        try:
            with xsync:
                setsel = X11Window.XSetSelectionOwner(self.xid, self._selection, time)
                log("claim_selection: set selection owner returned %s, owner=%#x",
                    setsel, X11Window.XGetSelectionOwner(self._selection))
                event_mask = StructureNotifyMask
                log("claim_selection: sending message to root window")
                owner = X11Window.XGetSelectionOwner(self._selection)
                self.owned = owner==self.xid
                if not self.owned:
                    log.warn("we failed to get ownership of the '%s' selection", self._selection)
                else:
                    #send announcement:
                    root = get_default_root_window()
                    root_xid = get_xwindow(root)
                    X11Window.sendClientMessage(root_xid, root_xid, False, event_mask, "MANAGER",
                                      CurrentTime, self._selection, self.xid)
                log("claim_selection: done, owned=%s", self.owned)
        except Exception:
            log("failed to claim selection '%s'", self._selection, exc_info=True)
            raise

    def do_xpra_client_message_event(self, event):
        if event.message_type=="_GTK_LOAD_ICONTHEMES":
            #ignore this crap
            return
        log.info("clipboard window %#x received an X11 message", get_xwindow(self.window))
        log.info(" %s", event)


    def get_wintitle(self, xid):
        data = X11Window.XGetWindowProperty(xid, "WM_NAME", "STRING")
        if data:
            return data.decode("latin1")
        data = X11Window.XGetWindowProperty(xid, "_NET_WM_NAME", "STRING")
        if data:
            return data.decode("utf8")
        xid = X11Window.getParent(xid)
        return None

    def get_wininfo(self, xid):
        with xswallow:
            title = self.get_wintitle(xid)
            if title:
                return "'%s'" % title
        with xswallow:
            while xid:
                title = self.get_wintitle(xid)
                if title:
                    return "child of '%s'" % title
                xid = X11Window.getParent(xid)
        return hex(xid)

    ############################################################################
    # forward local requests to the remote clipboard:
    ############################################################################
    def do_selection_request_event(self, event):
        #an app is requesting clipboard data from us
        log("do_selection_request_event(%s)", event)
        requestor = event.requestor
        assert requestor
        wininfo = self.get_wininfo(get_xwindow(requestor))
        log("clipboard request for %s from window %#x: %s",
            self._selection, get_xwindow(requestor), wininfo)
        prop = event.property
        target = str(event.target)
        def nodata():
            self.set_selection_response(requestor, target, prop, "STRING", 8, b"", time=event.time)
        if not self._enabled:
            nodata()
            return
        if wininfo.startswith("'") and wininfo.endswith("'") and wininfo.strip("'") in BLACKLISTED_CLIPBOARD_CLIENTS:
            if first_time("clipboard-blacklisted:%s" % wininfo.strip("'")):
                log.warn("receiving clipboard requests from blacklisted client %s", wininfo)
                log.warn(" all requests will be silently ignored")
            nodata()
            return
        if not self.owned:
            log.warn("Warning: clipboard selection request received,")
            log.warn(" but we don't own the selection,")
            log.warn(" sending an empty reply")
            nodata()
            return
        if not self._can_receive:
            log.warn("Warning: clipboard selection request received,")
            log.warn(" but receiving remote data is disabled,")
            log.warn(" sending an empty reply")
            nodata()
            return
        if must_discard(target):
            log.info("clipboard %s discarding invalid target '%s'", self._selection, target)
            nodata()
            return

        if target=="TARGETS":
            if self.targets:
                log("using existing TARGETS value as response")
                xatoms = strings_to_xatoms(self.targets)
                self.set_selection_response(requestor, target, prop, "ATOM", 32, xatoms, event.time)
                return
            if "TARGETS" not in self.remote_requests:
                self.emit("send-clipboard-request", self._selection, "TARGETS")
            #when appending, the time may not be honoured
            #and we may reply with data from an older request
            self.remote_requests.setdefault("TARGETS", []).append((requestor, prop, event.time))
            return

        if self.targets and target not in self.targets:
            log.info("client is requesting an unknown target: '%s'", target)
            log.info(" valid targets: %s", csv(self.targets))
            if must_discard_extra(target):
                log.info(" dropping the request")
                nodata()
                return

        target_data = self.target_data.get(target)
        if target_data:
            #we have it already
            dtype, dformat, data = target_data
            dtype = bytestostr(dtype)
            log("setting target data for '%s': %s, %s, %s (%s)",
                target, dtype, dformat, repr_ellipsized(str(data)), type(data))
            self.set_selection_response(requestor, target, prop, dtype, dformat, data, event.time)
            return

        if target not in self.remote_requests:
            self.emit("send-clipboard-request", self._selection, target)
        self.remote_requests.setdefault(target, []).append((requestor, prop, event.time))

    def set_selection_response(self, requestor, target, prop, dtype, dformat, data, time=0):
        log("set_selection_response(%s, %s, %s, %s, %s, %r, %i)",
            requestor, target, prop, dtype, dformat, repr_ellipsized(str(data)), time)
        #answer the selection request:
        with xsync:
            xid = get_xwindow(requestor)
            if data is not None:
                X11Window.XChangeProperty(xid, prop, dtype, dformat, data)
            else:
                #maybe even delete the property?
                #X11Window.XDeleteProperty(xid, prop)
                prop = None
            X11Window.sendSelectionNotify(xid, self._selection, target, prop, time)

    def got_contents(self, target, dtype=None, dformat=None, data=None):
        #if this is the special target 'TARGETS', cache the result:
        if target=="TARGETS" and dtype=="ATOM" and dformat==32:
            self.targets = xatoms_to_strings(data)
        #the remote peer sent us a response,
        #find all the pending requests for this target
        #and give them the response they are waiting for:
        pending = self.remote_requests.pop(target, [])
        log("got_contents%s pending=%s",
            (target, dtype, dformat, repr_ellipsized(str(data))), csv(pending))
        for requestor, prop, time in pending:
            log("setting response %s to property %s of window %s as %s",
                     repr_ellipsized(data), prop, self.get_wininfo(get_xwindow(requestor)), dtype)
            self.set_selection_response(requestor, target, prop, dtype, dformat, data, time)


    ############################################################################
    # local clipboard events, which may or may not be sent to the remote end
    ############################################################################
    def do_selection_notify_event(self, event):
        owned = self.owned
        self.owned = event.owner and get_xwindow(event.owner)==self.xid
        log("do_selection_notify_event(%s) owned=%s, was %s, enabled=%s, can-send=%s",
            event, self.owned, owned, self._enabled, self._can_send)
        if not self._enabled:
            return
        if self.owned or not self._can_send:
            return
        self.schedule_emit_token()

    def schedule_emit_token(self):
        if not (self._want_targets or self._greedy_client):
            self._have_token = False
            self.emit("send-clipboard-token", ())
        #we need the targets, and the target data for greedy clients:
        def send_token_with_targets():
            token_data = (self.targets, )
            self._have_token = False
            self.emit("send-clipboard-token", token_data)
        def with_targets(targets):
            if not self._greedy_client:
                send_token_with_targets()
                return
            #find the preferred text target:
            text_targets = tuple(x for x in targets if x in TEXT_TARGETS)
            if not text_targets:
                send_token_with_targets()
                return
            text_target = text_targets[0]
            def got_text_target(dtype, dformat, data):
                log("got_text_target(%s, %s, %s)", dtype, dformat, repr_ellipsized(str(data)))
                if not (dtype and dformat and data):
                    send_token_with_targets()
                    return
                token_data = (targets, (text_target, dtype, dformat, data))
                self._have_token = False
                self.emit("send-clipboard-token", token_data)
            self.get_contents(text_target, got_text_target)
        if self.targets:
            with_targets(self.targets)
            return
        def got_targets(dtype, dformat, data):
            assert dtype=="ATOM" and dformat==32
            self.targets = xatoms_to_strings(data)
            log("got_targets: %s", self.targets)
            with_targets(self.targets)
        self.get_contents("TARGETS", got_targets)


    def do_selection_clear_event(self, event):
        log("do_xpra_selection_clear(%s) was owned=%s", event, self.owned)
        if not self._enabled:
            return
        self.owned = False
        self.do_owner_changed()

    def do_owner_changed(self):
        log("do_owner_changed()")
        if not self._enabled:
            return
        self.target_data = {}
        self.targets = ()

    def get_contents(self, target, got_contents, time=0):
        log("get_contents(%s, %s, %i) owned=%s, have-token=%s",
            target, got_contents, time, self.owned, self._have_token)
        if target=="TARGETS":
            if self.targets:
                xatoms = strings_to_xatoms(self.targets)
                got_contents("ATOM", 32, xatoms)
                return
        else:
            target_data = self.target_data.get(target)
            if target_data:
                dtype, dformat, value = target_data
                got_contents(dtype, dformat, value)
                return
        prop = "%s-%s" % (self._selection, target)
        request_id = self.local_request_counter
        self.local_request_counter += 1
        timer = glib.timeout_add(CONVERT_TIMEOUT, self.timeout_get_contents, target, request_id)
        self.local_requests.setdefault(target, {})[request_id] = (timer, got_contents, time)
        with xsync:
            owner = X11Window.XGetSelectionOwner(self._selection)
            self.owned = owner==self.xid
            if self.owned:
                #we are the clipboard owner!
                log("we are the %s selection owner, using empty reply", self._selection)
                got_contents(None, None, None)
                return
            log("requesting local XConvertSelection from %s for '%s' into '%s'", self.get_wininfo(owner), target, prop)
            X11Window.ConvertSelection(self._selection, target, prop, self.xid, time=time)

    def timeout_get_contents(self, target, request_id):
        try:
            target_requests = self.local_requests.get(target)
            if target_requests is None:
                return
            timer, got_contents, time = target_requests.pop(request_id)
            if not target_requests:
                del self.local_requests[target]
        except KeyError:
            return
        glib.source_remove(timer)
        log.warn("Warning: %s selection request for '%s' timed out", self._selection, target)
        log.warn(" request %i at time=%i", request_id, time)
        if target=="TARGETS":
            got_contents("ATOM", 32, b"")
        else:
            got_contents(None, None, None)

    def do_property_notify(self, event):
        log("do_property_notify(%s)", event)
        if not self._enabled:
            return
        #ie: atom="PRIMARY-TARGETS", atom="PRIMARY-STRING"
        parts = event.atom.split("-", 1)
        assert len(parts)==2
        #selection = parts[0]        #ie: PRIMARY
        target = parts[1]           #ie: VALUE
        try:
            with xsync:
                dtype, dformat = X11Window.GetWindowPropertyType(self.xid, event.atom)
                dtype = bytestostr(dtype)
                MAX_DATA_SIZE = 4*1024*1024
                data = X11Window.XGetWindowProperty(self.xid, event.atom, dtype, None, MAX_DATA_SIZE)
                X11Window.XDeleteProperty(self.xid, event.atom)
        except PropertyError:
            log("do_property_notify() property '%s' is gone?", event.atom, exc_info=True)
            return
        log("%s=%s (%s : %s)", event.atom, repr_ellipsized(bytestostr(data)), dtype, dformat)
        if target=="TARGETS":
            self.targets = xatoms_to_strings(data or b"")
        self.got_local_contents(target, dtype, dformat, data)

    def got_local_contents(self, target, dtype=None, dformat=None, data=None):
        target_requests = self.local_requests.pop(target, {})
        for timer, got_contents, time in target_requests.values():
            log("got_local_contents: calling %s%s, time=%i", got_contents, (dtype, dformat, data), time)
            glib.source_remove(timer)
            got_contents(dtype, dformat, data)

gobject.type_register(ClipboardProxy)
