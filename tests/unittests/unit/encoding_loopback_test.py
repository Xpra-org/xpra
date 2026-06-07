#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Cross-side interaction test: wires the client `Encodings` subsystem to the
server `EncodingServer` subsystem (+ `EncodingsConnection` source).

Exercises the quality/speed control packets (client -> server): the server
decodes them and dispatches to the matching per-window source method.
"""

import unittest
from unittest.mock import patch, MagicMock

from xpra.util.objects import AdHocStruct

from unit.loopback_util import LoopbackTest


def _client_opts():
    opts = AdHocStruct()
    opts.encodings = ("rgb", "png")
    opts.encoding = "auto"
    opts.video_scaling = "auto"
    opts.quality = 80
    opts.min_quality = 0
    opts.speed = 50
    opts.min_speed = -1
    opts.csc_modules = ()
    opts.video_decoders = ()
    return opts


def _server_opts():
    opts = AdHocStruct()
    opts.encoding = "auto"
    opts.encodings = ("rgb", "png")
    opts.quality = -1
    opts.min_quality = 0
    opts.speed = -1
    opts.min_speed = 0
    opts.video = False
    opts.video_scaling = "auto"
    opts.video_encoders = ()
    opts.csc_modules = ()
    return opts


class EncodingLoopbackTest(LoopbackTest):

    def _connect(self):
        from xpra.client.subsystem.encoding import Encodings
        from xpra.server.subsystem.encoding import EncodingServer
        from xpra.server.source.encoding import EncodingsConnection
        # skip codec discovery / background threads on both sides:
        with patch.object(Encodings, "load", lambda self: None), \
             patch.object(EncodingServer, "setup", lambda self: None):
            return self.connect(Encodings, EncodingServer, EncodingsConnection,
                                client_opts=_client_opts(), server_opts=_server_opts(),
                                caps={"encoding": {"options": ("rgb", "png"), "core": ("rgb", "png")}})

    def test_quality_and_speed_reach_window_source(self):
        client, _server, source = self._connect()
        # stand in for a per-window source (none exist in the harness):
        ws = MagicMock()
        source.window_sources = {1: ws}

        client.quality = 80
        client.send_quality()
        client.speed = 50
        client.send_speed()

        # both control packets crossed the wire:
        self.assertIn(("quality", 80), [tuple(p) for p in self.c2s])
        self.assertIn(("speed", 50), [tuple(p) for p in self.c2s])
        # and the server dispatched them to the window source:
        ws.set_quality.assert_called_once_with(80)
        ws.set_speed.assert_called_once_with(50)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
