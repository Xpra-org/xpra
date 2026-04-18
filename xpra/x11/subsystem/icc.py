# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.server.common import get_sources_by_type
from xpra.server.source.display import DisplayConnection
from xpra.util.env import envbool
from xpra.util.str_fn import hexstr
from xpra.util.objects import typedict
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger

log = Logger("screen")

SYNC_ICC: bool = envbool("XPRA_SYNC_ICC", True)


class ICCServer(StubServerMixin):
    PREFIX = "icc"

    def __init__(self):
        StubServerMixin.__init__(self)
        self.icc_profile = b""

    def add_new_client(self, ss, caps: typedict) -> None:
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
        from xpra.x11.xroot_props import root_set, root_array_set
        display_clients = get_sources_by_type(self, DisplayConnection)
        if len(display_clients) != 1:
            log("%i display clients, resetting ICC profile to default", len(display_clients))
            self.reset_icc_profile()
            return
        icc_client = display_clients[0]
        icc = typedict(icc_client.icc)
        for x in ("data", "icc-data", "icc-profile"):
            data = icc.bytesget(x)
            if data:
                log("set_icc_profile() icc data for %s: %s (%i bytes)", icc_client, hexstr(data), len(data))
                self.icc_profile = data
                root_array_set("_ICC_PROFILE", "u32", data)
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
