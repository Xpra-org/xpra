# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2023 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
from typing import Dict, Any, Tuple

from xpra.platform.features import (
    CLIPBOARDS, CLIPBOARD_PREFERRED_TARGETS,
    CLIPBOARD_WANT_TARGETS, CLIPBOARD_GREEDY,
    )
from xpra.util import csv
from xpra.net.common import PacketType
from xpra.scripts.config import FALSE_OPTIONS
from xpra.server.mixins.stub_server_mixin import StubServerMixin
from xpra.log import Logger

log = Logger("clipboard")


class ClipboardServer(StubServerMixin):
    """
    Mixin for servers that handle clipboard synchronization.
    """

    def __init__(self):
        self.clipboard = False
        self.clipboard_direction = "none"
        self.clipboard_filter_file = None
        self._clipboard_helper = None
        self._clipboard_client = None
        self._clipboards : Tuple[str,...] = ()

    def init(self, opts) -> None:
        self.clipboard = (opts.clipboard or "").lower() not in FALSE_OPTIONS
        self.clipboard_direction = opts.clipboard_direction
        self.clipboard_filter_file = opts.clipboard_filter_file

    def setup(self) -> None:
        self.init_clipboard()

    def cleanup(self) -> None:
        ch = self._clipboard_helper
        if ch:
            self._clipboard_helper = None
            ch.cleanup()

    def cleanup_protocol(self, protocol) -> None:
        ch = self._clipboard_helper
        if ch and self._clipboard_client and self._clipboard_client.protocol==protocol:
            self._clipboard_client = None
            ch.client_reset()


    def parse_hello(self, ss, _caps, send_ui:bool) -> None:
        if send_ui and self.clipboard:
            self.parse_hello_ui_clipboard(ss)


    def get_info(self, _proto) -> Dict[str,Any]:
        if self._clipboard_helper is None:
            return {}
        ci = self._clipboard_helper.get_info()
        cc = self._clipboard_client
        if cc:
            ci["client"] = cc.uuid
        return {"clipboard" : ci}


    def get_server_features(self, server_source=None) -> Dict[str,Any]:
        clipboard = self._clipboard_helper is not None
        log("clipboard_helper=%s, clipboard_client=%s, source=%s, clipboard=%s",
            self._clipboard_helper, self._clipboard_client, server_source, clipboard)
        if not clipboard:
            return {}
        ccaps = {
            "notifications"         : True,
            "selections"            : self._clipboards,
            "enable-selections"     : True,             #client check removed in v4
            "contents-slice-fix"    : True,             #fixed in v2.4, removed check in v4.3
            "want_targets"          : CLIPBOARD_WANT_TARGETS,
            "greedy"                : CLIPBOARD_GREEDY,
            "preferred-targets"     : CLIPBOARD_PREFERRED_TARGETS,
            "set_enabled"           : True,     #v4 servers no longer use or show this flag
            "direction"             : self.clipboard_direction,
            }
        log("clipboard server caps=%s", ccaps)
        return {
            "clipboard"             : ccaps,
            #for versions older than v4.4, duplicated here without the namespace:
            "clipboards"            : self._clipboards,
            "clipboard-direction"   : self.clipboard_direction,
            }

    def init_clipboard(self) -> None:
        log("init_clipboard() enabled=%s, filter file=%s", self.clipboard, self.clipboard_filter_file)
        ### Clipboard handling:
        if not self.clipboard:
            return
        clipboard_filter_res = []
        if self.clipboard_filter_file:
            if not os.path.exists(self.clipboard_filter_file):
                log.error("invalid clipboard filter file: '%s' does not exist - clipboard disabled!",
                          self.clipboard_filter_file)
                return
            try:
                with open(self.clipboard_filter_file, "r", encoding="utf8") as f:
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
            if not clipboard_class:
                raise RuntimeError("no native clipboard support on this platform")
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
            self._clipboard_helper.init_proxies_claim()
            self._clipboards = CLIPBOARDS
        except Exception:
            #log("gdk clipboard helper failure", exc_info=True)
            log.error("Error: failed to setup clipboard helper", exc_info=True)
            self.clipboard = False

    def parse_hello_ui_clipboard(self, ss) -> None:
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

    def set_clipboard_source(self, ss) -> None:
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
            log(" client initial selections: %s", csv(ss.clipboard_selections))
            ch.set_greedy_client(ss.clipboard_greedy)
            ch.set_want_targets_client(ss.clipboard_want_targets)
            ch.enable_selections(ss.clipboard_selections)
            ch.set_preferred_targets(ss.clipboard_preferred_targets)
            ch.send_tokens(ss.clipboard_selections)
        else:
            ch.enable_selections(None)


    def last_client_exited(self) -> None:
        ch = self._clipboard_helper
        if ch:
            ch.client_reset()


    def set_session_driver(self, source) -> None:
        self.set_clipboard_source(source)


    def _process_clipboard_packet(self, proto, packet : PacketType) -> None:
        assert self.clipboard
        if self.readonly:
            return
        ss = self.get_server_source(proto)
        if not ss:
            #protocol has been dropped!
            return
        packet_type = packet[0]
        if packet_type=="clipboard-status":
            self._process_clipboard_status(proto, packet)
            return
        if self._clipboard_client!=ss:
            log("the clipboard packet '%s' does not come from the clipboard owner!", packet[0])
            return
        if not ss.clipboard_enabled:
            #this can happen when we disable clipboard in the middle of transfers
            #(especially when there is a clipboard loop)
            log.warn("Warning: unexpected clipboard packet")
            log.warn(" clipboard is disabled for %r", ss.uuid)
            return
        ch = self._clipboard_helper
        assert ch, "received a clipboard packet but clipboard sharing is disabled"
        self.idle_add(ch.process_clipboard_packet, packet)

    def _process_clipboard_status(self, proto, packet : PacketType) -> None:
        assert self.clipboard
        if self.readonly:
            return
        clipboard_enabled = packet[1]
        ss = self.get_server_source(proto)
        if ss:
            self.set_clipboard_enabled_status(ss, clipboard_enabled)

    def set_clipboard_enabled_status(self, ss, clipboard_enabled:bool) -> None:
        ch = self._clipboard_helper
        if not ch:
            log.warn("Warning: client try to toggle clipboard-enabled status,")
            log.warn(" but we do not support clipboard at all! Ignoring it.")
            return
        cc = self._clipboard_client
        if not cc:
            return
        cc.clipboard_enabled = clipboard_enabled
        log("toggled clipboard to %s for %s", clipboard_enabled, ss.protocol)
        if cc!=ss or ss is None:
            log("received a request to change the clipboard status,")
            log(" but it does not come from the clipboard owner! Ignoring it.")
            log(" from %s", cc)
            log(" owner is %s", self._clipboard_client)
            return
        if not clipboard_enabled:
            ch.enable_selections(None)

    def clipboard_progress(self, local_requests, _remote_requests) -> None:
        assert self.clipboard
        if self._clipboard_client:
            self._clipboard_client.send_clipboard_progress(local_requests)

    def send_clipboard_packet(self, *parts) -> None:
        assert self.clipboard
        if self._clipboard_client:
            self._clipboard_client.send_clipboard(parts)


    def init_packet_handlers(self) -> None:
        if self.clipboard:
            self.add_packet_handler("set-clipboard-enabled", self._process_clipboard_status)
            for x in (
                "token", "request", "contents", "contents-none",
                "pending-requests", "enable-selections", "loop-uuids",
                "status",
                ):
                self.add_packet_handler("clipboard-%s" % x, self._process_clipboard_packet)
