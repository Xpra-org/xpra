# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# pylint: disable-msg=E1101

from typing import Any

from xpra.net.common import PacketType
from xpra.util.objects import typedict
from xpra.util.env import envbool
from xpra.client.base.stub_client_mixin import StubClientMixin
from xpra.log import Logger

log = Logger("cursor")

SAVE_CURSORS: bool = envbool("XPRA_SAVE_CURSORS", False)


class CursorClient(StubClientMixin):
    """
    Add cursor handling
    """
    PREFIX = "cursor"

    def __init__(self):
        self.server_cursors: bool = False
        self.client_supports_cursors: bool = False
        self.cursors_enabled: bool = False
        self.default_cursor_data = None

    def init(self, opts) -> None:
        self.client_supports_cursors = opts.cursors

    def get_info(self) -> dict[str, Any]:
        return self.get_caps()

    ######################################################################
    # hello:
    def get_caps(self) -> dict[str, Any]:
        return {
            "cursors": self.client_supports_cursors,
        }

    def parse_server_capabilities(self, c: typedict) -> bool:
        self.server_cursors = c.boolget("cursors", True)  # added in 0.5, default to True!
        self.cursors_enabled = self.server_cursors and self.client_supports_cursors
        self.default_cursor_data = c.tupleget("cursor.default", None)
        return True

    def _process_cursor(self, packet: PacketType) -> None:
        if not self.cursors_enabled:
            return
        if len(packet) == 2:
            # marker telling us to use the default cursor:
            new_cursor = packet[1]
            setdefault = False
        else:
            if len(packet) < 9:
                raise ValueError(f"invalid cursor packet: only {len(packet)} items")
            # trim packet-type:
            new_cursor = list(packet[1:])
            encoding = str(new_cursor[0])
            setdefault = encoding.startswith("default:")
            if setdefault:
                encoding = encoding.split(":")[1]
            new_cursor[0] = encoding
            if encoding == "png":
                pixels = new_cursor[8]
                if SAVE_CURSORS:
                    serial = new_cursor[7]
                    with open(f"raw-cursor-{serial:x}.png", "wb") as f:
                        f.write(pixels)
                from xpra.codecs.pillow.decoder import open_only  # pylint: disable=import-outside-toplevel
                img = open_only(pixels, ("png",))
                new_cursor[8] = img.tobytes("raw", "BGRA")
                log("used PIL to convert png cursor to raw")
                new_cursor[0] = "raw"
            elif encoding != "raw":
                log.warn(f"Warning: invalid cursor encoding: {encoding}")
                return
        if setdefault:
            log(f"setting default cursor={new_cursor!r}")
            self.default_cursor_data = new_cursor
        else:
            self.set_windows_cursor(self._id_to_window.values(), new_cursor)

    def reset_cursor(self) -> None:
        self.set_windows_cursor(self._id_to_window.values(), [])

    def set_windows_cursor(self, client_windows, new_cursor) -> None:
        raise NotImplementedError()

    def init_authenticated_packet_handlers(self) -> None:
        self.add_packets("cursor", main_thread=True)
