#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# ABOUTME: Tests for the generic DecoderPool at xpra/codecs/decoder_pool.py.
# ABOUTME: Uses stub create/reset/destroy callables; no hardware or Cython.

import threading
import time
import unittest

from xpra.codecs.decoder_pool import DecoderPool


class Handle:
    """Opaque handle returned by the stub create_fn."""

    def __init__(self, W, H, key):
        self.W = W
        self.H = H
        self.key = key
        self.destroyed = False
        self.reset_count = 0


class StubCodec:
    """
    Stub create/reset/destroy callables.

    Tests configure behavior (e.g. reset_should_fail) and inspect counters.
    """

    def __init__(self):
        self.create_count = 0
        self.reset_count = 0
        self.destroy_count = 0
        self.reset_should_fail = False
        self.create_should_fail = False
        self.create_delay_s = 0.0
        self._lock = threading.Lock()

    def create(self, W, H, key):
        with self._lock:
            self.create_count += 1
        if self.create_delay_s:
            time.sleep(self.create_delay_s)
        if self.create_should_fail:
            raise RuntimeError("create failed")
        return Handle(W, H, key)

    def reset(self, handle, W, H, key):
        with self._lock:
            self.reset_count += 1
        if self.reset_should_fail:
            raise RuntimeError("reset failed")
        handle.W = W
        handle.H = H
        handle.key = key
        handle.reset_count += 1

    def destroy(self, handle):
        with self._lock:
            self.destroy_count += 1
        handle.destroyed = True


class SyncScheduler:
    """Test scheduler that runs work items synchronously in the caller's thread."""

    def __init__(self):
        self.submitted: list = []

    def __call__(self, callable_, daemon=False):
        self.submitted.append((callable_, daemon))
        callable_()


class DeferredScheduler:
    """Test scheduler that collects work items without running them; tests
    drain the queue explicitly."""

    def __init__(self):
        self.pending: list = []

    def __call__(self, callable_, daemon=False):
        self.pending.append((callable_, daemon))

    def drain(self):
        while self.pending:
            item, _daemon = self.pending.pop(0)
            item()


def make_pool(stub=None, scheduler=None, target_size=4, idle_timeout_s=60.0):
    stub = stub or StubCodec()
    scheduler = scheduler or SyncScheduler()
    pool = DecoderPool(
        name="stub",
        create_fn=stub.create,
        reset_fn=stub.reset,
        destroy_fn=stub.destroy,
        target_size=target_size,
        idle_timeout_s=idle_timeout_s,
        work_scheduler=scheduler,
    )
    return pool, stub, scheduler


class TestDecoderPool(unittest.TestCase):

    def test_acquire_on_empty_pool_creates(self):
        pool, stub, _ = make_pool()
        slot = pool.acquire(1920, 1080, "key")
        self.assertEqual(stub.create_count, 1)
        self.assertEqual(stub.reset_count, 0)
        self.assertTrue(slot.in_use)
        self.assertEqual(slot.max_W, 1920)
        self.assertEqual(slot.max_H, 1080)
        self.assertEqual(slot.key, "key")

    def test_release_returns_to_pool_and_updates_last_used(self):
        pool, _, _ = make_pool()
        slot = pool.acquire(1920, 1080, "k")
        before = slot.last_used
        time.sleep(0.001)
        pool.release(slot)
        self.assertFalse(slot.in_use)
        self.assertGreater(slot.last_used, before)
        self.assertIn(slot, pool._slots)

    def test_second_acquire_same_key_fits_hits_cache(self):
        pool, stub, _ = make_pool()
        slot = pool.acquire(1920, 1080, "k")
        pool.release(slot)
        slot2 = pool.acquire(1920, 1080, "k")
        self.assertIs(slot, slot2)
        self.assertEqual(stub.create_count, 1)
        self.assertEqual(stub.reset_count, 1)

    def test_acquire_smaller_dims_fits_same_slot(self):
        pool, stub, _ = make_pool()
        slot = pool.acquire(1920, 1080, "k")
        pool.release(slot)
        slot2 = pool.acquire(1280, 720, "k")
        self.assertIs(slot, slot2)
        self.assertEqual(stub.create_count, 1)
        self.assertEqual(stub.reset_count, 1)
        # Cached slot retains the max dims so later larger requests in the
        # range still fit.
        self.assertEqual(slot2.max_W, 1920)
        self.assertEqual(slot2.max_H, 1080)

    def test_allow_grow_prewarm_not_suppressed_by_smaller_slot(self):
        """With allow_grow, a small idle slot must NOT suppress a larger
        prewarm — the whole point of the fullscreen prewarm is to have a
        fullscreen-sized slot ready on first use."""
        stub = StubCodec()
        sched = DeferredScheduler()
        pool = DecoderPool(
            name="stub",
            create_fn=stub.create,
            reset_fn=stub.reset,
            destroy_fn=stub.destroy,
            target_size=4,
            idle_timeout_s=60.0,
            work_scheduler=sched,
            allow_grow=True,
        )
        # Seed a small idle slot.
        small = pool.acquire(1280, 720, "k")
        pool.release(small)
        # Prewarm fullscreen. In allow_grow mode the small slot "fits"
        # under fits(), but it does NOT cover, so prewarm must proceed.
        pool.prewarm(2880, 1800, "k")
        sched.drain()
        self.assertEqual(stub.create_count, 2,
                         "prewarm must create the larger slot")

    def test_allow_grow_prewarm_not_superseded_by_smaller_slot(self):
        """The supersede check at the end of _do_prewarm must use cover,
        not fits — otherwise the just-built fullscreen slot is detached
        and destroyed because a smaller slot happens to exist."""
        stub = StubCodec()
        sched = DeferredScheduler()
        pool = DecoderPool(
            name="stub",
            create_fn=stub.create,
            reset_fn=stub.reset,
            destroy_fn=stub.destroy,
            target_size=4,
            idle_timeout_s=60.0,
            work_scheduler=sched,
            allow_grow=True,
        )
        pool.prewarm(2880, 1800, "k")
        # Before the prewarm task runs, a small slot materializes.
        small = pool.acquire(1280, 720, "k")
        pool.release(small)
        # Drain the prewarm: its new fullscreen slot must stay, not be
        # detached-and-destroyed in favor of the smaller slot.
        sched.drain()
        self.assertEqual(stub.destroy_count, 0)
        self.assertEqual(len(pool._slots), 2)

    def test_allow_grow_prefers_covering_slot_over_smaller(self):
        """With allow_grow, a prewarmed fullscreen slot shouldn't be
        bypassed by an older smaller slot — the covering slot is free
        to serve, while the smaller one would have to grow."""
        stub = StubCodec()
        pool = DecoderPool(
            name="stub",
            create_fn=stub.create,
            reset_fn=stub.reset,
            destroy_fn=stub.destroy,
            target_size=4,
            idle_timeout_s=60.0,
            work_scheduler=SyncScheduler(),
            allow_grow=True,
        )
        # Seed: an older small slot, then a larger "prewarmed" slot.
        small = pool.acquire(1280, 720, "k")
        big = pool.acquire(2880, 1800, "k")
        pool.release(small)
        pool.release(big)
        # Request 1920x1080: small needs to grow, big covers it.
        picked = pool.acquire(1920, 1080, "k")
        self.assertIs(picked, big,
                      "must prefer the covering slot over a smaller one")

    def test_allow_grow_reuses_slot_for_larger_dims(self):
        """With allow_grow=True, an idle slot serves a LARGER request via
        reset (used by oneVPL where Close+Init can reallocate)."""
        stub = StubCodec()
        pool = DecoderPool(
            name="stub",
            create_fn=stub.create,
            reset_fn=stub.reset,
            destroy_fn=stub.destroy,
            target_size=4,
            idle_timeout_s=60.0,
            work_scheduler=SyncScheduler(),
            allow_grow=True,
        )
        slot = pool.acquire(1280, 720, "k")
        pool.release(slot)
        slot2 = pool.acquire(1920, 1080, "k")
        self.assertIs(slot, slot2)
        self.assertEqual(stub.create_count, 1)
        self.assertEqual(stub.reset_count, 1)
        # Envelope grows to the larger request.
        self.assertEqual(slot2.max_W, 1920)
        self.assertEqual(slot2.max_H, 1080)

    def test_acquire_larger_dims_miss(self):
        pool, stub, _ = make_pool()
        slot = pool.acquire(1280, 720, "k")
        pool.release(slot)
        slot2 = pool.acquire(1920, 1080, "k")
        self.assertIsNot(slot, slot2)
        self.assertEqual(stub.create_count, 2)

    def test_acquire_different_key_miss(self):
        pool, stub, _ = make_pool()
        slot = pool.acquire(1920, 1080, "k1")
        pool.release(slot)
        slot2 = pool.acquire(1920, 1080, "k2")
        self.assertIsNot(slot, slot2)
        self.assertEqual(stub.create_count, 2)

    def test_smallest_fit_preferred(self):
        pool, stub, _ = make_pool()
        big = pool.acquire(1920, 1080, "k")
        small = pool.acquire(1280, 720, "k")
        pool.release(big)
        pool.release(small)
        # Request 1000x700: both fit; smallest-fit picks `small`.
        picked = pool.acquire(1000, 700, "k")
        self.assertIs(picked, small)

    def test_reset_failure_destroys_and_retries_then_creates(self):
        stub = StubCodec()
        pool, _, sched = make_pool(stub=stub)
        slot = pool.acquire(1920, 1080, "k")
        pool.release(slot)
        stub.reset_should_fail = True
        slot2 = pool.acquire(1920, 1080, "k")
        # Failed reset: original slot destroyed, new slot created.
        self.assertIsNot(slot, slot2)
        self.assertEqual(stub.destroy_count, 1)
        self.assertEqual(stub.create_count, 2)
        self.assertTrue(slot.handle.destroyed)

    def test_reset_failure_destroys_synchronously_before_retry(self):
        """Hardware codecs with tight session/decoder limits need the
        failed handle to be freed BEFORE the retry create fires. Verify
        destroy happens synchronously, not via the deferred worker."""
        stub = StubCodec()
        sched = DeferredScheduler()  # won't run anything until drain
        pool, _, _ = make_pool(stub=stub, scheduler=sched)
        slot = pool.acquire(1920, 1080, "k")
        pool.release(slot)
        stub.reset_should_fail = True
        slot2 = pool.acquire(1920, 1080, "k")
        # Destroy must have run synchronously before acquire returned;
        # the scheduler queue must be empty for the destroy.
        self.assertEqual(stub.destroy_count, 1)
        self.assertTrue(slot.handle.destroyed)
        self.assertEqual(len(sched.pending), 0,
                         "destroy must be synchronous, not scheduled")
        self.assertIsNot(slot, slot2)

    def test_reset_failure_depth_guarded(self):
        """If reset keeps failing, we shouldn't infinite-loop."""
        stub = StubCodec()
        pool, _, _ = make_pool(stub=stub)
        # Seed two slots for same key+fit.
        a = pool.acquire(1920, 1080, "k")
        b = pool.acquire(1920, 1080, "k")
        pool.release(a)
        pool.release(b)
        stub.reset_should_fail = True
        # Must terminate, not recurse indefinitely.
        fresh = pool.acquire(1920, 1080, "k")
        self.assertTrue(fresh.in_use)
        # At most one reset-failure retry before create.
        self.assertLessEqual(stub.reset_count, 2)

    def test_concurrent_acquires_unique_slots(self):
        stub = StubCodec()
        stub.create_delay_s = 0.01  # widen the create window
        pool, _, _ = make_pool(stub=stub)
        slots = []
        errors = []
        lock = threading.Lock()

        def worker():
            try:
                s = pool.acquire(1920, 1080, "k")
                with lock:
                    slots.append(s)
            except Exception as e:  # pylint: disable=broad-except
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(slots), 8)
        self.assertEqual(len(set(id(s) for s in slots)), 8)
        for s in slots:
            self.assertTrue(s.in_use)

    def test_pool_grows_past_target_size(self):
        pool, stub, _ = make_pool(target_size=2)
        a = pool.acquire(1920, 1080, "k")
        b = pool.acquire(1920, 1080, "k")
        c = pool.acquire(1920, 1080, "k")  # exceeds target
        self.assertEqual(stub.create_count, 3)
        pool.release(a)
        pool.release(b)
        pool.release(c)
        # All three remain in pool; reaper handles trim, not release.
        self.assertEqual(len(pool._slots), 3)

    def test_reaper_prunes_idle_past_timeout(self):
        pool, stub, sched = make_pool(idle_timeout_s=0.01)
        a = pool.acquire(1920, 1080, "k")
        pool.release(a)
        time.sleep(0.02)
        pool.reap()
        self.assertEqual(len(pool._slots), 0)
        self.assertEqual(stub.destroy_count, 1)

    def test_reaper_keeps_in_use_slots_regardless_of_age(self):
        pool, stub, _ = make_pool(idle_timeout_s=0.01)
        a = pool.acquire(1920, 1080, "k")
        # `a` is in_use; never eligible for reap.
        time.sleep(0.02)
        pool.reap()
        self.assertEqual(len(pool._slots), 1)
        self.assertEqual(stub.destroy_count, 0)

    def test_reaper_trims_over_target(self):
        pool, stub, _ = make_pool(target_size=2, idle_timeout_s=3600.0)
        a = pool.acquire(1920, 1080, "k")
        b = pool.acquire(1920, 1080, "k")
        c = pool.acquire(1920, 1080, "k")
        pool.release(a)
        pool.release(b)
        pool.release(c)
        pool.reap()
        # Idle timeout not reached, but over-target trim to 2 applies.
        self.assertEqual(len(pool._slots), 2)
        self.assertEqual(stub.destroy_count, 1)

    def test_reaper_over_target_does_not_trim_in_use(self):
        pool, stub, _ = make_pool(target_size=1, idle_timeout_s=3600.0)
        a = pool.acquire(1920, 1080, "k")  # in use
        b = pool.acquire(1920, 1080, "k")
        pool.release(b)
        # Target is 1 and pool has 2. `a` is in_use, `b` is idle.
        pool.reap()
        # Only `b` can be trimmed.
        self.assertEqual(len(pool._slots), 1)
        self.assertIn(a, pool._slots)
        self.assertEqual(stub.destroy_count, 1)

    def test_prewarm_creates_idle_slot_usable_on_next_acquire(self):
        stub = StubCodec()
        sched = DeferredScheduler()
        pool, _, _ = make_pool(stub=stub, scheduler=sched)
        pool.prewarm(1920, 1080, "k")
        self.assertEqual(stub.create_count, 0)
        sched.drain()
        self.assertEqual(stub.create_count, 1)
        self.assertEqual(len(pool._slots), 1)
        slot = pool.acquire(1920, 1080, "k")
        self.assertEqual(stub.create_count, 1)  # hit, not miss
        self.assertEqual(stub.reset_count, 1)
        self.assertTrue(slot.in_use)

    def test_prewarm_deduplicates(self):
        stub = StubCodec()
        sched = DeferredScheduler()
        pool, _, _ = make_pool(stub=stub, scheduler=sched)
        pool.prewarm(1920, 1080, "k")
        pool.prewarm(1920, 1080, "k")  # same key+dims; deduped
        self.assertEqual(len(sched.pending), 1)
        sched.drain()
        self.assertEqual(stub.create_count, 1)

    def test_shutdown_destroys_all_and_falls_through(self):
        pool, stub, _ = make_pool()
        a = pool.acquire(1920, 1080, "k1")
        pool.release(a)
        b = pool.acquire(1280, 720, "k2")
        pool.release(b)
        self.assertEqual(len(pool._slots), 2)
        pool.shutdown()
        self.assertEqual(stub.destroy_count, 2)
        self.assertEqual(len(pool._slots), 0)
        # After shutdown: acquire goes direct (no pooling).
        c = pool.acquire(800, 600, "k")
        self.assertEqual(stub.create_count, 3)
        self.assertEqual(len(pool._slots), 0)
        pool.release(c)
        # Direct path destroys on release.
        self.assertEqual(stub.destroy_count, 3)

    def test_shutdown_leaves_in_use_slots_until_release(self):
        pool, stub, _ = make_pool()
        held = pool.acquire(1920, 1080, "k")
        idle = pool.acquire(1280, 720, "k2")
        pool.release(idle)
        # shutdown: `held` is still in use, must NOT be destroyed yet;
        # `idle` goes down synchronously.
        pool.shutdown()
        self.assertEqual(stub.destroy_count, 1)
        self.assertFalse(held.handle.destroyed)
        self.assertTrue(idle.handle.destroyed)
        # Releasing the held slot after shutdown destroys it (no double-destroy).
        pool.release(held)
        self.assertEqual(stub.destroy_count, 2)
        self.assertTrue(held.handle.destroyed)

    def test_post_shutdown_release_destroys_synchronously(self):
        """After shutdown the background worker may be stopping; release of
        an in-use slot must not enqueue the destroy behind the worker
        sentinel (where it would leak)."""
        stub = StubCodec()
        sched = DeferredScheduler()  # never drained — proves no schedule
        pool, _, _ = make_pool(stub=stub, scheduler=sched)
        held = pool.acquire(1920, 1080, "k")
        pool.shutdown()
        pool.release(held)
        self.assertTrue(held.handle.destroyed)
        self.assertEqual(stub.destroy_count, 1)
        self.assertEqual(len(sched.pending), 0)

    def test_prewarm_superseded_by_acquire_does_not_duplicate(self):
        stub = StubCodec()
        sched = DeferredScheduler()
        pool, _, _ = make_pool(stub=stub, scheduler=sched)
        pool.prewarm(1920, 1080, "k")
        # Real acquire races ahead of the queued prewarm and creates its own
        # slot, then releases it.
        real = pool.acquire(1920, 1080, "k")
        pool.release(real)
        # Now drain the prewarm: its handle should be detached + destroyed,
        # not appended as a duplicate idle slot.
        sched.drain()
        self.assertEqual(len(pool._slots), 1)
        self.assertEqual(stub.create_count, 2)  # real + prewarm
        # drain() ran the prewarm create AND the subsequent schedule_destroy
        # (SyncScheduler semantics). Actually DeferredScheduler defers the
        # destroy too; drain one more round.
        sched.drain()
        self.assertEqual(stub.destroy_count, 1)

    def test_prewarm_skips_when_idle_slot_already_fits(self):
        """Opportunistic prewarm after release shouldn't create a second
        decoder when the pool already has an idle one that fits."""
        stub = StubCodec()
        sched = DeferredScheduler()
        pool, _, _ = make_pool(stub=stub, scheduler=sched)
        slot = pool.acquire(1920, 1080, "k")
        pool.release(slot)
        self.assertEqual(stub.create_count, 1)
        pool.prewarm(1920, 1080, "k")
        self.assertEqual(len(sched.pending), 0)
        sched.drain()
        self.assertEqual(stub.create_count, 1)

    def test_prewarm_tuple_key_accepted(self):
        """Tuple keys (a common real-world key type like
        (profile, bit_depth)) work for prewarm."""
        stub = StubCodec()
        sched = DeferredScheduler()
        pool, _, _ = make_pool(stub=stub, scheduler=sched)
        pool.prewarm(1920, 1080, ("rext", 10))
        sched.drain()
        self.assertEqual(stub.create_count, 1)
        slot = pool.acquire(1920, 1080, ("rext", 10))
        self.assertEqual(stub.create_count, 1)
        self.assertTrue(slot.in_use)

    def test_prewarm_skips_create_if_shutdown_before_pickup(self):
        """Prewarm queued, then shutdown before worker picks up: skip the
        expensive create — the handle would be torn down anyway."""
        stub = StubCodec()
        sched = DeferredScheduler()
        pool, _, _ = make_pool(stub=stub, scheduler=sched)
        pool.prewarm(1920, 1080, "k")
        self.assertEqual(len(sched.pending), 1)
        pool.shutdown()
        sched.drain()
        self.assertEqual(stub.create_count, 0)
        self.assertEqual(stub.destroy_count, 0)

    def test_prewarm_uses_daemon_scheduling_destroy_does_not(self):
        """Destroys are mandatory (daemon=False) so shutdown drains them.
        Prewarms are speculative (daemon=True) so force-stop drops them."""
        stub = StubCodec()
        sched = DeferredScheduler()
        pool, _, _ = make_pool(stub=stub, scheduler=sched)
        pool.prewarm(1920, 1080, "k")
        # First queued task is the prewarm.
        _item, daemon = sched.pending[0]
        self.assertTrue(daemon, "prewarm must be scheduled with daemon=True")
        sched.drain()
        # After prewarm ran, a destroy could be queued (supersession check
        # is a no-op here so nothing queued). Force a destroy:
        slot = pool.acquire(1920, 1080, "k")
        pool.release(slot)
        # Evict by over-target reap to queue a destroy.
        pool.target_size = 0
        pool.reap()
        self.assertTrue(sched.pending, "reap should queue a destroy")
        _item, daemon = sched.pending[-1]
        self.assertFalse(daemon, "destroy must be scheduled with daemon=False")

    def test_shutdown_waits_for_queued_destroys(self):
        """shutdown() must wait for destroys already queued by release()
        or reap() so consumers can safely tear down runtime state after
        shutdown() returns."""
        import threading as _th
        stub = StubCodec()
        destroy_started = _th.Event()
        destroy_can_finish = _th.Event()
        orig_destroy = stub.destroy

        def blocking_destroy(handle):
            destroy_started.set()
            destroy_can_finish.wait(timeout=5.0)
            orig_destroy(handle)
        stub.destroy = blocking_destroy

        def thread_scheduler(item, daemon=False):
            t = _th.Thread(target=item, daemon=True)
            t.start()
        pool = DecoderPool(
            name="stub",
            create_fn=stub.create,
            reset_fn=stub.reset,
            destroy_fn=stub.destroy,
            target_size=0,  # any release triggers reap-style evict behavior
            idle_timeout_s=60.0,
            work_scheduler=thread_scheduler,
        )
        pool.PREWARM_DRAIN_TIMEOUT_S = 2.0
        slot = pool.acquire(1920, 1080, "k")
        pool.release(slot)
        pool.reap()
        self.assertTrue(destroy_started.wait(timeout=1.0))

        shutdown_done = _th.Event()

        def do_shutdown():
            pool.shutdown()
            shutdown_done.set()
        t = _th.Thread(target=do_shutdown, daemon=True)
        t.start()
        self.assertFalse(shutdown_done.wait(timeout=0.1),
                         "shutdown should block on queued destroy")
        destroy_can_finish.set()
        self.assertTrue(shutdown_done.wait(timeout=3.0),
                        "shutdown should complete after destroy finishes")
        t.join(timeout=1.0)

    def test_shutdown_waits_for_in_flight_prewarm(self):
        """shutdown() must wait for an in-flight prewarm create so the
        caller can safely tear down shared device state afterward."""
        stub = StubCodec()
        import threading as _th
        started = _th.Event()
        can_finish = _th.Event()
        orig_create = stub.create

        def blocking_create(W, H, key):
            started.set()
            can_finish.wait(timeout=5.0)
            return orig_create(W, H, key)
        stub.create = blocking_create

        # Use a real thread scheduler — not synchronous — so prewarm runs
        # concurrently with shutdown().
        def thread_scheduler(item, daemon=False):
            t = _th.Thread(target=item, daemon=True)
            t.start()
        pool = DecoderPool(
            name="stub",
            create_fn=stub.create,
            reset_fn=stub.reset,
            destroy_fn=stub.destroy,
            target_size=4,
            idle_timeout_s=60.0,
            work_scheduler=thread_scheduler,
        )
        pool.PREWARM_DRAIN_TIMEOUT_S = 2.0
        pool.prewarm(1920, 1080, "k")
        self.assertTrue(started.wait(timeout=1.0),
                        "prewarm thread should start")

        shutdown_done = _th.Event()

        def do_shutdown():
            pool.shutdown()
            shutdown_done.set()
        t = _th.Thread(target=do_shutdown, daemon=True)
        t.start()
        # shutdown must NOT have returned yet — prewarm is still blocked.
        self.assertFalse(shutdown_done.wait(timeout=0.1),
                         "shutdown should block on in-flight prewarm")
        # Release the prewarm; shutdown should now complete.
        can_finish.set()
        self.assertTrue(shutdown_done.wait(timeout=3.0),
                        "shutdown should unblock after prewarm finishes")
        t.join(timeout=1.0)

    def test_create_failure_propagates(self):
        stub = StubCodec()
        stub.create_should_fail = True
        pool, _, _ = make_pool(stub=stub)
        with self.assertRaises(RuntimeError):
            pool.acquire(1920, 1080, "k")
        self.assertEqual(len(pool._slots), 0)


if __name__ == "__main__":
    unittest.main()
