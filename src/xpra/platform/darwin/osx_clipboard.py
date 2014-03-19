# This file is part of Xpra.
# Copyright (C) 2012-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject

from xpra.log import Logger
log = Logger("clipboard", "osx")

from xpra.clipboard.gdk_clipboard import GDKClipboardProtocolHelper
from xpra.clipboard.clipboard_base import ClipboardProxy, TEXT_TARGETS

update_clipboard_change_count = None

change_callbacks = []
change_count = 0
pasteboard = None

def init_pasteboard():
    global pasteboard, change_callbacks, change_count, update_clipboard_change_count
    if pasteboard is not None:
        return False
    try:
        from AppKit import NSPasteboard      #@UnresolvedImport
        pasteboard = NSPasteboard.generalPasteboard()
        if pasteboard is None:
            log.warn("cannot load Pasteboard, maybe not running from a GUI session?")
            return False

        def update_change_count():
            global change_count
            change_count = pasteboard.changeCount()
            return change_count
        update_clipboard_change_count = update_change_count

        def timer_clipboard_check():
            global change_count
            c = change_count
            change_count = pasteboard.changeCount()
            log("timer_clipboard_check() was %s, now %s", c, change_count)
            if c!=change_count:
                for x in change_callbacks:
                    try:
                        x()
                    except Exception, e:
                        log("error in change callback %s: %s", x, e)

        from xpra.platform.ui_thread_watcher import get_UI_watcher
        w = get_UI_watcher()
        if w is None:
            log.warn("no UI watcher available, cannot watch for clipboard events")
            return False
        log("UI watcher=%s", w)
        w.add_alive_callback(timer_clipboard_check)
        return True
    except ImportError, e:
        log.warn("cannot monitor OSX clipboard count: %s", e)
        return False


class OSXClipboardProtocolHelper(GDKClipboardProtocolHelper):
    """
        Full of OSX quirks!
        darwin/features.py should be set
        * CLIPBOARD_GREEDY: request the other end to send tokens for all owner change events
        * CLIPBOARD_WANT_TARGETS: include targets with the tokens
    """

    def __init__(self, send_packet_cb, progress_cb=None):
        init_pasteboard()
        GDKClipboardProtocolHelper.__init__(self, send_packet_cb, progress_cb, ["CLIPBOARD"])

    def make_proxy(self, clipboard):
        return OSXClipboardProxy(clipboard)

    def _get_clipboard_from_remote_handler(self, proxy, selection, target):
        #cannot work on osx, the nested mainloop doesn't run :(
        #so we don't even try and rely on the "wants_targets" flag
        #to get the server to send us the data with the token
        #see "got_token" below
        return None

    def __str__(self):
        return "OSXClipboardProtocolHelper"


class OSXClipboardProxy(ClipboardProxy):

    def __init__(self, selection):
        ClipboardProxy.__init__(self, selection)
        global change_callbacks
        change_callbacks.append(self.local_clipboard_changed)

    def got_token(self, targets, target_data):
        # We got the anti-token.
        log("got token, selection=%s, targets=%s, target_data=%s", self._selection, targets, target_data)
        self._block_owner_change = True
        self._have_token = True
        for target in targets:
            self.selection_add_target(self._selection, target, 0)
        self.selection_owner_set(self._selection)
        if target_data:
            for text_target in TEXT_TARGETS:
                if text_target in target_data:
                    text_data = target_data.get(text_target)
                    log("clipboard %s set to '%s'", self._selection, text_data)
                    self._clipboard.set_text(text_data)
        #prevent our change from firing another clipboard update:
        if update_clipboard_change_count:
            c = update_clipboard_change_count()
            log("change count now at %s", c)
        gobject.idle_add(self.remove_block)

    def local_clipboard_changed(self):
        log("local_clipboard_changed() greedy_client=%s", self._greedy_client)
        if (self._greedy_client or not self._have_token) and not self._block_owner_change:
            self._have_token = False
            self.emit("send-clipboard-token", self._selection)
            self._sent_token_events += 1

gobject.type_register(OSXClipboardProxy)





def main():
    global change_count
    import time
    from xpra.platform import init
    init("OSX Clipboard Change Test")

    #init UI watcher with gobject (required by pasteboard monitoring code)
    from xpra.platform.ui_thread_watcher import get_UI_watcher
    gobject.threads_init()
    import gtk.gdk
    gtk.gdk.threads_init()
    get_UI_watcher(gobject.timeout_add)

    log.info("testing pasteboard")
    if not init_pasteboard():
        return
    assert update_clipboard_change_count is not None
    log.info("pasteboard=%s", pasteboard)
    log.info("direct call to pasteboard.changeCount()=%s", pasteboard.changeCount())
    cc = update_clipboard_change_count()
    log.info("current change count=%s", cc)
    clipboard = gtk.Clipboard(selection="CLIPBOARD")
    log.info("changing clipboard %s contents", clipboard)
    clipboard.set_text("HELLO WORLD %s" % time.time())
    cc = update_clipboard_change_count()
    log.info("new change count=%s", cc)
    log.info("please update your clipboard at least once in the next 20 seconds")
    for _ in range(20):
        v = update_clipboard_change_count()
        if v!=cc:
            log.info("success! the clipboard change has been detected, new change count=%s", v)
            break
        else:
            log.info(".")
        time.sleep(1)
    if v==cc:
        log.info("no clipboard change detected")


if __name__ == "__main__":
    main()
