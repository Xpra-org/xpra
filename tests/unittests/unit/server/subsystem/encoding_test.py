#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.objects import AdHocStruct
from unit.server.subsystem.servermixintest_util import ServerMixinTest


class EncodingMixinTest(ServerMixinTest):

    def test_encoding(self):
        from xpra.server.subsystem.encoding import EncodingServer
        from xpra.server.source.encoding import EncodingsConnection
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
        self._test_mixin_class(EncodingServer, opts, {
            "encodings.core" : opts.encodings,
        }, EncodingsConnection)
        self.handle_packet(("quality", 10))
        #assert self.mixin.get_info(self.protocol).get("encodings").get
        #    "quality"       : self._process_quality,
        #    "min-quality"   : self._process_min_quality,
        #    "speed"         : self._process_speed,
        #    "min-speed"     : self._process_min_speed,
        #    "encoding"      : self._process_encoding,


def main():
    unittest.main()


if __name__ == '__main__':
    main()
