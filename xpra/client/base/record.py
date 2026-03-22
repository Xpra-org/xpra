# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Sequence

from xpra.client.base.gobject import GObjectClientAdapter
from xpra.net.common import Packet
from xpra.util.objects import typedict
from xpra.util.str_fn import csv
from xpra.log import Logger

log = Logger("client", "encoding")

EXT_ALIASES = {"jpg": "jpeg"}


def get_client_base_classes() -> tuple[type, ...]:
    classes: list[type] = []
    # Warning: MmapClient must come first,
    # so it is initialized by the time XpraClientBase creates the hello packet
    from xpra.client.base import features
    if features.mmap:
        from xpra.client.subsystem.mmap import MmapClient
        classes.append(MmapClient)
    if features.ping:
        from xpra.client.subsystem.ping import PingClient
        classes.append(PingClient)
    # ServerInfoClient?
    # ClipboardClient, KeyboardClient, PointerClient, NotificationClient, Encodings -> emulate it
    # TrayClient -> use custom tray instead
    from xpra.client.base.command import XpraClientBase
    classes.append(XpraClientBase)
    log("RecordClient base classes=%s", csv(classes))
    return tuple(classes)


CLIENT_BASES = get_client_base_classes()
ClientBaseClass = type('ClientBaseClass', CLIENT_BASES, {})


class RecordClient(GObjectClientAdapter, ClientBaseClass):

    def __init__(self, options):
        GObjectClientAdapter.__init__(self)
        for cc in CLIENT_BASES:
            cc.__init__(self)
        self.client_type = "recorder"
        self.windows = options.windows
        self.encodings: Sequence[str] = ("png", "webp", "jpeg")

    def init(self, opts) -> None:
        for cc in CLIENT_BASES:
            cc.init(self, opts)
        if opts.encoding and opts.encoding not in self.encodings:
            self.encodings = tuple(list(self.encodings) + [opts.encoding])
        # why is this here!?
        self.encoding_options = {
            "options": self.encodings,
            "core": self.encodings,
            "setting": opts.encoding,
        }
        for attr, value in {
            "quality": opts.quality,
            "min-quality": opts.min_quality,
            "speed": opts.speed,
            "min-speed": opts.min_speed,
        }.items():
            if value > 0:
                self.encoding_options[attr] = value
        self.install_signal_handlers()

    def client_toolkit(self) -> str:
        raise "offscreen-recorder"

    def make_hello(self) -> dict[str, Any]:
        caps: dict[str, Any] = {}
        if self.windows:
            caps["windows"] = True
            caps["encoding"] = self.encoding_options
        return caps

    def server_connection_established(self, c: typedict) -> bool:
        for cc in CLIENT_BASES:
            if not cc.parse_server_capabilities(self, c):
                return False
        # this will call do_command()
        return super().server_connection_established(c)

    def _process_startup_complete(self, packet: Packet) -> None:
        pass

    def _process_encodings(self, packet: Packet) -> None:
        encodings = typedict(packet.get_dict(1)).dictget("encodings", {}).get("core", ())
        common = tuple(set(self.encodings) & set(encodings))
        log("server encodings=%s, common=%s", encodings, common)

    def init_authenticated_packet_handlers(self) -> None:
        self.add_packets("startup-complete", "encodings", main_thread=True)
