#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.server.source import encoding
from xpra.server.source.window import WindowsConnection


def window_source(geometry=(0, 0, 800, 600), **overrides):
    values = dict(mapped_at=geometry, suspended=False, iconic=False, has_alpha=False, has_shape=False, opacity=-1,
                  fullscreen=False, maximized=False, batch_config=SimpleNamespace(last_updated=0),
                  statistics=Mock(), calculate_batch_delay=Mock(), reconfigure=Mock(), cleanup=Mock())
    values.update(overrides)
    source = SimpleNamespace(**values)
    source.map = lambda coords: setattr(source, "mapped_at", coords)
    source.unmap = lambda: setattr(source, "mapped_at", None)
    return source


class WindowConnectionTest(unittest.TestCase):

    @staticmethod
    def connection():
        source = WindowsConnection()
        source.init_state()
        source.window_sources = {1: window_source((100, 100, 200, 200)), 2: window_source()}
        return source

    @staticmethod
    def encoding_connection():
        class Connection(WindowsConnection, encoding.EncodingsConnection):
            pass

        source = Connection()
        WindowsConnection.init_state(source)
        encoding.EncodingsConnection.init_state(source)
        source.window_sources = {1: window_source((100, 100, 200, 200)), 2: window_source(maximized=True)}
        source.get_focus = lambda: 2
        source.statistics = None
        source.protocol = SimpleNamespace(is_closed=lambda: False, _conn=SimpleNamespace(output_bytecount=0))
        return source

    def test_coverage_uses_client_stacking_and_geometry(self):
        source = self.connection()
        self.assertIsNone(source.get_window_coverage(1))
        source.set_window_stacking((1, 99, 2, 1))
        self.assertEqual(source.window_stacking, (1, 99, 2))
        self.assertTrue(source.get_window_coverage(1))
        self.assertFalse(source.get_window_coverage(2))
        self.assertIsNone(source.get_window_coverage(99))
        for geometry in ((100, 100, 200, 200), (-500, -500, 1000, 1000)):
            source.window_sources[2].mapped_at = geometry
            self.assertTrue(source.get_window_coverage(1))
        source.window_sources[2].opacity = 0xffffffff
        self.assertTrue(source.get_window_coverage(1))
        for geometry in ((200, 100, 200, 200), (1920, 0, 1920, 1080), (100, 100, 0, 0)):
            source.window_sources[2].mapped_at = geometry
            self.assertFalse(source.get_window_coverage(1))
        source.window_sources[2].mapped_at = (0, 0, 800, 600)
        source.set_window_stacking((2, 1))
        self.assertFalse(source.get_window_coverage(1))
        source.set_window_stacking((1,))
        self.assertFalse(source.get_window_coverage(1))

    def test_unsuitable_covering_windows_are_ignored(self):
        source = self.connection()
        source.set_window_stacking((1, 2))
        for overrides in (dict(has_alpha=True), dict(has_shape=True), dict(suspended=True), dict(iconic=True),
                          dict(opacity=0), dict(opacity=0x80000000),
                          dict(mapped_at=None), dict(mapped_at=(0, 0))):
            with self.subTest(overrides=overrides):
                source.window_sources[2] = window_source(**overrides)
                self.assertFalse(source.get_window_coverage(1))
        source.window_sources.pop(2)
        self.assertFalse(source.get_window_coverage(1))

    def test_unknown_target_geometry_falls_back(self):
        source = self.connection()
        source.set_window_stacking((1, 2))
        for geometry in (None, (0, 0), (0, 0, 0, 100), (0, 0, 100, -1)):
            source.window_sources[1].mapped_at = geometry
            self.assertIsNone(source.get_window_coverage(1))
        source.window_sources[1] = window_source(suspended=True)
        self.assertIsNone(source.get_window_coverage(1))

    def test_stacking_is_per_client_and_schedules_recalculation(self):
        first, second = self.connection(), self.connection()
        first.may_recalculate = Mock()
        first.set_window_stacking((1, 2))
        first.may_recalculate.assert_any_call(1, 0, force=True)
        first.may_recalculate.assert_any_call(2, 0, force=True)
        first.may_recalculate.reset_mock()
        first.set_window_stacking((1, 2))
        first.may_recalculate.assert_not_called()
        second.set_window_stacking((2, 1))
        self.assertTrue(first.get_window_coverage(1))
        self.assertFalse(second.get_window_coverage(1))

    def test_stacking_reaches_delay_worker_without_damage(self):
        source = self.encoding_connection()
        with patch.object(encoding, "add_work_item") as enqueue:
            source.set_window_stacking((1, 2))
            self.assertEqual(source.calculate_window_ids, {1, 2})
            self.assertEqual(source.calculate_window_pixels, {1: 0, 2: 0})
            enqueue.assert_called_with(source.recalculate_delays)
        source.recalculate_delays()
        source.window_sources[1].calculate_batch_delay.assert_called_once_with(False, False, True, True)
        source.window_sources[2].calculate_batch_delay.assert_called_once_with(True, False, False, False)
        self.assertFalse(source.calculate_window_ids)
        for ws in source.window_sources.values():
            ws.reconfigure.assert_called_once_with()

    @patch.object(encoding, "monotonic", return_value=100)
    def test_geometry_changes_recalculate_coverage_without_damage(self, _monotonic):
        source = self.encoding_connection()
        source.window_stacking = (1, 2)
        source.can_send_window = lambda _window: True
        target = source.window_sources[1]
        covering = source.window_sources[2]
        window = object()
        cases = (
            ("move away", lambda: source.map_window(2, window, (1920, 0, 800, 600)), False),
            ("move back", lambda: source.map_window(2, window, (0, 0, 800, 600)), True),
            ("shrink", lambda: source.map_window(2, window, (0, 0, 200, 200)), False),
            ("expand", lambda: source.map_window(2, window, (0, 0, 800, 600)), True),
            ("move target out", lambda: source.map_window(1, window, (1000, 100, 200, 200)), False),
            ("move target back", lambda: source.map_window(1, window, (100, 100, 200, 200)), True),
            ("unmap", lambda: source.unmap_window(2, window), False),
            ("map again", lambda: source.map_window(2, window, (0, 0, 800, 600)), True),
            ("remove", lambda: source.remove_window(2, window), False),
        )
        for name, action, covered in cases:
            with self.subTest(name=name), patch.object(encoding, "add_work_item") as enqueue:
                source.calculate_last_time = 0
                target.calculate_batch_delay.reset_mock()
                action()
                enqueue.assert_called_with(source.recalculate_delays)
                self.assertIn(1, source.calculate_window_ids)
                self.assertEqual(source.calculate_window_pixels[1], 0)
                source.recalculate_delays()
                self.assertEqual(target.calculate_batch_delay.call_args.args[-1], covered)
                self.assertEqual(source.window_stacking, (1, 2))
        covering.cleanup.assert_called_once_with()

    def test_unchanged_geometry_and_missing_stacking_do_not_schedule(self):
        source = self.connection()
        source.window_stacking = (1, 2)
        source.may_recalculate = Mock()
        window = object()
        source.map_window(2, window, (0, 0, 800, 600))
        source.unmap_window(99, window)
        source.may_recalculate.assert_not_called()
        source.unmap_window(2, window)
        source.may_recalculate.assert_any_call(1, 0, force=True)
        source.may_recalculate.reset_mock()
        source.unmap_window(2, window)
        source.may_recalculate.assert_not_called()
        source.window_stacking = ()
        source.map_window(2, window, (1920, 0, 800, 600))
        source.unmap_window(2, window)
        source.may_recalculate.assert_not_called()

    @patch.object(encoding, "monotonic", return_value=100)
    def test_repeated_geometry_changes_share_the_pending_recalculation(self, _monotonic):
        source = self.encoding_connection()
        source.window_stacking = (1, 2)
        source.calculate_last_time = 100
        with patch.object(encoding.GLib, "timeout_add", return_value=1) as timeout:
            source.map_window(2, object(), (1920, 0, 800, 600))
            source.map_window(2, object(), (10, 10, 800, 600))
            timeout.assert_called_once()
            self.assertEqual(source.calculate_window_ids, {1, 2})
        source.recalculate_delays()
        source.window_sources[1].calculate_batch_delay.assert_called_once_with(False, False, True, True)


if __name__ == "__main__":
    unittest.main()
