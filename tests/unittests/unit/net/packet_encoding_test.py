#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.net import packet_encoding

class TestPacketEncoding(unittest.TestCase):

    def test_env_log(self):
        packet_encoding.init_all()
        packet_encoding.sanity_checks()
        assert packet_encoding.get_packet_encoding_caps()
        assert packet_encoding.get_enabled_encoders()
        for x in packet_encoding.get_enabled_encoders():
            e = packet_encoding.get_encoder(x)
            for packet_data in (
                ["hello", {"foo" : 1, "bar" : True}],
                #b"foo",
                ):
                assert e
                v, flag = e(packet_data)
                assert v
                if x=="none":
                    #'none' cannot decode back
                    continue
                try:
                    r = packet_encoding.decode(v, flag)
                    assert r
                except Exception:
                    print("error calling decode(%s, %s) for encoder %s" % (v, flag, x))
                    raise
        #one-shot function:
        assert packet_encoding.pack_one_packet(["hello", {}])

def main():
    unittest.main()

if __name__ == '__main__':
    main()
