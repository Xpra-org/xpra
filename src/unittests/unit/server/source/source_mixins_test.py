#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import unittest
from io import BytesIO

from xpra.util import typedict, AdHocStruct
from xpra.os_util import POSIX, OSX, get_util_logger


class SourceMixinsTest(unittest.TestCase):

    def test_clientinfo(self):
        from xpra.server.source.clientinfo_mixin import ClientInfoMixin
        x = ClientInfoMixin()
        x.init_state()
        assert x.get_connect_info()
        assert x.get_info()
        c = typedict()
        x.parse_client_caps(c)
        assert x.get_connect_info()
        assert x.get_info()
        x.cleanup()
        assert x.get_connect_info()
        assert x.get_info()

    def test_clientdisplay(self):
        from xpra.server.source.clientdisplay_mixin import ClientDisplayMixin
        x = ClientDisplayMixin()
        x.init_state()
        assert x.get_info()
        c = typedict()
        x.parse_client_caps(c)
        assert x.get_info()
        x.cleanup()
        assert x.get_info()

    def test_webcam(self):
        if not POSIX or OSX:
            get_util_logger().info("webcam test skipped: %s not supported yet", sys.platform)
            return
        from xpra.platform.xposix.webcam import get_virtual_video_devices, check_virtual_dir
        if not check_virtual_dir():
            get_util_logger().info("webcam test skipped: no virtual video device directory")
            return
        devices = get_virtual_video_devices()
        if not devices:
            get_util_logger().info("webcam test skipped: no virtual video devices found")
            return
        from xpra.server.source.webcam_mixin import WebcamMixin
        server = AdHocStruct()
        wm = WebcamMixin()
        server.webcam_enabled     = True
        server.webcam_device      = None
        server.webcam_encodings   = ["png", "jpeg"]
        wm.init_from(None, server)
        wm.init_state()
        wm.hello_sent = True
        packets = []
        def send(*args):
            packets.append(args)
        #wm.send = send
        wm.send_async = send
        try:
            assert wm.get_info()
            device_id = 0
            w, h = 640, 480
            assert wm.start_virtual_webcam(device_id, w, h)
            assert wm.get_info().get("webcam", {}).get("active-devices", 0)==1
            assert len(packets)==1    #ack sent
            assert packets[0][0]=="webcam-ack"
            frame_no = 0
            from PIL import Image
            image = Image.new('RGB', size=(w, h), color=(155, 0, 0))
            buf = BytesIO()
            image.save(buf, "png")
            data = buf.getvalue()
            buf.close()
            assert wm.process_webcam_frame(device_id, frame_no, "png", w, h, data)
            assert len(packets)==2    #ack sent
            assert packets[1][0]=="webcam-ack"
            #now send a jpeg as png,
            #which should fail and stop:
            buf = BytesIO()
            image.save(buf, "jpeg")
            data = buf.getvalue()
            buf.close()
            #suspend error logging to avoid the scary message:
            from xpra.server.source.webcam_mixin import log as webcam_log
            elog = webcam_log.error
            try:
                webcam_log.error = webcam_log.debug
                assert not wm.process_webcam_frame(device_id, frame_no, "png", w, h, data)
            finally:
                #restore it:
                webcam_log.error = elog
            assert len(packets)==3
            assert packets[2][0]=="webcam-stop"
        finally:
            wm.cleanup()

    def test_avsync(self):
        from xpra.server.source.avsync_mixin import AVSyncMixin
        #test disabled:
        #what the client sets doesn't matter:
        for e in (True, False):
            av = AVSyncMixin()
            av.av_sync = False
            av.window_sources = {}
            av.init_state()
            caps = typedict({"av-sync" : e})
            av.parse_client_caps(caps)
            i = av.get_info()
            assert i
            avi = i.get("av-sync")
            assert avi and not avi.get("enabled", True)
        #now enabled:
        def get_sound_source_latency():
            return 20
        for e in (True, False):
            av = AVSyncMixin()
            av.av_sync = True
            av.window_sources = {}
            av.init_state()
            av.get_sound_source_latency = get_sound_source_latency
            caps = typedict({"av-sync" : e})
            av.parse_client_caps(caps)
            i = av.get_info()
            assert i
            avi = i.get("av-sync")
            assert avi and avi.get("enabled", not e)==e


def main():
    unittest.main()


if __name__ == '__main__':
    main()
