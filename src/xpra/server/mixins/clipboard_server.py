# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path

from xpra.log import Logger
log = Logger("clipboard")

from xpra.platform.features import CLIPBOARDS
from xpra.util import csv
from xpra.scripts.config import FALSE_OPTIONS
from xpra.server.mixins.stub_server_mixin import StubServerMixin


"""
Mixin for servers that handle clipboard synchronization.
"""
class ClipboardServer(StubServerMixin):

    def __init__(self):
        self.clipboard = False
        self.clipboard_direction = "none"
        self.clipboard_filter_file = None

    def init(self, opts):
        self.clipboard = not ((opts.clipboard or "").lower() in FALSE_OPTIONS)
        self.clipboard_direction = opts.clipboard_direction
        self.clipboard_filter_file = opts.clipboard_filter_file

    def setup(self):
        self.init_clipboard()

    def cleanup(self):
        ch = self._clipboard_helper
        if ch:
            self._clipboard_helper = None
            ch.cleanup()

    def cleanup_protocol(self, proto):
        ch = self._clipboard_helper
        if ch and self._clipboard_client and self._clipboard_client.protocol==proto:
            self._clipboard_client = None
            ch.client_reset()


    def parse_hello(self, ss, caps, send_ui):
        if send_ui:
            self.parse_hello_ui_clipboard(ss, caps)


    def get_info(self, _proto):
        if self._clipboard_helper is None:
            return {}
        return {"clipboard" : self._clipboard_helper.get_info()}


    def get_server_features(self, server_source=None):
        clipboard = self._clipboard_helper is not None and self._clipboard_client == server_source
        log("clipboard_helper=%s, clipboard_client=%s, source=%s, clipboard=%s", self._clipboard_helper, self._clipboard_client, server_source, clipboard)
        if not clipboard:
            return {}
        f = {
            "clipboards"            : self._clipboards,
            "clipboard-direction"   : self.clipboard_direction,
            "clipboard" : {
                ""                  : True,
                "enable-selections" : True,
                },
            }
        if self._clipboard_helper:
            f["clipboard.loop-uuids"] = self._clipboard_helper.get_loop_uuids()
        return f

    def init_clipboard(self):
        log("init_clipboard() enabled=%s, filter file=%s", self.clipboard, self.clipboard_filter_file)
        ### Clipboard handling:
        self._clipboard_helper = None
        self._clipboard_client = None
        self._clipboards = []
        if not self.clipboard:
            return
        clipboard_filter_res = []
        if self.clipboard_filter_file:
            if not os.path.exists(self.clipboard_filter_file):
                log.error("invalid clipboard filter file: '%s' does not exist - clipboard disabled!", self.clipboard_filter_file)
                return
            try:
                with open(self.clipboard_filter_file, "r" ) as f:
                    for line in f:
                        clipboard_filter_res.append(line.strip())
                    log("loaded %s regular expressions from clipboard filter file %s", len(clipboard_filter_res), self.clipboard_filter_file)
            except:
                log.error("error reading clipboard filter file %s - clipboard disabled!", self.clipboard_filter_file, exc_info=True)
                return
        try:
            from xpra.clipboard.gdk_clipboard import GDKClipboardProtocolHelper
            kwargs = {
                      "filters"     : clipboard_filter_res,
                      "can-send"    : self.clipboard_direction in ("to-client", "both"),
                      "can-receive" : self.clipboard_direction in ("to-server", "both"),
                      }
            self._clipboard_helper = GDKClipboardProtocolHelper(self.send_clipboard_packet, self.clipboard_progress, **kwargs)
            self._clipboards = CLIPBOARDS
        except Exception:
            #log("gdk clipboard helper failure", exc_info=True)
            log.error("Error: failed to setup clipboard helper", exc_info=True)
            self.clipboard = False

    def parse_hello_ui_clipboard(self, ss, c):
        #take the clipboard if no-one else has it yet:
        if not ss.clipboard_enabled:
            log("client does not support clipboard")
            return
        if not self._clipboard_helper:
            log("server does not support clipboard")
            return
        cc = self._clipboard_client
        if cc and not cc.is_closed():
            log("another client already owns the clipboard")
            return
        self._clipboard_client = ss
        self._clipboard_helper.init_proxies_uuid()
        #deal with buggy win32 clipboards:
        if "clipboard.greedy" not in c:
            #old clients without the flag: take a guess based on platform:
            client_platform = c.strget("platform", "")
            greedy = client_platform.startswith("win") or client_platform.startswith("darwin")
        else:
            greedy = c.boolget("clipboard.greedy")
        self._clipboard_helper.set_greedy_client(greedy)
        want_targets = c.boolget("clipboard.want_targets")
        self._clipboard_helper.set_want_targets_client(want_targets)
        #the selections the client supports (default to all):
        client_selections = c.strlistget("clipboard.selections", CLIPBOARDS)
        log("client %s is the clipboard peer", ss)
        log(" greedy=%s", greedy)
        log(" want targets=%s", want_targets)
        log(" server has selections: %s", csv(self._clipboards))
        log(" client initial selections: %s", csv(client_selections))
        self._clipboard_helper.enable_selections(client_selections)

    def _process_clipboard_packet(self, proto, packet):
        if self.readonly:
            return
        ss = self._server_sources.get(proto)
        if not ss:
            #protocol has been dropped!
            return
        assert self._clipboard_client==ss, \
                "the clipboard packet '%s' does not come from the clipboard owner!" % packet[0]
        if not ss.clipboard_enabled:
            #this can happen when we disable clipboard in the middle of transfers
            #(especially when there is a clipboard loop)
            log.warn("received a clipboard packet from a source which does not have clipboard enabled!")
            return
        ch = self._clipboard_helper
        assert ch, "received a clipboard packet but clipboard sharing is disabled"
        def do_check():
            if self.clipboard_nesting_check("receiving", packet[0], ss):
                ch.process_clipboard_packet(packet)
        #the nesting check and the clipboard handlers call gtk:
        self.idle_add(do_check)

    def clipboard_nesting_check(self, action, packet_type, ss):
        log("clipboard_nesting_check(%s, %s, %s)", action, packet_type, ss)
        cc = self._clipboard_client
        if cc is None:
            log("not %s clipboard packet '%s': no clipboard client", action, packet_type)
            return False
        if not cc.clipboard_enabled:
            log("not %s clipboard packet '%s': client %s has clipboard disabled", action, packet_type, cc)
            return False
        from xpra.clipboard.clipboard_base import nesting_check
        if not nesting_check():
            #turn off clipboard at our end:
            self.set_clipboard_enabled_status(ss, False)
            #if we can, tell the client to do the same:
            if ss.clipboard_set_enabled:
                ss.send_clipboard_enabled("probable clipboard loop detected")
            return  False
        return True

    def _process_clipboard_enabled_status(self, proto, packet):
        if self.readonly:
            return
        clipboard_enabled = packet[1]
        ss = self._server_sources.get(proto)
        self.set_clipboard_enabled_status(ss, clipboard_enabled)

    def set_clipboard_enabled_status(self, ss, clipboard_enabled):
        ch = self._clipboard_helper
        if not ch:
            log.warn("Warning: client try to toggle clipboard-enabled status,")
            log.warn(" but we do not support clipboard at all! Ignoring it.")
            return
        cc = self._clipboard_client
        if cc!=ss or ss is None:
            log.warn("Warning: received a request to change the clipboard status,")
            log.warn(" but it does not come from the clipboard owner! Ignoring it.")
        cc.clipboard_enabled = clipboard_enabled
        if not clipboard_enabled:
            ch.enable_selections([])
        log("toggled clipboard to %s for %s", clipboard_enabled, ss.protocol)

    def clipboard_progress(self, local_requests, _remote_requests):
        assert self._clipboard_helper is not None
        if self._clipboard_client:
            self._clipboard_client.send_clipboard_progress(local_requests)

    def send_clipboard_packet(self, *parts):
        assert self._clipboard_helper is not None
        if self._clipboard_client:
            self._clipboard_client.send_clipboard(parts)


    def init_packet_handlers(self):
        if self.clipboard:
            self._authenticated_packet_handlers.update({
                "set-clipboard-enabled":                self._process_clipboard_enabled_status,
              })
            for x in ("token", "request", "contents", "contents-none", "pending-requests", "enable-selections", "loop-uuids"):
                self._authenticated_ui_packet_handlers["clipboard-%s" % x] = self._process_clipboard_packet
