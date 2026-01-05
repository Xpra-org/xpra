# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# pylint: disable-msg=E1101

from typing import Any
from importlib.util import find_spec

from xpra.common import BACKWARDS_COMPATIBLE
from xpra.net.common import Packet
from xpra.util.str_fn import Ellipsizer
from xpra.util.objects import typedict
from xpra.util.env import envbool
from xpra.client.base.stub import StubClientMixin
from xpra.log import Logger

log = Logger("cursor")

SAVE_CURSORS: bool = envbool("XPRA_SAVE_CURSORS", False)


def decompress_cursor_data(encoding: str, cpixels, serial: int) -> bytes:
    if encoding == "raw":
        return cpixels
    if encoding == "png":
        if SAVE_CURSORS:
            with open(f"raw-cursor-{serial:x}.png", "wb") as f:
                f.write(cpixels)
        from xpra.codecs.pillow.decoder import open_only  # pylint: disable=import-outside-toplevel
        img = open_only(cpixels, ("png",))
        raw = img.tobytes("raw", "BGRA")
        log("used PIL to convert png cursor to raw")
        return raw
    log.warn(f"Warning: invalid cursor encoding: {encoding}")
    return b""


class CursorClient(StubClientMixin):
    """
    Add cursor handling
    """
    PREFIX = "cursor"

    def __init__(self):
        self.server_cursors: bool = False
        self.client_supports_cursors: bool = False
        self.cursors_enabled: bool = False
        self.default_cursor_data = ()

    def init(self, opts) -> None:
        self.client_supports_cursors = opts.cursors

    def get_info(self) -> dict[str, Any]:
        return self.get_caps()

    def get_caps(self) -> dict[str, Any]:
        encodings = ["raw", "default"]
        if find_spec("PIL"):
            encodings.append("png")
        cursor_caps: dict[str, Any] = {
            "encodings": encodings,
        }
        from xpra.platform.gui import get_default_cursor_size, get_max_cursor_size
        for name, size in {
            "default": get_default_cursor_size(),
            "max": get_max_cursor_size(),
        }.items():
            if min(size) > 0:
                cursor_caps[name] = size
        if BACKWARDS_COMPATIBLE:
            dsize = get_default_cursor_size()
            if max(dsize) > 0:
                cursor_caps["size"] = round(sum(get_default_cursor_size()) / (self.xscale + self.yscale))
        caps: dict[str, Any] = {CursorClient.PREFIX: cursor_caps}
        if BACKWARDS_COMPATIBLE:
            caps["cursors"] = self.client_supports_cursors
        log("cursor caps=%s", caps)
        return caps

    def parse_server_capabilities(self, c: typedict) -> bool:
        cursor = c.get("cursor")
        self.server_cursors = bool(cursor)
        if isinstance(cursor, dict):
            self.default_cursor_data = typedict(cursor).tupleget("default", ())
        if BACKWARDS_COMPATIBLE:
            self.server_cursors |= c.boolget("cursors", True)
        self.cursors_enabled = self.server_cursors and self.client_supports_cursors
        log("parse_server_capabilities(..) cursor=%s, default=%s", self.cursors_enabled, self.default_cursor_data)
        return True

    def _process_cursor(self, packet: Packet) -> None:
        assert BACKWARDS_COMPATIBLE
        if not self.cursors_enabled:
            return
        if len(packet) == 2:
            # marker telling us to use the default cursor:
            new_cursor = packet[1]
            setdefault = False
        else:
            if len(packet) < 9:
                raise ValueError(f"invalid cursor packet: only {len(packet)} items")
            new_cursor = list(packet[1:])
            if len(new_cursor) >= 12:
                ssize = new_cursor[10]
                smax = new_cursor[11]
                log("server cursor sizes: default=%s, max=%s", ssize, smax)
            # trim packet-type:
            encoding = str(new_cursor[0])
            setdefault = encoding.startswith("default:")
            if setdefault:
                encoding = encoding.split(":")[1]
            serial = int(new_cursor[5])
            pixels = decompress_cursor_data(encoding, new_cursor[8], serial)
            new_cursor[8] = pixels
            new_cursor[0] = "raw"
        if setdefault:
            log("setting default cursor=%s", Ellipsizer(new_cursor))
            self.default_cursor_data = new_cursor
        else:
            self.set_windows_cursor(self._id_to_window.values(), new_cursor)

    def _process_cursor_data(self, packet: Packet) -> None:
        if not self.cursors_enabled:
            return
        encoding = packet.get_str(1)
        w = packet.get_u16(2)
        h = packet.get_u16(3)
        xhot = packet.get_u16(4)
        yhot = packet.get_u16(5)
        serial = packet.get_u64(6)
        cpixels = packet.get_bytes(7)
        name = packet.get_str(8)
        pixels = decompress_cursor_data(encoding, cpixels, serial)
        cursor_data = ("raw", 0, 0, w, h, xhot, yhot, serial, pixels, name)
        self.set_windows_cursor(self._id_to_window.values(), cursor_data)

    def _process_cursor_default(self, packet: Packet) -> None:
        if not self.cursors_enabled:
            return
        self.reset_cursor()

    def reset_cursor(self) -> None:
        self.set_windows_cursor(self._id_to_window.values(), ())

    def set_windows_cursor(self, client_windows, new_cursor) -> None:
        raise NotImplementedError()

    def init_authenticated_packet_handlers(self) -> None:
        if BACKWARDS_COMPATIBLE:
            self.add_packets("cursor", main_thread=True)
        self.add_packets("cursor-data", "cursor-default", main_thread=True)
