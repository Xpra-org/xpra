#!/usr/bin/env python3

import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import current_thread
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.server.window import compress
from xpra.server.window.compress import WindowSource


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


if __name__ == "__main__":
    unittest.main()
