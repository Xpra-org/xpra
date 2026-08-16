#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import mock_open, patch

from xpra.client.base.encode import EncodeClient
from xpra.exit_codes import ExitCode
from xpra.net.common import Packet


class EncodeClientTest(unittest.TestCase):

    def test_encode_response_field_order(self):
        client = EncodeClient.__new__(EncodeClient)
        client.filenames = []
        quit_codes = []
        client.quit = quit_codes.append
        packet = Packet(
            "encode-response", "png", b"encoded", {},
            1920, 1080, 7680, 32, {"filename": "source.raw"},
        )

        output = mock_open()
        with patch("builtins.open", output):
            client._process_encode_response(packet)

        output.assert_called_once_with("source.png", "wb")
        output().write.assert_called_once_with(b"encoded")
        self.assertEqual(quit_codes, [ExitCode.OK])


def main():
    unittest.main()


if __name__ == '__main__':
    main()
