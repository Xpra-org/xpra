#!/usr/bin/env python3

import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import current_thread
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.server.window import compress
from xpra.server.window.compress import WindowSource
from xpra.util.objects import typedict


class CompressTest(unittest.TestCase):

    @staticmethod
    def make_cancellable_source() -> WindowSource:
        source = object.__new__(WindowSource)
        source.wid = 1
        source._sequence = 5
        source._damage_cancelled = 0
        source._damage_delayed = None
        source.encode_queue = []
        source.refresh_regions = []
        source.refresh_event_time = 0
        for timer in ("expire_timer", "may_send_timer", "soft_timer", "refresh_timer",
                      "timeout_timer", "av_sync_timer", "decode_error_refresh_timer"):
            setattr(source, timer, 0)
        source.statistics = SimpleNamespace(encoding_pending={})
        source.window = Mock()
        return source

    def test_dropping_a_delayed_region_acknowledges_it(self) -> None:
        source = self.make_cancellable_source()
        source._damage_delayed = "some delayed regions"
        source.cancel_damage()
        self.assertIsNone(source._damage_delayed)
        source.window.acknowledge_changes.assert_called_once_with()

    def test_cancelling_without_a_delayed_region_acknowledges_nothing(self) -> None:
        source = self.make_cancellable_source()
        source.cancel_damage()
        source.window.acknowledge_changes.assert_not_called()

    def test_network_thread_cancellation_acknowledges_on_the_main_thread(self) -> None:
        for delayed in (False, True):
            with self.subTest(delayed=delayed):
                source = self.make_cancellable_source()
                if delayed:
                    source._damage_delayed = "some delayed regions"
                window = source.window
                ack_threads = []
                window.acknowledge_changes.side_effect = lambda: ack_threads.append(current_thread())

                with patch.object(compress.GLib, "idle_add") as idle_add:
                    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="parse") as executor:
                        executor.submit(source.cancel_damage).result(timeout=5)

                    self.assertIsNone(source._damage_delayed)
                    window.acknowledge_changes.assert_not_called()
                    if not delayed:
                        idle_add.assert_not_called()
                        continue
                    idle_add.assert_called_once_with(window.acknowledge_changes)
                    # Cleanup can clear the source's window before the main loop runs.
                    source.window = None
                    callback = idle_add.call_args.args[0]
                    callback()

                window.acknowledge_changes.assert_called_once_with()
                self.assertEqual(ack_threads, [current_thread()])

    def test_client_properties_preserve_render_size(self) -> None:
        # the client only sends the properties that have changed:
        source = object.__new__(WindowSource)
        source.client_render_size = (0, 0)
        source.client_bit_depth = 24
        source.supports_transparency = True
        source.is_tray = False
        source.encoding = "auto"
        source.update_encoding_selection = Mock()
        for k, v in {
            "client_refresh_encodings": (), "full_frames_only": False,
            "encodings": ("rgb24", ), "core_encodings": ("rgb24", ), "rgb_formats": ("BGRX", ),
            "decoder_speed": typedict(), "full_csc_modes": typedict(), "_all_encoders": {}, "_encoders": {},
        }.items():
            setattr(source, k, v)
        source.do_set_client_properties(typedict({"encoding.render-size": (640, 480)}))
        self.assertEqual(source.client_render_size, (640, 480))
        source.do_set_client_properties(typedict({"encoding.transparency": False}))
        self.assertEqual(source.client_render_size, (640, 480))
        source.do_set_client_properties(typedict({"encoding.render-size": (800, 600)}))
        self.assertEqual(source.client_render_size, (800, 600))

    def test_maximized_follows_window(self) -> None:
        source = object.__new__(WindowSource)
        source.maximized = False
        source.window = SimpleNamespace(get_property=lambda name: {"maximized": True}[name])
        source.reconfigure = Mock()
        source._maximized_changed(source.window)
        self.assertTrue(source.maximized)
        source.reconfigure.assert_called_once_with(True)


if __name__ == "__main__":
    unittest.main()
