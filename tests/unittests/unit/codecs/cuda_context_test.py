#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from threading import Event, RLock, Thread
from unittest.mock import Mock

try:
    from xpra.codecs.nvidia.cuda_context import cuda_device_context
except ImportError:
    cuda_device_context = None


@unittest.skipUnless(cuda_device_context, "PyCUDA is not available")
class TestCudaContext(unittest.TestCase):

    def test_free_waits_for_context_to_be_popped(self):
        waiting = Event()

        class ObservedLock:
            def __init__(self):
                self.lock = RLock()

            def acquire(self, *args):
                return self.lock.acquire(*args)

            def release(self):
                self.lock.release()

            def __enter__(self):
                waiting.set()
                self.lock.acquire()

            def __exit__(self, *_args):
                self.lock.release()

        context = Mock()
        device_context = cuda_device_context(1, Mock())
        device_context.context = context
        device_context.lock = ObservedLock()
        errors = []

        def free():
            try:
                device_context.free()
            except Exception as exc:
                errors.append(exc)

        worker = Thread(target=free, daemon=True)
        try:
            with device_context as pushed:
                self.assertIs(pushed, context)
                worker.start()
                self.assertTrue(waiting.wait(5), "free() did not try to acquire the lock")
                self.assertIs(device_context.context, context)
                context.detach.assert_not_called()
        finally:
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        context.push.assert_called_once_with()
        context.pop.assert_called_once_with()
        context.detach.assert_called_once_with()
        self.assertIsNone(device_context.context)
        self.assertIsNone(device_context.device)
        device_context.free()
        context.detach.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
