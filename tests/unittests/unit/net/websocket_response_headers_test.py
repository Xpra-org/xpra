#!/usr/bin/env python3
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
        f({"upgrade" : "not-websocket"})
        f({"upgrade" : "websocket",
           "sec-websocket-protocol" : "not-binary",
           })
        f({"upgrade" : "websocket",
           "sec-websocket-protocol" : "binary",
           "sec-websocket-accept" : "",
           })
        f({"upgrade" : "websocket",
           "sec-websocket-protocol" : "binary",
           "sec-websocket-accept" : "key",
           })
        key = b"somekey"
        verify_response_headers({
            "upgrade" : "websocket",
            "sec-websocket-protocol" : "binary",
            "sec-websocket-accept" : make_websocket_accept_hash(key),
        }, key)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
