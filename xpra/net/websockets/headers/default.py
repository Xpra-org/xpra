# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util.str_fn import strtobytes

# noinspection PyPep8
HEADERS = {
    b"Connection": b"Upgrade",
    b"Upgrade": b"websocket",
    b"Sec-WebSocket-Version": b"13",
    b"Sec-WebSocket-Protocol": b"binary",
}


def get_headers(host: str, port: int) -> dict[bytes, bytes]:     # pylint: disable=unused-argument
    headers = HEADERS.copy()
    if host:
        headers[b"Host"] = strtobytes(f"{host}:{port}")
    return headers
