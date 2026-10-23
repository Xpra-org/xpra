#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>

import os
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.util import glib_idle


class IdleQueueDetectionTest(unittest.TestCase):

    def test_environment_override_and_version_detection(self):
        with patch.object(glib_idle, "has_create_closure", return_value=True) as closure, \
                patch.dict(os.environ, {"XPRA_GLIB_IDLE_QUEUE": ""}):
            self.assertIsNone(glib_idle.get_env_value())
            self.assertTrue(glib_idle.needs_idle_queue(SimpleNamespace(version_info=(3, 44, 1))))
            closure.return_value = False
            self.assertFalse(glib_idle.needs_idle_queue(SimpleNamespace(version_info=(3, 44, 1))))
            closure.reset_mock()
            self.assertFalse(glib_idle.needs_idle_queue(SimpleNamespace(version_info=(3, 44, 2))))
            closure.assert_not_called()
            for value, expected in (("yes", True), ("no", False)):
                with self.subTest(value=value):
                    os.environ["XPRA_GLIB_IDLE_QUEUE"] = value
                    self.assertEqual(glib_idle.needs_idle_queue(SimpleNamespace(version_info=(3, 56, 0))), expected)

    def test_library_lookup_fallbacks(self):
        library = object()
        with patch("ctypes.CDLL", side_effect=[OSError("missing"), library]) as cdll:
            self.assertIs(glib_idle.get_girepository_library(), library)
            self.assertEqual(cdll.call_count, 2)
        with patch("ctypes.CDLL", side_effect=OSError("missing")) as cdll:
            self.assertIsNone(glib_idle.get_girepository_library())
            self.assertEqual(cdll.call_count, 3)

    def test_repository_version_and_closure_symbol(self):
        library = SimpleNamespace(gi_get_major_version=Mock(return_value=1), gi_get_minor_version=Mock(return_value=72),
                                  gi_get_micro_version=Mock(return_value=0), g_callable_info_create_closure=object())
        with patch.object(glib_idle, "get_girepository_library", return_value=library) as get_library:
            self.assertEqual(glib_idle.get_girepository_version(), "1.72.0")
            self.assertTrue(glib_idle.has_create_closure())
            get_library.return_value = SimpleNamespace()
            self.assertEqual(glib_idle.get_girepository_version(), "unknown")
            self.assertFalse(glib_idle.has_create_closure())
            get_library.return_value = None
            self.assertEqual(glib_idle.get_girepository_version(), "unknown")
            self.assertFalse(glib_idle.has_create_closure())


class FakeSource:
    """The GLib.Source boundary; queueing and dispatch use the production implementation."""

    def __init__(self):
        setattr(self, "__pygi_custom_source", object())
        self.destroyed = False
        self.cleared = False

    def set_priority(self, priority):
        self.priority = priority

    def attach(self, context):
        self.context = context

    def destroy(self):
        self.destroyed = True

    def _clear_boxed(self):
        self.cleared = True


class IdleQueueTest(unittest.TestCase):

    def setUp(self):
        self.context = SimpleNamespace(wakeup=Mock())
        self.native_idle_add = Mock(return_value=123)
        self.native_remove = Mock(return_value=False)
        self.glib = SimpleNamespace(Source=FakeSource, PRIORITY_DEFAULT_IDLE=200, SOURCE_CONTINUE=True,
                                    MainContext=SimpleNamespace(default=lambda: self.context),
                                    idle_add=self.native_idle_add, source_remove=self.native_remove)
        with patch.object(glib_idle, "needs_idle_queue", return_value=True), \
                patch.dict(sys.modules, {"gi": SimpleNamespace(__version__="3.44.1")}), \
                patch.object(glib_idle, "get_girepository_version", return_value="1.72.0"), \
                patch("xpra.log.Logger") as logger, patch("atexit.register") as register:
            glib_idle.install(self.glib)
            self.log = logger.return_value
            self.destroy = register.call_args.args[0]
        self.source = self.glib._xpra_idle_queue
        self.addCleanup(self.cleanup_source)

    def cleanup_source(self):
        if hasattr(self.source, "__pygi_custom_source"):
            self.destroy()

    def test_install_is_idempotent_and_shutdown_destroys_source(self):
        self.assertIs(self.source.context, self.context)
        self.assertEqual(self.source.priority, 200)
        with patch("atexit.register") as register:
            glib_idle.install(self.glib)
            register.assert_not_called()
        self.assertIs(self.glib._xpra_idle_queue, self.source)
        self.destroy()
        self.assertTrue(self.source.destroyed)
        self.assertTrue(self.source.cleared)
        self.assertFalse(hasattr(self.source, "__pygi_custom_source"))

    def test_prepare_wakeup_and_repeating_callback(self):
        callback = Mock(side_effect=[True, False])
        self.assertEqual(self.source.prepare(), (False, -1))
        sid = self.glib.idle_add(callback, "arg")
        self.assertGreaterEqual(sid, glib_idle.LAST_ID)
        self.context.wakeup.assert_called_once_with()
        self.assertEqual(self.source.prepare(), (True, -1))
        self.assertTrue(self.source.check())
        self.assertTrue(self.source.dispatch(None, None))
        self.assertTrue(self.source.check())
        self.source.dispatch(None, None)
        self.assertFalse(self.source.check())
        self.assertEqual(callback.call_count, 2)
        callback.assert_called_with("arg")

    def test_callback_can_cancel_a_later_callback_in_the_same_dispatch(self):
        later = Mock(return_value=False)

        def cancel_later():
            self.assertTrue(self.glib.source_remove(later_id))
            return False

        self.glib.idle_add(cancel_later)
        later_id = self.glib.idle_add(later)
        self.context.wakeup.assert_called_once_with()
        self.source.dispatch(None, None)
        later.assert_not_called()
        self.assertFalse(self.source.check())
        self.assertFalse(self.glib.source_remove(later_id))
        self.native_remove.assert_called_once_with(later_id)

    def test_new_callbacks_wait_for_next_dispatch_and_exceptions_do_not_stop_others(self):
        later = Mock(return_value=False)

        def add_later():
            self.glib.idle_add(later)
            return False

        self.glib.idle_add(add_later)
        self.glib.idle_add(Mock(side_effect=ValueError("failed")))
        survivor = Mock(return_value=False)
        self.glib.idle_add(survivor)
        self.source.dispatch(None, None)
        later.assert_not_called()
        survivor.assert_called_once_with()
        self.log.error.assert_called_once()
        self.source.dispatch(None, None)
        later.assert_called_once_with()
        self.assertFalse(self.source.check())

    def test_priority_and_native_source_ids_are_forwarded(self):
        callback = Mock()
        self.assertEqual(self.glib.idle_add(callback, "arg", priority=100), 123)
        self.native_idle_add.assert_called_once_with(callback, "arg", priority=100)
        self.assertFalse(self.glib.source_remove(123))
        self.native_remove.assert_called_once_with(123)
        self.assertFalse(self.source.check())

    def test_ids_wrap_and_background_threads_can_queue_callbacks(self):
        self.source.counter = glib_idle.LAST_ID
        first = self.glib.idle_add(lambda: False)
        self.assertEqual(first, glib_idle.FIRST_ID)
        self.assertTrue(self.glib.source_remove(first))
        calls = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(lambda index: self.glib.idle_add(calls.append, index), range(100)))
        self.assertEqual(len(set(ids)), 100)
        self.source.dispatch(None, None)
        self.assertCountEqual(calls, range(100))
        self.assertFalse(self.source.check())

    def test_current_runtime_does_not_install_a_queue(self):
        glib = SimpleNamespace(idle_add=self.native_idle_add, source_remove=self.native_remove)
        with patch.object(glib_idle, "needs_idle_queue", return_value=False):
            glib_idle.install(glib)
        self.assertFalse(hasattr(glib, "_xpra_idle_queue"))
        self.assertIs(glib.idle_add, self.native_idle_add)


class NativeIdleQueueTest(unittest.TestCase):

    def test_real_glib_source_dispatches_without_patching_the_global_module(self):
        try:
            from xpra.os_util import gi_import
            GLib = gi_import("GLib")
        except ImportError:
            self.skipTest("PyGObject is not installed")
        context = GLib.MainContext.new()
        glib = SimpleNamespace(Source=GLib.Source, PRIORITY_DEFAULT_IDLE=GLib.PRIORITY_DEFAULT_IDLE,
                               SOURCE_CONTINUE=GLib.SOURCE_CONTINUE, idle_add=GLib.idle_add, source_remove=GLib.source_remove,
                               MainContext=SimpleNamespace(default=lambda: context))
        original_idle_add = GLib.idle_add
        with patch.object(glib_idle, "needs_idle_queue", return_value=True), \
                patch.object(glib_idle, "get_girepository_version", return_value="1.72.0"), \
                patch("xpra.log.Logger"), patch("atexit.register") as register:
            glib_idle.install(glib)
        try:
            calls = []
            glib.idle_add(calls.append, "dispatched")
            self.assertTrue(context.iteration(False))
            self.assertEqual(calls, ["dispatched"])
            self.assertFalse(glib._xpra_idle_queue.check())
            self.assertIs(GLib.idle_add, original_idle_add)
        finally:
            register.call_args.args[0]()


if __name__ == "__main__":
    unittest.main()
