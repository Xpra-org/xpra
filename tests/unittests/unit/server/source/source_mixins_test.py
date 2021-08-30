#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import unittest
from io import BytesIO

from gi.repository import GLib

from unit.test_util import LoggerSilencer, silence_error, silence_info

from xpra.util import typedict, AdHocStruct
from xpra.os_util import POSIX, OSX, get_util_logger


class SourceMixinsTest(unittest.TestCase):

    AUDIO_SERVER_PROPS = {
                "sound_properties"      : {},
                "sound_source_plugin"   : None,
                "supports_microphone"   : True,
                "microphone_codecs"     : (),
                "supports_speaker"      : False,
                "speaker_codecs"        : (),
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
            mixin_class = type("Mixin-%s" % (mixin_classes,), mixin_classes, {})
        #test the instance:
        #fake server object:
        server = AdHocStruct()
        if server_props:
            for k,v in server_props.items():
                setattr(server, k, v)
        #fake client caps object (as a typedict):
        d = typedict()
        if client_caps:
            for k,v in client_caps.items():
                d[k] = v
        m = mixin_class()
        m.source_remove = GLib.source_remove
        m.idle_add = GLib.idle_add
        m.timeout_add = GLib.timeout_add
        m.packet_queue = []
        m.protocol = protocol
        def encode_queue_size():
            return 0
        m.encode_queue_size = encode_queue_size
        for c in mixin_classes:
            c.__init__(m)
        for c in mixin_classes:
            try:
                c.init_from(m, m.protocol, server)
            except Exception:
                print("failed to initialize from %s" % (server,))
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
        for c in mixin_classes:
            c.user_event(m)
            c.may_notify(m)
            c.queue_encode(m, ("item",))
            c.send_more(m, ("packet-type", 0))
            c.send_async(m, ("packet-type", 0))
        for c in mixin_classes:
            if test_fn:
                test_fn(c, m)
        for c in mixin_classes:
            c.cleanup(m)
        return m

    def test_stub(self):
        from xpra.server.source.stub_source_mixin import StubSourceMixin
        self._test_mixin_class(StubSourceMixin)

    #############################################################################
    #The following tests are incomplete:
    def test_audio(self):
        from xpra.server.source.audio_mixin import AudioMixin
        def loop_check(_c, m):
            m.audio_loop_check()
        self._test_mixin_class(AudioMixin, SourceMixinsTest.AUDIO_SERVER_PROPS, test_fn=loop_check)

    def test_clientconnection(self):
        from xpra.server.source.client_connection import ClientConnection
        assert ClientConnection.is_needed(typedict()) is True
        #self._test_mixin_class(ClientConnection)

    def test_clipboard(self):
        from xpra.server.source.clipboard_connection import ClipboardConnection
        for fix in (False, True):
            self._test_mixin_class(ClipboardConnection, None, {
                "clipboard.contents-slice-fix" : fix,
                })

    def test_dbus(self):
        try:
            from xpra.server import dbus
            assert dbus
            from xpra.server.source.dbus_mixin import DBUS_Mixin
        except ImportError:
            pass
        else:
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
            },
        {
            "encodings.core"     : ("rgb32", "rgb24"),
            })

    def test_fileprint(self):
        from xpra.server.source.fileprint_mixin import FilePrintMixin
        from xpra.net.file_transfer import FileTransferAttributes
        self._test_mixin_class(FilePrintMixin, {
            "file_transfer" : FileTransferAttributes(),
            "machine_id"    : "123",
            })

    def test_idle(self):
        from xpra.server.source.idle_mixin import IdleMixin
        def idle_test(_c, m):
            m.idle_grace_timedout()
            m.idle_notification_action(10, "cancel")
            m.idle_notification_action(20, "other")
            m.idle_timedout()
        self._test_mixin_class(IdleMixin, {
            "idle_timeout"  : 1000,
            }, test_fn=idle_test)

    def test_input(self):
        from xpra.server.source.input_mixin import InputMixin
        self._test_mixin_class(InputMixin)

    def test_mmap(self):
        from xpra.server.source import mmap_connection
        import tempfile
        file = tempfile.NamedTemporaryFile(prefix="xpra-mmap-test")
        file.write(b"0"*1024*1024)
        for server_mmap_filename in (None, file.name, "/this-path/should-not-exist"):
            for supports_mmap in (False, True):
                for has_file in (True, False):
                    caps = {
                        "mmap.namespace"    : True,
                        "min_mmap_size"     : 128*1024,
                        }
                    if has_file:
                        caps["mmap.file"] = file.name
                        caps["mmap_file"] = file.name
                    with LoggerSilencer(mmap_connection, ("error", "warn")):
                        self._test_mixin_class(mmap_connection.MMAP_Connection, {
                            "mmap_filename" : server_mmap_filename,
                            "supports_mmap" : supports_mmap,
                            "min_mmap_size" : 10000,
                            }, caps)

    def test_networkstate(self):
        from xpra.server.source.networkstate_mixin import NetworkStateMixin
        def test_ping(_c, m):
            m.ping()
            m.check_ping_echo_timeout(0, 0)
            m.cleanup()
        self._test_mixin_class(NetworkStateMixin, test_fn=test_ping)

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
            "get_transient_for" : get_transient_for,
            "get_focus"         : get_focus,
            "get_cursor_data"   : get_cursor_data,
            "get_window_id"     : get_window_id,
            "window_filters"    : (),
            "readonly"          : False,
            }

    def test_windows(self):
        from xpra.server.source.windows_mixin import WindowsMixin
        self._test_mixin_class(WindowsMixin, self._get_window_mixin_server_attributes())


    def test_clientinfo(self):
        from xpra.server.source.clientinfo_mixin import ClientInfoMixin
        def test_connect_info(_c, m):
            m.get_connect_info()
        self._test_mixin_class(ClientInfoMixin, {}, {
            "session-type"      : "test",
            "opengl"            : {"renderer" : "fake"},
            "proxy"             : True,
            "proxy.hostname"    : "some-hostname",
            }, test_fn=test_connect_info)

    def test_clientdisplay(self):
        from xpra.server.source.clientdisplay_mixin import ClientDisplayMixin
        self._test_mixin_class(ClientDisplayMixin)

    def test_shell(self):
        from xpra.server.source import shell_mixin
        protocol = AdHocStruct()
        protocol._conn = AdHocStruct()
        protocol._conn.options = {"shell" : "yes"}
        m = self._test_mixin_class(shell_mixin.ShellMixin, protocol=protocol)
        def noop(*_args):
            pass
        m.send = noop
        out,err = m.shell_exec("print('hello')")
        assert out==b"hello\n", "expected 'hello' but got '%s'" % out
        assert not err
        with silence_error(shell_mixin):
            out,err = m.shell_exec("--not-a-statement--")
        assert not out
        assert err

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
        for need in (False, True):
            from xpra.server.source import webcam_mixin
            for enabled in (False, True):
                wm = self._test_mixin_class(webcam_mixin.WebcamMixin, {
                    "webcam"            : need,
                    "webcam_enabled"    : enabled,
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
            with silence_info(webcam_mixin.log):
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
        #needs both mixins:
        from xpra.server.source.windows_mixin import WindowsMixin
        from xpra.server.source.audio_mixin import AudioMixin
        from xpra.server.source.avsync_mixin import AVSyncMixin
        server_props = SourceMixinsTest.AUDIO_SERVER_PROPS.copy()
        server_props.update({
            "av_sync" : True,
            "sound_properties"  : {"foo" : "bar"},
            "sound.pulseaudio_id"   : "fake-one",
            "sound.pulseaudio.server" : "some-path",
            })
        server_props.update(self._get_window_mixin_server_attributes())
        self._test_mixin_classes((WindowsMixin, AudioMixin, AVSyncMixin), server_props, {
            "sound.send"    : True,
            "sound.receive" : True,
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

    def test_notification(self):
        from xpra.server.source.notification_mixin import NotificationMixin
        self._test_mixin_class(NotificationMixin)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
