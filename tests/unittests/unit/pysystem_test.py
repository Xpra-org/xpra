#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Tests for xpra/util/pysystem.py
"""

import sys
import threading
import unittest
from unittest.mock import MagicMock


class TestDumpAllFrames(unittest.TestCase):

    def test_runs_without_error(self):
        from xpra.util.pysystem import dump_all_frames
        dump_all_frames()

    def test_with_custom_logger(self):
        from xpra.util.pysystem import dump_all_frames
        calls = []
        logger = MagicMock(side_effect=lambda *a, **kw: calls.append(a))
        dump_all_frames(logger=logger)
        # should have logged at least one frame (the current one)
        self.assertGreater(len(calls), 0)

    def test_logs_frame_count(self):
        from xpra.util.pysystem import dump_all_frames
        messages = []
        logger = MagicMock(side_effect=lambda *a, **kw: messages.append(a[0] if a else ""))
        dump_all_frames(logger=logger)
        # first call should say "found N frames"
        self.assertTrue(any("found" in str(m) and "frame" in str(m) for m in messages))


class TestDumpGcFrames(unittest.TestCase):

    def test_runs_without_error(self):
        from xpra.util.pysystem import dump_gc_frames
        dump_gc_frames()

    def test_with_custom_logger(self):
        from xpra.util.pysystem import dump_gc_frames
        calls = []
        logger = MagicMock(side_effect=lambda *a, **kw: calls.append(a))
        dump_gc_frames(logger=logger)
        # gc.get_objects() may or may not have frames — just shouldn't raise
        self.assertIsInstance(calls, list)


class TestDumpFrames(unittest.TestCase):

    def test_empty_frames(self):
        from xpra.util.pysystem import dump_frames
        calls = []
        logger = MagicMock(side_effect=lambda *a, **kw: calls.append(a))
        dump_frames([], logger=logger)
        # first call: "found 0 frames"
        self.assertEqual(len(calls), 1)
        self.assertIn("0", str(calls[0]))

    def test_with_real_frame(self):
        from xpra.util.pysystem import dump_frames
        import sys
        frames = list(sys._current_frames().items())
        calls = []
        logger = MagicMock(side_effect=lambda *a, **kw: calls.append(a))
        dump_frames(frames, logger=logger)
        # should have at least two calls: "found N frames" + one per frame
        self.assertGreater(len(calls), 1)

    def test_frame_with_none_id(self):
        from xpra.util.pysystem import dump_frames
        import sys
        real_frame = list(sys._current_frames().values())[0]
        calls = []
        logger = MagicMock(side_effect=lambda *a, **kw: calls.append(a))
        # fid=None should be handled gracefully (fidstr left empty)
        dump_frames([(None, real_frame)], logger=logger)
        self.assertGreater(len(calls), 0)

    def test_uses_default_logger_when_none(self):
        from xpra.util.pysystem import dump_frames
        # should not raise even without an explicit logger
        dump_frames([])


class TestDetectLeaks(unittest.TestCase):

    def test_returns_callable(self):
        from xpra.util.pysystem import detect_leaks
        fn = detect_leaks()
        self.assertTrue(callable(fn))

    def test_callable_returns_true(self):
        from xpra.util.pysystem import detect_leaks
        fn = detect_leaks()
        result = fn()
        self.assertTrue(result)

    def test_callable_can_be_called_twice(self):
        from xpra.util.pysystem import detect_leaks
        fn = detect_leaks()
        self.assertTrue(fn())
        self.assertTrue(fn())


class TestGetFrameInfo(unittest.TestCase):

    def test_returns_dict(self):
        from xpra.util.pysystem import get_frame_info
        info = get_frame_info()
        self.assertIsInstance(info, dict)

    def test_has_count_key(self):
        from xpra.util.pysystem import get_frame_info
        info = get_frame_info()
        self.assertIn("count", info)
        self.assertIsInstance(info["count"], int)
        self.assertGreater(info["count"], 0)

    def test_has_native_id_key(self):
        from xpra.util.pysystem import get_frame_info
        info = get_frame_info()
        self.assertIn("native-id", info)
        self.assertIsInstance(info["native-id"], int)

    def test_frame_entries_have_stack(self):
        from xpra.util.pysystem import get_frame_info
        info = get_frame_info()
        frame_entries = {k: v for k, v in info.items() if isinstance(k, int)}
        # integer-keyed frame entries are populated when the internal frame walk succeeds;
        # if present they must have a "stack" key
        for entry in frame_entries.values():
            self.assertIn("stack", entry)
            self.assertIsInstance(entry["stack"], list)

    def test_ignore_threads_reduces_count(self):
        from xpra.util.pysystem import get_frame_info
        info_all = get_frame_info()
        # ignoring current thread
        current = threading.current_thread()
        info_filtered = get_frame_info(ignore_threads=(current,))
        self.assertLessEqual(info_filtered["count"], info_all["count"])

    def test_stack_entries_are_tuples(self):
        from xpra.util.pysystem import get_frame_info
        info = get_frame_info()
        for k, v in info.items():
            if isinstance(k, int):
                for frame_entry in v["stack"]:
                    self.assertIsInstance(frame_entry, tuple)

    def test_no_none_in_stack_entries(self):
        from xpra.util.pysystem import get_frame_info
        info = get_frame_info()
        for k, v in info.items():
            if isinstance(k, int):
                for frame_entry in v["stack"]:
                    for element in frame_entry:
                        self.assertIsNotNone(element, f"None in stack entry {frame_entry!r}")


class TestEnforceFeatures(unittest.TestCase):

    def test_enabled_feature_does_not_block(self):
        from xpra.util.pysystem import enforce_features
        features = MagicMock()
        features.foo = True
        # module already not blocked; enabling it should be a no-op
        enforce_features(features, {"foo": "this_module_does_not_exist_xyz"})
        # module should not be blocked
        self.assertNotIn("this_module_does_not_exist_xyz", sys.modules)

    def test_disabled_feature_blocks_unloaded_module(self):
        from xpra.util.pysystem import enforce_features
        module_name = "_test_enforce_fake_module_abc123"
        # ensure it's not in sys.modules
        sys.modules.pop(module_name, None)
        features = MagicMock()
        features.bar = False
        try:
            enforce_features(features, {"bar": module_name})
            # sys.modules[module_name] should be None (blocked)
            self.assertIn(module_name, sys.modules)
            self.assertIsNone(sys.modules[module_name])
        finally:
            sys.modules.pop(module_name, None)

    def test_disabled_feature_already_loaded_warns(self):
        from xpra.util.pysystem import enforce_features
        module_name = "_test_enforce_loaded_module_xyz456"
        fake_module = MagicMock()
        sys.modules[module_name] = fake_module
        features = MagicMock()
        features.baz = False
        try:
            # Should not raise; should log a warning
            enforce_features(features, {"baz": module_name})
            # the module stays loaded (cannot be un-loaded)
            self.assertIs(sys.modules[module_name], fake_module)
        finally:
            sys.modules.pop(module_name, None)

    def test_empty_feature_map(self):
        from xpra.util.pysystem import enforce_features
        features = MagicMock()
        # should not raise
        enforce_features(features, {})

    def test_empty_module_string_is_skipped(self):
        from xpra.util.pysystem import enforce_features
        features = MagicMock()
        features.empty = False
        # comma-separated with empty parts
        enforce_features(features, {"empty": ",,"})
        # nothing should be blocked


def main():
    unittest.main()


if __name__ == "__main__":
    main()
