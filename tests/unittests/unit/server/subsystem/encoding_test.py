#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.objects import AdHocStruct, typedict
from unit.server.subsystem.servermixintest_util import ServerMixinTest


def _make_opts():
    opts = AdHocStruct()
    opts.encoding = ""
    opts.encodings = ["rgb", "png"]
    opts.quality = 0
    opts.min_quality = 20
    opts.speed = 0
    opts.min_speed = 20
    opts.video = True
    opts.video_scaling = "auto"
    opts.video_encoders = []
    opts.csc_modules = []
    return opts


class EncodingMixinTest(ServerMixinTest):

    def test_encoding(self):
        from xpra.server.subsystem.encoding import EncodingServer
        from xpra.server.source.encoding import EncodingsConnection
        opts = _make_opts()
        self._test_mixin_class(EncodingServer, opts, {
            "encodings.core": opts.encodings,
        }, EncodingsConnection)
        self.handle_packet(("quality", 10))

    def _setup_encoding(self):
        from xpra.server.subsystem.encoding import EncodingServer
        from xpra.server.source.encoding import EncodingsConnection
        opts = _make_opts()
        self._test_mixin_class(EncodingServer, opts, {
            "encodings.core": opts.encodings,
        }, EncodingsConnection)
        # register the source so reinit_encodings can find it
        self.mixin._server_sources[self.protocol] = self.source
        # ensure the source wants encoding caps so threaded_init_complete proceeds
        self.source.wants = ["encodings", "features"]
        # capture packets sent to the client
        packets = []
        self.source.send_async = lambda pt, *a, **kw: packets.append(pt)
        return packets

    def test_reinit_encodings_sends_caps(self):
        """reinit_encodings() should push full encoding capabilities to connected clients."""
        import xpra.server.subsystem.encoding as enc_mod
        from xpra.net.common import BACKWARDS_COMPATIBLE
        packets = self._setup_encoding()
        self.source.reinit_encoders = lambda: None
        orig = enc_mod.is_windows_source
        enc_mod.is_windows_source = lambda _ss: True
        try:
            self.mixin.reinit_encodings()
        finally:
            enc_mod.is_windows_source = orig
        expected = "encodings" if BACKWARDS_COMPATIBLE else "encoding-set"
        self.assertIn(expected, packets,
                      f"reinit_encodings should send {expected!r} to update client encoding capabilities")

    def test_add_new_client_sends_caps_when_init_done(self):
        """add_new_client() should send encoding caps immediately when threaded setup is complete."""
        from xpra.net.common import BACKWARDS_COMPATIBLE
        packets = self._setup_encoding()
        self.mixin.threaded_encoding_done = True
        self.mixin.add_new_client(self.source, typedict(), True, 0)
        expected = "encodings" if BACKWARDS_COMPATIBLE else "encoding-set"
        self.assertIn(expected, packets,
                      f"add_new_client should send {expected!r} when encoding setup is complete")

    def test_add_new_client_defers_caps_when_init_pending(self):
        """add_new_client() should not send encoding caps while threaded setup is still running."""
        from xpra.net.common import BACKWARDS_COMPATIBLE
        packets = self._setup_encoding()
        self.mixin.threaded_encoding_done = False
        self.mixin.add_new_client(self.source, typedict(), True, 0)
        expected = "encodings" if BACKWARDS_COMPATIBLE else "encoding-set"
        self.assertNotIn(expected, packets,
                         "add_new_client should not send encoding caps while setup is still running")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
