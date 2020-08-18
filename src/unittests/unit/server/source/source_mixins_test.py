#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import unittest
from io import BytesIO

from gi.repository import GLib

from xpra.util import typedict, AdHocStruct
from xpra.os_util import POSIX, OSX, get_util_logger


class SourceMixinsTest(unittest.TestCase):

    def _test_mixin_class(self, mixin_class, server_props=None):
        assert mixin_class.is_needed(typedict()) in (True, False)
        c = mixin_class()
        c.source_remove = GLib.source_remove
        c.idle_add = GLib.idle_add
        c.timeout_add = GLib.timeout_add
        #test the instance:
        c.init_state()
        server = AdHocStruct()
        if server_props:
            for k,v in server_props.items():
                setattr(server, k, v)
        c.init_from(None, server)
        assert not c.is_closed()
        assert c.get_info() is not None
        assert c.get_caps() is not None
        assert not c.is_closed()
        return c

    def test_stub(self):
        from xpra.server.source.stub_source_mixin import StubSourceMixin
        s = self._test_mixin_class(StubSourceMixin)
        assert not s.is_closed()
        s.parse_client_caps(typedict())
        assert s.get_caps() is not None
        assert s.get_info() is not None
        s.user_event()
        s.may_notify()
        s.queue_encode(("item",))
        s.send_more(("packet-type", 0))
        s.send_async(("packet-type", 0))
        s.cleanup()

    #############################################################################
    #The following tests are incomplete:
    def test_audio(self):
        from xpra.server.source.audio_mixin import AudioMixin
        self._test_mixin_class(AudioMixin, {
            "sound_properties"      : {},
            "sound_source_plugin"   : None,
            "supports_microphone"   : True,
            "microphone_codecs"     : (),
            "supports_speaker"      : False,
            "speaker_codecs"        : (),
            })

    def test_clientconnection(self):
        from xpra.server.source.client_connection import ClientConnection
        assert ClientConnection.is_needed(typedict()) is True
        #self._test_mixin_class(ClientConnection)

    def test_clipboard(self):
        from xpra.server.source.clipboard_connection import ClipboardConnection
        self._test_mixin_class(ClipboardConnection)

    def test_dbus(self):
        from xpra.server.source.dbus_mixin import DBUS_Mixin
        self._test_mixin_class(DBUS_Mixin, {
            "dbus_control"  : True,
            })

    def test_encodings(self):
        from xpra.server.source.encodings_mixin import EncodingsMixin
        self._test_mixin_class(EncodingsMixin, {
            "core_encodings"    : ("rgb32", "rgb24", "png", ),
            "encodings"         : ("rgb", "png", ),
            "default_encoding"  : "auto",
            "scaling_control"   : 50,
            "default_quality"   : 50,
            "default_min_quality"   : 10,
            "default_speed"     : 50,
            "default_min_speed"     : 10,
            })

    def test_fileprint(self):
        from xpra.server.source.fileprint_mixin import FilePrintMixin
        from xpra.net.file_transfer import FileTransferAttributes
        self._test_mixin_class(FilePrintMixin, {
            "file_transfer" : FileTransferAttributes(),
            })

    def test_idle(self):
        from xpra.server.source.idle_mixin import IdleMixin
        self._test_mixin_class(IdleMixin, {
            "idle_timeout"  : 1000,
            })

    def test_input(self):
        from xpra.server.source.input_mixin import InputMixin
        self._test_mixin_class(InputMixin)

    def test_mmap(self):
        from xpra.server.source.mmap_connection import MMAP_Connection
        self._test_mixin_class(MMAP_Connection, {
            "supports_mmap" : True,
            "mmap_filename" : "/tmp/fakefile",
            "min_mmap_size" : 128*1024,
            })

    def test_networkstate(self):
        from xpra.server.source.networkstate_mixin import NetworkStateMixin
        x = self._test_mixin_class(NetworkStateMixin)
        x.protocol = None
        x.ping()
        x.check_ping_echo_timeout(0, 0)

    def Xtest_windows(self):
        from xpra.server.source.windows_mixin import WindowsMixin
        def get_transient_for(_w):
            return None
        def get_focus():
            return 0
        def get_cursor_data():
            return None
        def get_window_id(_w):
            return 0
        self._test_mixin_class(WindowsMixin, {
            "get_transient_for" : get_transient_for,
            "get_focus"         : get_focus,
            "get_cursor_data"   : get_cursor_data,
            "get_window_id"     : get_window_id,
            "window_filters"    : (),
            "readonly"          : False,
            })
    #############################################################################


    def test_clientinfo(self):
        from xpra.server.source.clientinfo_mixin import ClientInfoMixin
        self._test_mixin_class(ClientInfoMixin)
        x = ClientInfoMixin()
        x.init_state()
        assert x.get_connect_info()
        assert x.get_info()
        c = typedict()
        c.update({
            "session-type"      : "test",
            "opengl"            : {"renderer" : "fake"},
            "proxy"             : True,
            "proxy.hostname"    : "some-hostname",
            })
        x.parse_client_caps(c)
        assert x.get_connect_info()
        assert x.get_info()
        x.cleanup()
        assert x.get_connect_info()
        assert x.get_info()

    def test_clientdisplay(self):
        from xpra.server.source.clientdisplay_mixin import ClientDisplayMixin
        self._test_mixin_class(ClientDisplayMixin)
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
        wm = self._test_mixin_class(WebcamMixin, {
                "webcam_enabled"    : True,
                "webcam_device"     : None,
                "webcam_encodings"  : ("png", "jpeg"),
                })
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
        self._test_mixin_class(AVSyncMixin, {
            "av_sync" : True,
            })
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
            av.set_av_sync_delay(10)
            av.sound_control_av_sync_delta("100")
            try:
                av.sound_control_av_sync_delta("invalid")
            except Exception:
                pass
            assert av.get_info().get("av-sync").get("delta")==100


def main():
    unittest.main()


if __name__ == '__main__':
    main()
