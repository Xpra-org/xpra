#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import unittest
from io import BytesIO
from threading import Event
from time import monotonic
from unittest.mock import patch

from unit.test_util import LoggerSilencer, silence_error, silence_info

from xpra.util.objects import typedict, AdHocStruct
from xpra.net.common import BACKWARDS_COMPATIBLE
from xpra.os_util import POSIX, OSX
from xpra.util.io import get_util_logger
from xpra.util.signal_emitter import SignalEmitter


class FakeServer(SignalEmitter):
    """ stands in for the owning server: keeps a `__dict__`, so tests can set anything on it """


class SourceMixinsTest(unittest.TestCase):
    event = Event()
    event.set()
    AUDIO_SERVER_PROPS = {
        "audio_initialized": event,
        "properties": {},
        "source_plugin": None,
        "supports_microphone": True,
        "microphone_codecs": (),
        "supports_speaker": False,
        "speaker_codecs": (),
    }

    def _test_mixin_class(self, mixin_class, server_props=None, client_caps=None, protocol=None, test_fn=None,
                          subsystems=None):
        return self._test_mixin_classes((mixin_class, ), server_props, client_caps, protocol, test_fn, subsystems)

    def _test_mixin_classes(self, mixin_classes, server_props=None, client_caps=None, protocol=None, test_fn=None,
                            subsystems=None):
        assert mixin_classes
        for mixin_class in mixin_classes:
            assert mixin_class.is_needed(typedict(client_caps or {})) in (True, False)
        if len(mixin_classes)==1:
            mixin_class = mixin_classes[0]
        else:
            mixin_class = type(f"Mixin-{mixin_classes}", mixin_classes, {})
        # test the instance:
        # fake server object: a plain subclass, so it has the `__dict__` that
        # `SignalEmitter` itself no longer provides, and takes arbitrary attributes
        server = FakeServer()
        server.session_name = "foo"
        server.unix_socket_paths = ["/some/path"]
        server.limit = 0
        server.detection = False
        if server_props:
            for k,v in server_props.items():
                setattr(server, k, v)
        server.subsystems = {
            "audio": server,
            "bandwidth": server,
            "dbus": server,
            "encoding": server,
            "file": server,
            "idle": server,
            "mmap": server,
            "printer": server,
            "webcam": server,
            "window": server,
        }
        # some subsystems keep state of their own that the fake server can't stand in for:
        server.subsystems.update(subsystems or {})
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
        m.user_event("test")
        for c in mixin_classes:
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

    def test_readonly(self):
        from xpra.server.source.readonly import ReadonlyConnection
        protocol = AdHocStruct()
        protocol._conn = AdHocStruct()
        protocol._conn.options = {"readonly": "yes"}
        source = self._test_mixin_class(ReadonlyConnection, {"readonly": False}, {"readonly": True}, protocol)
        self.assertTrue(source.client_readonly)
        self.assertTrue(source.connection_readonly)
        self.assertTrue(source.effective_readonly())
        self.assertTrue(source.server_enforced_readonly())
        source.set_client_readonly(False)
        self.assertTrue(source.effective_readonly())
        source.connection_readonly = False
        self.assertFalse(source.effective_readonly())
        source.server.readonly = True
        self.assertTrue(source.effective_readonly())

    #############################################################################
    # The following tests are incomplete:
    def test_audio(self):
        from xpra.server.source.audio import AudioConnection, FakeSink

        def loop_check(_c, m):
            m.audio_loop_check()
        source = self._test_mixin_class(AudioConnection, SourceMixinsTest.AUDIO_SERVER_PROPS, test_fn=loop_check)
        info = source.get_audio_info()
        # `active` answers "is audio being forwarded right now?" without parsing state strings:
        for mode in ("speaker", "microphone"):
            assert info[mode]["active"] is False
            assert info[mode]["state"] in ("disabled", "inactive")
        # a sink rejected by the audio loop check must still show up in the info:
        source.supports_microphone = True
        source.audio_sink = FakeSink("opus")
        microphone = source.get_audio_info()["microphone"]
        assert microphone["state"] == "blocked"
        assert microphone["active"] is False

    def test_clientconnection(self):
        from xpra.server.source.client_connection import ClientConnection
        assert ClientConnection.is_needed(typedict()) is True
        # self._test_mixin_class(ClientConnection)

    def test_clipboard(self):
        from xpra.net.compression import Compressible, Compressed
        from xpra.server.source.clipboard import ClipboardConnection
        for fix in (False, True):
            self._test_mixin_class(ClipboardConnection, None, {
                "clipboard.contents-slice-fix" : fix,
            })

        data = b"clipboard data"
        for compressors, expected in (
                (("lz4",), "lz4"),
                (("lz4", "brotli"), "brotli"),
                ((), "")):
            source = ClipboardConnection()
            source.init_state()
            source.parse_client_caps(typedict({
                "clipboard": {"enabled": True},
                "compressors": compressors,
            }))
            packets = []
            source.queue_packet = packets.append
            compressed = Compressed("test", b"compressed")
            with patch("xpra.net.compression.compressed_wrapper", return_value=compressed) as wrapper:
                source.compress_clipboard(("clipboard-contents", Compressible("text", data)))
            kwargs = wrapper.call_args.kwargs
            self.assertEqual(kwargs.get("brotli", False), expected == "brotli")
            self.assertEqual(kwargs.get("lz4", False), expected == "lz4")
            self.assertEqual(packets, [("clipboard-contents", compressed)])

    def test_dbus(self):
        try:
            from xpra.server import dbus
            assert dbus
            from xpra.server.source.dbus import DBUS_Connection
        except ImportError:
            pass
        else:
            self._test_mixin_class(DBUS_Connection, {
                "control"  : True,
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
            # modern clients send their encodings in the `encoding` namespace;
            # the flat `encodings.core` cap is ignored with BC=0
            "encoding": {
                "core": ("rgb32", "rgb24"),
                "options": ("rgb32", "rgb24"),
            },
        })

    def test_file(self):
        from xpra.server.source.file import FileConnection
        from xpra.net.file_transfer import FileTransferAttributes
        self._test_mixin_class(FileConnection, {
            "file_transfer": FileTransferAttributes(),
            "machine_id": "123",
        })

    def test_file_printer(self):
        # `FileConnection` and `PrinterConnection` are mixed into the same instance
        # and share a single set of file-transfer attributes:
        # initializing the printer half must not wipe the file half - see #5028
        from xpra.server.source.file import FileConnection
        from xpra.server.source.printer import PrinterConnection
        from xpra.net.file_transfer import FileTransferAttributes
        file_transfer = FileTransferAttributes()
        file_transfer.init_attributes(file_transfer="yes", file_size_limit="10M",
                                      open_files="yes", open_url="yes", open_command="open-it")
        # `PrinterServer` keeps its own copy, which is the one that owns `printing`:
        printer_ft = AdHocStruct()
        printer_ft.file_transfer = FileTransferAttributes()
        printer_ft.file_transfer.init_attributes(printing="yes")

        def check(_c, source):
            # `cleanup()` resets the attributes, so this has to run before it:
            self.assertTrue(source.file_transfer)
            self.assertTrue(source.open_files)
            self.assertTrue(source.open_url)
            self.assertEqual(source.open_command, "open-it")
            self.assertEqual(source.file_size_limit, 10 * 1000 * 1000)
            # and `printing` must come from the printer subsystem's own copy:
            self.assertTrue(source.printing)
            self.assertTrue(source.remote_file_transfer)
            self.assertTrue(source.remote_printing)

        self._test_mixin_classes((FileConnection, PrinterConnection), {
            "file_transfer": file_transfer,
            "machine_id": "123",
        }, {
            # `printing` is parsed from the `file` namespace with backwards compatibility,
            # from the `printer` one without it:
            "file": {"enabled": True, "printing": True},
            "printer": {"printing": True},
        }, test_fn=check, subsystems={"printer": printer_ft})

    def test_idle(self):
        from xpra.server.source.idle_mixin import IdleConnection

        def idle_test(_c, m):
            m.idle_grace_timedout()
            m.idle_notification_action(10, "cancel")
            m.idle_notification_action(20, "other")
            m.idle_timedout()
        self._test_mixin_class(IdleConnection, {
            "timeout": 1000,
        }, test_fn=idle_test)

    def test_input(self):
        from xpra.server.source.keyboard import KeyboardConnection
        self._test_mixin_class(KeyboardConnection)

    def test_mmap(self):
        from xpra.server.source import mmap
        import tempfile
        tmp = tempfile.NamedTemporaryFile(prefix="xpra-mmap-test")
        tmp.write(b"0"*1024*1024)
        tmpdir = tempfile.mkdtemp(prefix="xpra-mmap-test")
        for server_mmap_dirs, server_mmap_files in (
            ((), ()),
            ((), (tmp.name, )),
            ((), ("/this-path/should-not-exist", )),
            ((tmpdir, ), ()),
            ((tmpdir, ), (tmp.name, )),
        ):
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
                            "dirs": server_mmap_dirs,
                            "files": server_mmap_files,
                            "supported": mmap_supported,
                            "min_size": 10000,
                        }, caps)
        os.rmdir(tmpdir)

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

        def get_window_geometry(_w):
            return 0, 0, 0, 0
        return {
            "get_transient_for": get_transient_for,
            "get_focus": get_focus,
            "get_cursor_data": get_cursor_data,
            "get_window_id": get_window_id,
            "get_window_geometry": get_window_geometry,
            "window_filters": (),
            "readonly": False,
        }

    def test_windows(self):
        from xpra.server.source.window import WindowsConnection
        self._test_mixin_class(WindowsConnection, self._get_window_mixin_server_attributes())

    def test_window_display_area(self):
        # `sharing=combine`: the windows outside this client's area of the virtual display
        # are sent to it, but hidden, and the coordinates are relative to that area
        from xpra.server.source.window import WindowsConnection, HIDDEN_METADATA
        from xpra.util.rectangle import rectangle

        class FakeWindow:
            def __init__(self, geometry):
                self.geometry = geometry

            @staticmethod
            def is_tray() -> bool:
                return False

            def get_property(self, prop):
                return {"iconic": False, "skip-taskbar": False, "skip-pager": True}.get(prop)

        source = WindowsConnection()
        WindowsConnection.__init__(source)
        source.init_state()
        source.hello_sent = True
        source.window_enabled = True
        source.window_metadata_supported = HIDDEN_METADATA
        source.get_server_geometry = lambda window: window.geometry
        packets = []
        source.send = lambda *packet: packets.append(packet)

        inside = FakeWindow((5000, 200, 800, 600))
        outside = FakeWindow((100, 200, 800, 600))
        # without an area, everything is visible and the coordinates are unchanged:
        self.assertEqual(source.to_client_position(5000, 200), (5000, 200))
        self.assertFalse(source.update_window_visibility(1, outside))
        self.assertEqual(packets, [])

        source.display_area = rectangle(4480, 0, 2560, 1440)
        self.assertEqual(source.to_client_position(5000, 200), (520, 200))
        self.assertFalse(source.update_window_visibility(1, inside))
        self.assertEqual(packets, [], "a visible window needs no metadata update")
        self.assertTrue(source.update_window_visibility(2, outside))
        self.assertTrue(source.is_window_hidden(outside))
        self.assertEqual(packets, [("window-metadata", 2, {k: True for k in HIDDEN_METADATA})])
        # the override is applied to the metadata sent with the window itself:
        self.assertEqual(source._make_metadata(outside, "iconic", skip_defaults=True), {"iconic": True})
        self.assertEqual(source._make_metadata(inside, "iconic", skip_defaults=True), {})
        # moving it back into the area restores the real values:
        packets.clear()
        outside.geometry = (4600, 200, 800, 600)
        self.assertFalse(source.update_window_visibility(2, outside))
        self.assertFalse(source.is_window_hidden(outside))
        self.assertEqual(packets, [
            ("window-metadata", 2, {"iconic": False, "skip-taskbar": False, "skip-pager": True}),
        ])

    def test_window_hidden_damage(self):
        # a hidden window is unmapped as far as that client is concerned:
        # no pixels are sent for it, and its window source is told to go idle
        from xpra.server.source.window import WindowsConnection, HIDDEN_METADATA
        from xpra.util.rectangle import rectangle

        class FakeWindowSource:
            def __init__(self):
                self.calls = []

            def unmap(self):
                self.calls.append("unmap")

            def map(self, mapped_at):
                self.calls.append(("map", mapped_at))

            def cancel_damage(self):
                self.calls.append("cancel_damage")

            def damage(self, x, y, w, h, options):
                self.calls.append(("damage", x, y, w, h))

        class FakeWindow:
            geometry = (100, 200, 800, 600)

            @staticmethod
            def is_tray() -> bool:
                return False

            @staticmethod
            def get_dimensions():
                return 800, 600

            @staticmethod
            def get_property(prop):
                return False

        source = WindowsConnection()
        WindowsConnection.__init__(source)
        source.init_state()
        source.hello_sent = True
        source.window_enabled = True
        source.window_metadata_supported = HIDDEN_METADATA
        source.get_server_geometry = lambda window: window.geometry
        source.send = lambda *packet: None
        source.statistics = None
        window = FakeWindow()
        ws = FakeWindowSource()
        source.window_sources[3] = ws
        source.display_area = rectangle(4480, 0, 2560, 1440)

        self.assertTrue(source.update_window_visibility(3, window))
        self.assertEqual(ws.calls, ["unmap"])
        # damage is dropped while it is hidden:
        source.damage(3, window, 0, 0, 800, 600)
        self.assertEqual(ws.calls, ["unmap"])
        # once it moves into the area, it is mapped again (at its position on the
        # server's display, like `_window_mapped_at` records) and fully refreshed:
        ws.calls.clear()
        window.geometry = (4600, 200, 800, 600)
        self.assertFalse(source.update_window_visibility(3, window))
        self.assertEqual(ws.calls, [("map", (4600, 200)), "cancel_damage", ("damage", 0, 0, 800, 600)])

    def test_window_stacking_sync_is_ungated(self):
        from xpra.server.source.window import WindowsConnection

        protocol = AdHocStruct()
        protocol._conn = AdHocStruct()
        protocol._conn.options = {"record": "no", "sync": "no"}
        for window_caps in ({"record": True}, {"sync-stacking": True}):
            source = WindowsConnection()
            source.protocol = protocol
            source.init_state()
            source.parse_client_caps(typedict({"window": window_caps}))
            self.assertTrue(source.window_sync_stacking)
            self.assertFalse(source.window_record)
            self.assertFalse(source.window_sync_position)
            self.assertFalse(source.window_sync_focus)

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
        from xpra.net.packet_type import DISPLAY_RESIZED, DISPLAY_SHOW_DESKTOP

        expected_packet_type = "show-desktop" if BACKWARDS_COMPATIBLE else "display-show-desktop"
        self.assertEqual(DISPLAY_SHOW_DESKTOP, expected_packet_type)
        expected_resize_packet_type = "desktop_size" if BACKWARDS_COMPATIBLE else "display-resized"
        self.assertEqual(DISPLAY_RESIZED, expected_resize_packet_type)

        def check_monitor_layout(_cls, source):
            source.set_monitors({
                0: {"geometry": (-1920, 0, 1920, 1080)},
                1: {"geometry": (0, 0, 2560, 1440)},
            })
            self.assertEqual(source.get_monitor_position(0, (100, 50)), (100, 50))
            self.assertEqual(source.get_monitor_position(1, (100, 50)), (2020, 50))
            normalized = source.get_normalized_monitor_definitions()
            self.assertEqual(normalized[0]["geometry"], (0, 0, 1920, 1080))
            self.assertEqual(normalized[1]["geometry"], (1920, 0, 2560, 1440))
            packets = []
            source.send_async = lambda *packet: packets.append(packet)
            source.send = source.send_async
            source.show_desktop_allowed = True
            source.hello_sent = True
            source.show_desktop(True)
            self.assertEqual(packets, [(DISPLAY_SHOW_DESKTOP, True)])
            self.assertTrue(source.updated_desktop_size(1024, 768, 3840, 2160))
            self.assertEqual(packets[-1], (DISPLAY_RESIZED, 1024, 768, 3840, 2160))
            # `sharing=combine`: this client only occupies part of the virtual display,
            # so its monitor positions are offset by its area, and it is only told about its area:
            from xpra.util.rectangle import rectangle
            self.assertEqual(source.get_display_origin(), (0, 0))
            self.assertEqual(source.get_display_area_size(), ())
            source.set_display_area(rectangle(4480, 100, 2560, 1440))
            self.assertEqual(source.get_display_origin(), (4480, 100))
            self.assertEqual(source.get_display_area_size(), (2560, 1440))
            self.assertEqual(source.get_info().get("area"), (4480, 100, 2560, 1440))
            self.assertEqual(source.get_monitor_position(0, (100, 50)), (4580, 150))
            self.assertEqual(source.get_monitor_position(1, (100, 50)), (6500, 150))
            self.assertIsNone(source.get_monitor_position(99, (100, 50)))
            self.assertTrue(source.updated_desktop_size(7040, 1540, 7040, 1540))
            self.assertEqual(packets[-1], (DISPLAY_RESIZED, 2560, 1440, 2560, 1440))
            source.set_display_area(None)
            self.assertEqual(source.get_monitor_position(0, (100, 50)), (100, 50))
            self.assertNotIn("area", source.get_info())

        caps = None if BACKWARDS_COMPATIBLE else {"display": {"monitors": {}}}
        self._test_mixin_class(DisplayConnection, client_caps=caps, test_fn=check_monitor_layout)

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
                    "enabled"           : enabled,
                    "device"            : None,
                    "encodings"         : ("png", "jpeg"),
                    "client_mode"       : False,
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
            "properties": {"foo": "bar"},
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
