# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2020 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path

from xpra.platform.features import CLIPBOARDS, CLIPBOARD_PREFERRED_TARGETS
from xpra.util import csv, nonl
from xpra.scripts.config import FALSE_OPTIONS
from xpra.server.mixins.stub_server_mixin import StubServerMixin
from xpra.log import Logger

log = Logger("clipboard")


"""
Mixin for servers that handle clipboard synchronization.
"""
class ClipboardServer(StubServerMixin):

    def __init__(self):
        self.clipboard = False
        self.clipboard_direction = "none"
        self.clipboard_filter_file = None
        self._clipboard_helper = None

    def init(self, opts):
        self.clipboard = not (opts.clipboard or "").lower() in FALSE_OPTIONS
        self.clipboard_direction = opts.clipboard_direction
        self.clipboard_filter_file = opts.clipboard_filter_file

    def setup(self):
        self.init_clipboard()

    def cleanup(self):
        ch = self._clipboard_helper
        if ch:
            self._clipboard_helper = None
            ch.cleanup()

    def cleanup_protocol(self, protocol):
        ch = self._clipboard_helper
        if ch and self._clipboard_client and self._clipboard_client.protocol==protocol:
            self._clipboard_client = None
            ch.client_reset()


    def parse_hello(self, ss, _caps, send_ui):
        if send_ui and self.clipboard:
            self.parse_hello_ui_clipboard(ss)


    def get_info(self, _proto) -> dict:
        if self._clipboard_helper is None:
            return {}
        ci = self._clipboard_helper.get_info()
        cc = self._clipboard_client
        if cc:
            ci["client"] = cc.uuid
        return {"clipboard" : ci}


    def get_server_features(self, server_source=None) -> dict:
        clipboard = self._clipboard_helper is not None
        log("clipboard_helper=%s, clipboard_client=%s, source=%s, clipboard=%s",
            self._clipboard_helper, self._clipboard_client, server_source, clipboard)
        if not clipboard:
            return {}
        f = {
            "clipboards"            : self._clipboards,
            "clipboard-direction"   : self.clipboard_direction,
            "clipboard" : {
                ""                      : True,
                "enable-selections"     : True,             #client check removed in v4
                "contents-slice-fix"    : True,             #fixed in v2.4
                "preferred-targets"     : CLIPBOARD_PREFERRED_TARGETS,
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
                log.error("invalid clipboard filter file: '%s' does not exist - clipboard disabled!",
                          self.clipboard_filter_file)
                return
            try:
                with open(self.clipboard_filter_file, "r" ) as f:
                    for line in f:
                        clipboard_filter_res.append(line.strip())
                    log("loaded %s regular expressions from clipboard filter file %s",
                        len(clipboard_filter_res), self.clipboard_filter_file)
            except OSError:
                log.error("Error: reading clipboard filter file %s - clipboard disabled!",
                          self.clipboard_filter_file, exc_info=True)
                return
        try:
            from xpra.platform.gui import get_clipboard_native_class
            clipboard_class = get_clipboard_native_class()
            assert clipboard_class, "no native clipboard support"
            parts = clipboard_class.split(".")
            mod = ".".join(parts[:-1])
            module = __import__(mod, {}, {}, [parts[-1]])
            ClipboardClass = getattr(module, parts[-1])
            log("ClipboardClass for %s: %s", clipboard_class, ClipboardClass)
            kwargs = {
                      "filters"     : clipboard_filter_res,
                      "can-send"    : self.clipboard_direction in ("to-client", "both"),
                      "can-receive" : self.clipboard_direction in ("to-server", "both"),
                      }
            self._clipboard_helper = ClipboardClass(self.send_clipboard_packet,
                                                    self.clipboard_progress, **kwargs)
            self._clipboard_helper.init_proxies_uuid()
            self._clipboards = CLIPBOARDS
        except Exception:
            #log("gdk clipboard helper failure", exc_info=True)
            log.error("Error: failed to setup clipboard helper", exc_info=True)
            self.clipboard = False

    def parse_hello_ui_clipboard(self, ss):
        #take the clipboard if no-one else has it yet:
        if not getattr(ss, "clipboard_enabled", False):
            log("client does not support clipboard")
            return
        if not self._clipboard_helper:
            log("server does not support clipboard")
            return
        cc = self._clipboard_client
        if cc and not cc.is_closed():
            log("another client already owns the clipboard")
            return
        self.set_clipboard_source(ss)

    def set_clipboard_source(self, ss):
        if not getattr(ss, "clipboard_enabled", False):
            #don't use this client as clipboard source!
            #(its clipboard is disabled)
            return
        if self._clipboard_client==ss:
            return
        self._clipboard_client = ss
        ch = self._clipboard_helper
        log("client %s is the clipboard peer, helper=%s", ss, ch)
        if not ch:
            return
        if ss:
            log(" greedy=%s", ss.clipboard_greedy)
            log(" want targets=%s", ss.clipboard_want_targets)
            log(" server has selections: %s", csv(self._clipboards))
            log(" client initial selections: %s", csv(ss.clipboard_client_selections))
            ch.set_greedy_client(ss.clipboard_greedy)
            ch.set_want_targets_client(ss.clipboard_want_targets)
            ch.enable_selections(ss.clipboard_client_selections)
            ch.set_clipboard_contents_slice_fix(ss.clipboard_contents_slice_fix)
            ch.set_preferred_targets(ss.clipboard_preferred_targets)
            ch.send_tokens(ss.clipboard_client_selections)
        else:
            ch.enable_selections([])


    def last_client_exited(self):
        ch = self._clipboard_helper
        if ch:
            ch.client_reset()


    def set_session_driver(self, source):
        self.set_clipboard_source(source)


    def _process_clipboard_packet(self, proto, packet):
        assert self.clipboard
        if self.readonly:
            return
        ss = self.get_server_source(proto)
        if not ss:
            #protocol has been dropped!
            return
        if self._clipboard_client!=ss:
            log("the clipboard packet '%s' does not come from the clipboard owner!", packet[0])
            return
        if not ss.clipboard_enabled:
            #this can happen when we disable clipboard in the middle of transfers
            #(especially when there is a clipboard loop)
            log.warn("Warning: unexpected clipboard packet")
            log.warn(" clipboard is disabled for %s", nonl(ss.uuid))
            return
        ch = self._clipboard_helper
        assert ch, "received a clipboard packet but clipboard sharing is disabled"
        self.idle_add(ch.process_clipboard_packet, packet)

    def _process_clipboard_enabled_status(self, proto, packet):
        assert self.clipboard
        if self.readonly:
            return
        clipboard_enabled = packet[1]
        ss = self.get_server_source(proto)
        self.set_clipboard_enabled_status(ss, clipboard_enabled)

    def set_clipboard_enabled_status(self, ss, clipboard_enabled):
        ch = self._clipboard_helper
        if not ch:
            log.warn("Warning: client try to toggle clipboard-enabled status,")
            log.warn(" but we do not support clipboard at all! Ignoring it.")
            return
        cc = self._clipboard_client
        cc.clipboard_enabled = clipboard_enabled
        log("toggled clipboard to %s for %s", clipboard_enabled, ss.protocol)
        if cc!=ss or ss is None:
            log("received a request to change the clipboard status,")
            log(" but it does not come from the clipboard owner! Ignoring it.")
            log(" from %s", cc)
            log(" owner is %s", self._clipboard_client)
            return
        if not clipboard_enabled:
            ch.enable_selections([])

    def clipboard_progress(self, local_requests, _remote_requests):
        assert self.clipboard
        if self._clipboard_client:
            self._clipboard_client.send_clipboard_progress(local_requests)

    def send_clipboard_packet(self, *parts):
        assert self.clipboard
        if self._clipboard_client:
            self._clipboard_client.send_clipboard(parts)


    def init_packet_handlers(self):
        if self.clipboard:
            self.add_packet_handler("set-clipboard-enabled", self._process_clipboard_enabled_status)
            for x in (
                "token", "request", "contents", "contents-none",
                "pending-requests", "enable-selections", "loop-uuids",
                ):
                self.add_packet_handler("clipboard-%s" % x, self._process_clipboard_packet)
