#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# ABOUTME: Codec-agnostic decoder pool that reuses decoders across init/clean
# ABOUTME: cycles using create/reset/destroy callables supplied by the codec.

"""
Generic decoder pool.

Consumers supply three callables:

- ``create_fn(W, H, key) -> handle`` — allocate a new decoder (expensive,
  ~90ms for oneVPL HEVC). Called outside the pool lock.
- ``reset_fn(handle, W, H, key)`` — reconfigure an existing handle for new
  dimensions without re-allocating surfaces. Raises on failure. Called
  outside the pool lock after the slot has been marked ``in_use``.
- ``destroy_fn(handle)`` — release a handle. Posted to the caller-supplied
  ``work_scheduler`` (defaults to ``xpra.util.background_worker.add_work_item``
  with ``daemon=False``) so that the main thread never blocks on the
  ~30ms teardown.

``key`` must be hashable and immutable (use ``int``, ``str``, ``tuple``,
``frozenset``, or similar). Slots compare keys by equality; a mutated key
would corrupt the partitioning and cause decoders to be reused across
incompatible formats.

The pool uses an industry-standard "max-allocate + reset for smaller" model:
a slot is keyed by the caller-supplied ``key`` (e.g., bit depth), tracks its
``max_W / max_H`` (largest dims ever allocated), and can serve any request
that fits within its current envelope. Requests that exceed the envelope
allocate a fresh slot.

``target_size`` is a soft cap. ``acquire`` never blocks on it; the pool is
allowed to grow past the target to serve concurrent demand. The reaper
trims excess idle slots on each tick (see ``reap``).

Lifecycle contract
------------------

The pool assumes each slot owns its own resources (per-decoder session,
driver handles, GPU allocations). There is no shared device state
managed by the pool, so ``shutdown()`` does NOT need to fence against
every in-flight operation — only against the ones that touch pool
bookkeeping. Specifically:

- ``shutdown()`` waits for in-flight prewarm ``create_fn`` calls so a
  successful prewarm won't insert a slot into an already-shut-down pool.
- ``shutdown()`` does NOT wait for an in-flight foreground ``acquire()``.
  Two sub-cases:
    * ``acquire`` mid-``_create``: returns a detached slot (``_shutdown``
      re-checked under lock before enroll). Caller's subsequent
      ``release()`` destroys it synchronously.
    * ``acquire`` mid-fit-check on an existing cached slot: the racing
      acquire can still mark an idle slot ``in_use=True`` and call
      ``reset_fn`` after ``shutdown()`` has flipped ``_shutdown=True``.
      That's benign for our consumers: the slot's handle owns its own
      runtime state, and the eventual ``release()`` routes through the
      shutdown-aware destroy path.
- Queued (non-daemon) destroys posted via ``_schedule_destroy`` run to
  completion on the background worker during its own orderly shutdown;
  they do not need to drain before ``shutdown()`` returns because the
  pool never freed the resources they own (the worker thread does).

If you bolt this pool onto a codec with shared device state that the
caller tears down immediately after ``shutdown()``, add explicit
drain-all semantics here — don't rely on the current behavior.
"""

from threading import Condition, Lock
from time import monotonic
from collections.abc import Callable
from typing import Any

from xpra.log import Logger

log = Logger("util")


DEFAULT_TARGET_SIZE = 4
DEFAULT_IDLE_TIMEOUT_S = 60.0


def _default_scheduler(item: Callable, daemon: bool = False) -> None:
    # Lazy import: background_worker pulls in GLib via xpra.os_util which
    # would make this module unimportable in minimal test environments.
    #
    # daemon=False (default) — mandatory work (destroy). ``clean_quit`` waits
    # for these to drain, so a handle is never leaked on shutdown.
    # daemon=True — speculative work (prewarm). Dropped on force-stop so
    # orderly exit doesn't block on a ~90ms decoder init.
    from xpra.util.background_worker import add_work_item
    add_work_item(item, allow_duplicates=True, daemon=daemon)


class CachedDecoder:
    """A single pooled decoder handle with its current allocation envelope.

    Carries a back-reference to its owning pool so ``release(slot)`` in a
    wrapper module can route to the pool that created it — needed because
    xpra's client reconnect path (``Encodings.cleanup`` →
    ``unload_codecs`` → reload) can call ``init_pool`` a second time in
    the same process, replacing the wrapper's singleton before any
    lingering slot has released.
    """

    __slots__ = ("handle", "max_W", "max_H", "key", "in_use", "last_used",
                 "owner")

    def __init__(self, handle: Any, W: int, H: int, key: Any,
                 owner: "DecoderPool | None" = None):
        self.handle = handle
        self.max_W = W
        self.max_H = H
        self.key = key
        self.in_use = True
        self.last_used = monotonic()
        self.owner = owner

    def fits(self, W: int, H: int, key: Any,
             allow_grow: bool = False) -> bool:
        """True if this idle slot can serve a ``W x H`` request for ``key``.

        ``allow_grow`` controls upper-bound behavior: when False (default)
        the slot must be at least as large as the request
        (max-allocate-for-smaller pattern); when True the slot matches any
        size — the caller's ``reset_fn`` is expected to reconfigure to the
        new dimensions (e.g. oneVPL Close+Init reallocates surfaces).
        """
        if self.in_use or self.key != key:
            return False
        if allow_grow:
            return True
        return W <= self.max_W and H <= self.max_H

    def __repr__(self):
        return (
            f"CachedDecoder(key={self.key!r}, max={self.max_W}x{self.max_H}, "
            f"in_use={self.in_use})"
        )


class DecoderPool:

    def __init__(
        self,
        name: str,
        create_fn: Callable,
        reset_fn: Callable,
        destroy_fn: Callable,
        target_size: int = DEFAULT_TARGET_SIZE,
        idle_timeout_s: float = DEFAULT_IDLE_TIMEOUT_S,
        work_scheduler: Callable | None = None,
        allow_grow: bool = False,
        min_kept_idle: int = 0,
    ):
        self.name = name
        self._create = create_fn
        self._reset = reset_fn
        self._destroy = destroy_fn
        self.target_size = target_size
        self.idle_timeout_s = idle_timeout_s
        # allow_grow: let idle slots serve requests LARGER than their
        # current max_W/max_H. Use only when reset_fn can reconfigure to
        # arbitrary new dims without caller-visible failure (e.g. oneVPL
        # Close+Init cycle). Default off matches the max-allocate +
        # reuse-for-smaller pattern used by NVIDIA CUVID, etc.
        self.allow_grow = allow_grow
        # min_kept_idle: protect up to N idle slots from the reaper,
        # preferring the largest-max_W*max_H (then freshest last_used).
        # Used by pools with prewarm so the prewarmed largest slot stays
        # warm indefinitely — otherwise idle_timeout reaps it and the
        # next acquire pays the full create cost. Default 0 = no
        # protection, full reap behavior.
        self.min_kept_idle = min_kept_idle
        self._schedule = work_scheduler or _default_scheduler
        self._lock = Lock()
        self._prewarm_cond = Condition(self._lock)
        self._slots: list[CachedDecoder] = []
        # Queued prewarm tokens (scheduled, not necessarily running yet) —
        # used for dedup and coalescing at enqueue time.
        self._pending_prewarm: set = set()
        # Count of prewarm create_fn calls currently executing on the
        # background worker — used by shutdown() to drain only in-flight
        # creates, not queue items that will be no-op'd on pickup.
        self._inflight_prewarm: int = 0
        # Count of destroy_fn calls enqueued via _schedule_destroy but not
        # yet run. shutdown() waits for this to drain so consumers that
        # tear down shared runtime state after shutdown() returns don't
        # race with queued decoder destroys.
        self._pending_destroys: int = 0
        self._destroy_cond = Condition(self._lock)
        self._shutdown = False

    def is_shutdown(self) -> bool:
        return self._shutdown

    # -------- acquire / release --------

    def acquire(self, W: int, H: int, key: Any) -> CachedDecoder:
        """Acquire a decoder fitting W x H / key. Creates if none available.

        If ``shutdown()`` has been called the pool is bypassed and a fresh
        handle is returned outside the pool (``release`` on such a slot
        will destroy immediately).
        """
        if self._shutdown:
            return self._create_direct(W, H, key)
        return self._acquire_with_retry(W, H, key, retries_left=1)

    def _acquire_with_retry(
        self, W: int, H: int, key: Any, retries_left: int,
    ) -> CachedDecoder:
        slot = self._take_fitting_slot(W, H, key)
        if slot is None:
            return self._create_and_insert(W, H, key)
        try:
            self._reset(slot.handle, W, H, key)
        except Exception as e:  # pylint: disable=broad-except
            log.warn("Warning: %s pool reset failed: %s", self.name, e)
            # Remove the slot from the pool AND destroy its handle
            # synchronously before retrying: hardware codecs with tight
            # session/decoder limits (e.g. oneVPL) will fail the next
            # create if the failed handle is still holding resources.
            with self._lock:
                try:
                    self._slots.remove(slot)
                except ValueError:
                    pass
            try:
                self._destroy(slot.handle)
            except Exception as de:  # pylint: disable=broad-except
                log.warn("Warning: %s pool destroy after reset failure: %s",
                         self.name, de)
            if retries_left > 0:
                return self._acquire_with_retry(W, H, key, retries_left - 1)
            return self._create_and_insert(W, H, key)
        # Reset updated the handle; keep max envelope non-shrinking.
        slot.max_W = max(slot.max_W, W)
        slot.max_H = max(slot.max_H, H)
        log("%s pool hit: %s", self.name, slot)
        return slot

    def _take_fitting_slot(
        self, W: int, H: int, key: Any,
    ) -> CachedDecoder | None:
        """Under lock: pick smallest fitting slot, mark ``in_use``, return it."""
        with self._lock:
            # Two-pass selection in allow_grow mode:
            #   1) smallest slot whose envelope already covers the request
            #      (no grow needed — reuses the exact allocation, so a
            #      prewarmed fullscreen slot isn't bypassed by an older
            #      small slot that would need a costly resize Init).
            #   2) fallback: smallest slot overall (will grow on reset).
            # When allow_grow=False the second pass never runs because
            # fits() already enforces the W/H upper bound.
            best_cover = None
            best_cover_area = 0
            best_any = None
            best_any_area = 0
            for s in self._slots:
                if not s.fits(W, H, key, self.allow_grow):
                    continue
                area = s.max_W * s.max_H
                if best_any is None or area < best_any_area:
                    best_any = s
                    best_any_area = area
                if W <= s.max_W and H <= s.max_H:
                    if best_cover is None or area < best_cover_area:
                        best_cover = s
                        best_cover_area = area
            best = best_cover if best_cover is not None else best_any
            if best is not None:
                best.in_use = True
            return best

    def _create_and_insert(self, W: int, H: int, key: Any) -> CachedDecoder:
        """Create outside lock; insert slot (in_use=True) under lock."""
        handle = self._create(W, H, key)
        slot = CachedDecoder(handle, W, H, key, owner=self)
        with self._lock:
            if self._shutdown:
                # Pool closed mid-create: don't enroll; return a detached slot.
                # Caller's release() will destroy it directly.
                return slot
            self._slots.append(slot)
        log("%s pool miss: created %s", self.name, slot)
        return slot

    def _create_direct(self, W: int, H: int, key: Any) -> CachedDecoder:
        """Post-shutdown path: create a handle not tracked by the pool."""
        handle = self._create(W, H, key)
        return CachedDecoder(handle, W, H, key, owner=self)

    def release(self, slot: CachedDecoder) -> None:
        with self._lock:
            if slot in self._slots and not self._shutdown:
                slot.in_use = False
                slot.last_used = monotonic()
                log("%s pool release: %s", self.name, slot)
                return
            # Either pool is shutting down (must drop the slot and destroy)
            # or the slot is detached (already removed from _slots).
            if slot in self._slots:
                self._slots.remove(slot)
        # _schedule_destroy is shutdown-aware: synchronous during shutdown,
        # otherwise queued on the background worker.
        self._schedule_destroy(slot.handle)

    # -------- prewarm --------

    def prewarm(self, W: int, H: int, key: Any) -> None:
        """Schedule a background create so the first acquire is a cache hit.

        Dedupes by (W, H, key): repeated prewarm calls for the same key
        while an earlier one is still pending are no-ops.
        """
        if self._shutdown:
            return
        token = (W, H, key)
        with self._lock:
            # Short-circuit: only skip prewarm if an idle slot already
            # COVERS the request (envelope ≥ WxH). allow_grow permits
            # reset-to-larger, but for prewarm we specifically want a
            # slot of the requested size — a small idle slot that would
            # need a resize Init on first use defeats the prewarm's
            # purpose (hiding the fullscreen-init latency).
            for s in self._slots:
                if (not s.in_use and s.key == key
                        and W <= s.max_W and H <= s.max_H):
                    return
            # Dedup exact repeats. We intentionally do NOT coalesce across
            # different sizes (e.g. suppress a smaller prewarm because a
            # larger one is pending). Our actual consumer calls prewarm
            # at most once per module init with a single WxH; cross-size
            # coalescing would be dead code. Add it back if a future
            # caller prewarms multiple sizes.
            if token in self._pending_prewarm:
                return
            self._pending_prewarm.add(token)

        def _do_prewarm():
            # Check _shutdown AND reserve the in-flight counter under the
            # same lock so shutdown()'s drain-wait never misses this
            # prewarm: either shutdown sees _inflight_prewarm > 0 and
            # waits, or we observe _shutdown=True here and skip the
            # create entirely.
            with self._lock:
                if self._shutdown:
                    self._pending_prewarm.discard(token)
                    return
                self._inflight_prewarm += 1
            try:
                try:
                    handle = self._create(W, H, key)
                except Exception as e:  # pylint: disable=broad-except
                    log.warn("Warning: %s pool prewarm failed: %s",
                             self.name, e)
                    return
                slot = CachedDecoder(handle, W, H, key, owner=self)
                slot.in_use = False
                detach = False
                with self._lock:
                    if self._shutdown:
                        detach = True
                    else:
                        # Race: a real acquire may already have created an
                        # idle slot matching this key+envelope. Don't add a
                        # redundant one — detach and destroy. Cover check
                        # (not fits()) because allow_grow would otherwise
                        # discard our newly-built fullscreen slot in favor
                        # of any older smaller one.
                        for existing in self._slots:
                            if (not existing.in_use and existing.key == key
                                    and W <= existing.max_W
                                    and H <= existing.max_H):
                                detach = True
                                break
                        if not detach:
                            self._slots.append(slot)
                if detach:
                    self._schedule_destroy(handle)
                    log("%s pool prewarm superseded; handle destroyed",
                        self.name)
                else:
                    log("%s pool prewarm done: %s", self.name, slot)
            finally:
                with self._lock:
                    self._pending_prewarm.discard(token)
                    self._inflight_prewarm -= 1
                    if self._inflight_prewarm == 0:
                        self._prewarm_cond.notify_all()

        # daemon=True: prewarm is speculative. On force-stop the worker
        # drops daemon items, so we don't block ``clean_quit`` on a ~90ms
        # decoder init that isn't needed for correctness.
        # Intentionally no try/except around the scheduler call: the
        # default scheduler (xpra.util.background_worker.add_work_item)
        # puts on an unbounded Queue and cannot fail in practice. A
        # custom scheduler that raises would leave a stale pending
        # token; pass a scheduler that doesn't raise, or add a rollback
        # here if you must.
        self._schedule(_do_prewarm, daemon=True)

    # -------- reaper --------

    def reap(self) -> bool:
        """Prune idle slots past timeout and trim oldest idle over target.

        Public API: callers schedule this on a periodic timer (e.g.
        ``GLib.timeout_add(10_000, pool.reap)``). Returns ``True`` so a
        GLib source stays alive; when the pool has been shut down returns
        ``False`` to let the source drop itself.
        """
        if self._shutdown:
            return False
        now = monotonic()
        victims: list = []
        with self._lock:
            # Step 0: pick protected idle slots (largest first, fresher
            # wins ties). These survive both idle-timeout and over-target
            # trim so a prewarmed large slot stays warm indefinitely.
            protected: set[int] = set()
            if self.min_kept_idle > 0:
                idle = [s for s in self._slots if not s.in_use]
                idle.sort(
                    key=lambda s: (s.max_W * s.max_H, s.last_used),
                    reverse=True,
                )
                protected = {id(s) for s in idle[:self.min_kept_idle]}
            # Step 1: idle timeout.
            kept: list[CachedDecoder] = []
            for s in self._slots:
                if (not s.in_use
                        and id(s) not in protected
                        and (now - s.last_used) > self.idle_timeout_s):
                    victims.append(s.handle)
                else:
                    kept.append(s)
            self._slots = kept
            # Step 2: over-target trim (oldest idle first, skip protected).
            if len(self._slots) > self.target_size:
                idle = [s for s in self._slots
                        if not s.in_use and id(s) not in protected]
                idle.sort(key=lambda s: s.last_used)
                over = len(self._slots) - self.target_size
                to_trim = idle[:over]
                if to_trim:
                    trim_ids = {id(s) for s in to_trim}
                    victims.extend(s.handle for s in to_trim)
                    self._slots = [s for s in self._slots if id(s) not in trim_ids]
        for h in victims:
            self._schedule_destroy(h)
        if victims:
            log("%s pool reaped %i slots", self.name, len(victims))
        return True

    # -------- shutdown --------

    PREWARM_DRAIN_TIMEOUT_S = 5.0

    def shutdown(self) -> None:
        """Close the pool: destroy idle slots now; in-use slots are destroyed
        by ``release()`` when the caller returns them.

        Blocks until any in-flight background ``prewarm`` create finishes
        (bounded by ``PREWARM_DRAIN_TIMEOUT_S``) so the caller can safely
        tear down shared device state after ``shutdown()`` returns.

        Safe against concurrent holders: an in-use handle is never freed out
        from under its caller. New ``acquire()`` calls after shutdown go
        through a direct create/destroy path (not pooled).
        """
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            # Wait for in-flight prewarm creates to finish, if any. Bounded
            # so a stuck worker doesn't hang shutdown forever. Queued-but-
            # not-started prewarms are no-op'd by ``_do_prewarm``'s
            # ``_shutdown`` check, so we only wait for the ones whose
            # ``_create`` call is currently running.
            if self._inflight_prewarm:
                log("%s pool shutdown: waiting for %i prewarm(s) to drain",
                    self.name, self._inflight_prewarm)
                deadline_reached = not self._prewarm_cond.wait_for(
                    lambda: self._inflight_prewarm == 0,
                    timeout=self.PREWARM_DRAIN_TIMEOUT_S,
                )
                if deadline_reached:
                    log.warn(
                        "Warning: %s pool shutdown timed out waiting for "
                        "%i prewarm(s)", self.name, self._inflight_prewarm)
            # Wait for any destroys already queued via _schedule_destroy
            # (e.g. from recent release() or reap()) to finish. Otherwise
            # consumers that tear down shared runtime state after
            # shutdown() would race those queued destroys.
            if self._pending_destroys:
                log("%s pool shutdown: waiting for %i queued destroy(s)",
                    self.name, self._pending_destroys)
                deadline_reached = not self._destroy_cond.wait_for(
                    lambda: self._pending_destroys == 0,
                    timeout=self.PREWARM_DRAIN_TIMEOUT_S,
                )
                if deadline_reached:
                    log.warn(
                        "Warning: %s pool shutdown timed out waiting for "
                        "%i queued destroy(s)",
                        self.name, self._pending_destroys)
            idle = [s for s in self._slots if not s.in_use]
            # Keep in-use slots in the list so release() finds them and
            # routes through the post-shutdown destroy path.
            self._slots = [s for s in self._slots if s.in_use]
            in_use_count = len(self._slots)
        # Synchronous, foreground destroy of idle slots: the worker thread
        # may be stopping too, so we can't rely on self._schedule here.
        for s in idle:
            try:
                self._destroy(s.handle)
            except Exception as e:  # pylint: disable=broad-except
                log.warn("Warning: %s pool shutdown destroy failed: %s", self.name, e)
        log("%s pool shutdown: destroyed %i idle slots, %i still in use",
            self.name, len(idle), in_use_count)

    # -------- helpers --------

    def _schedule_destroy(self, handle: Any) -> None:
        """Destroy ``handle`` on the background worker — unless shutdown has
        started, in which case run synchronously. The default background
        worker drops any work items enqueued after its sentinel, so
        scheduling during teardown leaks the handle."""
        # Check _shutdown AND reserve a destroy counter slot under the same
        # lock so shutdown()'s drain-wait never misses this destroy: either
        # shutdown sees _pending_destroys > 0 and waits, or we observe
        # _shutdown=True here and run synchronously.
        with self._lock:
            if self._shutdown:
                shutdown_now = True
            else:
                shutdown_now = False
                self._pending_destroys += 1
        if shutdown_now:
            try:
                self._destroy(handle)
            except Exception as e:  # pylint: disable=broad-except
                log.warn("Warning: %s pool destroy failed: %s", self.name, e)
            return

        def _do_destroy():
            try:
                self._destroy(handle)
            except Exception as e:  # pylint: disable=broad-except
                log.warn("Warning: %s pool destroy failed: %s", self.name, e)
            finally:
                with self._lock:
                    self._pending_destroys -= 1
                    if self._pending_destroys == 0:
                        self._destroy_cond.notify_all()
        # Intentionally no try/except around _schedule: see the matching
        # note in prewarm(). If a custom scheduler raises here we'd leak
        # _pending_destroys; don't pass one that can raise.
        # daemon=False: destroys are mandatory work. A custom scheduler
        # whose default is daemon=True would otherwise let force-stop
        # drop these and leak the decoder handle.
        self._schedule(_do_destroy, daemon=False)
