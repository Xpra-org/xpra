# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.common import BACKWARDS_COMPATIBLE
from xpra.net.common import Packet
from xpra.util.system import is_X11
from xpra.util.objects import typedict
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger

log = Logger("cursor")


class CursorManager(StubServerMixin):
    """
    Servers that send cursor bitmaps.
    """
    PREFIX = "cursor"

    def __init__(self):
        StubServerMixin.__init__(self)
        self.cursors = False
        self.cursor_size = 0
        self.cursor_suspended: bool = False
        # x11:
        self.default_cursor_image = None
        self.last_cursor_image = ()

    def init(self, opts) -> None:
        log("init(..) cursors=%s", opts.cursors)
        self.cursors = opts.cursors

    def add_new_client(self, ss, c: typedict, send_ui: bool, share_count: int) -> None:
        if not send_ui:
            return
        if share_count > 0:
            self.cursor_size = 24
        else:
            self.cursor_size = c.intget("cursor.size", 0)

    def send_initial_data(self, ss, caps, send_ui: bool, share_count: int) -> None:
        if not send_ui:
            return
        from xpra.server.source.cursor import CursorsConnection
        if isinstance(ss, CursorsConnection):
            ss.send_cursor()

    def get_caps(self, source) -> dict[str, Any]:
        from xpra.platform.gui import get_default_cursor_size, get_max_cursor_size
        cursor_caps = {}
        sizes = cursor_caps.setdefault("sizes", {})
        dsize = get_default_cursor_size()
        if min(dsize) > 0:
            sizes["default"] = dsize
            if BACKWARDS_COMPATIBLE:
                cursor_caps["default_size"] = round(sum(dsize) / len(dsize))
        max_size = get_max_cursor_size()
        if min(max_size) > 0:
            sizes["max"] = max_size
            if BACKWARDS_COMPATIBLE:
                cursor_caps["max_size"] = max_size
        if self.default_cursor_image and "default_cursor" in source.wants:
            ce = getattr(source, "cursor_encodings", ())
            if "default" not in ce:
                # we have to send it this way
                # instead of using send_initial_cursors()
                if BACKWARDS_COMPATIBLE:
                    cursor_caps["cursor.default"] = self.default_cursor_image
                cursor_caps["default"] = self.default_cursor_image
        caps: dict[str, Any] = {"cursor": cursor_caps}
        if BACKWARDS_COMPATIBLE:
            caps["cursors"] = self.cursors
        log("cursor caps=%s", caps)
        return caps

    def get_info(self, _proto) -> dict[str, Any]:
        return {
            CursorManager.PREFIX: {
                "": self.cursors,
                "size": self.cursor_size,
                "current": self.get_cursor_info(),
            },
        }

    def get_cursor_info(self) -> dict[str, Any]:
        # (NOT from UI thread)
        # copy to prevent race:
        cd = self.last_cursor_image
        if not cd:
            return {}
        dci = self.default_cursor_image
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
        info: dict[str, Any] = {}
        from xpra.platform.gui import get_default_cursor_size, get_max_cursor_size
        for name, size in {
            "default": get_default_cursor_size(),
            "max": get_max_cursor_size(),
        }.items():
            info.setdefault("sizes", {})[name] = size
        if is_X11():
            from xpra.x11.error import xswallow
            with xswallow:
                from xpra.x11.bindings.core import X11CoreBindings
                info["position"] = X11CoreBindings().query_pointer()
        return {CursorManager.PREFIX: info}

    def _process_set_cursors(self, proto, packet: Packet) -> None:
        self._process_cursor_set(proto, packet)

    def _process_cursor_set(self, proto, packet: Packet) -> None:
        assert self.cursors, "cannot toggle send_cursors: the feature is disabled"
        ss = self.get_server_source(proto)
        if ss:
            ss.send_cursors = packet.get_bool(1)

    def suspend_cursor(self, proto) -> None:
        # this is called by shadow and desktop servers
        # when we're receiving pointer events but the pointer
        # is no longer over the active window area,
        # so we have to tell the client to switch back to the default cursor
        if self.cursor_suspended:
            return
        self.cursor_suspended = True
        ss = self.get_server_source(proto)
        if ss:
            ss.cancel_cursor_timer()
            ss.send_empty_cursor()

    def restore_cursor(self, proto) -> None:
        # see suspend_cursor
        if not self.cursor_suspended:
            return
        self.cursor_suspended = False
        ss = self.get_server_source(proto)
        if ss and hasattr(ss, "send_cursor"):
            ss.send_cursor()

    def init_packet_handlers(self) -> None:
        self.add_packets(f"{CursorManager.PREFIX}-set")
        self.add_legacy_alias("set-cursors", f"{CursorManager.PREFIX}-set")
