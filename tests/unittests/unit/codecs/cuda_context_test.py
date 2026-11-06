#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from threading import Event, Thread
from unittest.mock import Mock

from xpra.codecs.constants import TransientCodecException

try:
    from xpra.codecs.nvidia.cuda import context
except ImportError:
    context = None


@unittest.skipIf(context is None, "PyCUDA is not available")
class TestCUDAContext(unittest.TestCase):

    def make_context(self, initialized=False):
        device = Mock()
        cuda_context = Mock()
        device.make_context.return_value = cuda_context
        cdc = context.cuda_device_context(0, device)
        if initialized:
            cdc.context = cuda_context
        self.addCleanup(cdc.free)
        return cdc, device, cuda_context

    def assert_lock_available(self, cdc, expected=True):
        # RLock is reentrant, so acquisition must be checked from another thread.
        results = []

        def acquire():
            acquired = cdc.lock.acquire(False)
            if acquired:
                cdc.lock.release()
            results.append(acquired)

        thread = Thread(target=acquire, daemon=True)
        thread.start()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results, [expected])

    def test_enter_failure_releases_lock(self):
        for operation in ("creation", "initial-pop", "push"):
            for error_type in (RuntimeError, KeyboardInterrupt):
                with self.subTest(operation=operation, error_type=error_type):
                    cdc, device, cuda_context = self.make_context(initialized=operation == "push")
                    error = error_type(operation)
                    if operation == "creation":
                        device.make_context.side_effect = error
                    elif operation == "initial-pop":
                        cuda_context.pop.side_effect = error
                    else:
                        cuda_context.push.side_effect = error
                    with self.assertRaises(error_type) as caught:
                        with cdc:
                            self.fail("entered a failed context")
                    self.assertIs(caught.exception, error)
                    self.assert_lock_available(cdc)

    def test_exit_failure_releases_lock(self):
        for error_type in (RuntimeError, KeyboardInterrupt):
            with self.subTest(error_type=error_type):
                cdc, _, cuda_context = self.make_context(initialized=True)
                error = error_type("pop failed")
                cuda_context.pop.side_effect = error
                with self.assertRaises(error_type) as caught:
                    with cdc:
                        pass
                self.assertIs(caught.exception, error)
                self.assert_lock_available(cdc)

    def test_body_failure_releases_lock(self):
        cdc, _, cuda_context = self.make_context(initialized=True)
        error = RuntimeError("body failed")
        with self.assertRaises(RuntimeError) as caught:
            with cdc:
                raise error
        self.assertIs(caught.exception, error)
        cuda_context.pop.assert_called_once_with()
        self.assert_lock_available(cdc)

    def test_normal_entry_and_exit(self):
        cdc, device, cuda_context = self.make_context()
        with cdc as current:
            self.assertIs(current, cuda_context)
            self.assert_lock_available(cdc, False)
        self.assert_lock_available(cdc)
        device.make_context.assert_called_once()
        cuda_context.push.assert_called_once_with()
        self.assertEqual(cuda_context.pop.call_count, 2)

    def test_failed_nested_entry_keeps_outer_lock(self):
        cdc, _, cuda_context = self.make_context(initialized=True)
        with cdc:
            cuda_context.push.side_effect = RuntimeError("nested push failed")
            with self.assertRaisesRegex(RuntimeError, "nested push failed"):
                with cdc:
                    self.fail("entered a failed context")
            self.assert_lock_available(cdc, False)
        self.assert_lock_available(cdc)

    def test_busy_context_is_skipped(self):
        cdc, device, cuda_context = self.make_context()
        ready = Event()
        release = Event()

        def hold_lock():
            with cdc.lock:
                ready.set()
                release.wait(5)

        thread = Thread(target=hold_lock, daemon=True)
        thread.start()
        try:
            self.assertTrue(ready.wait(5))
            with self.assertRaises(TransientCodecException):
                with cdc:
                    self.fail("entered a busy context")
            device.make_context.assert_not_called()
            cuda_context.push.assert_not_called()
        finally:
            release.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assert_lock_available(cdc)


if __name__ == "__main__":
    unittest.main()
