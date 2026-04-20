#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# ABOUTME: Thin VPL wrapper around the generic DecoderPool: env-var parsing,
# ABOUTME: singleton lifecycle, optional fullscreen prewarm at module init.

"""
xpra.codecs.vpl.pool — VPL-specific DecoderPool wiring.

Consumers (the VPL Cython module) call ``init_pool`` with
``create_fn / reset_fn / destroy_fn`` bound to the Cython
``vpl_decoder_create / _reset / _destroy`` helpers. This module does not
import the Cython layer itself so that unit tests can drive the pool with
stub callables on any platform.

Environment variables:

- ``XPRA_VPL_POOL`` — set to ``0`` to disable pooling entirely (handled
  by the VPL decoder; this module only ever sees callables it's told
  to use).
- ``XPRA_VPL_POOL_SIZE`` — soft cap, default 4.
- ``XPRA_VPL_IDLE_TIMEOUT`` — seconds before idle slots are reaped,
  default 60.
- ``XPRA_VPL_PREWARM_FULLSCREEN`` — ``WxH`` or ``WxH@bitdepth``; when set
  and ``init_pool`` is called, a background prewarm is scheduled for
  those dimensions so the first full-screen acquire is a cache hit.
  Default empty (disabled).
"""

import os
from collections.abc import Callable
from threading import Lock
from typing import Optional, Tuple

from xpra.codecs.decoder_pool import DecoderPool, CachedDecoder
from xpra.util.env import envint
from xpra.log import Logger

log = Logger("vpl")


DEFAULT_POOL_SIZE = 4
DEFAULT_IDLE_TIMEOUT = 60

# All VPL pool slots share a single partition — see parse_prewarm's
# docstring for why bit_depth does not participate in keying.
VPL_POOL_KEY = "vpl"


_pool: Optional[DecoderPool] = None
_pool_init_lock = Lock()


def _detect_prewarm_size() -> Optional[Tuple[int, int]]:
    """Return the max (width, height) across all connected monitors,
    accounting for HiDPI scale factors. Used to auto-pick a prewarm size
    when ``XPRA_VPL_PREWARM_FULLSCREEN`` is unset — covers the case of
    dragging a window from the laptop screen to a larger external
    display. Returns ``None`` if GDK isn't available or no monitors are
    found."""
    try:
        from xpra.os_util import gi_import
        Gdk = gi_import("Gdk")
        display = Gdk.Display.get_default()
        if display is None:
            return None
        max_w = max_h = 0
        for i in range(display.get_n_monitors()):
            monitor = display.get_monitor(i)
            if monitor is None:
                continue
            geom = monitor.get_geometry()
            scale = monitor.get_scale_factor() or 1
            w, h = geom.width * scale, geom.height * scale
            if w * h > max_w * max_h:
                max_w, max_h = w, h
        if max_w and max_h:
            return (max_w, max_h)
    except Exception as e:  # pylint: disable=broad-except
        log.warn("Warning: VPL prewarm auto-detect failed: %s", e)
    return None


def parse_prewarm(spec: str) -> Optional[Tuple[int, int]]:
    """Parse ``WxH`` into ``(W, H)``; returns ``None`` for empty/malformed.

    We intentionally do NOT key the pool by bit depth: ``vpl_decoder_create``
    is given a bit-depth hint at creation, but ``lazy_init`` re-runs
    ``DecodeHeader`` + ``Init`` against the actual bitstream on every
    stream start, so a slot seeded for 8-bit can serve a 10-bit stream
    (and vice versa) without extra cost. Dropping the bit-depth partition
    keeps the prewarmed slot reachable regardless of the first stream's
    profile.
    """
    if not spec:
        return None
    try:
        # Accept a trailing "@bitdepth" (previously used) — value ignored.
        dims = spec.split("@", 1)[0] if "@" in spec else spec
        w_str, h_str = dims.split("x", 1)
        return (int(w_str), int(h_str))
    except (ValueError, AttributeError):
        return None


def init_pool(create_fn: Callable, reset_fn: Callable, destroy_fn: Callable,
              *, scheduler: Optional[Callable] = None) -> DecoderPool:
    """Create the VPL decoder pool singleton, reading env vars for sizing.

    If ``XPRA_VPL_PREWARM_FULLSCREEN`` is set to a valid ``WxH`` or
    ``WxH@bitdepth`` spec, schedules a background prewarm.

    ``scheduler`` defaults to the pool's built-in ``add_work_item`` adapter;
    tests inject a synchronous stub.
    """
    global _pool
    # Serialize so concurrent first-use from multiple threads cannot
    # create two pools and orphan one. Also recreate the pool if the
    # existing singleton has already been shut down — xpra's client
    # reconnect path (Encodings.cleanup → unload_codecs → reload)
    # triggers codec re-initialization in the same process.
    with _pool_init_lock:
        if _pool is not None and _pool.is_shutdown():
            _pool = None
        if _pool is not None:
            # Second call: return the existing singleton. Warn if the
            # caller passed different callables than we stored, since the
            # pool will keep using the originals and the new ones are
            # silently dropped. This can indicate an accidental re-import
            # that binds fresh Cython helpers.
            # Bound methods (e.g. ``stubs.create``) are freshly instantiated
            # on each attribute access so ``is`` comparison gives false
            # positives; compare by equality.
            if (_pool._create != create_fn
                    or _pool._reset != reset_fn
                    or _pool._destroy != destroy_fn):
                log.warn("Warning: vpl.init_pool called again with "
                         "different callables; new ones will be ignored")
            return _pool
        # Read env vars at init time (not import time) so overrides set by
        # the caller — or cleared by tests in setUp() — take effect.
        pool_size = envint("XPRA_VPL_POOL_SIZE", DEFAULT_POOL_SIZE)
        idle_timeout = envint("XPRA_VPL_IDLE_TIMEOUT", DEFAULT_IDLE_TIMEOUT)
        prewarm_spec = os.environ.get("XPRA_VPL_PREWARM_FULLSCREEN", "")
        kwargs = {
            "name": "vpl",
            "create_fn": create_fn,
            "reset_fn": reset_fn,
            "destroy_fn": destroy_fn,
            "target_size": pool_size,
            "idle_timeout_s": float(idle_timeout),
            # vpl_decoder_reset does MFXVideoDECODE_Close + Init, which
            # reallocates surfaces for any new dimensions. So a single
            # slot can serve 1280x720 → 1920x1080 → 4K without cycling.
            "allow_grow": True,
        }
        if scheduler is not None:
            kwargs["work_scheduler"] = scheduler
        _pool = DecoderPool(**kwargs)
        # Capture the instance we just published so prewarm/return always
        # target this caller's pool, even if a concurrent shutdown+init
        # replaces ``_pool`` after we release the lock.
        new_pool = _pool
        prewarm = parse_prewarm(prewarm_spec)
        prewarm_source = "env"
    # Auto-detect (max across all connected monitors) if no explicit env
    # var was given. Env var is still respected as an override — useful
    # when the remote desktop exceeds any local monitor. Set
    # XPRA_VPL_PREWARM=0 to disable prewarm entirely (e.g. in tests).
    autodetect = os.environ.get("XPRA_VPL_PREWARM", "1") != "0"
    if prewarm is None and not prewarm_spec and autodetect:
        prewarm = _detect_prewarm_size()
        prewarm_source = "auto"
    if prewarm is not None:
        W, H = prewarm
        log("vpl pool: prewarming %dx%d (%s)", W, H, prewarm_source)
        new_pool.prewarm(W, H, VPL_POOL_KEY)
    elif prewarm_spec:
        log.warn("Warning: XPRA_VPL_PREWARM_FULLSCREEN=%r malformed; "
                 "expected WxH", prewarm_spec)
    return new_pool


def get_pool() -> Optional[DecoderPool]:
    return _pool


def acquire(W: int, H: int) -> CachedDecoder:
    """Acquire a VPL decoder fitting WxH. Bit depth is auto-detected per
    stream by ``lazy_init`` in the C layer, so slots are not partitioned
    by it — see ``parse_prewarm``."""
    assert _pool is not None, "init_pool() not called"
    return _pool.acquire(W, H, VPL_POOL_KEY)


def release(slot: CachedDecoder) -> None:
    # Route to the slot's ORIGINATING pool, not the current singleton —
    # they differ after an init_pool → shutdown → init_pool sequence
    # (xpra client reconnect path) while a slot is still held.
    owner = slot.owner
    if owner is not None:
        owner.release(slot)
        return
    assert _pool is not None, "init_pool() not called"
    _pool.release(slot)


def shutdown() -> None:
    """Shut down the pool. The singleton reference is KEPT so a caller
    that still holds a ``CachedDecoder`` slot across module teardown can
    safely ``release(slot)`` — ``DecoderPool.release`` routes through its
    own shutdown-safe destroy path.

    Serialized against ``init_pool`` via ``_pool_init_lock`` so a
    concurrent startup cannot publish a fresh pool during teardown and
    outlive it.
    """
    # Hold the init lock across p.shutdown() so a concurrent init_pool()
    # cannot observe the old pool as "not shut down" between us reading
    # _pool and the pool flipping its own _shutdown flag. Bounded by the
    # pool's PREWARM_DRAIN_TIMEOUT_S (~5s).
    with _pool_init_lock:
        if _pool is None:
            return
        _pool.shutdown()


def _reset_for_testing() -> None:
    """Test-only: drop the singleton so the next ``init_pool()`` creates
    a fresh pool. Not for production use."""
    global _pool
    with _pool_init_lock:
        if _pool is not None:
            _pool.shutdown()
        _pool = None
