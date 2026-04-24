# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from typing import Any

from xpra.net.common import FULL_INFO, pretty_socket, BACKWARDS_COMPATIBLE
from xpra.net.net_util import get_network_caps, get_info
from xpra.client.base.stub import StubClientMixin
from xpra.util.objects import typedict
from xpra.log import Logger

log = Logger("client", "network")


class NetworkClient(StubClientMixin):
    """
    Protocol caps
    """

    def __init__(self):
        # legacy:
        self.compression_level: int = 0

    def init(self, opts) -> None:
        self.compression_level = opts.compression_level
        self.server_compressors = []
        if BACKWARDS_COMPATIBLE:
            self.server_packet_types = ()

    def get_caps(self) -> dict[str, Any]:
        caps = get_network_caps(FULL_INFO)
        caps["network-state"] = True
        return caps

    def parse_server_capabilities(self, caps: typedict) -> bool:
        p = self._protocol
        if not p:
            log.warn("Warning: cannot parse network capabilities, no connection!")
            return False
        if p.TYPE == "rfb":
            return True
        if not p.enable_encoder_from_caps(caps):
            return False
        p.set_compression_level(self.compression_level)
        p.enable_compressor_from_caps(caps)
        p.parse_remote_caps(caps)
        self.server_compressors = caps.strtupleget("compressors")
        if BACKWARDS_COMPATIBLE:
            self.server_packet_types = caps.strtupleget("packet-types")
            log(f"parse_network_capabilities(..) server_packet_types={self.server_packet_types}")
        return True

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
        cinfo = conn.get_info()
        return pretty_socket(cinfo.get("endpoint", conn.target)).split("?")[0]
