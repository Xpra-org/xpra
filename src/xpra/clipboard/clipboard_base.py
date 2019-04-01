# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.gtk_common.gobject_util import no_arg_signal, SIGNAL_RUN_LAST
from xpra.gtk_common.gtk_util import (
    GetClipboard, PROPERTY_CHANGE_MASK,
    selection_owner_set, selection_add_target, selectiondata_get_selection,
    selectiondata_get_target, selectiondata_get_data,
    selectiondata_get_data_type, selectiondata_get_format,
    selectiondata_set, clipboard_request_contents,
    set_clipboard_data,
    )
from xpra.gtk_common.nested_main import NestedMainLoop
from xpra.os_util import WIN32, bytestostr, is_X11, is_Wayland
from xpra.util import repr_ellipsized, first_time, envbool
from xpra.platform.features import CLIPBOARD_GREEDY
from xpra.gtk_common.gobject_compat import import_gobject, import_gtk, import_glib, is_gtk3
from xpra.clipboard.clipboard_core import (
    ClipboardProtocolHelperCore, ClipboardProxyCore,
    must_discard, TRANSLATED_TARGETS, LOOP_DISABLE, TEXT_TARGETS,
    )
from xpra.log import Logger

log = Logger("clipboard")

gobject = import_gobject()
glib = import_glib()
gtk = import_gtk()

STORE_ON_EXIT = envbool("XPRA_CLIPBOARD_STORE_ON_EXIT", True)

MAX_NESTING = 20


def nesting_check():
    l = gtk.main_level()
    if l>=MAX_NESTING:
        log.warn("Warning: clipboard loop nesting too deep: %s", l)
        log.warn(" your setup may have a clipboard forwarding loop,")
        log.warn(" disabling the clipboard")
        return False
    return True


#may get overriden
def nosanitize_gtkselectiondata(_selectiondata):
    return False
sanitize_gtkselectiondata = nosanitize_gtkselectiondata



class ClipboardProtocolHelperBase(ClipboardProtocolHelperCore):

    def __repr__(self):
        return "ClipboardProtocolHelperBase"

    def nesting_check(self):
        return nesting_check()

    def get_info(self):
        info = ClipboardProtocolHelperCore.get_info(self)
        info["sanitize-gtkselectiondata"] = sanitize_gtkselectiondata!=nosanitize_gtkselectiondata
        return info

    def verify_remote_loop_uuids(self, uuids):
        log("verify_remote_loop_uuids(%s)", uuids)
        if not uuids:
            return
        for proxy in self._clipboard_proxies.values():
            proxy._clipboard.request_text(self._verify_remote_loop_uuids, (proxy, uuids))

    def _verify_remote_loop_uuids(self, clipboard, value, user_data):
        log("_verify_remote_loop_uuids(%s)", (clipboard, value, user_data))
        proxy, uuids = user_data
        if value:
            for selection, rvalue in uuids.items():
                log("%s=%s", proxy._selection, value)
                if rvalue==proxy._loop_uuid:
                    set_clipboard_data(clipboard, "")
                if rvalue and value==rvalue:
                    set_clipboard_data(clipboard, "")
                    if selection==proxy._selection:
                        log.warn("Warning: loop detected for %s clipboard", selection)
                    else:
                        log.warn("Warning: loop detected")
                        log.warn(" local %s clipboard matches remote %s clipboard",
                                 proxy._selection, selection)
                    if LOOP_DISABLE:
                        log.warn(" synchronization has been disabled")
                        proxy._enabled = False
                        if selection not in self.disabled_by_loop:
                            self.disabled_by_loop.append(selection)

    def make_proxy(self, selection):
        proxy = ClipboardProxy(selection)
        proxy.set_direction(self.can_send, self.can_receive)
        proxy.connect("send-clipboard-token", self._send_clipboard_token_handler)
        proxy.connect("get-clipboard-from-remote", self._get_clipboard_from_remote_handler)
        proxy.show()
        return proxy


    def _get_clipboard_from_remote_handler(self, _proxy, selection, target):
        assert self.can_receive
        if must_discard(target):
            log("invalid target '%s'", target)
            return None
        request_id = self._clipboard_request_counter
        self._clipboard_request_counter += 1
        log("get clipboard from remote handler id=%s", request_id)
        loop = NestedMainLoop()
        self._clipboard_outstanding_requests[request_id] = loop
        self.progress()
        self.send("clipboard-request", request_id, self.local_to_remote(selection), target)
        result = loop.main(1 * 1000, 2 * 1000)
        log("get clipboard from remote result(%s)=%s", request_id, result)
        del self._clipboard_outstanding_requests[request_id]
        self.progress()
        return result

    def _clipboard_got_contents(self, request_id, dtype, dformat, data):
        assert self.can_receive
        loop = self._clipboard_outstanding_requests.get(request_id)
        log("got clipboard contents for id=%s len=%s, loop=%s (type=%s, format=%s)",
              request_id, len(data or []), loop, dtype, dformat)
        if loop is None:
            log("got unexpected response to clipboard request %s", request_id)
            return
        loop.done({"type": dtype, "format": dformat, "data": data})



class DefaultClipboardProtocolHelper(ClipboardProtocolHelperBase):
    """
        Default clipboard implementation with all 3 selections.
        But without gdk atom support, see gdk_clipboard for a better one!
    """
    pass


class ClipboardProxy(ClipboardProxyCore, gtk.Invisible):
    __gsignals__ = {
        # arguments: (selection, target)
        "get-clipboard-from-remote": (SIGNAL_RUN_LAST,
                                      gobject.TYPE_PYOBJECT,
                                      (gobject.TYPE_PYOBJECT,) * 2,
                                      ),
        # arguments: (selection,)
        "send-clipboard-token": no_arg_signal,
        }

    def __init__(self, selection):
        ClipboardProxyCore.__init__(self, selection)
        gtk.Invisible.__init__(self)
        self.add_events(PROPERTY_CHANGE_MASK)
        self._clipboard = GetClipboard(selection)
        #this workaround is only needed on win32 AFAIK:
        self._strip_nullbyte = WIN32

        if is_X11():
            try:
                from xpra.x11.gtk_x11.prop import prop_get
                self.prop_get = prop_get
            except ImportError as e:
                log.warn("Warning: limited support for clipboard properties")
                log.warn(" %s", e)
                self.prop_get = None

        self._clipboard.connect("owner-change", self.do_owner_changed)

    def init_uuid(self):
        ClipboardProxyCore.init_uuid(self)
        set_clipboard_data(self._clipboard, "")

    def cleanup(self):
        ClipboardProxyCore.cleanup(self)
        if self._can_receive and not self._have_token and STORE_ON_EXIT:
            self._clipboard.store()
        self.destroy()

    def __repr__(self):
        return  "ClipboardProxy(%s)" % self._selection

    def do_emit_token(self):
        self.emit("send-clipboard-token")


    def do_selection_request_event(self, event):
        log("do_selection_request_event(%s)", event)
        self._selection_request_events += 1
        if not self._enabled or not self._can_receive:
            gtk.Invisible.do_selection_request_event(self, event)
            return
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
        assert str(event.selection) == self._selection, "expected %s but got %s" % (event.selection, self._selection)
        target = str(event.target)
        if target == "TIMESTAMP":
            pass
        elif target == "MULTIPLE":
            if not self.prop_get:
                log("MULTIPLE for property '%s' not handled due to missing xpra.x11.gtk_x11 bindings", event.property)
                gtk.Invisible.do_selection_request_event(self, event)
                return
            atoms = self.prop_get(event.window, event.property, ["multiple-conversion"])
            log("MULTIPLE clipboard atoms: %r", atoms)
            if atoms:
                targets = atoms[::2]
                for t in targets:
                    selection_add_target(self, self._selection, t, 0)
        else:
            if not must_discard(target):
                log("target for %s: %r", self._selection, target)
                selection_add_target(self, self._selection, target, 0)
        log("do_selection_request_event(%s) target=%s, selection=%s", event, target, self._selection)
        gtk.Invisible.do_selection_request_event(self, event)

    # This function is called by GTK+ when we own the clipboard and a local
    # app is requesting its contents:
    def do_selection_get(self, selection_data, info, time):
        # Either call selection_data.set() or don't, and then return.
        # In practice, send a call across the wire, then block in a recursive
        # main loop.
        def nodata():
            selectiondata_set(selection_data, "STRING", 8, "")
        if not self._enabled or not self._can_receive:
            nodata()
            return
        if not self._have_token:
            try:
                return gtk.Invisible.do_selection_get(self, selection_data, info, time)
            except Exception as e:
                log("gtk.Invisible.do_selection_get", exc_info=True)
                if first_time("selection-%s-not-implemented" % self._selection):
                    log.warn("Warning: limited clipboard support for %s", self._selection)
                    if is_Wayland():
                        log.warn(" looks like a Wayland implementation limitation")
                    log.warn(" %s", e)
                nodata()
                return
        selection = selectiondata_get_selection(selection_data)
        target = selectiondata_get_target(selection_data)
        log("do_selection_get(%s, %s, %s) selection=%s", selection_data, info, time, selection)
        self._selection_get_events += 1
        assert str(selection) == self._selection, "expected %s but got %s" % (selection, self._selection)
        self._request_contents_events += 1
        result = self.emit("get-clipboard-from-remote", self._selection, target)
        if result is None or result["type"] is None:
            log("remote selection fetch timed out or empty")
            nodata()
            return
        data = result["data"]
        dformat = result["format"]
        dtype = result["type"]
        log("do_selection_get(%s,%s,%s) calling selection_data.set(%s, %s, %s:%s)",
              selection_data, info, time, dtype, dformat, type(data), len(data or ""))
        boc = self._block_owner_change
        self._block_owner_change = True
        if is_gtk3() and dtype in (b"UTF8_STRING", b"STRING") and dformat==8:
            #GTK3 workaround: can only use set_text and only on the clipboard?
            s = bytestostr(data)
            self._clipboard.set_text(s, len(s))
        else:
            selectiondata_set(selection_data, dtype, dformat, data)
        if boc is False:
            glib.idle_add(self.remove_block)

    def do_selection_clear_event(self, event):
        # Someone else on our side has the selection
        log("do_selection_clear_event(%s) have_token=%s, block_owner_change=%s selection=%s",
            event, self._have_token, self._block_owner_change, self._selection)
        self._selection_clear_events += 1
        if self._enabled and not self._block_owner_change:
            #if greedy_client is set, do_owner_changed will fire the token
            #so don't bother sending it now (same if we don't have it)
            send = self._have_token or (self._greedy_client and not self._block_owner_change)
            self._have_token = False

            # Emit a signal -> send a note to the other side saying "hey its
            # ours now"
            # Send off the anti-token.
            if send:
                self.emit_token()
        gtk.Invisible.do_selection_clear_event(self, event)

    def got_token(self, targets, target_data, claim=True, synchronous_client=False):
        # We got the anti-token.
        self.cancel_emit_token()
        if not self._enabled:
            return
        self._got_token_events += 1
        log("got token, selection=%s, targets=%s, target data=%s, claim=%s, can-receive=%s",
            self._selection, targets, target_data, claim, self._can_receive)
        if self._greedy_client or CLIPBOARD_GREEDY:
            self._block_owner_change = True
            #re-enable the flag via idle_add so events like do_owner_changed
            #get a chance to run first.
            glib.idle_add(self.remove_block)
        if (CLIPBOARD_GREEDY or synchronous_client) and self._can_receive:
            if targets:
                for target in targets:
                    selection_add_target(self, self._selection, target, 0)
                selection_owner_set(self, self._selection)
            if target_data:
                for text_target in TEXT_TARGETS:
                    if text_target in target_data:
                        dtype, dformat, text_data = target_data.get(text_target)
                        log("clipboard %s set to '%s' (dtype=%s, dformat=%s)", self._selection, repr_ellipsized(text_data), dtype, dformat)
                        set_clipboard_data(self._clipboard, text_data, text_target)
        if not claim:
            log("token packet without claim, not setting the token flag")
            #the other end is just telling us to send the token again next time something changes,
            #not that they want to own the clipboard selection
            return
        self._have_token = True
        if self._can_receive:
            if not self._block_owner_change:
                #if we don't claim the selection (can-receive=False),
                #we will have to send the token back on owner-change!
                self._block_owner_change = True
                glib.idle_add(self.remove_block)
            self.claim()

    def claim(self):
        log("claim() selection=%s, enabled=%s", self._selection, self._enabled)
        if self._enabled and not selection_owner_set(self, self._selection):
            # I don't know how this can actually fail, given that we pass
            # CurrentTime, but just in case:
            log.warn("Warning: failed to acquire local clipboard %s", self._selection)
            log.warn(" will not be able to pass local apps contents of remote clipboard")


    # This function is called by the xpra core when the peer has requested the
    # contents of this clipboard:
    def get_contents(self, target, cb):
        log("get_contents(%s, %s) selection=%s, enabled=%s, can-send=%s",
            target, cb, self._selection, self._enabled, self._can_send)
        if not self._enabled or not self._can_send:
            cb(None, None, None)
            return
        self._get_contents_events += 1
        if self._have_token:
            log.warn("Warning: our peer requested the contents of the clipboard,")
            log.warn(" but *I* thought *they* had it... weird.")
            cb(None, None, None)
            return
        if target=="TARGETS":
            #handle TARGETS using "request_targets"
            def got_targets(c, targets, *args):
                log("got_targets(%s, %s, %s)", c, targets, args)
                if is_gtk3():
                    targets = [x.name() for x in targets]
                cb("ATOM", 32, targets)
                self._last_targets = targets or ()
            self._clipboard.request_targets(got_targets)
            return
        def unpack(clipboard, selection_data, _user_data=None):
            log("unpack %s: %s", clipboard, type(selection_data))
            global sanitize_gtkselectiondata
            if selection_data and sanitize_gtkselectiondata(selection_data):
                self._clipboard.set_text("", len=-1)
                selection_data = None
            if selection_data is None:
                cb(None, None, None)
                return
            log("unpack: %s", selection_data)
            data = selectiondata_get_data(selection_data)
            dtype = selectiondata_get_data_type(selection_data)
            dformat = selectiondata_get_format(selection_data)
            log("unpack(..) type=%s, format=%s, data=%s:%s", dtype, dformat, type(data), len(data or ""))
            isstring = dtype in (b"UTF8_STRING", b"STRING") and dformat==8
            if isstring:
                if self._strip_nullbyte:
                    #we may have to strip the nullbyte:
                    if data and data[-1]=='\0':
                        log("stripping end of string null byte")
                        data = data[:-1]
                if data and data==self._loop_uuid:
                    log("not sending loop uuid value '%s', returning an empty string instead", data)
                    data= ""
            cb(str(dtype), dformat, data)
        #some applications (ie: firefox, thunderbird) can request invalid targets,
        #when that happens, translate it to something the application can handle (if any)
        translated_target = TRANSLATED_TARGETS.get(target)
        if (translated_target is not None) and self._last_targets and (target not in self._last_targets) and \
            (translated_target in self._last_targets) and (not must_discard(translated_target)):
            log("invalid target %s, replaced with %s", target, translated_target)
            target = translated_target
        clipboard_request_contents(self._clipboard, target, unpack)

gobject.type_register(ClipboardProxy)
