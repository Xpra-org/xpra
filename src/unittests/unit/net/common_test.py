#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

from xpra.os_util import OSEnvContext
from xpra.net import common

class TestLogPackets(unittest.TestCase):


    def info(self, *args):
        self.log_messages.append(args)

    def setup_log_intercept(self):
        #get_log_packets, may_log_packet, log
        self.log_messages = []
        common.log = self

    def lm(self, n=0):
        assert len(self.log_messages)==n, "expected %i log messages, got %i" % (n, len(self.log_messages))
        self.log_messages = []

    def t(self, sending, packet_type, *args):
        packet = [packet_type] + list(args)
        return common.may_log_packet(sending, packet_type, packet)


    def test_env_log(self):
        with OSEnvContext():
            os.environ["XPRA_LOG_PACKETS"] = "info,ping,-bell"
            for log_packet_type in (False, True):
                os.environ["XPRA_LOG_PACKET_TYPE"] = str(int(log_packet_type))
                common.init()
                inc = int(log_packet_type)
                logged = 1+inc
                for sending in (True, False):
                    self.setup_log_intercept()
                    def t(packet_type, *args):
                        return self.t(sending, packet_type, *args)  #pylint: disable=cell-var-from-loop
                    self.lm()
                    t("hello", {})
                    self.lm(inc)
                    t("info", {"foo" : "bar"})
                    self.lm(logged)
                    t("ping", 1, 2, 3)
                    self.lm(logged)
                    t("ping-echo", 1, 2, 3)
                    self.lm(inc)
                    t("bell", 100)
                    self.lm(inc)
                    t("info", "0"*common.PACKET_LOG_MAX_SIZE*2)
                    assert len(self.log_messages[-1])<=common.PACKET_LOG_MAX_SIZE
                    self.lm(logged)

    def test_default_nolog(self):
        with OSEnvContext():
            os.environ.pop("XPRA_LOG_PACKETS", None)
            self.setup_log_intercept()
            for pt in common.PACKET_TYPES:
                self.t(True, pt, (1, 2))
                self.t(False, pt, (1, 2))
                self.lm(0)


def main():
    unittest.main()

if __name__ == '__main__':
    main()
