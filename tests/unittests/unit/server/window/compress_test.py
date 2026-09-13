#!/usr/bin/env python3

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

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


if __name__ == "__main__":
    unittest.main()
