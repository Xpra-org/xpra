#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import MagicMock, patch

from xpra.util.objects import AdHocStruct
from xpra.client.subsystem.webcam import WebcamForwarder
from unit.client.subsystem.clientmixintest_util import ClientMixinTest


class WebcamTest(ClientMixinTest):

    def test_suspend_resume_inactive(self):
        webcam = WebcamForwarder()
        with patch.object(webcam, "start_sending_webcam") as start:
            webcam.suspend_webcam(None)
            webcam.resume_webcam(None)
        assert webcam.resume_restart == ()
        start.assert_not_called()

    def test_suspend_resume_active(self):
        webcam = WebcamForwarder()
        webcam.client = MagicMock()
        webcam.server_enabled = True
        webcam.device = MagicMock()
        webcam.device_no = 7
        webcam.device_str = "/dev/video7"

        webcam.suspend_webcam(None)

        assert webcam.resume_restart == (7, "/dev/video7")
        assert webcam.device is None
        with patch.object(webcam, "start_sending_webcam") as start:
            webcam.resume_webcam(None)
        assert webcam.resume_restart == ()
        start.assert_called_once_with(7, "/dev/video7")

    def test_webcam(self):
        opts = AdHocStruct()
        opts.webcam = "on"
        self._test_mixin_class(WebcamForwarder, opts, {
            "webcam" : True,
            "webcam.encodings" : ("png", "jpeg"),
            "virtual-video-devices" : 1,
        })
        x = self.mixin
        if not x.device:
            print("no webcam device found, test skipped")
            return
        self.glib.timeout_add(2500, x.stop_sending_webcam)
        self.glib.timeout_add(5000, self.stop)
        self.main_loop.run()
        assert len(self.packets)>2
        self.verify_packet(0, ("webcam-start", 0, ))
        self.verify_packet(1, ("webcam-frame", 0, ))
        self.verify_packet(-1, ("webcam-stop", 0, ))


def main():
    unittest.main()


if __name__ == '__main__':
    main()
