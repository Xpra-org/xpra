#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.net.websockets.common import verify_response_headers, make_websocket_accept_hash
from xpra.log import Logger

log = Logger("network")


class WebsocketHeaderTest(unittest.TestCase):

    def test_verify_response_headers(self):
        def f(v, key=b""):
            try:
                verify_response_headers(v, key)
            except Exception:
                pass
            else:
                raise Exception("bad header should have failed")
        f(None)
        f({b"Upgrade" : b"not-websocket"})
        f({b"Upgrade" : b"websocket",
           b"Sec-WebSocket-Protocol" : b"not-binary",
           })
        f({b"Upgrade" : b"websocket",
           b"Sec-WebSocket-Protocol" : b"binary",
           b"Sec-WebSocket-Accept" : b"",
           })
        f({b"Upgrade" : b"websocket",
           b"Sec-WebSocket-Protocol" : b"binary",
           b"Sec-WebSocket-Accept" : b"key",
           })
        key = b"somekey"
        verify_response_headers({
            b"Upgrade" : b"websocket",
            b"Sec-WebSocket-Protocol" : b"binary",
            b"Sec-WebSocket-Accept" : make_websocket_accept_hash(key),
            }, key)

def main():
    unittest.main()


if __name__ == '__main__':
    main()
