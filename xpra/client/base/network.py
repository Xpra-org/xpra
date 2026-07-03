# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from typing import Any
from collections.abc import Sequence

from xpra.net import compression
from xpra.net.common import FULL_INFO, pretty_socket, BACKWARDS_COMPATIBLE
from xpra.net.net_util import get_network_caps, get_info
from xpra.client.base.stub import StubClientSubsystem
from xpra.util.objects import typedict
from xpra.log import Logger

log = Logger("client", "network")


class Network(StubClientSubsystem):
    """
    Protocol caps
    """
    PREFIX = "network"

    def __init__(self, client=None):
        StubClientSubsystem.__init__(self, client)
        # legacy:
        self.compression_level: int = 0
        # populated by `init()`/`parse_server_capabilities()`, but `compressed_wrapper()`
        # may be called earlier (eg: logging during startup), so default them here:
        self.server_compressors: Sequence[str] = ()
        self.server_packet_types: Sequence[str] = ()

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
        p = self.client._protocol
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
        p = self.client._protocol
        if not p:
            return ""
        conn = getattr(p, "_conn", None)
        if not conn:
            return ""
        cinfo = conn.get_info()
        return pretty_socket(cinfo.get("endpoint", conn.target)).split("?")[0]

    def compressed_wrapper(self, datatype, data, level=5, **kwargs) -> compression.Compressed:
        if level > 0 and len(data) >= 256:
            kw = {}
            # brotli is not enabled by default as a generic compressor
            # but callers may choose to enable it via kwargs:
            for algo, defval in {
                "lz4": True,
                "brotli": False,
            }.items():
                kw[algo] = algo in self.server_compressors and compression.use(algo) and kwargs.get(algo, defval)
            cw = compression.compressed_wrapper(datatype, data, level=level, can_inline=False, **kw)
            if len(cw) < len(data):
                # the compressed version is smaller, use it:
                return cw
        # we can't compress, so at least avoid warnings in the protocol layer:
        return compression.Compressed(f"raw {datatype}", data)
