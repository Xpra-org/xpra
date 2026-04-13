#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# ABOUTME: Tests that nvenc encoder context cleanup always decrements the context
# ABOUTME: counter, even when the CUDA device lock is held by another thread.

"""
Reproduces the nvenc context leak caused by lock contention during cleanup.

The bug: when threaded_clean() runs while compress_image() holds the CUDA
device lock, do_clean()'s non-blocking lock acquisition fails. Because
do_clean() is `cdef void` without exception handling, the exception is
silently swallowed and context_counter is never decremented.
"""

import unittest
import threading
import time
import warnings


class AtomicCounter:
    """Simplified version of xpra's AtomicInteger for testing."""
    def __init__(self, value=0):
        self._value = value
        self._lock = threading.Lock()

    def get(self):
        return self._value

    def increase(self):
        with self._lock:
            self._value += 1

    def decrease(self):
        with self._lock:
            self._value -= 1


class TransientCodecException(Exception):
    pass


class FakeCudaContext:
    """Simulates PyCUDA context push/pop."""
    def push(self):
        pass

    def pop(self):
        pass


class FakeCudaDeviceContext:
    """
    Simulates xpra's cuda_device_context with the same non-blocking
    lock behavior that causes the bug.
    """
    def __init__(self):
        self.lock = threading.RLock()
        self.context = FakeCudaContext()

    def __enter__(self):
        if not self.lock.acquire(False):
            raise TransientCodecException("failed to acquire cuda device lock")
        self.context.push()
        return self.context

    def __exit__(self, *args):
        self.context.pop()
        self.lock.release()


class FakeNvencEncoder:
    """
    Simulates the nvenc Encoder's cleanup flow, mirroring the actual
    cdef void do_clean() / cuda_clean() behavior from encoder.pyx.
    """
    def __init__(self, context_counter, cuda_device_context):
        self.context_counter = context_counter
        self.cuda_device_context = cuda_device_context
        self.context_active = True  # simulates self.context != NULL
        self.closed = False
        self.threaded_init = True
        self.cleanup_errors = []

    def open_session(self):
        """Simulate opening an NVENC encoding session."""
        self.context_counter.increase()
        self.context_active = True

    def do_clean_BUGGY(self):
        """
        Reproduces the buggy cdef void do_clean() behavior.
        When the lock is held, the TransientCodecException from `with cdc:`
        is silently swallowed by Cython's cdef void — cuda_clean() never runs.

        We simulate the Cython cdef void behavior by catching and suppressing
        the exception (with a warning, as Cython does).
        """
        cdc = self.cuda_device_context
        if cdc:
            try:
                with cdc:
                    self.cuda_clean()
                    self.cuda_device_context = None
            except Exception:
                # Cython silently swallows exceptions from cdef void methods.
                # cuda_clean() never ran, counter never decremented.
                warnings.warn("module in out-of-thread context could not be cleaned up",
                              UserWarning, stacklevel=1)
                return

    def do_clean_FIXED(self):
        """
        Fixed cleanup: uses blocking lock acquisition with timeout,
        and has a fallback to decrement the counter if the lock times out.
        """
        cdc = self.cuda_device_context
        if cdc:
            if not cdc.lock.acquire(timeout=5):
                self._force_context_release()
                self.cuda_device_context = None
            else:
                try:
                    if cdc.context:
                        cdc.context.push()
                    try:
                        self.cuda_clean()
                    finally:
                        if cdc.context:
                            cdc.context.pop()
                    self.cuda_device_context = None
                finally:
                    cdc.lock.release()

    def _force_context_release(self):
        """Fallback: decrement counter without proper NVENC API cleanup."""
        if self.context_active:
            self.context_active = False
            self.context_counter.decrease()

    def cuda_clean(self):
        """Simulates cuda_clean() — must always decrement the counter."""
        if self.context_active:
            try:
                # Simulate NVENC API calls (nvEncDestroyBitstreamBuffer, etc.)
                pass
            finally:
                self.context_active = False
                self.context_counter.decrease()

    def clean(self, use_fixed=False):
        """Simulates clean() — sets closed flag and runs cleanup."""
        if not self.closed:
            self.closed = True
            do_clean = self.do_clean_FIXED if use_fixed else self.do_clean_BUGGY
            if self.threaded_init:
                t = threading.Thread(target=do_clean, daemon=True)
                t.start()
                t.join(timeout=10)
            else:
                do_clean()


class TestNvencContextCleanup(unittest.TestCase):
    """Tests for nvenc encoder context cleanup under lock contention."""

    def test_cleanup_without_contention(self):
        """Baseline: cleanup works when no lock contention."""
        counter = AtomicCounter()
        cdc = FakeCudaDeviceContext()
        encoder = FakeNvencEncoder(counter, cdc)

        encoder.open_session()
        self.assertEqual(counter.get(), 1)

        encoder.clean(use_fixed=False)
        self.assertEqual(counter.get(), 0, "Counter should be 0 after clean without contention")

    def test_buggy_cleanup_leaks_under_contention(self):
        """
        Demonstrates the bug: when the CUDA lock is held by another thread
        (simulating compress_image()), the buggy cleanup silently fails and
        the context counter is never decremented.

        The contention is cross-thread (RLock allows same-thread reentrance).
        """
        counter = AtomicCounter()
        cdc = FakeCudaDeviceContext()
        encoder = FakeNvencEncoder(counter, cdc)

        encoder.open_session()
        self.assertEqual(counter.get(), 1)

        # Simulate encode thread holding the lock (as during compress_image)
        lock_acquired = threading.Event()
        can_release = threading.Event()

        def hold_lock():
            cdc.lock.acquire()
            lock_acquired.set()
            can_release.wait(timeout=10)
            cdc.lock.release()

        holder = threading.Thread(target=hold_lock)
        holder.start()
        lock_acquired.wait()

        # Run buggy cleanup in a separate thread (as threaded_clean does)
        cleanup_done = threading.Event()

        def run_cleanup():
            encoder.do_clean_BUGGY()
            cleanup_done.set()

        cleaner = threading.Thread(target=run_cleanup, daemon=True)
        cleaner.start()
        cleaner.join(timeout=2)

        # The counter was NOT decremented — this is the bug
        self.assertEqual(counter.get(), 1,
                         "Buggy cleanup leaks: counter still 1 after failed cleanup")

        # Release the lock and clean up the holder thread
        can_release.set()
        holder.join(timeout=5)

    def test_fixed_cleanup_succeeds_under_contention(self):
        """
        The fix: blocking lock acquisition waits for the encode thread
        to finish, then cleans up properly.
        """
        counter = AtomicCounter()
        cdc = FakeCudaDeviceContext()
        encoder = FakeNvencEncoder(counter, cdc)

        encoder.open_session()
        self.assertEqual(counter.get(), 1)

        # Hold the lock briefly, then release (simulating compress_image finishing)
        lock_held = threading.Event()
        lock_released = threading.Event()

        def hold_lock_briefly():
            cdc.lock.acquire()
            lock_held.set()
            time.sleep(0.1)  # simulate encode time
            cdc.lock.release()
            lock_released.set()

        holder = threading.Thread(target=hold_lock_briefly)
        holder.start()
        lock_held.wait()

        # Start cleanup — should block until the lock is released
        cleanup_done = threading.Event()
        cleanup_error = []

        def do_cleanup():
            try:
                encoder.do_clean_FIXED()
            except Exception as e:
                cleanup_error.append(e)
            cleanup_done.set()

        cleaner = threading.Thread(target=do_cleanup)
        cleaner.start()
        cleaner.join(timeout=5)
        holder.join(timeout=5)

        self.assertFalse(cleanup_error, f"Cleanup should not raise: {cleanup_error}")
        self.assertEqual(counter.get(), 0,
                         "Fixed cleanup should always decrement counter")

    def test_fixed_cleanup_threaded_under_contention(self):
        """
        Full integration: simulate the threaded cleanup path with lock contention.
        """
        counter = AtomicCounter()
        cdc = FakeCudaDeviceContext()
        encoder = FakeNvencEncoder(counter, cdc)

        encoder.open_session()
        self.assertEqual(counter.get(), 1)

        # Hold the lock briefly (simulating concurrent compress_image)
        def hold_lock_briefly():
            cdc.lock.acquire()
            time.sleep(0.05)
            cdc.lock.release()

        holder = threading.Thread(target=hold_lock_briefly)
        holder.start()
        time.sleep(0.01)  # let the holder acquire the lock first

        # Run the full clean() with threaded_init=True (starts daemon thread)
        encoder.clean(use_fixed=True)
        holder.join(timeout=5)

        self.assertEqual(counter.get(), 0,
                         "Threaded cleanup should decrement counter even under contention")

    def test_multiple_encoder_lifecycle(self):
        """
        Simulate multiple encoders being created and destroyed (as happens
        when pipeline scoring changes). Each encoder should clean up properly.
        """
        counter = AtomicCounter()
        cdc = FakeCudaDeviceContext()
        num_cycles = 10

        for i in range(num_cycles):
            encoder = FakeNvencEncoder(counter, cdc)
            encoder.open_session()

            # Simulate some contention on half the cycles
            if i % 2 == 0:
                def hold_and_release():
                    cdc.lock.acquire()
                    time.sleep(0.01)
                    cdc.lock.release()
                holder = threading.Thread(target=hold_and_release)
                holder.start()
                time.sleep(0.005)
                encoder.clean(use_fixed=True)
                holder.join(timeout=5)
            else:
                encoder.clean(use_fixed=True)

        self.assertEqual(counter.get(), 0,
                         f"After {num_cycles} create/destroy cycles, counter should be 0")


if __name__ == "__main__":
    unittest.main()
