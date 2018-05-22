#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import unittest
from xpra.os_util import pollwait, OSX, POSIX, PYTHON2
from unit.server_test_util import ServerTestUtil, log


class ServerAuthTest(ServerTestUtil):

    @classmethod
    def setUpClass(cls):
        ServerTestUtil.setUpClass()
        cls.default_xpra_args = ["--systemd-run=no", "--pulseaudio=no", "--socket-dirs=/tmp"]
        cls.display = None
        cls.xvfb = None
        if True:
            #use a single display for the server that we recycle:
            cls.display = cls.find_free_display()
            cls.xvfb = cls.start_Xvfb(cls.display)
            time.sleep(1)
            assert cls.display in cls.find_X11_displays()

    @classmethod
    def tearDownClass(cls):
        ServerTestUtil.tearDownClass()
        if cls.xvfb:
            cls.xvfb.terminate()


    def _test(self, options={}):
        log("starting test server with options=%s", options)
        args = ["--%s=%s" % (k,v) for k,v in options.items()]
        if self.display:
            display = self.display
            args.append("--use-display")
        else:
            display = self.find_free_display()
        server = self.check_start_server(display, *args)
        #we should always be able to get the version:
        client = self.run_xpra(["version", display])
        assert pollwait(client, 5)==0, "version client failed to connect to server with options=%s" % options
        #try to connect
        cmd = ["info", display]
        client = self.run_xpra(cmd)
        r = pollwait(client, 5)
        assert r==0, "info client failed and returned %s for options=%s" % (r, options)
        server.terminate()

    def test_nooptions(self):
        self._test()

    def test_nonotifications(self):
        self._test({"notifications" : False})

    def test_all(self):
        OPTIONS = (
            "notifications",
            "webcam",
            "clipboard",
            "speaker",
            "microphone",
            "av-sync",
            "printing",
            "file-transfer",
            "mmap",
            #"readonly",
            "dbus-proxy",
            "remote-logging",
            "windows",
            )
        #to test all:
        #TEST_VALUES = range(2**len(OPTIONS))
        #to test nothing disabled and everything disabled only:
        TEST_VALUES = (0, 2**len(OPTIONS)-1)
        #test every option disabled individually:
        #TEST_VALUES = tuple(2**i for i in range(len(OPTIONS)))
        for i in TEST_VALUES:
            options = {}
            for o, option in enumerate(OPTIONS):
                options[option] = bool((2**o) & i)
            log("test options for %i: %s", i, options)
            self._test(options)


def main():
    if POSIX and PYTHON2 and not OSX:
        unittest.main()


if __name__ == '__main__':
    main()
