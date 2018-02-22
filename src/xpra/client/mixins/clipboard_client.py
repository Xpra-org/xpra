# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("clipboard")


from xpra.client.mixins.stub_client_mixin import StubClientMixin
from xpra.platform.features import CLIPBOARD_WANT_TARGETS, CLIPBOARD_GREEDY, CLIPBOARDS
from xpra.scripts.config import FALSE_OPTIONS
from xpra.os_util import bytestostr
try:
    from xpra.clipboard.clipboard_base import ALL_CLIPBOARDS
except:
    ALL_CLIPBOARDS = []


"""
Utility superclass for clients that handle clipboard synchronization
"""
class ClipboardClient(StubClientMixin):
    __signals__ = ["clipboard-toggled"]

    def __init__(self):
        self.client_clipboard_type = ""
        self.client_clipboard_direction = "both"
        self.client_supports_clipboard = False
        self.clipboard_enabled = False
        self.server_clipboard_direction = "both"
        self.server_clipboard = False
        self.server_clipboard_loop_uuids = {}
        self.server_clipboard_direction = ""
        self.server_clipboard_enable_selections = False
        self.server_clipboards = []
        self.clipboard_helper = None

    def init(self, opts):
        self.client_clipboard_type = opts.clipboard
        self.client_clipboard_direction = opts.clipboard_direction
        self.client_supports_clipboard = not ((opts.clipboard or "").lower() in FALSE_OPTIONS)


    def cleanup(self):
        ch = self.clipboard_helper
        log("ClipboardClient.cleanup() clipboard_helper=%s", ch)
        if ch:
            self.clipboard_helper = None
            try:
                ch.cleanup()
            except:
                log.error("error on clipboard helper '%s' cleanup", ch, exc_info=True)


    def get_clipboard_caps(self):
        return {
            ""                          : self.client_supports_clipboard,
            "notifications"             : self.client_supports_clipboard,
            "selections"                : CLIPBOARDS,
            #buggy osx clipboards:
            "want_targets"              : CLIPBOARD_WANT_TARGETS,
            #buggy osx and win32 clipboards:
            "greedy"                    : CLIPBOARD_GREEDY,
            "set_enabled"               : True,
            }

    def parse_server_capabilities(self):
        c = self.server_capabilities
        self.server_clipboard = c.boolget("clipboard")
        self.server_clipboard_loop_uuids = c.dictget("clipboard.loop-uuids")
        self.server_clipboard_direction = c.strget("clipboard-direction", "both")
        if self.server_clipboard_direction!=self.client_clipboard_direction and self.server_clipboard_direction!="both":
            if self.client_clipboard_direction=="disabled":
                pass
            elif self.server_clipboard_direction=="disabled":
                log.warn("Warning: server clipboard synchronization is currently disabled")
                self.client_clipboard_direction = "disabled"
            elif self.client_clipboard_direction=="both":
                log.warn("Warning: server only supports '%s' clipboard transfers", self.server_clipboard_direction)
                self.client_clipboard_direction = self.server_clipboard_direction
            else:
                log.warn("Warning: incompatible clipboard direction settings")
                log.warn(" server setting: %s, client setting: %s", self.server_clipboard_direction, self.client_clipboard_direction)
        self.server_clipboard_enable_selections = c.boolget("clipboard.enable-selections")
        self.server_clipboards = c.strlistget("clipboards", ALL_CLIPBOARDS)
        log("server clipboard: supported=%s, direction=%s, supports enable selection=%s",
                     self.server_clipboard, self.server_clipboard_direction, self.server_clipboard_enable_selections)
        log("client clipboard: supported=%s, direction=%s",
                     self.client_supports_clipboard, self.client_clipboard_direction)
        self.clipboard_enabled = self.client_supports_clipboard and self.server_clipboard
        log("parse_clipboard_caps() clipboard enabled=%s", self.clipboard_enabled)
        return True

    def process_ui_capabilities(self):
        if self.clipboard_enabled:
            self.clipboard_helper = self.make_clipboard_helper()
            self.clipboard_enabled = self.clipboard_helper is not None
            log("clipboard helper=%s", self.clipboard_helper)
            if self.clipboard_enabled and self.server_clipboard_enable_selections:
                #tell the server about which selections we really want to sync with
                #(could have been translated, or limited if the client only has one, etc)
                log("clipboard enabled clipboard helper=%s", self.clipboard_helper)
                self.send_clipboard_selections(self.clipboard_helper.remote_clipboards)
        #ui may want to know this is now set:
        self.emit("clipboard-toggled")
        if self.server_clipboard:
            #from now on, we will send a message to the server whenever the clipboard flag changes:
            self.connect("clipboard-toggled", self.clipboard_toggled)


    def init_authenticated_packet_handlers(self):
        self.set_packet_handlers(self._ui_packet_handlers, {
            "set-clipboard-enabled":        self._process_clipboard_enabled_status,
            "clipboard-token":              self.process_clipboard_packet,
            "clipboard-request":            self.process_clipboard_packet,
            "clipboard-contents":           self.process_clipboard_packet,
            "clipboard-contents-none":      self.process_clipboard_packet,
            "clipboard-pending-requests":   self.process_clipboard_packet,
            "clipboard-enable-selections":  self.process_clipboard_packet,
            })

    def get_clipboard_helper_classes(self):
        return []

    def make_clipboard_helper(self):
        """
            Try the various clipboard classes until we find one
            that loads ok. (some platforms have more options than others)
        """
        clipboard_options = self.get_clipboard_helper_classes()
        log("make_clipboard_helper() options=%s", clipboard_options)
        for helperclass in clipboard_options:
            try:
                return self.setup_clipboard_helper(helperclass)
            except ImportError as e:
                log.error("Error: cannot instantiate %s:", helperclass)
                log.error(" %s", e)
                del e
            except:
                log.error("cannot instantiate %s", helperclass, exc_info=True)
        return None

    def process_clipboard_packet(self, packet):
        ch = self.clipboard_helper
        log("process_clipboard_packet: %s, helper=%s", packet[0], ch)
        if ch:
            ch.process_clipboard_packet(packet)

    def _process_clipboard_enabled_status(self, packet):
        clipboard_enabled, reason = packet[1:3]
        if self.clipboard_enabled!=clipboard_enabled:
            log.info("clipboard toggled to %s by the server, reason given:", ["off", "on"][int(clipboard_enabled)])
            log.info(" %s", bytestostr(reason))
            self.clipboard_enabled = bool(clipboard_enabled)
            self.emit("clipboard-toggled")

    def clipboard_toggled(self, *args):
        log("clipboard_toggled%s clipboard_enabled=%s, server_clipboard=%s", args, self.clipboard_enabled, self.server_clipboard)
        if self.server_clipboard:
            self.send("set-clipboard-enabled", self.clipboard_enabled)
            if self.clipboard_enabled:
                ch = self.clipboard_helper
                assert ch is not None
                self.send_clipboard_selections(ch.remote_clipboards)
                ch.send_all_tokens()
            else:
                pass    #FIXME: todo!

    def send_clipboard_selections(self, selections):
        log("send_clipboard_selections(%s) server_clipboard_enable_selections=%s", selections, self.server_clipboard_enable_selections)
        if self.server_clipboard_enable_selections:
            self.send("clipboard-enable-selections", selections)

    def send_clipboard_loop_uuids(self):
        uuids = self.clipboard_helper.get_loop_uuids()
        log("send_clipboard_loop_uuid() uuids=%s", uuids)
        if self.server_clipboard_loop_uuids:
            self.send("clipboard-loop-uuids", uuids)
