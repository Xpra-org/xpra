# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.common import SYNC_ICC
from xpra.util.str_fn import hexstr
from xpra.util.objects import typedict
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger

log = Logger("screen")


class ICCServer(StubServerMixin):
    PREFIX = "icc"

    def __init__(self):
        StubServerMixin.__init__(self)
        self.icc_profile = b""

    def parse_hello(self, ss, caps, send_ui: bool):
        if send_ui:
            self.set_icc_profile()

    # TODO: should use its own packet rather than getting called by `DisplayManager`:
    def process_icc(self, ss, iccdata: dict[str, Any]):
        if iccdata:
            iccd = typedict(iccdata)
            ss.icc = iccd.get("global", ss.icc)
            ss.display_icc = iccd.get("display", ss.display_icc)
            self.set_icc_profile()

    def last_client_exited(self) -> None:
        self.reset_icc_profile()

    def get_info(self, _proto) -> dict[str, Any]:
        return {"icc": self.get_icc_info()}

    def get_icc_info(self) -> dict[str, Any]:
        icc_info: dict[str, Any] = {
            "sync": SYNC_ICC,
        }
        if SYNC_ICC:
            icc_info["profile"] = hexstr(self.icc_profile)
        return icc_info

    def set_icc_profile(self) -> None:
        if not SYNC_ICC:
            return
        from xpra.x11.xroot_props import root_set
        ui_clients = [s for s in self._server_sources.values() if s.ui_client]
        if len(ui_clients) != 1:
            log("%i UI clients, resetting ICC profile to default", len(ui_clients))
            self.reset_icc_profile()
            return
        icc = typedict(ui_clients[0].icc)
        for x in ("data", "icc-data", "icc-profile"):
            data = icc.bytesget(x)
            if data:
                log("set_icc_profile() icc data for %s: %s (%i bytes)", ui_clients[0], hexstr(data), len(data))
                self.icc_profile = data
                root_set("_ICC_PROFILE", ["u32"], data)
                root_set("_ICC_PROFILE_IN_X_VERSION", "u32", 0 * 100 + 4)  # 0.4 -> 0*100+4*1
                return
        log("no icc data found in %s", icc)
        self.reset_icc_profile()

    def reset_icc_profile(self) -> None:
        log("reset_icc_profile()")
        from xpra.x11.xroot_props import root_del
        root_del("_ICC_PROFILE")
        root_del("_ICC_PROFILE_IN_X_VERSION")
        self.icc_profile = b""
