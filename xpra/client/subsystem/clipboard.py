# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from time import monotonic
from typing import Any
from importlib import import_module
from collections.abc import Sequence

from xpra.clipboard.common import ALL_CLIPBOARDS, parse_greedy, parse_want_targets
from xpra.client.base.stub import StubClientSubsystem
from xpra.platform.clipboard import get_backend_module
from xpra.net.common import Packet, PacketElement, BACKWARDS_COMPATIBLE
from xpra.net import compression
from xpra.util.env import envbool
from xpra.util.parsing import parse_simple_dict, TRUE_OPTIONS, FALSE_OPTIONS
from xpra.util.objects import typedict
from xpra.log import Logger

log = Logger("clipboard")

CLIPBOARD_CLASS = os.environ.get("XPRA_CLIPBOARD_CLASS", "")
CLIPBOARD_NOTIFY = envbool("XPRA_CLIPBOARD_NOTIFY", True)


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
        log(" found %i clipboard types matching %r", len(filtered), ct)
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


class ClipboardClient(StubClientSubsystem):
    """
    Utility mixin for clients that handle clipboard synchronization.
    This subsystem owns the `clipboard-toggled` signal (via `SignalEmitter`):
    peers subscribe with `get_subsystem("clipboard").connect("clipboard-toggled", ...)`.
    """
    __slots__ = (
        "client_clipboard_direction", "client_clipboard_type", "client_supports_clipboard",
        "clipboard_enabled", "clipboard_helper", "clipboard_notification_timer", "last_clipboard_notification",
        "local_clipboard", "local_clipboard_requests", "remote_clipboard", "remote_clipboard_requests",
        "server_clipboard", "server_clipboard_direction", "server_clipboard_greedy",
        "server_clipboard_preferred_targets", "server_clipboard_selections", "server_clipboard_want_targets",
    )
    PREFIX = "clipboard"
    __signals__ = ["clipboard-toggled"]

    def __init__(self, client=None):
        StubClientSubsystem.__init__(self, client)
        self.client_clipboard_type: str = ""
        self.client_clipboard_direction: str = "both"
        self.client_supports_clipboard: bool = False
        self.clipboard_enabled: bool = False
        self.server_clipboard_direction: str = "both"
        self.server_clipboard: bool = False
        self.server_clipboard_preferred_targets: Sequence[str] = ()
        self.server_clipboard_greedy: tuple[str, ...] = ()
        self.server_clipboard_want_targets: tuple[str, ...] = ()
        self.server_clipboard_selections: Sequence[str] = ()
        self.clipboard_helper = None
        self.local_clipboard_requests: int = 0
        self.remote_clipboard_requests: int = 0
        # tray notification (blink the tray icon while requests are in progress):
        self.clipboard_notification_timer = 0
        self.last_clipboard_notification: float = 0
        # only used with the translated clipboard class:
        self.local_clipboard: str = ""
        self.remote_clipboard: str = ""

    def init(self, opts) -> None:
        self.client_clipboard_type = opts.clipboard
        self.client_clipboard_direction = opts.clipboard_direction
        self.client_supports_clipboard = (opts.clipboard or "").lower() not in FALSE_OPTIONS
        self.remote_clipboard = opts.remote_clipboard
        self.local_clipboard = opts.local_clipboard

    def load(self) -> None:
        log("load()")
        try:
            from xpra import clipboard
            self.client_supports_clipboard = clipboard is not None
            self.init_clipboard_helper()
        except ImportError:
            log.warn("Warning: clipboard module is missing")
            self.client_supports_clipboard = False

    def cleanup(self) -> None:
        self.cancel_clipboard_notification_timer()
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
        ch = self.clipboard_helper
        if not self.client_supports_clipboard or not ch:
            return {}
        caps: dict[str, Any] = {
            "notifications": True,
        }
        caps.update(ch.get_caps())
        log("clipboard.get_caps()=%s", caps)
        return {ClipboardClient.PREFIX: caps}

    def parse_server_capabilities(self, c: typedict) -> bool:
        if not self.client_supports_clipboard:
            return True
        caps = c.dictget("clipboard")
        self.parse_clipboard_capabilities(typedict(caps))
        if self.server_clipboard and self.clipboard_helper:
            self.configure_clipboard()
            self.client.after_handshake(self.start_clipboard_sync)
        return True

    def init_clipboard_helper(self) -> None:
        if self.clipboard_helper:
            return
        ch = self.make_clipboard_helper()
        if not ch:
            log.warn("Warning: no clipboard support")
        self.clipboard_helper = ch
        self.clipboard_enabled = ch is not None
        if ch:
            # reset the tray notification whenever the clipboard is toggled
            # (only start watching after the handshake to avoid loops):
            self.client.after_handshake(self.watch_clipboard_toggled)
            if self.server_clipboard:
                # from now on, notify the server whenever the clipboard flag changes:
                self.connect("clipboard-toggled", self.clipboard_toggled)

    def watch_clipboard_toggled(self) -> None:
        self.connect("clipboard-toggled", self.reset_clipboard_notification)

    def reset_clipboard_notification(self, *_args) -> None:
        # reset the tray icon:
        self.local_clipboard_requests = 0
        self.remote_clipboard_requests = 0
        self.clipboard_notify(0)

    def parse_clipboard_capabilities(self, caps: typedict) -> None:
        self.server_clipboard = bool(caps)
        self.server_clipboard_direction = caps.strget("direction", "both")
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
        self.server_clipboard_selections = caps.strtupleget("selections", ALL_CLIPBOARDS)
        log("server clipboard: supported=%s, selections=%s, direction=%s",
            self.server_clipboard, self.server_clipboard_selections, self.server_clipboard_direction)
        log("client clipboard: supported=%s, direction=%s",
            self.client_supports_clipboard, self.client_clipboard_direction)
        self.clipboard_enabled = bool(self.clipboard_helper) and self.client_supports_clipboard and self.server_clipboard
        self.server_clipboard_greedy = parse_greedy(caps, self.server_clipboard_selections)
        self.server_clipboard_want_targets = parse_want_targets(caps, self.server_clipboard_selections)
        self.server_clipboard_preferred_targets = caps.strtupleget("preferred-targets", ())
        log("server clipboard: greedy=%s, want_targets=%s, selections=%s",
            self.server_clipboard_greedy, self.server_clipboard_want_targets, self.server_clipboard_selections)
        log("parse_clipboard_caps() clipboard enabled=%s", self.clipboard_enabled)
        self.server_clipboard_preferred_targets = caps.strtupleget("preferred-targets", ())

    def configure_clipboard(self) -> None:
        hc = self.clipboard_helper
        hc.set_preferred_targets(self.server_clipboard_preferred_targets)
        hc.set_greedy_client(self.server_clipboard_greedy)
        hc.set_want_targets_client(self.server_clipboard_want_targets)
        hc.enable_selections(self.server_clipboard_selections)

    def start_clipboard_sync(self) -> None:
        ch = self.clipboard_helper
        log("start_clipboard_sync() enabled=%s, helper=%s", self.clipboard_enabled, ch)
        if not self.clipboard_enabled or not ch:
            return
        # tell the server about which selections we really want to sync with
        # (could have been translated, or limited if the client only has one, etc.)
        self.send_clipboard_selections(ch.get_remote_selections())
        ch.send_all_tokens()
        # ui may want to know this is now set:
        self.emit("clipboard-toggled")

    def init_authenticated_packet_handlers(self) -> None:
        self.add_legacy_alias("set-clipboard-enabled", f"{ClipboardClient.PREFIX}-status")
        for x in (
            "data", "request",
            "contents", "contents-none",
            "pending-requests", "enable-selections",
            "status",
        ):
            self.add_packet_handler(f"{ClipboardClient.PREFIX}-{x}", self._process_clipboard_packet, True)
        if BACKWARDS_COMPATIBLE:
            self.add_packet_handler(f"{ClipboardClient.PREFIX}-token", self._process_clipboard_packet, True)

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
        self.client_supports_clipboard = False
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
            "can-send": self.client_clipboard_direction in ("to-server", "both"),
            "can-receive": self.client_clipboard_direction in ("to-client", "both"),
            # the local clipboard we want to sync to (with the translated clipboard only):
            "clipboard.local": self.local_clipboard,
            # the remote clipboard we want to we sync to (with the translated clipboard only):
            "clipboard.remote": self.remote_clipboard,
        }
        log("setup_clipboard_helper() kwargs=%s", kwargs)
        return helper_class(self.clipboard_send, self.clipboard_progress, **kwargs)

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

    def clipboard_notify(self, n: int) -> None:
        # blink the tray icon while clipboard requests are in progress;
        # the actual tray rendering is owned by the `tray` subsystem:
        tray = self.get_subsystem("tray")
        tray_widget = tray.tray if tray else None
        if not tray_widget or not CLIPBOARD_NOTIFY:
            return
        log("clipboard_notify(%i) notification timer=%s", n, self.clipboard_notification_timer)
        self.cancel_clipboard_notification_timer()
        if n > 0 and self.clipboard_enabled:
            self.last_clipboard_notification = monotonic()
            tray_widget.set_icon("clipboard")
            tray_widget.set_tooltip(f"{n} clipboard requests in progress")
            tray_widget.set_blinking(True)
        else:
            # no more pending clipboard transfers,
            # reset the tray icon,
            # but wait at least N seconds after the last clipboard transfer:
            N = 1
            delay = max(0, round(1000 * (self.last_clipboard_notification + N - monotonic())))
            self.clipboard_notification_timer = self.timeout_add(delay, self.reset_clipboard_tray)

    def reset_clipboard_tray(self) -> None:
        self.clipboard_notification_timer = 0
        if tray := self.get_subsystem("tray"):
            tray.reset_tray_icon()

    def cancel_clipboard_notification_timer(self) -> None:
        if cnt := self.clipboard_notification_timer:
            self.clipboard_notification_timer = 0
            self.source_remove(cnt)

    def compressible_item(self, compressible) -> compression.Compressible:
        """
            converts a 'Compressible' item into something that will
            call `self.compressed_wrapper` when compression is requested
            by the network encode thread.
        """
        mixin = self

        class ProtocolCompressible(compression.Compressible):
            __slots__ = ()

            def compress(self) -> compression.Compressed:
                return mixin.compressed_wrapper(self.datatype, self.data,
                                                level=9, can_inline=False, brotli=True)
        return ProtocolCompressible(compressible.datatype, compressible.data)
