# This file is part of Xpra.
# Copyright (C) 2012-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from AppKit import NSStringPboardType, NSPasteboard     #@UnresolvedImport

from xpra.clipboard.clipboard_timeout_helper import ClipboardTimeoutHelper
from xpra.clipboard.clipboard_core import (
    _filter_targets, ClipboardProxyCore, TEXT_TARGETS,
    )
from xpra.platform.ui_thread_watcher import get_UI_watcher
from xpra.gtk_common.gobject_compat import import_glib
from xpra.util import csv
from xpra.os_util import bytestostr
from xpra.log import Logger

log = Logger("clipboard", "osx")

glib = import_glib()

TARGET_TRANS = {
    NSStringPboardType : "STRING",
    }

def filter_targets(targets):
    return _filter_targets(TARGET_TRANS.get(x, x) for x in targets)


class OSXClipboardProtocolHelper(ClipboardTimeoutHelper):

    def __init__(self, *args, **kwargs):
        self.pasteboard = NSPasteboard.generalPasteboard()
        if self.pasteboard is None:
            raise Exception("cannot load Pasteboard, maybe not running from a GUI session?")
        kwargs["clipboard.local"] = "CLIPBOARD"
        kwargs["clipboards.local"] = ["CLIPBOARD"]
        ClipboardTimeoutHelper.__init__(self, *args, **kwargs)


    def __repr__(self):
        return "OSXClipboardProtocolHelper"


    def cleanup(self):
        ClipboardTimeoutHelper.cleanup(self)
        self.pasteboard = None

    def make_proxy(self, clipboard):
        proxy = OSXClipboardProxy(clipboard, self.pasteboard,
                                  self._send_clipboard_request_handler, self._send_clipboard_token_handler)
        proxy.set_direction(self.can_send, self.can_receive)
        return proxy

    ############################################################################
    # just pass ATOM targets through
    # (we use them internally as strings)
    ############################################################################
    def _munge_wire_selection_to_raw(self, encoding, dtype, dformat, data):
        if encoding=="atoms":
            return _filter_targets(data)
        return ClipboardTimeoutHelper._munge_wire_selection_to_raw(self, encoding, dtype, dformat, data)


class OSXClipboardProxy(ClipboardProxyCore):

    def __init__(self, selection, pasteboard, send_clipboard_request_handler, send_clipboard_token_handler):
        self.pasteboard = pasteboard
        self.send_clipboard_request_handler = send_clipboard_request_handler
        self.send_clipboard_token_handler = send_clipboard_token_handler
        ClipboardProxyCore.__init__(self, selection)
        self.update_change_count()
        #setup clipboard counter watcher:
        w = get_UI_watcher(glib.timeout_add, glib.source_remove)
        if w is None:
            log.warn("Warning: no UI watcher instance available")
            log.warn(" cannot detect clipboard change events")
        else:
            w.add_alive_callback(self.timer_clipboard_check)

    def cleanup(self):
        ClipboardProxyCore.cleanup(self)
        w = get_UI_watcher()
        if w:
            try:
                w.remove_alive_callback(self.timer_clipboard_check)
            except (KeyError, ValueError):
                pass

    def timer_clipboard_check(self):
        c = self.change_count
        self.update_change_count()
        log("timer_clipboard_check() was %s, now %s", c, self.change_count)
        if c!=self.change_count:
            self.local_clipboard_changed()

    def update_change_count(self):
        p = self.pasteboard
        if p:
            self.change_count = p.changeCount()

    def clear(self):
        self.pasteboard.clearContents()

    def do_emit_token(self):
        targets = filter_targets(self.pasteboard.types())
        log("do_emit_token() targets=%s", targets)
        packet_data = [targets, ]
        if self._greedy_client:
            text = self.get_clipboard_text()
            if text:
                packet_data += ["STRING", "bytes", 8, text]
        self.send_clipboard_token_handler(self, packet_data)


    def get_clipboard_text(self):
        text = self.pasteboard.stringForType_(NSStringPboardType)
        log("get_clipboard_text() NSStringPboardType=%s (%s)", text, type(text))
        return str(text)

    def get_contents(self, target, got_contents):
        log("get_contents%s", (target, got_contents))
        if target=="TARGETS":
            #we only support text at the moment:
            got_contents("ATOM", 32, ["TEXT", "STRING", "text/plain", "text/plain;charset=utf-8", "UTF8_STRING"])
            return
        if target not in ("TEXT", "STRING", "text/plain", "text/plain;charset=utf-8", "UTF8_STRING"):
            #we don't know how to handle this target,
            #return an empty response:
            got_contents(target, 8, b"")
            return
        text = self.get_clipboard_text()
        got_contents(target, 8, text)

    def got_token(self, targets, target_data=None, claim=True, _synchronous_client=False):
        # the remote end now owns the clipboard
        self.cancel_emit_token()
        if not self._enabled:
            return
        self._got_token_events += 1
        log("got token, selection=%s, targets=%s, target data=%s, claim=%s, can-receive=%s",
            self._selection, targets, target_data, claim, self._can_receive)
        if self._can_receive:
            self.targets = _filter_targets(targets or ())
            self.target_data = target_data or {}
            if targets:
                self.got_contents("TARGETS", "ATOM", 32, targets)
            if target_data:
                for target, td_def in target_data.items():
                    dtype, dformat, data = td_def
                    dtype = bytestostr(dtype)
                    self.got_contents(target, dtype, dformat, data)
            #since we claim to be greedy
            #the peer should have sent us the target and target_data,
            #if not then request it:
            if not targets:
                self.send_clipboard_request_handler(self, self._selection, "TARGETS")
        if not claim:
            log("token packet without claim, not setting the token flag")
            return
        if claim:
            self._have_token = True

    def got_contents(self, target, dtype=None, dformat=None, data=None):
        #if this is the special target 'TARGETS', cache the result:
        if target=="TARGETS" and dtype=="ATOM" and dformat==32:
            self.targets = _filter_targets(data)
            #TODO: tell system what targets we have
            log("got_contents: tell OS we have %s", csv(self.targets))
        if dformat==8 and dtype in TEXT_TARGETS:
            log("we got a byte string: %s", data)
            self.set_clipboard_text(data)

    def set_clipboard_text(self, text):
        self.pasteboard.clearContents()
        r = self.pasteboard.setString_forType_(text.decode("utf8"), NSStringPboardType)
        log("set_clipboard_text(%s) success=%s", text, r)
        self.update_change_count()


    def local_clipboard_changed(self):
        log("local_clipboard_changed()")
        self.do_owner_changed()


def main():
    import time
    from xpra.platform import program_context
    with program_context("OSX Clipboard Change Test"):
        log.enable_debug()

        #init UI watcher with gobject (required by pasteboard monitoring code)
        from xpra.gtk_common.gtk_util import import_gtk
        gtk = import_gtk()
        get_UI_watcher(glib.timeout_add, glib.source_remove)

        def noop(*_args):
            pass
        log.info("testing pasteboard")
        pasteboard = NSPasteboard.generalPasteboard()
        proxy = OSXClipboardProxy("CLIPBOARD", pasteboard, noop, noop)
        log.info("current change count=%s", proxy.change_count)
        clipboard = gtk.Clipboard(selection="CLIPBOARD")
        log.info("changing clipboard %s contents", clipboard)
        clipboard.set_text("HELLO WORLD %s" % time.time())
        proxy.update_change_count()
        log.info("new change count=%s", proxy.change_count)
        log.info("any update to your clipboard should get logged (^C to exit)")
        cc = proxy.change_count
        while True:
            v = proxy.change_count
            if v!=cc:
                log.info("success! the clipboard change has been detected, new change count=%s", v)
            else:
                log.info(".")
            time.sleep(1)
        if v==cc:
            log.info("no clipboard change detected")


if __name__ == "__main__":
    main()
