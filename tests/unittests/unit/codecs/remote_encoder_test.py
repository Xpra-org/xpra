#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import shutil
import tempfile
import unittest

from xpra.codecs.remote.encoder import EncoderClient, safe_dict


class FakeProtocol:

    def start(self) -> None:
        pass


class RemoteEncoderClientTest(unittest.TestCase):

    def setUp(self) -> None:
        self.mmap_dir = tempfile.mkdtemp(prefix="xpra-remote-test-")

    def tearDown(self) -> None:
        shutil.rmtree(self.mmap_dir, ignore_errors=True)

    def test_defaults(self) -> None:
        # the codec options only contain what was specified, ie: "remote:uri=..."
        client = EncoderClient({"uri": "socket:///nonexistent"})
        self.assertEqual(client.uri, "socket:///nonexistent")
        self.assertTrue(client.sessions_dir)
        # bidirectional mmap is the default:
        self.assertEqual(client.mmap_option, "both")
        client.load()
        self.assertIsNotNone(client.mmap_read_area)
        self.assertIsNotNone(client.mmap_write_area)
        client.cleanup()

    def test_mmap_dirs(self) -> None:
        # ie: "remote:uri=socket:///run/encoder/socket,mmap=/run/encoder/mmap:/run/encoder/mmap"
        mmap = os.pathsep.join((self.mmap_dir, self.mmap_dir))
        client = EncoderClient({"uri": "socket:///nonexistent", "mmap": mmap})
        client.load()
        for area in (client.mmap_read_area, client.mmap_write_area):
            self.assertIsNotNone(area)
            self.assertEqual(area.filename, self.mmap_dir)
        client.cleanup()

    def test_mmap_disabled(self) -> None:
        client = EncoderClient({"uri": "socket:///nonexistent", "mmap": "no"})
        client.load()
        self.assertFalse(client.mmap_supported)
        self.assertIsNone(client.mmap_read_area)
        self.assertIsNone(client.mmap_write_area)

    def test_hello_network_caps(self) -> None:
        # the server refuses connections which do not list the packet encoders they support:
        # `make_protocol` initializes the packet encoders before `send_hello` is called:
        from xpra.net.packet_encoding import init_all
        init_all()
        client = EncoderClient({"uri": "socket:///nonexistent", "mmap": "no"})
        sent = []
        client.send = lambda *packet: sent.append(packet)
        client.protocol = FakeProtocol()
        client.server_timeout = 0
        client.send_hello()
        self.assertEqual(len(sent), 1)
        packet_type, caps = sent[0]
        self.assertEqual(packet_type, "hello")
        self.assertTrue(caps.get("encoders"))
        self.assertIn("compressors", caps)
        self.assertEqual(caps.get("client_type"), "encode")


class SafeDictTest(unittest.TestCase):

    def test_safe_dict(self) -> None:
        opts = {
            "speed": 50,
            "encoding": "h264",
            "lossless": False,
            # the video encoders need the list of output formats:
            "dst-formats": ("YUV420P", "YUV444P"),
            "scaling": [1, 2],
            "ratio": 1.5,
            "nested": {"a": 1},
            "mixed": ("a", 1.5),
            1: "not a string key",
        }
        self.assertEqual(safe_dict(opts), {
            "speed": 50,
            "encoding": "h264",
            "lossless": False,
            "dst-formats": ("YUV420P", "YUV444P"),
            "scaling": [1, 2],
        })


def main():
    unittest.main()


if __name__ == "__main__":
    main()
