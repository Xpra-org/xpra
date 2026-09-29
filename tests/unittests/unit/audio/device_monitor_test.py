# This file is part of Xpra.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import ctypes
import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.platform.darwin.audio_device_monitor import AudioDeviceMonitor


class CoreAudioMonitorTest(unittest.TestCase):
    def test_wrapper_reports_failed_registration(self):
        from xpra.audio.device_monitor import AudioDeviceMonitor as DeviceMonitor

        with patch("xpra.audio.device_monitor.OSX", True), \
                patch.object(AudioDeviceMonitor, "reusable", return_value=AudioDeviceMonitor()), \
                patch.object(AudioDeviceMonitor, "start", side_effect=OSError("temporarily unavailable")):
            monitor = DeviceMonitor()
            self.assertFalse(monitor.start(Mock()))
            self.assertIsNone(monitor.monitor)

    def test_output_change_and_unregister(self):
        device_id = [7]
        coreaudio = Mock()

        def read(_object, _address, _qualifier_size, _qualifier, _size, data):
            ctypes.cast(data, ctypes.POINTER(ctypes.c_uint32))[0] = device_id[0]
            return 0

        coreaudio.AudioObjectGetPropertyData.side_effect = read
        coreaudio.AudioObjectAddPropertyListener.return_value = 0
        coreaudio.AudioObjectRemovePropertyListener.return_value = 0
        changed = Mock()
        with patch("xpra.platform.darwin.audio_device_monitor.ctypes.CDLL", return_value=coreaudio), \
                patch("xpra.platform.darwin.audio_device_monitor.GLib.timeout_add", return_value=9), \
                patch("xpra.platform.darwin.audio_device_monitor.GLib.source_remove") as remove:
            monitor = AudioDeviceMonitor()
            monitor.start(changed)
            coreaudio.AudioObjectAddPropertyListener.assert_called_once()
            self.assertTrue(monitor.poll())
            changed.assert_not_called()
            device_id[0] = 8
            monitor.listener(1, 1, None, None)
            self.assertTrue(monitor.poll())
            changed.assert_called_once()
            monitor.listener(1, 1, None, None)
            monitor.poll()
            changed.assert_called_once()
            monitor.stop()
            coreaudio.AudioObjectRemovePropertyListener.assert_called_once()
            remove.assert_called_once_with(9)
            self.assertFalse(monitor.poll())

    def test_temporary_read_failure_does_not_restart_audio(self):
        device_id = [7]
        fail = [False]
        coreaudio = Mock()

        def read(_object, _address, _qualifier_size, _qualifier, _size, data):
            if fail[0]:
                return 42
            ctypes.cast(data, ctypes.POINTER(ctypes.c_uint32))[0] = device_id[0]
            return 0

        coreaudio.AudioObjectGetPropertyData.side_effect = read
        coreaudio.AudioObjectAddPropertyListener.return_value = 0
        coreaudio.AudioObjectRemovePropertyListener.return_value = 0
        changed = Mock()
        with patch("xpra.platform.darwin.audio_device_monitor.ctypes.CDLL", return_value=coreaudio), \
                patch("xpra.platform.darwin.audio_device_monitor.GLib.timeout_add", return_value=9), \
                patch("xpra.platform.darwin.audio_device_monitor.GLib.source_remove"):
            monitor = AudioDeviceMonitor()
            monitor.start(changed)
            monitor.poll()
            fail[0] = True
            monitor.listener(1, 1, None, None)
            monitor.poll()
            self.assertEqual(monitor.device_id, 7)
            self.assertTrue(monitor.changed.is_set())
            changed.assert_not_called()
            fail[0] = False
            monitor.poll()
            changed.assert_not_called()
            device_id[0] = 0  # A successful read of zero means no default output.
            monitor.listener(1, 1, None, None)
            monitor.poll()
            changed.assert_called_once()
            self.assertEqual(monitor.device_id, 0)
            monitor.stop()

    def test_initial_read_failure_establishes_baseline_without_restart(self):
        device_id = [7]
        fail = [True]
        coreaudio = Mock()

        def read(_object, _address, _qualifier_size, _qualifier, _size, data):
            if fail[0]:
                return 42
            ctypes.cast(data, ctypes.POINTER(ctypes.c_uint32))[0] = device_id[0]
            return 0

        coreaudio.AudioObjectGetPropertyData.side_effect = read
        coreaudio.AudioObjectAddPropertyListener.return_value = 0
        coreaudio.AudioObjectRemovePropertyListener.return_value = 0
        changed = Mock()
        with patch("xpra.platform.darwin.audio_device_monitor.ctypes.CDLL", return_value=coreaudio), \
                patch("xpra.platform.darwin.audio_device_monitor.GLib.timeout_add", return_value=9), \
                patch("xpra.platform.darwin.audio_device_monitor.GLib.source_remove"):
            monitor = AudioDeviceMonitor()
            monitor.start(changed)
            self.assertIsNone(monitor.device_id)
            monitor.poll()
            fail[0] = False
            monitor.poll()
            self.assertEqual(monitor.device_id, 7)
            changed.assert_not_called()
            device_id[0] = 8
            monitor.listener(1, 1, None, None)
            monitor.poll()
            changed.assert_called_once()
            monitor.stop()

    def test_failed_unregister_retains_and_reuses_listener(self):
        from xpra.audio.device_monitor import AudioDeviceMonitor as DeviceMonitor

        coreaudio = Mock()
        device_id = [7]

        def read(_object, _address, _qualifier_size, _qualifier, _size, data):
            ctypes.cast(data, ctypes.POINTER(ctypes.c_uint32))[0] = device_id[0]
            return 0

        coreaudio.AudioObjectGetPropertyData.side_effect = read
        coreaudio.AudioObjectAddPropertyListener.return_value = 0
        coreaudio.AudioObjectRemovePropertyListener.side_effect = (42, 0)
        with patch("xpra.platform.darwin.audio_device_monitor.ctypes.CDLL", return_value=coreaudio), \
                patch("xpra.platform.darwin.audio_device_monitor.GLib.timeout_add", return_value=9), \
                patch("xpra.platform.darwin.audio_device_monitor.GLib.source_remove"), \
                patch("xpra.audio.device_monitor.OSX", True):
            first = DeviceMonitor()
            first.start(Mock())
            listener = first.monitor.listener
            self.assertFalse(first.stop())
            self.assertIs(first.monitor.listener, listener)
            self.assertIs(AudioDeviceMonitor.reusable(), first.monitor)
            second = DeviceMonitor()
            on_change = Mock()
            second.start(on_change)
            self.assertIs(second.monitor, first.monitor)
            coreaudio.AudioObjectAddPropertyListener.assert_called_once()
            device_id[0] = 8
            listener(1, 1, None, None)
            second.monitor.poll()
            on_change.assert_called_once()
            self.assertTrue(second.stop())
            self.assertIsNone(AudioDeviceMonitor._pending_removal)
            coreaudio.AudioObjectRemovePropertyListener.assert_called_with(
                1, unittest.mock.ANY, listener, None)

    def test_unregister_exception_retains_callback_until_retry(self):
        coreaudio = Mock()
        coreaudio.AudioObjectGetPropertyData.return_value = 0
        coreaudio.AudioObjectAddPropertyListener.return_value = 0
        coreaudio.AudioObjectRemovePropertyListener.side_effect = (OSError("temporarily unavailable"), 0)
        with patch("xpra.platform.darwin.audio_device_monitor.ctypes.CDLL", return_value=coreaudio), \
                patch("xpra.platform.darwin.audio_device_monitor.GLib.timeout_add", return_value=9), \
                patch("xpra.platform.darwin.audio_device_monitor.GLib.source_remove"):
            monitor = AudioDeviceMonitor()
            monitor.start(Mock())
            listener = monitor.listener
            self.assertFalse(monitor.stop())
            self.assertIs(AudioDeviceMonitor.reusable(), monitor)
            self.assertIs(monitor.listener, listener)
            self.assertTrue(monitor.stop())
            self.assertIsNone(AudioDeviceMonitor._pending_removal)


class WindowsMonitorLifetimeTest(unittest.TestCase):
    def test_registration_window_and_failed_unregister(self):
        # Emulate the COM vtable on Linux; native Windows calling conventions
        # and frozen-client behavior still require a Windows test.
        kernel32 = SimpleNamespace(CreateEventW=Mock(return_value=99),
                                   ResetEvent=Mock(), CloseHandle=Mock(),
                                   SetEvent=Mock(), WaitForSingleObject=Mock())
        signaled = [False]

        def set_event(_event):
            signaled[0] = True

        def wait_event(_event, _timeout):
            if signaled[0]:
                signaled[0] = False  # auto-reset happens atomically with the successful wait
                return 0
            return 1

        kernel32.SetEvent.side_effect = set_event
        kernel32.WaitForSingleObject.side_effect = wait_event
        ole32 = SimpleNamespace(CoInitializeEx=Mock(return_value=0),
                                CoCreateInstance=Mock(), CoUninitialize=Mock())
        with patch.object(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE, create=True), \
                patch.object(ctypes, "HRESULT", ctypes.c_int32, create=True), \
                patch.object(ctypes, "windll", SimpleNamespace(ole32=ole32, kernel32=kernel32), create=True):
            path = Path(__file__).resolve().parents[4] / "xpra/platform/win32/audio_device_monitor.py"
            spec = importlib.util.spec_from_file_location("test_windows_audio_device_monitor", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            unregister_status = [-1]
            registered = []

            @module._ENUM_REGISTER
            def register(_enumerator, _client):
                registered.append((module._event, module._on_change))
                module._vtbl.OnDefaultDeviceChanged(ctypes.addressof(module._client), 0, 0, "new device")
                return 0

            @module._ENUM_UNREGISTER
            def unregister(_enumerator, _client):
                return unregister_status[0]

            @module._RELEASE
            def release(_enumerator):
                return 0

            vtable = (ctypes.c_void_p * 20)()
            for index, callback in ((2, release), (6, register), (7, unregister)):
                vtable[index] = ctypes.cast(callback, ctypes.c_void_p).value
            vtable_pointer = ctypes.c_void_p(ctypes.addressof(vtable))
            enumerator = ctypes.cast(ctypes.pointer(vtable_pointer), ctypes.c_void_p)

            def create(_clsid, _outer, _context, _iid, result):
                ctypes.cast(result, ctypes.POINTER(ctypes.c_void_p))[0] = enumerator
                return 0

            ole32.CoCreateInstance.side_effect = create
            with patch.object(module.GLib, "timeout_add", side_effect=(47, 48)), \
                    patch.object(module.GLib, "source_remove"):
                def notify():
                    if on_change.call_count == 1:
                        module._vtbl.OnDefaultDeviceChanged(ctypes.addressof(module._client), 0, 0, "next device")

                on_change = Mock(side_effect=notify)
                module.start(on_change)
                kernel32.CreateEventW.assert_called_once_with(None, False, False, None)
                self.assertEqual(registered, [(99, on_change)])
                kernel32.SetEvent.assert_called_once_with(99)
                self.assertTrue(module._check_event())
                on_change.assert_called_once()
                self.assertTrue(module._check_event())
                self.assertEqual(on_change.call_count, 2)
                kernel32.ResetEvent.assert_not_called()
                kernel32.SetEvent.reset_mock()
                module._vtbl.OnDefaultDeviceChanged(ctypes.addressof(module._client), 0, 1, "multimedia")
                module._vtbl.OnDefaultDeviceChanged(ctypes.addressof(module._client), 0, 2, "communications")
                module._vtbl.OnDefaultDeviceChanged(ctypes.addressof(module._client), 1, 2, "capture")
                kernel32.SetEvent.assert_not_called()
                module._check_event()
                self.assertEqual(on_change.call_count, 2)
                self.assertFalse(module.stop())
                self.assertTrue(module._registered)
                self.assertIsNotNone(module._client)
                self.assertTrue(module._prevent_gc)
                kernel32.CloseHandle.assert_not_called()
                ole32.CoUninitialize.assert_not_called()

                module._vtbl.OnDefaultDeviceChanged(ctypes.addressof(module._client), 0, 0, "during stop")
                module.start(on_change)
                module._check_event()
                self.assertEqual(on_change.call_count, 3)
                kernel32.ResetEvent.assert_not_called()
                ole32.CoCreateInstance.assert_called_once()
                with patch.object(module, "_ENUM_UNREGISTER", side_effect=RuntimeError("COM failure")):
                    self.assertFalse(module.stop())
                self.assertTrue(module._prevent_gc)
                kernel32.CloseHandle.assert_not_called()
                unregister_status[0] = 0
                self.assertTrue(module.stop())
                self.assertFalse(module._registered)
                self.assertFalse(module._prevent_gc)
                kernel32.CloseHandle.assert_called_once_with(99)
                ole32.CoUninitialize.assert_called_once()


if __name__ == "__main__":
    unittest.main()
