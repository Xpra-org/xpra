# This file is part of Xpra.
# Copyright (C) 2019-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Dict

from xpra.os_util import strtobytes

HEADERS = {
    b"Connection"               : b"Upgrade",
    b"Upgrade"                  : b"websocket",
    b"Sec-WebSocket-Version"    : b"13",
    b"Sec-WebSocket-Protocol"   : b"binary",
    }


def get_headers(host:str, port:int) -> Dict[bytes,bytes]:    #pylint: disable=unused-argument
    headers = HEADERS.copy()
    if host:
        headers[b"Host"] = strtobytes(f"{host}:{port}")
    return headers
