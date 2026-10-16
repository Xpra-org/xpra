# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.net.common import Packet
from xpra.util.env import first_time
from xpra.util.objects import typedict
from xpra.server.subsystem.stub import StubSubsystem
from xpra.log import Logger

log = Logger("cursor")


class CursorManager(StubSubsystem):
    """
    Servers that send cursor bitmaps.
    """
    __slots__ = ("default_image", "enabled", "last_image", "size", "suspended")
    PREFIX = "cursor"
    toggle_features = ("cursors",)

    def __init__(self, server=None):
        StubSubsystem.__init__(self, server)
        self.enabled = False
        self.size = 0
        self.suspended: bool = False
        # x11:
        self.default_image = None
        self.last_image = ()

    def init(self, opts) -> None:
        log("init(..) cursors=%s", opts.cursors)
        self.enabled = opts.cursors

    def add_new_client(self, ss, c: typedict) -> None:
        caps = typedict(c.dictget("cursor"))
        default_cursor_size = caps.inttupleget("default", (0, 0))
        cursor_size = max(0, default_cursor_size[0], default_cursor_size[1])
        try:
            from xpra.server.source.window import WindowsConnection
        except ImportError:
            # the `window` subsystem is disabled (ie: `--windows=no`):
            windows_clients = 0
        else:
            windows_clients = self.get_sources_by_type(WindowsConnection, ss)
        if windows_clients:
            client_sizes = tuple(getattr(x, "cursor_size", 0) for x in windows_clients)
            if cursor_size and all(size == cursor_size for size in client_sizes):
                self.size = cursor_size
            else:
                self.size = 32
        elif cursor_size:
            self.size = cursor_size

    def send_initial_data(self, ss) -> None:
        from xpra.server.source.cursor import CursorsConnection
        if isinstance(ss, CursorsConnection):
            ss.send_cursor()

    def get_cursor_data(self, skip_default=True):
        if first_time(f"no-cursor-data-{type(self).__name__}"):
            log.warn("Warning: get_cursor_data() not implemented by %s", type(self).__name__)
        return None

    def get_default_cursor_size(self) -> tuple[int, int]:
        return -1, -1

    def get_max_cursor_size(self) -> tuple[int, int]:
        return -1, -1

    def get_caps(self, source) -> dict[str, Any]:
        cursor_caps = {}
        sizes = cursor_caps.setdefault("sizes", {})
        dsize = self.get_default_cursor_size()
        if min(dsize) > 0:
            sizes["default"] = dsize
        max_size = self.get_max_cursor_size()
        if min(max_size) > 0:
            sizes["max"] = max_size
        if self.default_image:
            ce = getattr(source, "cursor_encodings", ())
            if "default" not in ce:
                cursor_caps["default"] = self.default_image
        caps: dict[str, Any] = {"cursor": cursor_caps}
        log("cursor caps=%s", caps)
        return caps

    def get_cursor_info(self) -> dict[str, Any]:
        # (NOT from UI thread)
        # copy to prevent race:
        cd = self.last_image
        if not cd:
            return {}
        dci = self.default_image
        cinfo = {
            "is-default": bool(dci) and len(dci) >= 8 and len(cd) >= 8 and cd[7] == dci[7],
        }
        # all but pixels:
        for i, x in enumerate(("x", "y", "width", "height", "xhot", "yhot", "serial", None, "name")):
            if x:
                v = cd[i] or ""
                cinfo[x] = v
        return cinfo

    def get_ui_info(self, _proto, **kwargs) -> dict[str, Any]:
        # (from UI thread)
        info: dict[str, Any] = {
            "": self.enabled,
            "size": self.size,
            "current": self.get_cursor_info(),
        }
        for name, size in {
            "default": self.get_default_cursor_size(),
            "max": self.get_max_cursor_size(),
        }.items():
            info.setdefault("sizes", {})[name] = size
        return {CursorManager.PREFIX: info}

    def _process_set(self, proto, packet: Packet) -> None:
        assert self.enabled, "cannot toggle send_cursors: the feature is disabled"
        if ss := self.get_server_source(proto):
            ss.send_cursors = packet.get_bool(1)

    def suspend_cursor(self, proto) -> None:
        # this is called by shadow and desktop servers
        # when we're receiving pointer events but the pointer
        # is no longer over the active window area,
        # so we have to tell the client to switch back to the default cursor
        if self.suspended:
            return
        self.suspended = True
        if ss := self.get_server_source(proto):
            ss.cancel_cursor_timer()
            ss.send_empty_cursor()

    def restore_cursor(self, proto) -> None:
        # see suspend_cursor
        if not self.suspended:
            return
        self.suspended = False
        ss = self.get_server_source(proto)
        if ss and hasattr(ss, "send_cursor"):
            ss.send_cursor()

    def init_packet_handlers(self) -> None:
        self.add_packets(f"{CursorManager.PREFIX}-set")
