#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import unittest
from io import BytesIO
from threading import Event
from time import monotonic

from unit.test_util import LoggerSilencer, silence_error, silence_info

from xpra.util.objects import typedict, AdHocStruct
from xpra.os_util import POSIX, OSX
from xpra.util.io import get_util_logger


class SourceMixinsTest(unittest.TestCase):
    event = Event()
    event.set()
    AUDIO_SERVER_PROPS = {
        "audio_initialized": event,
        "audio_properties": {},
        "audio_source_plugin": None,
        "supports_microphone": True,
        "microphone_codecs": (),
        "supports_speaker": False,
        "speaker_codecs": (),
    }

    def _test_mixin_class(self, mixin_class, server_props=None, client_caps=None, protocol=None, test_fn=None):
        return self._test_mixin_classes((mixin_class, ), server_props, client_caps, protocol, test_fn)

    def _test_mixin_classes(self, mixin_classes, server_props=None, client_caps=None, protocol=None, test_fn=None):
        assert mixin_classes
        for mixin_class in mixin_classes:
            assert mixin_class.is_needed(typedict(client_caps or {})) in (True, False)
        if len(mixin_classes)==1:
            mixin_class = mixin_classes[0]
        else:
            mixin_class = type(f"Mixin-{mixin_classes}", mixin_classes, {})
        # test the instance:
        # fake server object:
        server = AdHocStruct()
        server.session_name = "foo"
        server.unix_socket_paths = ["/some/path"]
        server.bandwidth_limit = 0
        server.bandwidth_detection = False
        if server_props:
            for k,v in server_props.items():
                setattr(server, k, v)
        #fake client caps object (as a typedict):
        d = typedict()
        if client_caps:
            for k,v in client_caps.items():
                d[k] = v
        m = mixin_class()
        m.wants = ["encodings", "versions", "features", "display"]
        m.packet_queue = []
        m.protocol = protocol
        m.suspended = False

        def encode_queue_size():
            return 0
        m.encode_queue_size = encode_queue_size
        for c in mixin_classes:
            c.__init__(m)
        for c in mixin_classes:
            try:
                c.init_from(m, m.protocol, server)
            except Exception:
                print(f"failed to initialize from {server}")
                raise
        for c in mixin_classes:
            c.init_state(m)
        for c in mixin_classes:
            assert not c.is_closed(m)
            c.parse_client_caps(m, d)
        for c in mixin_classes:
            assert c.get_info(m) is not None
            assert c.get_caps(m) is not None
            assert not c.is_closed(m)
        m.emit("user-event", "test")
        for c in mixin_classes:
            c.may_notify(m)
            c.queue_encode(m, ("item",))
            c.send_more(m, "packet-type", 0)
            c.send_async(m, "packet-type", 0)
        for c in mixin_classes:
            if test_fn:
                test_fn(c, m)
        for c in mixin_classes:
            c.cleanup(m)
        return m

    def test_stub(self):
        from xpra.server.source.stub import StubClientConnection
        self._test_mixin_class(StubClientConnection)

    #############################################################################
    # The following tests are incomplete:
    def test_audio(self):
        from xpra.server.source.audio import AudioConnection

        def loop_check(_c, m):
            m.audio_loop_check()
        self._test_mixin_class(AudioConnection, SourceMixinsTest.AUDIO_SERVER_PROPS, test_fn=loop_check)

    def test_clientconnection(self):
        from xpra.server.source.client_connection import ClientConnection
        assert ClientConnection.is_needed(typedict()) is True
        # self._test_mixin_class(ClientConnection)

    def test_clipboard(self):
        from xpra.server.source.clipboard import ClipboardConnection
        for fix in (False, True):
            self._test_mixin_class(ClipboardConnection, None, {
                "clipboard.contents-slice-fix" : fix,
            })

    def test_dbus(self):
        try:
            from xpra.server import dbus
            assert dbus
            from xpra.server.source.dbus import DBUS_Connection
        except ImportError:
            pass
        else:
            self._test_mixin_class(DBUS_Connection, {
                "dbus_control"  : True,
            })

    def test_encodings(self):
        from xpra.server.source.encoding import EncodingsConnection
        self._test_mixin_class(EncodingsConnection, {
            "core_encodings": ("rgb32", "rgb24", "png", ),
            "encodings": ("rgb", "png", ),
            "default_encoding": "auto",
            "scaling_control": 50,
            "default_quality": 50,
            "default_min_quality": 10,
            "default_speed": 50,
            "default_min_speed": 10,
        }, {
            "encodings.core": ("rgb32", "rgb24"),
        })

    def test_file(self):
        from xpra.server.source.file import FileConnection
        from xpra.net.file_transfer import FileTransferAttributes
        self._test_mixin_class(FileConnection, {
            "file_transfer": FileTransferAttributes(),
            "machine_id": "123",
        })

    def test_idle(self):
        from xpra.server.source.idle_mixin import IdleConnection

        def idle_test(_c, m):
            m.idle_grace_timedout()
            m.idle_notification_action(10, "cancel")
            m.idle_notification_action(20, "other")
            m.idle_timedout()
        self._test_mixin_class(IdleConnection, {
            "idle_timeout": 1000,
        }, test_fn=idle_test)

    def test_input(self):
        from xpra.server.source.keyboard import KeyboardConnection
        self._test_mixin_class(KeyboardConnection)

    def test_mmap(self):
        from xpra.server.source import mmap
        import tempfile
        tmp = tempfile.NamedTemporaryFile(prefix="xpra-mmap-test")
        tmp.write(b"0"*1024*1024)
        for server_mmap_filename in (None, tmp.name, "/this-path/should-not-exist"):
            for mmap_supported in (False, True):
                for has_file in (True, False):
                    caps = {
                        "mmap.namespace": True,
                        "mmap_min_size": 128*1024,
                    }
                    if has_file:
                        caps["mmap.file"] = tmp.name
                        caps["mmap_file"] = tmp.name
                    with LoggerSilencer(mmap):
                        self._test_mixin_class(mmap.MMAP_Connection, {
                            "mmap_filename": server_mmap_filename,
                            "mmap_supported": mmap_supported,
                            "mmap_min_size": 10000,
                        }, caps)

    def test_ping(self):
        from xpra.server.source.ping import PingConnection

        def send_ping(_c, m):
            m.ping()
        self._test_mixin_class(PingConnection, test_fn=send_ping)

    def test_bandwidth(self):
        from xpra.server.source.bandwidth import BandwidthConnection

        def test_update(_c, m):
            m.update_bandwidth_limits()
        self._test_mixin_class(BandwidthConnection, test_fn=test_update)

    def _get_window_mixin_server_attributes(self):
        def get_transient_for(_w):
            return None

        def get_focus():
            return 0

        def get_cursor_data():
            return None

        def get_window_id(_w):
            return 0
        return {
            "get_transient_for": get_transient_for,
            "get_focus": get_focus,
            "get_cursor_data": get_cursor_data,
            "get_window_id": get_window_id,
            "window_filters": (),
            "readonly": False,
        }

    def test_windows(self):
        from xpra.server.source.window import WindowsConnection
        self._test_mixin_class(WindowsConnection, self._get_window_mixin_server_attributes())

    def test_clientinfo(self):
        from xpra.server.source.clientinfo import ClientInfoConnection

        def test_connect_info(_c, m):
            m.get_connect_info()
        self._test_mixin_class(ClientInfoConnection, {}, {
            "session-type": "test",
            "opengl": {"renderer": "fake"},
            "proxy": True,
            "proxy.hostname": "some-hostname",
        }, test_fn=test_connect_info)

    def test_display(self):
        from xpra.server.source.display import DisplayConnection
        self._test_mixin_class(DisplayConnection)

    def test_shell(self):
        from xpra.server.source import shell
        protocol = AdHocStruct()
        protocol._conn = AdHocStruct()
        protocol._conn.options = {"shell" : "yes"}
        m = self._test_mixin_class(shell.ShellConnection, protocol=protocol)

        def noop(*_args):
            pass
        m.send = noop
        out,err = m.shell_exec("print('hello')")
        assert out.rstrip("\n")=="hello", "expected 'hello' but got '%s'" % out.rstrip("\n")
        assert not err
        with silence_error(shell):
            out,err = m.shell_exec("--not-a-statement--")
        assert not out
        assert err

    def test_webcam(self):
        if not POSIX or OSX:
            get_util_logger().info("webcam test skipped: %s not supported yet", sys.platform)
            return
        from xpra.platform.posix.webcam import get_virtual_video_devices, check_virtual_dir
        if not check_virtual_dir():
            get_util_logger().info("webcam test skipped: no virtual video device directory")
            return
        devices = get_virtual_video_devices()
        if not devices:
            get_util_logger().info("webcam test skipped: no virtual video devices found")
            return
        for need in (False, True):
            from xpra.server.source import webcam
            for enabled in (False, True):
                wm = self._test_mixin_class(webcam.WebcamConnection, {
                    "webcam"            : need,
                    "webcam_enabled"    : enabled,
                    "webcam_device"     : None,
                    "webcam_encodings"  : ("png", "jpeg"),
                })
        wm.init_state()
        wm.hello_sent = monotonic()
        packets = []

        from xpra.codecs.video import getVideoHelper
        getVideoHelper().set_modules(csc_modules={"csc_libyuv": {}, "csc_cython": {}})
        getVideoHelper().init_csc_options()

        def send(*args):
            packets.append(args)
        # wm.send = send
        wm.send_async = send
        try:
            assert wm.get_info()
            device_id = 0
            w, h = 640, 480
            with silence_info(webcam):
                assert wm.start_virtual_webcam(device_id, w, h)
            assert wm.get_info().get("webcam", {}).get("active-devices", 0)==1
            assert len(packets) == 1    #ack sent
            assert packets[0][0] == "webcam-ack"
            frame_no = 0
            from PIL import Image  # @UnresolvedImport
            image = Image.new('RGB', size=(w, h), color=(155, 0, 0))
            buf = BytesIO()
            image.save(buf, "png")
            data = buf.getvalue()
            buf.close()
            assert wm.process_webcam_frame(device_id, frame_no, "png", w, h, data, {})
            assert len(packets)==2    #ack sent
            assert packets[1][0]=="webcam-ack"
            #now send a jpeg as png,
            #which should fail and stop:
            buf = BytesIO()
            image.save(buf, "jpeg")
            data = buf.getvalue()
            buf.close()
            #suspend error logging to avoid the scary message:
            from xpra.server.source import webcam
            with silence_error(webcam):
                assert not wm.process_webcam_frame(device_id, frame_no, "png", w, h, data, {})
            assert len(packets) == 3
            assert packets[2][0] == "webcam-stop"
        finally:
            wm.cleanup()

    def test_avsync(self):
        # needs some other subsystems:
        from xpra.server.source.window import WindowsConnection
        from xpra.server.source.audio import AudioConnection
        from xpra.server.source.avsync import AVSyncConnection
        server_props = SourceMixinsTest.AUDIO_SERVER_PROPS.copy()
        server_props.update({
            "av_sync": True,
            "audio_properties": {"foo": "bar"},
            "sound.pulseaudio_id": "fake-one",
            "sound.pulseaudio.server": "some-path",
        })
        server_props.update(self._get_window_mixin_server_attributes())
        self._test_mixin_classes((WindowsConnection, AudioConnection, AVSyncConnection), server_props, {
            "audio": {
                "send": True,
                "receive": True,
            },
        })
        self._test_mixin_classes((WindowsConnection, AudioConnection, AVSyncConnection), server_props, {
            "audio": {
                "send": True,
                "receive": True,
            },
        })
        # test disabled:
        # what the client sets doesn't matter:
        for e in (True, False):
            av = AVSyncConnection()
            av.av_sync = False
            av.window_sources = {}
            av.init_state()
            caps = typedict({"av-sync" : e})
            av.parse_client_caps(caps)
            i = av.get_info()
            assert i
            avi = i.get("av-sync")
            assert avi and not avi.get("enabled", True)
        # now enabled:

        def get_audio_source_latency():
            return 20
        for e in (True, False):
            av = AVSyncConnection()
            av.av_sync = True
            av.window_sources = {}
            av.init_state()
            av.get_audio_source_latency = get_audio_source_latency
            caps = typedict({"av-sync" : e})
            av.parse_client_caps(caps)
            i = av.get_info()
            assert i
            avi = i.get("av-sync")
            assert avi and avi.get("enabled", not e)==e
            av.set_av_sync_delay(10)
            av.audio_control_av_sync_delta("100")
            try:
                av.audio_control_av_sync_delta("invalid")
            except Exception:
                pass
            assert av.get_info().get("av-sync").get("delta")==100

    def test_notification(self):
        from xpra.server.source.notification import NotificationConnection
        self._test_mixin_class(NotificationConnection)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
