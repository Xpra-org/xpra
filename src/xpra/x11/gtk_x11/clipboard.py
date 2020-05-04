# This file is part of Xpra.
# Copyright (C) 2019-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import struct
from io import BytesIO
from gi.repository import GLib, GObject, Gdk

from xpra.gtk_common.error import xsync, xswallow
from xpra.gtk_common.gobject_util import one_arg_signal, n_arg_signal
from xpra.gtk_common.gtk_util import get_default_root_window, GDKWindow
from xpra.x11.gtk_x11.gdk_bindings import (
    add_event_receiver,                          #@UnresolvedImport
    remove_event_receiver,                       #@UnresolvedImport
    init_x11_filter,
    cleanup_x11_filter,
    )
from xpra.gtk_common.error import XError
from xpra.clipboard.clipboard_core import (
    ClipboardProxyCore, TEXT_TARGETS,
    must_discard, must_discard_extra, _filter_targets,
    )
from xpra.clipboard.clipboard_timeout_helper import ClipboardTimeoutHelper, CONVERT_TIMEOUT
from xpra.x11.bindings.window_bindings import ( #@UnresolvedImport
    constants, PropertyError,                   #@UnresolvedImport
    X11WindowBindings,                          #@UnresolvedImport
    )
from xpra.os_util import bytestostr
from xpra.util import csv, repr_ellipsized, ellipsizer, first_time, envbool
from xpra.log import Logger

X11Window = X11WindowBindings()

log = Logger("x11", "clipboard")


CurrentTime = constants["CurrentTime"]
StructureNotifyMask = constants["StructureNotifyMask"]

sizeof_long = struct.calcsize(b'@L')

BLACKLISTED_CLIPBOARD_CLIENTS = os.environ.get("XPRA_BLACKLISTED_CLIPBOARD_CLIENTS", "clipit").split(",")
log("BLACKLISTED_CLIPBOARD_CLIENTS=%s", BLACKLISTED_CLIPBOARD_CLIENTS)
def parse_translated_targets(v):
    trans = {}
    #we can't use ";" or "/" as separators
    #because those are used in mime-types
    #and we use "," and ":" ourselves..
    for entry in v.split("#"):
        parts = entry.split(":", 1)
        if len(parts)!=2:
            log.warn("Warning: invalid clipboard translated target:")
            log.warn(" '%s'", entry)
            continue
        src_target = parts[0]
        dst_targets = parts[1].split(",")
        trans[src_target] = dst_targets
    return trans
DEFAULT_TRANSLATED_TARGETS = "#".join((
    "text/plain;charset=utf-8:UTF8_STRING,text/plain,public.utf8-plain-text",
    "TEXT:text/plain,text/plain;charset=utf-8,UTF8_STRING,public.utf8-plain-text",
    "STRING:text/plain,text/plain;charset=utf-8,UTF8_STRING,public.utf8-plain-text",
    "UTF8_STRING:text/plain;charset=utf-8,text/plain,public.utf8-plain-text",
    "GTK_TEXT_BUFFER_CONTENTS:UTF8_STRING,text/plain,public.utf8-plain-text",
    ))
TRANSLATED_TARGETS = parse_translated_targets(os.environ.get("XPRA_CLIPBOARD_TRANSLATED_TARGETS", DEFAULT_TRANSLATED_TARGETS))
log("TRANSLATED_TARGETS=%s", TRANSLATED_TARGETS)


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


class X11Clipboard(ClipboardTimeoutHelper, GObject.GObject):

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
        GObject.GObject.__init__(self)
        self.init_window()
        init_x11_filter()
        self.x11_filter = True
        super().__init__(send_packet_cb, progress_cb, **kwargs)

    def __repr__(self):
        return "X11Clipboard"

    def init_window(self):
        root = get_default_root_window()
        self.window = GDKWindow(root, width=1, height=1, title="Xpra-Clipboard", wclass=Gdk.WindowWindowClass.INPUT_ONLY)
        self.window.set_events(Gdk.EventMask.PROPERTY_CHANGE_MASK | self.window.get_events())
        xid = self.window.get_xid()
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
        if self.x11_filter:
            self.x11_filter = False
            cleanup_x11_filter()
        ClipboardTimeoutHelper.cleanup(self)
        self.cleanup_window()

    def make_proxy(self, selection):
        xid = self.window.get_xid()
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
        log.info("clipboard X11 window %#x received a client message", self.window.get_xid())
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
        return super()._munge_raw_selection_to_wire(target, dtype, dformat, data)

    def _munge_wire_selection_to_raw(self, encoding, dtype, dformat, data):
        if encoding=="atoms":
            return strings_to_xatoms(_filter_targets(data))
        return super()._munge_wire_selection_to_raw(encoding, dtype, dformat, data)

GObject.type_register(X11Clipboard)


class ClipboardProxy(ClipboardProxyCore, GObject.GObject):

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
        GObject.GObject.__init__(self)
        self.xid = xid
        self.owned = False
        self._want_targets = False
        self.remote_requests = {}
        self.local_requests = {}
        self.local_request_counter = 0
        self.targets = ()
        self.target_data = {}
        self.reset_incr_data()

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
                owner = X11Window.XGetSelectionOwner(self._selection)
                if owner==self.xid:
                    log("claim(%i) we already own the '%s' selection", time, self._selection)
                    return
                setsel = X11Window.XSetSelectionOwner(self.xid, self._selection, time)
                owner = X11Window.XGetSelectionOwner(self._selection)
                self.owned = owner==self.xid
                log("claim_selection: set selection owner returned %s, owner=%#x, owned=%s",
                    setsel, owner, self.owned)
                event_mask = StructureNotifyMask
                if not self.owned:
                    log.warn("Warning: we failed to get ownership of the '%s' clipboard selection", self._selection)
                    return
                #send announcement:
                log("claim_selection: sending message to root window")
                root = get_default_root_window()
                root_xid = root.get_xid()
                X11Window.sendClientMessage(root_xid, root_xid, False, event_mask, "MANAGER",
                                  time or CurrentTime, self._selection, self.xid)
                log("claim_selection: done, owned=%s", self.owned)
        except Exception:
            log("failed to claim selection '%s'", self._selection, exc_info=True)
            raise

    def do_xpra_client_message_event(self, event):
        if event.message_type=="_GTK_LOAD_ICONTHEMES":
            #ignore this crap
            return
        log.info("clipboard window %#x received an X11 message", event.window.get_xid())
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
        if not requestor:
            log.warn("Warning: clipboard selection request without a window, dropped")
            return
        wininfo = self.get_wininfo(requestor.get_xid())
        prop = event.property
        target = str(event.target)
        log("clipboard request for %s from window %#x: %s, target=%s, prop=%s",
            self._selection, requestor.get_xid(), wininfo, target, prop)
        if not target:
            log.warn("Warning: ignoring clipboard request without a TARGET")
            log.warn(" coming from %s", wininfo)
            return
        if not prop:
            log.warn("Warning: ignoring clipboard request without a property")
            log.warn(" coming from %s", wininfo)
            return
        def nodata():
            self.set_selection_response(requestor, target, prop, "STRING", 8, b"", time=event.time)
        if not self._enabled:
            nodata()
            return
        if wininfo and wininfo.strip("'") in BLACKLISTED_CLIPBOARD_CLIENTS:
            if first_time("clipboard-blacklisted:%s" % wininfo.strip("'")):
                log.warn("receiving clipboard requests from blacklisted client %s", wininfo)
                log.warn(" all requests will be silently ignored")
            log("responding with nodata for blacklisted client '%s'", wininfo)
            return
        if not self.owned:
            log.warn("Warning: clipboard selection request received,")
            log.warn(" coming from %s", wininfo)
            log.warn(" but we don't own the selection,")
            log.warn(" sending an empty reply")
            nodata()
            return
        if not self._can_receive:
            log.warn("Warning: clipboard selection request received,")
            log.warn(" coming from %s", wininfo)
            log.warn(" but receiving remote data is disabled,")
            log.warn(" sending an empty reply")
            nodata()
            return
        if must_discard(target):
            log.info("clipboard %s rejecting request for invalid target '%s'", self._selection, target)
            log.info(" coming from %s", wininfo)
            nodata()
            return

        if target=="TARGETS":
            if self.targets:
                log("using existing TARGETS value as response: %s", self.targets)
                xatoms = strings_to_xatoms(self.targets)
                self.set_selection_response(requestor, target, prop, "ATOM", 32, xatoms, event.time)
                return
            if "TARGETS" not in self.remote_requests:
                self.emit("send-clipboard-request", self._selection, "TARGETS")
            #when appending, the time may not be honoured
            #and we may reply with data from an older request
            self.remote_requests.setdefault("TARGETS", []).append((requestor, target, prop, event.time))
            return

        req_target = target
        if self.targets and target not in self.targets:
            if first_time("client-%s-invalidtarget-%s" % (wininfo, target)):
                l = log.info
            else:
                l = log.debug
            l("client %s is requesting an unknown target: '%s'", wininfo, target)
            translated_targets = TRANSLATED_TARGETS.get(target, ())
            can_translate = tuple(x for x in translated_targets if x in self.targets)
            if can_translate:
                req_target = can_translate[0]
                l(" using '%s' instead", req_target)
            else:
                l(" valid targets: %s", csv(self.targets))
                if must_discard_extra(target):
                    l(" dropping the request")
                    nodata()
                    return

        target_data = self.target_data.get(req_target)
        if target_data and self._have_token:
            #we have it already
            dtype, dformat, data = target_data
            dtype = bytestostr(dtype)
            log("setting target data for '%s': %s, %s, %s (%s)",
                target, dtype, dformat, ellipsizer(data), type(data))
            self.set_selection_response(requestor, target, prop, dtype, dformat, data, event.time)
            return

        if req_target not in self.remote_requests:
            self.emit("send-clipboard-request", self._selection, req_target)
        self.remote_requests.setdefault(req_target, []).append((requestor, target, prop, event.time))

    def set_selection_response(self, requestor, target, prop, dtype, dformat, data, time=0):
        log("set_selection_response(%s, %s, %s, %s, %s, %r, %i)",
            requestor, target, prop, dtype, dformat, ellipsizer(data), time)
        #answer the selection request:
        try:
            xid = requestor.get_xid()
            with xsync:
                if data is not None:
                    X11Window.XChangeProperty(xid, prop, dtype, dformat, data)
                else:
                    #maybe even delete the property?
                    #X11Window.XDeleteProperty(xid, prop)
                    prop = None
                X11Window.sendSelectionNotify(xid, self._selection, target, prop, time)
        except XError as e:
            log("failed to set selection", exc_info=True)
            log.warn("Warning: failed to set selection for target '%s'", target)
            log.warn(" on requestor %s", self.get_wininfo(xid))
            log.warn(" property '%s'", prop)
            log.warn(" %s", e)

    def got_contents(self, target, dtype=None, dformat=None, data=None):
        #if this is the special target 'TARGETS', cache the result:
        if target=="TARGETS" and dtype=="ATOM" and dformat==32:
            self.targets = xatoms_to_strings(data)
        #the remote peer sent us a response,
        #find all the pending requests for this target
        #and give them the response they are waiting for:
        pending = self.remote_requests.pop(target, [])
        log("got_contents%s pending=%s",
            (target, dtype, dformat, ellipsizer(data)), csv(pending))
        for requestor, actual_target, prop, time in pending:
            if log.is_debug_enabled():
                log("setting response %s as '%s' on property '%s' of window %s as %s",
                     ellipsizer(data), actual_target, prop, self.get_wininfo(requestor.get_xid()), dtype)
            if actual_target!=target and dtype==target:
                dtype = actual_target
            self.set_selection_response(requestor, actual_target, prop, dtype, dformat, data, time)


    ############################################################################
    # local clipboard events, which may or may not be sent to the remote end
    ############################################################################
    def do_selection_notify_event(self, event):
        owned = self.owned
        xid = 0
        if event.owner:
            xid = event.owner.get_xid()
        self.owned = xid and xid==self.xid
        log("do_selection_notify_event(%s) owned=%s, was %s (owner=%#x, xid=%#x), enabled=%s, can-send=%s",
            event, self.owned, owned, xid, self.xid, self._enabled, self._can_send)
        if not self._enabled:
            return
        if self.owned or not self._can_send or xid==0:
            return
        self.do_owner_changed()
        self.schedule_emit_token()

    def schedule_emit_token(self):
        if not (self._want_targets or self._greedy_client):
            self._have_token = False
            self.emit("send-clipboard-token", ())
            return
        #we need the targets, and the target data for greedy clients:
        def send_token_with_targets():
            token_data = (self.targets, )
            self._have_token = False
            self.emit("send-clipboard-token", token_data)
        def with_targets(targets):
            if not self._greedy_client:
                send_token_with_targets()
                return
            #find the preferred targets:
            targets = self.choose_targets(targets)
            if not targets:
                send_token_with_targets()
                return
            target = targets[0]
            def got_text_target(dtype, dformat, data):
                log("got_text_target(%s, %s, %s)", dtype, dformat, ellipsizer(data))
                if not (dtype and dformat and data):
                    send_token_with_targets()
                    return
                token_data = (targets, (target, dtype, dformat, data))
                self._have_token = False
                self.emit("send-clipboard-token", token_data)
            self.get_contents(target, got_text_target)
        if self.targets:
            with_targets(self.targets)
            return
        def got_targets(dtype, dformat, data):
            assert dtype=="ATOM" and dformat==32
            self.targets = xatoms_to_strings(data)
            log("got_targets: %s", self.targets)
            with_targets(self.targets)
        self.get_contents("TARGETS", got_targets)

    def choose_targets(self, targets):
        if self.preferred_targets:
            #prefer PNG, but only if supported by the client:
            if "image/png" in targets and "image/png" in self.preferred_targets:
                return ("image/png",)
            #if we can't choose a text target, at least choose a supported one:
            if not any(x for x in targets if x in TEXT_TARGETS and x in self.preferred_targets):
                return tuple(x for x in targets if x in self.preferred_targets)
        #otherwise choose a text target:
        return tuple(x for x in targets if x in TEXT_TARGETS)

    def do_selection_clear_event(self, event):
        log("do_xpra_selection_clear(%s) was owned=%s", event, self.owned)
        if not self._enabled:
            return
        self.owned = False
        self.do_owner_changed()

    def do_owner_changed(self):
        log("do_owner_changed()")
        self.target_data = {}
        self.targets = ()

    def get_contents(self, target, got_contents):
        log("get_contents(%s, %s) owned=%s, have-token=%s",
            target, got_contents, self.owned, self._have_token)
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
        with xsync:
            owner = X11Window.XGetSelectionOwner(self._selection)
            self.owned = owner==self.xid
            if self.owned:
                #we are the clipboard owner!
                log("we are the %s selection owner, using empty reply", self._selection)
                got_contents(None, None, None)
                return
            request_id = self.local_request_counter
            self.local_request_counter += 1
            timer = GLib.timeout_add(CONVERT_TIMEOUT, self.timeout_get_contents, target, request_id)
            self.local_requests.setdefault(target, {})[request_id] = (timer, got_contents)
            log("requesting local XConvertSelection from %s as '%s' into '%s'", self.get_wininfo(owner), target, prop)
            X11Window.ConvertSelection(self._selection, target, prop, self.xid, time=CurrentTime)

    def timeout_get_contents(self, target, request_id):
        try:
            target_requests = self.local_requests.get(target)
            if target_requests is None:
                return
            timer, got_contents = target_requests.pop(request_id)
            if not target_requests:
                del self.local_requests[target]
        except KeyError:
            return
        GLib.source_remove(timer)
        log.warn("Warning: %s selection request for '%s' timed out", self._selection, target)
        log.warn(" request %i", request_id)
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
        dtype = ""
        dformat = 8
        try:
            with xsync:
                dtype, dformat = X11Window.GetWindowPropertyType(self.xid, event.atom, True)
                dtype = bytestostr(dtype)
                MAX_DATA_SIZE = 4*1024*1024
                data = X11Window.XGetWindowProperty(self.xid, event.atom, dtype, None, MAX_DATA_SIZE, True)
                #all the code below deals with INCRemental transfers:
                if dtype=="INCR" and not self.incr_data_size:
                    #start of an incremental transfer, extract the size
                    assert dformat==32
                    self.incr_data_size = struct.unpack("@L", data)[0]
                    self.incr_data_chunks = []
                    self.incr_data_type = None
                    log("incremental clipboard data of size %s", self.incr_data_size)
                    self.reschedule_incr_data_timer()
                    return
                if self.incr_data_size>0:
                    #incremental is now in progress:
                    if not self.incr_data_type:
                        self.incr_data_type = dtype
                    elif self.incr_data_type!=dtype:
                        log.error("Error: invalid change of data type")
                        log.error(" from %s to %s", self.incr_data_type, dtype)
                        self.reset_incr_data()
                        self.cancel_incr_data_timer()
                        return
                    if data:
                        log("got incremental data: %i bytes", len(data))
                        self.incr_data_chunks.append(data)
                        self.reschedule_incr_data_timer()
                        return
                    self.cancel_incr_data_timer()
                    data = b"".join(self.incr_data_chunks)
                    log("got incremental data termination, total size=%i bytes", len(data))
                    self.reset_incr_data()
                    self.got_local_contents(target, dtype, dformat, data)
                    return
        except PropertyError:
            log("do_property_notify() property '%s' is gone?", event.atom, exc_info=True)
            return
        log("%s=%s (%s : %s)", event.atom, ellipsizer(data), dtype, dformat)
        if target=="TARGETS":
            self.targets = xatoms_to_strings(data or b"")
        self.got_local_contents(target, dtype, dformat, data)

    def got_local_contents(self, target, dtype=None, dformat=None, data=None):
        data = self.filter_data(target, dtype, dformat, data)
        target_requests = self.local_requests.pop(target, {})
        for timer, got_contents in target_requests.values():
            if log.is_debug_enabled():
                log("got_local_contents: calling %s%s",
                    got_contents, (dtype, dformat, ellipsizer(data)))
            GLib.source_remove(timer)
            got_contents(dtype, dformat, data)

    def filter_data(self, target, dtype=None, dformat=None, data=None):
        log("filter_data(%s, %s, %s, ..)", target, dtype, dformat)
        IMAGE_OVERLAY = os.environ.get("XPRA_CLIPBOARD_IMAGE_OVERLAY", None)
        if IMAGE_OVERLAY and not os.path.exists(IMAGE_OVERLAY):
            IMAGE_OVERLAY = None
        IMAGE_STAMP = envbool("XPRA_CLIPBOARD_IMAGE_STAMP", True)
        if dtype in ("image/png", ) and (IMAGE_STAMP or IMAGE_OVERLAY):
            from xpra.codecs.pillow.decoder import open_only
            img = open_only(data, ("png", ))
            has_alpha = img.mode=="RGBA"
            if not has_alpha and IMAGE_OVERLAY:
                img = img.convert("RGBA")
            w, h = img.size
            if IMAGE_OVERLAY:
                from PIL import Image   #@UnresolvedImport
                overlay = Image.open(IMAGE_OVERLAY)
                if overlay.mode!="RGBA":
                    log.warn("Warning: cannot use overlay image '%s'", IMAGE_OVERLAY)
                    log.warn(" invalid mode '%s'", overlay.mode)
                else:
                    log("adding clipboard image overlay to %s", dtype)
                    overlay_resized = overlay.resize((w, h), Image.ANTIALIAS)
                    composite = Image.alpha_composite(img, overlay_resized)
                    if not has_alpha and img.mode=="RGBA":
                        composite = composite.convert("RGB")
                    img = composite
            if IMAGE_STAMP:
                log("adding clipboard image stamp to %s", dtype)
                from datetime import datetime
                from PIL import ImageDraw
                img_draw = ImageDraw.Draw(img)
                w, h = img.size
                img_draw.text((10, max(0, h//2-16)), 'via Xpra, %s' % datetime.now().isoformat(), fill='black')
            buf = BytesIO()
            img.save(buf, "PNG")
            data = buf.getvalue()
            buf.close()
        return data


    def reschedule_incr_data_timer(self):
        self.cancel_incr_data_timer()
        self.incr_data_timer = GLib.timeout_add(1*1000, self.incr_data_timeout)

    def cancel_incr_data_timer(self):
        idt = self.incr_data_timer
        if idt:
            self.incr_data_timer = None
            GLib.source_remove(idt)

    def incr_data_timeout(self):
        self.incr_data_timer = None
        log.warn("Warning: incremental data timeout")
        self.incr_data = None

    def reset_incr_data(self):
        self.incr_data_size = 0
        self.incr_data_type = None
        self.incr_data_chunks = None
        self.incr_data_timer = None

GObject.type_register(ClipboardProxy)
