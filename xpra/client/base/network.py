# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from typing import Any

from xpra.common import FULL_INFO
from xpra.net.net_util import get_network_caps, get_info
from xpra.client.base.stub import StubClientMixin


class NetworkClient(StubClientMixin):
    """
    Protocol caps
    """

    def __init__(self):
        # legacy:
        self.compression_level: int = 0

    def get_caps(self) -> dict[str, Any]:
        caps = get_network_caps(FULL_INFO)
        caps["network-state"] = True
        return caps

    def get_info(self) -> dict[str, Any]:
        if FULL_INFO <= 0:
            return {}
        net_caps = get_info()
        net_caps["endpoint"] = self.get_connection_endpoint()
        return {"network": net_caps}

    def get_connection_endpoint(self) -> str:
        p = self._protocol
        if not p:
            return ""
        conn = getattr(p, "_conn", None)
        if not conn:
            return ""
        from xpra.net.bytestreams import pretty_socket
        cinfo = conn.get_info()
        return pretty_socket(cinfo.get("endpoint", conn.target)).split("?")[0]
