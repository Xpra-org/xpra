# This file is part of Xpra.
# Copyright (C) 2019-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.os_util import strtobytes

HEADERS = {
    b"Connection"               : b"Upgrade",
    b"Upgrade"                  : b"websocket",
    b"Sec-WebSocket-Version"    : b"13",
    b"Sec-WebSocket-Protocol"   : b"binary",
    }


def get_headers(host, port):
    headers = HEADERS.copy()
    if host:
        headers[b"Host"] = strtobytes("%s:%s" % (host, port))
    return headers
