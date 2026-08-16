#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest

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

        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                client._process_encode_response(packet)
            finally:
                os.chdir(old_cwd)
            with open(os.path.join(tmpdir, "source.png"), "rb") as output:
                self.assertEqual(output.read(), b"encoded")
        self.assertEqual(quit_codes, [ExitCode.OK])


def main():
    unittest.main()


if __name__ == '__main__':
    main()
