#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# ABOUTME: Reproducer for nvenc Encoder __dealloc__ use-after-free.
# ABOUTME: Drops the only ref to an inited Encoder; __dealloc__ spawns
# ABOUTME: threaded_clean via start_thread; the thread reads freed self.

"""
Reproducer for the nvenc Encoder use-after-free hypothesis (see
`nvenc-segv-hypothesis.md`).

Setup:
    1. Subprocess inits NVENC and creates ONE fully-initialized Encoder.
    2. Subprocess drops the only ref via `enc = None`.
       Refcount drops 1 → 0. Cython `__dealloc__` fires.
       __dealloc__ sees `self.closed == False` → calls `self.clean()`.
       clean() spawns `threaded_clean` via `start_thread`.
       The bound method captures `self` → refcount 0 → 1.
       __dealloc__ returns. Cython tp_dealloc continues to free the struct
       (no resurrection check in Cython cdef class tp_dealloc).
    3. Main thread sleeps long enough for `threaded_clean` to run.
       threaded_clean does `self.init_complete` and `self.do_clean()` — both
       read freed memory. If memory was reused, SEGV.
    4. Subprocess exits cleanly. Parent inspects exit code.

Outcome interpretation:
    - exit code == -11 (or 139): SEGV → hypothesis CONFIRMED.
    - exit code == 0 and no SEGV: hypothesis not reproduced under this run.
      Could mean (a) Cython actually handles resurrection, (b) memory not
      reused in the race window, or (c) something else holds the encoder
      alive that I missed. Run multiple times to estimate hit rate.
    - exit code != 0 and != -11: infra error.

Differences from `nvenc_cleanup_repro.py`:
    - That reproducer calls `enc.clean()` EXPLICITLY and tests the cleanup
      LEAK path (out-of-thread context warnings). This one does NOT call
      clean(); it drops the ref and lets __dealloc__ fire — that's the path
      under investigation.
    - That reproducer uses `os._exit(0)` to terminate the subprocess
      quickly. This one does NOT — we need the subprocess to live long
      enough for the spawned threaded_clean to execute and (potentially)
      access freed memory.

Usage:
    /usr/bin/python3 tests/scripts/nvenc_dealloc_uaf_repro.py
    /usr/bin/python3 tests/scripts/nvenc_dealloc_uaf_repro.py --runs=10

The default is 5 runs because the race is timing-dependent — one run may
or may not trigger the SEGV depending on whether freed memory has been
overwritten by the time threaded_clean reads from it.
"""

import argparse
import os
import signal
import subprocess
import sys
import time


# How long the worker waits after dropping the encoder ref. The spawned
# `threaded_clean` thread needs time to wake up, schedule, run, and try
# to access freed memory. 3s is generous — typical thread scheduling
# latency is <1ms but we want to allow for GIL contention and gc.
WORKER_WAIT_SECONDS = 3.0


# --------------------------- WORKER (subprocess) ---------------------------

def worker_main(args: argparse.Namespace) -> int:
    """Runs inside the subprocess. Builds an encoder, drops the only ref,
    waits for the use-after-free to potentially fire, exits."""
    import threading
    import gc

    print(f"[worker pid={os.getpid()}] starting", file=sys.stderr, flush=True)

    from xpra.codecs.nvidia.cuda.context import (
        init_all_devices, load_device, cuda_device_context,
    )
    from xpra.codecs.nvidia.nvenc import encoder as nvenc_encoder
    from xpra.codecs.image import ImageWrapper
    from xpra.util.objects import typedict

    nvenc_encoder.init_module({})
    devices = init_all_devices()
    if not devices:
        print("FAIL: no CUDA devices", file=sys.stderr, flush=True)
        return 2
    device_id = devices[0]
    device = load_device(device_id)
    cdc = cuda_device_context(device_id, device)
    with cdc:
        pass  # prime context

    W = H = 256
    pixels = bytes(W * H * 4)

    def make_image() -> ImageWrapper:
        return ImageWrapper(
            0, 0, W, H, pixels, "BGRX", 32, W * 4,
            planes=ImageWrapper.PACKED, thread_safe=True,
        )

    # Build a fully-initialized Encoder.
    # IMPORTANT: pass `threaded-init=True` so __dealloc__'s clean() path
    # will call start_thread (which is the path under test). If
    # threaded-init is False, clean() runs do_clean inline and the bug
    # does not exist.
    print("[worker] creating encoder with threaded-init=True",
          file=sys.stderr, flush=True)
    enc = nvenc_encoder.Encoder()
    options = typedict({
        "cuda-device-context": cdc,
        "dst-formats": ("YUV420P", "YUV444P"),
        "quality": 50, "speed": 50,
        "threaded-init": True,
    })
    enc.init_context("h264", W, H, "BGRX", options)
    # Wait for threaded_init to complete by polling is_ready(). The
    # underlying init_complete Event is a cdef-private attribute so we
    # can't wait on it directly from Python.
    deadline = time.monotonic() + 10
    while not enc.is_ready():
        if time.monotonic() >= deadline:
            print("FAIL: encoder not ready within 10s", file=sys.stderr, flush=True)
            return 3
        time.sleep(0.05)
    # Push a frame through so the encoder is fully wired.
    try:
        enc.compress_image(make_image(),
                           typedict({"cuda-device-context": cdc}))
    except Exception as e:
        print(f"[worker] compress_image raised: {e!r}", file=sys.stderr, flush=True)

    print(f"[worker] encoder built: {enc!r}", file=sys.stderr, flush=True)
    print(f"[worker] enc.closed = {enc.is_closed()}", file=sys.stderr, flush=True)

    # CRITICAL SECTION: drop the only ref.
    # `enc = None` decrefs the bound name. If `enc` was the only strong
    # reference, the Encoder's refcount hits 0 and __dealloc__ fires
    # synchronously here. __dealloc__ sees `self.closed == False`, calls
    # self.clean(), which spawns `threaded_clean` via start_thread,
    # which captures `self` in a bound method, resurrecting refcount to 1.
    # But Cython's tp_dealloc proceeds to free the struct anyway.
    # The spawned thread now holds a bound method whose __self__ points
    # at freed memory.
    print("[worker] dropping encoder ref now (this triggers __dealloc__)",
          file=sys.stderr, flush=True)
    sys.stderr.flush()
    enc = None

    # Force a GC pass to drive home any cycles. Shouldn't be needed for
    # a plain reference drop, but include for completeness.
    gc.collect()

    # Wait for the spawned threaded_clean to (try to) access self.
    # During this sleep, any of the following happens (mutually exclusive):
    #   1. threaded_clean runs, reads self.init_complete from freed memory,
    #      SEGV fires. Process dies with signal 11.
    #   2. threaded_clean runs, reads stale-but-coherent freed memory,
    #      runs through cleanup, possibly succeeds. No SEGV.
    #   3. threaded_clean is queued but not yet scheduled; we exit before
    #      it runs. No SEGV (false negative).
    print(f"[worker] sleeping {WORKER_WAIT_SECONDS}s waiting for threaded_clean",
          file=sys.stderr, flush=True)
    time.sleep(WORKER_WAIT_SECONDS)

    print(f"[worker] survived sleep, threading enumerate={[t.name for t in threading.enumerate()]}",
          file=sys.stderr, flush=True)
    print("[worker] no SEGV observed in this run", file=sys.stderr, flush=True)
    sys.stderr.flush()
    sys.stdout.flush()
    # Skip atexit: pycuda's shutdown path hangs when GPU resources are
    # leaked (which the fix intentionally does, instead of SEGVing). All
    # diagnostic output has already been printed.
    os._exit(0)


# --------------------------- PARENT (driver) ---------------------------

def signal_label(rc: int) -> str:
    """Convert a return code to a readable form. Negative = killed by signal."""
    if rc >= 0:
        return f"exited normally (rc={rc})"
    sig = -rc
    name = signal.Signals(sig).name if sig in signal.Signals._value2member_map_ else f"sig{sig}"
    return f"killed by {name} (rc={rc})"


def parent_main(args: argparse.Namespace) -> int:
    """Spawns the worker N times, counts SEGVs."""
    env = dict(os.environ)
    env["XPRA_NVENC_DEALLOC_UAF_REPRO_CHILD"] = "1"
    cmd = [sys.executable, os.path.abspath(__file__)]
    print(f"[parent] command: {' '.join(cmd)}")
    print(f"[parent] runs: {args.runs}")
    print(f"[parent] worker wait: {WORKER_WAIT_SECONDS}s")

    segvs = 0
    cleans = 0
    other = 0
    for run in range(1, args.runs + 1):
        print()
        print(f"=========== run {run}/{args.runs} ===========")
        sys.stdout.flush()
        proc = subprocess.run(
            cmd, env=env,
            stdout=sys.stdout, stderr=sys.stderr,
            timeout=WORKER_WAIT_SECONDS + 60,
        )
        rc = proc.returncode
        print(f"[parent] run {run} {signal_label(rc)}")
        # SIGSEGV is signal 11. subprocess returns -11 for signal 11.
        if rc == -signal.SIGSEGV or rc == -signal.SIGBUS:
            segvs += 1
        elif rc == 0:
            cleans += 1
        else:
            other += 1

    print()
    print("=" * 60)
    print(f"[parent] SUMMARY across {args.runs} runs:")
    print(f"[parent]   SEGV/BUS:    {segvs}")
    print(f"[parent]   clean exits: {cleans}")
    print(f"[parent]   other:       {other}")
    if segvs > 0:
        print(f"[parent] REPRO CONFIRMED — hypothesis fires {segvs}/{args.runs} times.")
        return 1
    if other > 0 or cleans == 0:
        print(f"[parent] INFRASTRUCTURE ERROR — {other} runs failed without SEGV,")
        print("[parent] {cleans} clean exits. NOT a valid REPRO NEGATIVE result.".format(cleans=cleans))
        return 2
    print("[parent] REPRO NEGATIVE — no SEGVs in this batch.")
    print("[parent] Hypothesis not confirmed; could be:")
    print("[parent]   (a) Cython handles resurrection (unlikely per docs)")
    print("[parent]   (b) freed memory not reused in time window")
    print("[parent]   (c) some other ref kept encoder alive")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--runs", type=int, default=5,
                    help="number of subprocess runs to drive (each builds 1 encoder)")
    args = ap.parse_args()

    if os.environ.get("XPRA_NVENC_DEALLOC_UAF_REPRO_CHILD"):
        return worker_main(args)
    return parent_main(args)


if __name__ == "__main__":
    sys.exit(main())
