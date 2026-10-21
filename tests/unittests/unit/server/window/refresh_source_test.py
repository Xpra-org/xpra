#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.server.window import window_source
from xpra.server.window.window_source import WindowSource
from xpra.util import typedict
from xpra.rectangle import rectangle


class RefreshDeadlineTest(unittest.TestCase):

    def test_partial_updates_have_a_bounded_refresh_deadline(self):
        source = object.__new__(WindowSource)
        source.encoding = "auto"
        source.image_depth = 24
        source.refresh_quality = 100
        source.window_dimensions = 100, 100
        source.base_auto_refresh_delay = 200
        source.min_auto_refresh_delay = 50
        source.batch_config = SimpleNamespace(delay=0)
        source.global_statistics = SimpleNamespace(congestion_value=0)
        source.refresh_regions = []
        source.refresh_timer = 0
        source.refresh_event_time = 0
        source.refresh_target_time = 0
        source.timeout_add = Mock(return_value=1)
        region = rectangle(0, 0, 50, 50)
        with patch.object(window_source, "monotonic") as clock:
            # Keep repainting a partial region while the UI timer is pending.
            # The initial 200ms refresh delay permits at most one second of postponement.
            for i in range(100):
                clock.return_value = 100 + i/100
                source.do_schedule_auto_refresh("jpeg", b"data", region, {"quality": 50}, typedict())
        self.assertEqual(source.refresh_event_time, 100)
        self.assertLessEqual(source.refresh_target_time, 101)


if __name__ == '__main__':
    unittest.main()
