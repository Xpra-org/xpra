# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
from typing import Any
from collections.abc import Sequence
from importlib import import_module

from xpra.clipboard.common import get_local_selections
from xpra.net.constants import ConnectionMessage
from xpra.server.source.clipboard import ClipboardConnection
from xpra.util.objects import typedict
from xpra.util.str_fn import csv
from xpra.net.common import Packet, PacketElement, BACKWARDS_COMPATIBLE
from xpra.util.parsing import FALSE_OPTIONS
from xpra.server.subsystem.stub import StubSubsystem
from xpra.log import Logger

log = Logger("clipboard")


class ClipboardManager(StubSubsystem):
    """
    Mixin for servers that handle clipboard synchronization.
    """
    __slots__ = ("client", "direction", "enabled", "filter_file", "helper", "selections")
    PREFIX = "clipboard"
    toggle_features = ("clipboard",)

    def __init__(self, server=None):
        StubSubsystem.__init__(self, server)
        self.enabled = False
        self.direction = "none"
        self.filter_file = None
        self.helper = None
        self.client = None
        self.selections: Sequence[str] = ()

    def init(self, opts) -> None:
        self.enabled = (opts.clipboard or "").lower() not in FALSE_OPTIONS
        self.direction = opts.clipboard_direction
        self.filter_file = opts.clipboard_filter_file
        log("init(..) clipboard=%s, direction=%r, filter-file=%r",
            self.enabled, self.direction, self.filter_file)

    def setup(self) -> None:
        self.init_clipboard()
        self.server.connect("last-client-exited", self.reset_clipboard)

        def new_ui_driver(_server, source) -> None:
            self.set_clipboard_source(source)
        self.server.connect("new-ui-driver", new_ui_driver)
        self.add_clipboard_control_commands()

    def add_clipboard_control_commands(self) -> None:
        ac = self.args_control
        ac("clipboard-direction", "restrict clipboard transfers", min_args=1, max_args=1)
        ac("clipboard-limits", "restrict clipboard transfers size", min_args=2, max_args=2, validation=[int, int])

    def reset_clipboard(self, *args) -> None:
        ch = self.helper
        log("reset_clipboard%s helper=%s", args, ch)
        if ch:
            ch.client_reset()

    def cleanup(self) -> None:
        if ch := self.helper:
            self.helper = None
            ch.cleanup()

    def cleanup_protocol(self, protocol) -> None:
        ch = self.helper
        if ch and self.client and self.client.protocol == protocol:
            self.client = None
            ch.client_reset()

    def parse_hello(self, ss, caps: typedict) -> str | ConnectionMessage:
        if self.enabled:
            self.parse_hello_ui_clipboard(ss)
        return ""

    def get_info(self, _proto) -> dict[str, Any]:
        if self.helper is None:
            return {}
        ci = self.helper.get_info()
        if cc := self.client:
            ci["client"] = cc.uuid
        return {ClipboardManager.PREFIX: ci}

    def get_caps(self, server_source=None) -> dict[str, Any]:
        ch = self.helper
        clipboard = ch is not None
        log("clipboard_helper=%s, clipboard_client=%s, source=%s, clipboard=%s",
            ch, self.client, server_source, clipboard)
        if not clipboard:
            return {}
        ccaps: dict[str, Any] = {
            "notifications": True,
            "selections": self.selections,
            "direction": self.direction,
        }
        ccaps.update(ch.get_caps())
        log("clipboard server caps=%s", ccaps)
        return {ClipboardManager.PREFIX: ccaps}

    def init_clipboard(self) -> None:
        log("init_clipboard() enabled=%s, filter file=%s", self.enabled, self.filter_file)
        # Clipboard handling:
        if not self.enabled:
            return
        clipboard_filter_res = []
        if self.filter_file:
            if not os.path.exists(self.filter_file):
                log.error("invalid clipboard filter file: '%s' does not exist - clipboard disabled!",
                          self.filter_file)
                return
            try:
                with open(self.filter_file, encoding="utf8") as f:
                    for line in f:
                        clipboard_filter_res.append(line.strip())
                    log("loaded %s regular expressions from clipboard filter file %s",
                        len(clipboard_filter_res), self.filter_file)
            except OSError:
                log.error("Error: reading clipboard filter file %s - clipboard disabled!",
                          self.filter_file, exc_info=True)
                return
        clipboard_class = self.get_clipboard_class()
        if not clipboard_class:
            log.warn("Warning: no clipboard backend class, clipboard is disabled!")
            self.enabled = True
            return
        log("clipboard_class=%s",clipboard_class)
        kwargs = {
            "filters": clipboard_filter_res,
            "can-send": self.direction in ("to-client", "both"),
            "can-receive": self.direction in ("to-server", "both"),
        }
        self.helper = clipboard_class(self.send_clipboard_packet, self.clipboard_progress, **kwargs)
        self.helper.init_proxies_claim()
        self.selections = get_local_selections()
        self.enabled = True

    @staticmethod
    def get_clipboard_class():
        clipboard_class = "unknown"
        try:
            from xpra.platform.clipboard import get_backend_module
            clipboard_class = get_backend_module()
            if not clipboard_class:
                raise RuntimeError("no native clipboard support on this platform")
            parts = clipboard_class.split(".")
            mod = ".".join(parts[:-1])
            class_name = parts[-1]
            module = import_module(mod)
            return getattr(module, class_name)
        except (ImportError, AttributeError) as e:
            log("get_clipboard_class()", exc_info=True)
            log.error(f"Error: unable to load the clipboard helper class {clipboard_class!r}")
            log.estr(e)
            return None

    def parse_hello_ui_clipboard(self, ss) -> None:
        # take the clipboard if no-one else has it yet:
        if not self.can_source_own_clipboard(ss):
            return
        if not self.helper:
            log("server does not support clipboard")
            return
        cc = self.client
        if cc and not cc.is_closed():
            log("another client already owns the clipboard")
            return
        self.set_clipboard_source(ss)

    @staticmethod
    def can_source_own_clipboard(ss) -> bool:
        if not getattr(ss, "clipboard_enabled", False):
            log("client does not support clipboard")
            return False
        if getattr(ss, "clipboard_record", False):
            log("client records clipboard, does not own it")
            return False
        return True

    def set_clipboard_source(self, ss) -> None:
        if not self.can_source_own_clipboard(ss):
            return
        if self.client == ss:
            return
        self.client = ss
        ch = self.helper
        log("client %s is the clipboard peer, helper=%s", ss, ch)
        if not ch:
            return
        if ss:
            log(" greedy=%s", ss.clipboard_greedy)
            log(" want targets=%s", ss.clipboard_want_targets)
            log(" server has selections: %s", csv(self.selections))
            log(" client initial selections: %s", csv(ss.clipboard_selections))
            ch.set_greedy_client(ss.clipboard_greedy)
            ch.set_want_targets_client(ss.clipboard_want_targets)
            ch.enable_selections(ss.clipboard_selections)
            ch.set_preferred_targets(ss.clipboard_preferred_targets)
            ch.send_tokens(ss.clipboard_selections)
        else:
            ch.enable_selections()

    def _process_clipboard_packet(self, proto, packet: Packet) -> None:
        assert self.enabled
        if self.is_readonly(proto):
            return
        ss = self.get_server_source(proto)
        if not ss:
            # protocol has been dropped!
            return
        self.may_record("server", *packet)
        packet_type = packet.get_type()
        if packet_type == "clipboard-status" or (BACKWARDS_COMPATIBLE and packet_type == "set-clipboard-enabled"):
            self._process_clipboard_status(proto, packet)
            return
        if self.client != ss:
            log("the clipboard packet %r does not come from the clipboard owner!", packet_type)
            log(" owner is %s, request from %s", self.client, ss)
            return
        if not ss.clipboard_enabled:
            # this can happen when we disable clipboard in the middle of transfers
            # (especially when there is a clipboard loop)
            log.warn("Warning: unexpected clipboard packet")
            log.warn(" clipboard is disabled for %r", ss.uuid)
            return
        ch = self.helper
        assert ch, "received a clipboard packet but clipboard sharing is disabled"
        self.idle_add(ch.process_clipboard_packet, packet)

    def _process_clipboard_status(self, proto, packet: Packet) -> None:
        assert self.enabled
        if self.is_readonly(proto):
            return
        clipboard_enabled = packet.get_bool(1)
        if ss := self.get_server_source(proto):
            self.set_clipboard_enabled_status(ss, clipboard_enabled)

    def set_clipboard_enabled_status(self, ss, clipboard_enabled: bool) -> None:
        ch = self.helper
        if not ch:
            log.warn("Warning: client try to toggle clipboard-enabled status,")
            log.warn(" but we do not support clipboard at all! Ignoring it.")
            return
        cc = self.client
        if not cc:
            return
        cc.clipboard_enabled = clipboard_enabled
        log("toggled clipboard to %s for %s", clipboard_enabled, ss.protocol)
        if cc != ss or ss is None:
            log("received a request to change the clipboard status,")
            log(" but it does not come from the clipboard owner! Ignoring it.")
            log(" from %s", cc)
            log(" owner is %s", self.client)
            return
        if not clipboard_enabled:
            ch.enable_selections()

    def clipboard_progress(self, local_requests: int, _remote_requests: int) -> None:
        assert self.enabled
        if self.client:
            self.client.send_clipboard_progress(local_requests)

    def send_clipboard_packet(self, packet_type: str, *parts: PacketElement) -> None:
        assert self.enabled
        if self.client:
            packet = (packet_type, *parts)
            self.client.send_clipboard(packet)
            self.may_record("client", packet_type, *parts)

    def may_record(self, direction, packet_type: str, *parts: PacketElement) -> None:
        clipboard_sources = self.get_sources_by_type(ClipboardConnection)
        for ss in clipboard_sources:
            if ss.clipboard_record:
                rec_packet = ("clipboard-record", direction, packet_type, *parts)
                ss.send_clipboard(rec_packet)

    def init_packet_handlers(self) -> None:
        if self.enabled:
            for x in (
                    "data", "request", "contents", "contents-none",
                    "pending-requests", "enable-selections", "loop-uuids",
                    "status",
            ):
                self.add_packet_handler(f"{ClipboardManager.PREFIX}-%s" % x, self._process_clipboard_packet)
            if BACKWARDS_COMPATIBLE:
                self.add_packet_handler(f"{ClipboardManager.PREFIX}-token", self._process_clipboard_packet)
            self.add_legacy_alias("set-clipboard-enabled", f"{ClipboardManager.PREFIX}-status")

    #########################################
    # Control Commands
    #########################################

    def control_command_clipboard_direction(self, direction: str, *_args) -> str:
        ch = self.helper
        assert self.enabled and ch
        direction = direction.lower()
        DIRECTIONS = ("to-server", "to-client", "both", "disabled")
        if direction not in DIRECTIONS:
            raise ValueError(f"invalid direction {direction!r}, must be one of " + csv(DIRECTIONS))
        self.direction = direction
        can_send = direction in ("to-server", "both")
        can_receive = direction in ("to-client", "both")
        ch.set_direction(can_send, can_receive)
        msg = f"clipboard direction set to {direction!r}"
        log(msg)
        self.setting_changed("clipboard-direction", direction)
        return msg

    def control_command_clipboard_limits(self, max_send: int, max_recv: int, *_args) -> str:
        ch = self.helper
        assert self.enabled and ch
        ch.set_limits(max_send, max_recv)
        msg = f"clipboard send limit set to {max_send}, recv limit set to {max_recv} (single copy/paste)"
        log(msg)
        self.setting_changed("clipboard-limits", {'send': max_send, 'recv': max_recv})
        return msg
