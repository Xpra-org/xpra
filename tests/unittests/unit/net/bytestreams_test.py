#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket
import unittest

from xpra.net.bytestreams import SSLSocketConnection, can_retry, untilConcludes
from xpra.os_util import WIN32


class TestCanRetry(unittest.TestCase):

    @staticmethod
    def retry_handlers():
        conn = SSLSocketConnection.__new__(SSLSocketConnection)
        return can_retry, conn.can_retry

    def test_can_retry_empty_args(self):
        for retry in self.retry_handlers():
            for error in (OSError(), ConnectionResetError(), socket.timeout(), Exception()):
                with self.subTest(handler=retry.__qualname__, error=type(error)):
                    self.assertFalse(error.args)
                    if isinstance(error, socket.timeout):
                        self.assertTrue(retry(error))
                    else:
                        self.assertIs(retry(error), False)

    def test_empty_exception_is_preserved(self):
        for retry in self.retry_handlers():
            error = OSError()

            def fail():
                raise error

            with self.subTest(handler=retry.__qualname__):
                with self.assertRaises(OSError) as caught:
                    untilConcludes(lambda: True, retry, fail)
                self.assertIs(caught.exception, error)


@unittest.skipUnless(WIN32, "win32 named pipes only available on Windows")
class TestNamedPipeCanRetry(unittest.TestCase):

    def test_can_retry_empty_args(self):
        from xpra.platform.win32.namedpipes.connection import NamedPipeConnection
        conn = NamedPipeConnection.__new__(NamedPipeConnection)
        for error in (OSError(), ConnectionResetError(), socket.timeout(), Exception()):
            with self.subTest(error=type(error)):
                self.assertIs(conn.can_retry(error), False)


if __name__ == "__main__":
    unittest.main()
