# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.util.str_fn import strtobytes
from xpra.net.websockets.headers.default import get_headers as get_default_headers

# the origin to send, or "auto" to derive it from the server we are connecting to:
ORIGIN = os.environ.get("XPRA_WEBSOCKET_ORIGIN", "auto")


def get_origin(host: str, port: int) -> str:
    if ORIGIN.lower() != "auto":
        return ORIGIN
    if not host:
        return ""
    # servers only compare the scheme against explicit `http-origin` allowlists,
    # `auto` and `strict` ignore it - so `http` is good enough for `wss` connections:
    # noinspection HttpUrlsUsage
    return f"http://{host}:{port}" if port else f"http://{host}"


def get_headers(host: str, port: int) -> dict[bytes, bytes]:
    """
    Send an `Origin` header identifying ourselves as the server we are connecting to.
    Browsers always send one, so servers configured with `http-origin=strict`
    reject the connections that don't have one.
    This module is not enabled by default, add it to `XPRA_WEBSOCKET_HEADERS_MODULES`:
    the default headers are included here so that `origin` can be used on its own.
    """
    headers = get_default_headers(host, port)
    origin = get_origin(host, port)
    if origin:
        headers[b"Origin"] = strtobytes(origin)
    return headers
