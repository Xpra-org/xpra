# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any
from importlib import import_module
from collections.abc import Sequence

from xpra.common import ALL_CLIPBOARDS, BACKWARDS_COMPATIBLE
from xpra.client.base.stub import StubClientMixin
from xpra.platform.features import CLIPBOARD_WANT_TARGETS, CLIPBOARD_GREEDY, CLIPBOARD_PREFERRED_TARGETS, CLIPBOARDS
from xpra.platform.clipboard import get_backend_module
from xpra.net.common import Packet, PacketElement
from xpra.net import compression
from xpra.util.parsing import parse_simple_dict, TRUE_OPTIONS, FALSE_OPTIONS
from xpra.util.objects import typedict
from xpra.log import Logger

log = Logger("clipboard")

CLIPBOARD_CLASS = os.environ.get("XPRA_CLIPBOARD_CLASS", "")


def get_clipboard_helper_classes(clipboard_type: str) -> list[type]:
    ct = clipboard_type
    if ct and ct.lower() in FALSE_OPTIONS:
        return []
    # first add the platform specific one, (which may be None):
    clipboard_classes = [
        CLIPBOARD_CLASS,
        get_backend_module(),
    ]
    log("get_clipboard_helper_classes() unfiltered list=%s", clipboard_classes)
    if ct and ct.lower() != "auto" and ct.lower() not in TRUE_OPTIONS:
        # try to match the string specified:
        filtered = [x for x in clipboard_classes if x and x.lower().find(ct) >= 0]
        if not filtered:
            log.warn(f"Warning: no clipboard types matching {ct!r}")
            log.warn(" clipboard synchronization is disabled")
            return []
        log(" found %i clipboard types matching '%s'", len(filtered), ct)
        clipboard_classes = filtered
    # now try to load them:
    log("get_clipboard_helper_classes() options=%s", clipboard_classes)
    loadable = []
    for co in clipboard_classes:
        if not co:
            continue
        parts = co.split(".")
        mod = ".".join(parts[:-1])
        class_name = parts[-1]
        try:
            module = import_module(mod)
            helper_class = getattr(module, class_name)
            loadable.append(helper_class)
        except ImportError:
            log("cannot load %s", co, exc_info=True)
            log.warn(f"Warning: cannot load clipboard class {class_name!r} from {mod!r}")
            continue
    log("get_clipboard_helper_classes()=%s", loadable)
    return loadable


class ClipboardClient(StubClientMixin):
    """
    Utility mixin for clients that handle clipboard synchronization
    """
    __signals__ = ["clipboard-toggled"]
    PREFIX = "clipboard"

    def __init__(self):
        self.client_clipboard_type: str = ""
        self.client_clipboard_direction: str = "both"
        self.client_supports_clipboard: bool = False
        self.clipboard_enabled: bool = False
        self.server_clipboard_direction: str = "both"
        self.server_clipboard: bool = False
        self.server_clipboard_preferred_targets: Sequence[str] = ()
        self.server_clipboard_greedy: bool = False
        self.server_clipboard_want_targets: bool = False
        self.server_clipboard_selections: Sequence[str] = ()
        self.clipboard_helper = None
        self.local_clipboard_requests: int = 0
        self.remote_clipboard_requests: int = 0
        # only used with the translated clipboard class:
        self.local_clipboard: str = ""
        self.remote_clipboard: str = ""

    def init(self, opts) -> None:
        self.client_clipboard_type = opts.clipboard
        self.client_clipboard_direction = opts.clipboard_direction
        self.client_supports_clipboard = (opts.clipboard or "").lower() not in FALSE_OPTIONS
        self.remote_clipboard = opts.remote_clipboard
        self.local_clipboard = opts.local_clipboard

    def cleanup(self) -> None:
        ch = self.clipboard_helper
        log("ClipboardClient.cleanup() clipboard_helper=%s", ch)
        if ch:
            self.clipboard_helper = None
            with log.trap_error(f"Error on clipboard helper {ch} cleanup"):
                ch.cleanup()

    def get_info(self) -> dict[str, dict[str, Any]]:
        info: dict[str, Any] = {
            "client":
            {
                "enabled": self.clipboard_enabled,
                "type": self.client_clipboard_type,
                "direction": self.client_clipboard_direction,
            },
            "server":
            {
                "enabled": self.server_clipboard,
                "direction": self.server_clipboard_direction,
                "selections": self.server_clipboard_selections,
            },
            "requests":
            {
                "local": self.local_clipboard_requests,
                "remote": self.remote_clipboard_requests,
            },
        }
        return {"clipboard": info}

    def get_caps(self) -> dict[str, Any]:
        if not self.client_supports_clipboard:
            return {}
        caps: dict[str, Any] = {
            "notifications": True,
            "selections": CLIPBOARDS,
            "preferred-targets": CLIPBOARD_PREFERRED_TARGETS,
        }
        # macos clipboard must provide targets:
        if CLIPBOARD_WANT_TARGETS:
            caps["want_targets"] = True
        # macos and win32 clipboards must provide values:
        if CLIPBOARD_GREEDY:
            caps["greedy"] = True
        if BACKWARDS_COMPATIBLE:
            caps["enabled"] = True
            caps[""] = True
        log("clipboard.get_caps()=%s", caps)
        return {ClipboardClient.PREFIX: caps}

    def parse_server_capabilities(self, c: typedict) -> bool:
        try:
            from xpra import clipboard
            assert clipboard
        except ImportError:
            log.warn("Warning: clipboard module is missing")
            self.clipboard_enabled = False
            return True
        self.server_clipboard = c.boolget("clipboard")
        self.server_clipboard_direction = c.strget("clipboard-direction", "both")
        if self.server_clipboard_direction not in ("both", self.client_clipboard_direction):
            if self.client_clipboard_direction == "disabled":
                log("client clipboard is disabled")
            elif self.server_clipboard_direction == "disabled":
                log.warn("Warning: server clipboard synchronization is currently disabled")
                self.client_clipboard_direction = "disabled"
            elif self.client_clipboard_direction == "both":
                log.warn("Warning: server only supports '%s' clipboard transfers", self.server_clipboard_direction)
                self.client_clipboard_direction = self.server_clipboard_direction
            else:
                log.warn("Warning: incompatible clipboard direction settings")
                log.warn(" server setting: %s, client setting: %s",
                         self.server_clipboard_direction, self.client_clipboard_direction)
        self.server_clipboard_selections = c.strtupleget("clipboard.selections", ALL_CLIPBOARDS)
        log("server clipboard: supported=%s, selections=%s, direction=%s",
            self.server_clipboard, self.server_clipboard_selections, self.server_clipboard_direction)
        log("client clipboard: supported=%s, selections=%s, direction=%s",
            self.client_supports_clipboard, CLIPBOARDS, self.client_clipboard_direction)
        self.clipboard_enabled = self.client_supports_clipboard and self.server_clipboard
        self.server_clipboard_greedy = c.boolget("clipboard.greedy")
        self.server_clipboard_want_targets = c.boolget("clipboard.want_targets")
        self.server_clipboard_preferred_targets = c.strtupleget("clipboard.preferred-targets", ())
        log("server clipboard: greedy=%s, want_targets=%s, selections=%s",
            self.server_clipboard_greedy, self.server_clipboard_want_targets, self.server_clipboard_selections)
        log("parse_clipboard_caps() clipboard enabled=%s", self.clipboard_enabled)
        self.server_clipboard_preferred_targets = c.strtupleget("clipboard.preferred-targets", ())
        return True

    def process_ui_capabilities(self, caps: typedict) -> None:
        log("process_ui_capabilities() clipboard_enabled=%s", self.clipboard_enabled)
        if self.clipboard_enabled:
            ch = self.make_clipboard_helper()
            if not ch:
                log.warn("Warning: no clipboard support")
            self.clipboard_helper = ch
            self.clipboard_enabled = ch is not None
            log("clipboard helper=%s", ch)
            if self.clipboard_enabled:
                # tell the server about which selections we really want to sync with
                # (could have been translated, or limited if the client only has one, etc.)
                self.send_clipboard_selections(ch.get_remote_selections())
                ch.send_all_tokens()
        # ui may want to know this is now set:
        self.emit("clipboard-toggled")

    def init_authenticated_packet_handlers(self) -> None:
        self.add_legacy_alias("set-clipboard-enabled", f"{ClipboardClient.PREFIX}-status")
        for x in (
            "token", "request",
            "contents", "contents-none",
            "pending-requests", "enable-selections",
            "status",
        ):
            self.add_packet_handler(f"{ClipboardClient.PREFIX}-{x}", self._process_clipboard_packet, True)

    def make_clipboard_helper(self):
        """
            Try the various clipboard classes until we find one
            that loads ok. (some platforms have more options than others)
        """
        parts = self.client_clipboard_type.split(":", 1)
        clipboard_type = parts[0]
        options = {}
        if len(parts) > 1:
            options = parse_simple_dict(parts[1])
        clipboard_classes = get_clipboard_helper_classes(clipboard_type)
        log("make_clipboard_helper() options=%s", clipboard_classes)
        for helperclass in clipboard_classes:
            try:
                return self.setup_clipboard_helper(helperclass, options)
            except (ImportError, AttributeError) as e:
                log.error("Error: cannot instantiate %s:", helperclass)
                log.estr(e)
                del e
            except RuntimeError:
                log.error("Error: cannot instantiate %s", helperclass, exc_info=True)
        return None

    def _process_clipboard_packet(self, packet: Packet) -> None:
        ch = self.clipboard_helper
        packet_type = packet.get_type()
        log("process_clipboard_packet: %s, helper=%s", packet_type, ch)
        if packet_type == "clipboard-status":
            self._process_clipboard_status(packet)
        elif ch:
            ch.process_clipboard_packet(packet)

    def _process_clipboard_status(self, packet: Packet) -> None:
        clipboard_enabled = packet.get_bool(1)
        reason = packet.get_str(2)
        if self.clipboard_enabled != clipboard_enabled:
            log.info("clipboard toggled to %s by the server", ["off", "on"][int(clipboard_enabled)])
            log.info(" reason given: %r", reason)
            self.clipboard_enabled = bool(clipboard_enabled)
            self.emit("clipboard-toggled")

    def clipboard_toggled(self, *args) -> None:
        log("clipboard_toggled%s clipboard_enabled=%s, server_clipboard=%s",
            args, self.clipboard_enabled, self.server_clipboard)
        if self.server_clipboard:
            packet_type = "set-clipboard-enabled" if BACKWARDS_COMPATIBLE else "clipboard-status"
            self.send_now(packet_type, self.clipboard_enabled)
            if self.clipboard_enabled:
                ch = self.clipboard_helper
                assert ch is not None
                self.send_clipboard_selections(ch.get_remote_selections())
                ch.send_all_tokens()

    def send_clipboard_selections(self, selections: Sequence[str]) -> None:
        log("send_clipboard_selections(%s)", selections)
        self.send_now("clipboard-enable-selections", tuple(selections))

    def setup_clipboard_helper(self, helper_class, options: dict):
        log("setup_clipboard_helper(%s, %s)", helper_class, options)
        # first add the platform specific one, (which may be None):
        kwargs = options.copy()
        kwargs |= {
            # all the local clipboards supported:
            "clipboards.local": CLIPBOARDS,
            # all the remote clipboards supported:
            "clipboards.remote": self.server_clipboard_selections,
            "can-send": self.client_clipboard_direction in ("to-server", "both"),
            "can-receive": self.client_clipboard_direction in ("to-client", "both"),
            # the local clipboard we want to sync to (with the translated clipboard only):
            "clipboard.local": self.local_clipboard,
            # the remote clipboard we want to we sync to (with the translated clipboard only):
            "clipboard.remote": self.remote_clipboard,
        }
        log("setup_clipboard_helper() kwargs=%s", kwargs)

        hc = helper_class(self.clipboard_send, self.clipboard_progress, **kwargs)
        hc.set_preferred_targets(self.server_clipboard_preferred_targets)
        hc.set_greedy_client(self.server_clipboard_greedy)
        hc.set_want_targets_client(self.server_clipboard_want_targets)
        hc.enable_selections(self.server_clipboard_selections)
        return hc

    def clipboard_send(self, packet_type: str, *parts: PacketElement) -> None:
        log("clipboard_send: %r", parts[0])
        if not self.clipboard_enabled:
            log("clipboard is disabled, not sending clipboard packet")
            return
        # replaces 'Compressible' items in a packet
        # with a subclass that calls self.compressed_wrapper
        # and which can therefore enable the brotli compressor:
        packet = list(parts)
        for i, v in enumerate(packet):
            if isinstance(v, compression.Compressible):
                packet[i] = self.compressible_item(v)
        self.send_now(packet_type, *packet)

    def clipboard_progress(self, local_requests: int, remote_requests: int) -> None:
        log("clipboard_progress(%s, %s)", local_requests, remote_requests)
        if local_requests >= 0:
            self.local_clipboard_requests = local_requests
        if remote_requests >= 0:
            self.remote_clipboard_requests = remote_requests
        n = self.local_clipboard_requests+self.remote_clipboard_requests
        self.clipboard_notify(n)

    def compressible_item(self, compressible) -> compression.Compressible:
        """
            converts a 'Compressible' item into something that will
            call `self.compressed_wrapper` when compression is requested
            by the network encode thread.
        """
        client = self

        class ProtocolCompressible(compression.Compressible):
            __slots__ = ()

            def compress(self) -> compression.Compressed:
                return client.compressed_wrapper(self.datatype, self.data,
                                                 level=9, can_inline=False, brotli=True)
        return ProtocolCompressible(compressible.datatype, compressible.data)

    def clipboard_notify(self, n: int) -> None:
        log("clipboard_notify(%i)", n)
