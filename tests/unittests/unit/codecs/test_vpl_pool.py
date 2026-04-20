#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# ABOUTME: Tests for xpra.codecs.vpl.pool — env-var parsing, singleton wiring
# ABOUTME: to DecoderPool, and prewarm scheduling. No Cython / no hardware.

import os
import unittest

from xpra.codecs.vpl import pool as vpl_pool


class _Handle:
    def __init__(self, W, H, bd):
        self.W = W
        self.H = H
        self.bd = bd


class _Stubs:
    def __init__(self):
        self.created = []
        self.reset_calls = []
        self.destroyed = []

    def create(self, W, H, bd):
        self.created.append((W, H, bd))
        return _Handle(W, H, bd)

    def reset(self, handle, W, H, bd):
        self.reset_calls.append((id(handle), W, H, bd))
        handle.W = W
        handle.H = H
        handle.bd = bd

    def destroy(self, handle):
        self.destroyed.append(id(handle))


def _sync(item, daemon=False):
    item()


class TestVplPool(unittest.TestCase):

    def setUp(self):
        vpl_pool._reset_for_testing()
        # Clear env vars that test_parse_prewarm_* rely on being unset.
        for k in ("XPRA_VPL_POOL_SIZE", "XPRA_VPL_IDLE_TIMEOUT",
                  "XPRA_VPL_PREWARM_FULLSCREEN"):
            os.environ.pop(k, None)
        # Disable monitor auto-detect so tests run in a headless env.
        os.environ["XPRA_VPL_PREWARM"] = "0"

    def tearDown(self):
        vpl_pool._reset_for_testing()
        os.environ.pop("XPRA_VPL_PREWARM", None)

    def test_parse_prewarm_fullscreen_WxH(self):
        self.assertEqual(vpl_pool.parse_prewarm("1920x1080"), (1920, 1080))

    def test_parse_prewarm_bitdepth_suffix_ignored(self):
        # Backward-compatibility: accept the old "@bd" suffix but ignore
        # the value since the pool doesn't partition by bit depth.
        self.assertEqual(vpl_pool.parse_prewarm("2880x1800@10"),
                         (2880, 1800))

    def test_parse_prewarm_empty_returns_none(self):
        self.assertIsNone(vpl_pool.parse_prewarm(""))

    def test_parse_prewarm_malformed_returns_none(self):
        self.assertIsNone(vpl_pool.parse_prewarm("garbage"))
        self.assertIsNone(vpl_pool.parse_prewarm("1920"))
        self.assertIsNone(vpl_pool.parse_prewarm("1920x"))
        self.assertIsNone(vpl_pool.parse_prewarm("AxB"))

    def test_init_pool_creates_singleton(self):
        stubs = _Stubs()
        vpl_pool.init_pool(stubs.create, stubs.reset, stubs.destroy,
                           scheduler=_sync)
        p = vpl_pool.get_pool()
        self.assertIsNotNone(p)
        self.assertIs(p, vpl_pool.get_pool())

    def test_env_var_pool_size_respected(self):
        os.environ["XPRA_VPL_POOL_SIZE"] = "2"
        stubs = _Stubs()
        vpl_pool.init_pool(stubs.create, stubs.reset, stubs.destroy,
                           scheduler=_sync)
        self.assertEqual(vpl_pool.get_pool().target_size, 2)

    def test_env_var_idle_timeout_respected(self):
        os.environ["XPRA_VPL_IDLE_TIMEOUT"] = "15"
        stubs = _Stubs()
        vpl_pool.init_pool(stubs.create, stubs.reset, stubs.destroy,
                           scheduler=_sync)
        self.assertEqual(vpl_pool.get_pool().idle_timeout_s, 15.0)

    def test_prewarm_fullscreen_triggers_create(self):
        # @bitdepth accepted but dropped — see parse_prewarm().
        os.environ["XPRA_VPL_PREWARM_FULLSCREEN"] = "1920x1080@10"
        stubs = _Stubs()
        vpl_pool.init_pool(stubs.create, stubs.reset, stubs.destroy,
                           scheduler=_sync)
        self.assertEqual(stubs.created, [(1920, 1080, vpl_pool.VPL_POOL_KEY)])

    def test_prewarm_default_unset_noop(self):
        stubs = _Stubs()
        vpl_pool.init_pool(stubs.create, stubs.reset, stubs.destroy,
                           scheduler=_sync)
        self.assertEqual(stubs.created, [])

    def test_prewarm_malformed_env_no_crash(self):
        os.environ["XPRA_VPL_PREWARM_FULLSCREEN"] = "garbage"
        stubs = _Stubs()
        # Must not raise.
        vpl_pool.init_pool(stubs.create, stubs.reset, stubs.destroy,
                           scheduler=_sync)
        self.assertEqual(stubs.created, [])

    def test_acquire_release_route_to_pool(self):
        stubs = _Stubs()
        vpl_pool.init_pool(stubs.create, stubs.reset, stubs.destroy,
                           scheduler=_sync)
        slot = vpl_pool.acquire(1280, 720)
        self.assertEqual(stubs.created, [(1280, 720, vpl_pool.VPL_POOL_KEY)])
        vpl_pool.release(slot)
        # Second acquire same key+fit: reset, not create.
        slot2 = vpl_pool.acquire(1280, 720)
        self.assertEqual(len(stubs.created), 1)
        self.assertEqual(len(stubs.reset_calls), 1)

    def test_defaults_apply_when_env_unset(self):
        # All XPRA_VPL_* env vars cleared in setUp.
        stubs = _Stubs()
        vpl_pool.init_pool(stubs.create, stubs.reset, stubs.destroy,
                           scheduler=_sync)
        p = vpl_pool.get_pool()
        self.assertEqual(p.target_size, vpl_pool.DEFAULT_POOL_SIZE)
        self.assertEqual(p.idle_timeout_s,
                         float(vpl_pool.DEFAULT_IDLE_TIMEOUT))
        self.assertEqual(stubs.created, [])

    def test_shutdown_destroys_all(self):
        stubs = _Stubs()
        vpl_pool.init_pool(stubs.create, stubs.reset, stubs.destroy,
                           scheduler=_sync)
        slot = vpl_pool.acquire(1280, 720)
        vpl_pool.release(slot)
        vpl_pool.shutdown()
        self.assertEqual(len(stubs.destroyed), 1)

    def test_concurrent_init_pool_creates_single_singleton(self):
        """Two threads calling init_pool at the same time must end up with
        the same pool instance — not two pools with one orphaned."""
        import threading as _th
        stubs = _Stubs()
        # Slow create so the race window is wide enough to hit reliably.
        orig_create = stubs.create
        start = _th.Event()

        def slow_create(W, H, bd):
            start.wait(timeout=1.0)
            return orig_create(W, H, bd)
        stubs.create = slow_create

        results = []
        errors = []

        def worker():
            try:
                p = vpl_pool.init_pool(stubs.create, stubs.reset,
                                       stubs.destroy, scheduler=_sync)
                results.append(p)
            except Exception as e:
                errors.append(e)

        threads = [_th.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        start.set()
        for t in threads:
            t.join(timeout=2.0)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 8)
        first = results[0]
        for p in results[1:]:
            self.assertIs(p, first,
                          "all init_pool callers must get the same pool")

    def test_init_pool_second_call_same_callables_silent(self):
        """Second init with the SAME callables (a typical re-import that
        rebinds to identical functions at the module level) should be a
        silent no-op — no warning."""
        stubs = _Stubs()
        vpl_pool.init_pool(stubs.create, stubs.reset, stubs.destroy,
                           scheduler=_sync)
        # Passing the same bound methods (compared by equality) must
        # not fire the "different callables" warning.
        with self.assertNoLogs(level="WARNING"):
            vpl_pool.init_pool(stubs.create, stubs.reset, stubs.destroy,
                               scheduler=_sync)

    def test_init_pool_after_shutdown_recreates(self):
        """Client reconnect path: cleanup_module → shutdown → init_module →
        init_pool must produce a fresh, working pool — not hand back the
        shut-down singleton, otherwise pooling silently stops working for
        the rest of the process."""
        stubs1 = _Stubs()
        vpl_pool.init_pool(stubs1.create, stubs1.reset, stubs1.destroy,
                           scheduler=_sync)
        p1 = vpl_pool.get_pool()
        vpl_pool.shutdown()
        stubs2 = _Stubs()
        p2 = vpl_pool.init_pool(stubs2.create, stubs2.reset, stubs2.destroy,
                                scheduler=_sync)
        self.assertIsNot(p1, p2)
        self.assertFalse(p2.is_shutdown())
        slot = vpl_pool.acquire(1280, 720)
        self.assertEqual(stubs1.created, [])
        self.assertEqual(stubs2.created,
                         [(1280, 720, vpl_pool.VPL_POOL_KEY)])
        vpl_pool.release(slot)

    def test_release_after_reinit_routes_to_original_pool(self):
        """A slot acquired before reinit must release via its ORIGINATING
        pool. Otherwise cleanup runs the new pool's destroy_fn on an old
        handle — or in the worst case a destroy_fn bound to a stub."""
        stubs1 = _Stubs()
        vpl_pool.init_pool(stubs1.create, stubs1.reset, stubs1.destroy,
                           scheduler=_sync)
        held = vpl_pool.acquire(1280, 720)
        vpl_pool.shutdown()
        stubs2 = _Stubs()
        vpl_pool.init_pool(stubs2.create, stubs2.reset, stubs2.destroy,
                           scheduler=_sync)
        vpl_pool.release(held)
        self.assertEqual(len(stubs1.destroyed), 1)
        self.assertEqual(len(stubs2.destroyed), 0)

    def test_release_after_shutdown_destroys_held_slot(self):
        """If a decoder outlives module shutdown, release must still work."""
        stubs = _Stubs()
        vpl_pool.init_pool(stubs.create, stubs.reset, stubs.destroy,
                           scheduler=_sync)
        held = vpl_pool.acquire(1280, 720)
        vpl_pool.shutdown()  # in-use; not destroyed yet
        self.assertEqual(len(stubs.destroyed), 0)
        vpl_pool.release(held)
        self.assertEqual(len(stubs.destroyed), 1)


if __name__ == "__main__":
    unittest.main()
