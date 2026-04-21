#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# ABOUTME: Synthetic reproducer for nvenc `_force_context_release` out-of-context
# ABOUTME: cleanup bug — builds a pool of fully-inited encoders, then tears them
# ABOUTME: down while cdc.lock is held externally so each cleanup times out.

"""
Reproducer for the nvenc cleanup bug observed 2026-04-19:

    pagelocked_host_allocation in out-of-thread context could not be cleaned up
    device_allocation in out-of-thread context could not be cleaned up

Root-cause hypothesis (see audit-findings.md):
    When `do_clean()`'s `cdc.lock.acquire(timeout=5)` times out
    (encoder.pyx:1141), it falls through to `_force_context_release()` which
    only decrements `context_counter` and does NOT null `self.inputBuffer`,
    `self.cudaInputBuffer`, `self.cudaOutputBuffer`. Those pycuda allocations
    remain live on the Encoder. When the Encoder is later GC'd, Cython drops
    those cdef refs from whatever thread holds the last reference — typically
    the cleanup daemon thread, which does NOT have the CUDA context pushed.
    pycuda's `__del__` emits "X in out-of-thread context could not be cleaned
    up" warnings; the CUDA resource leaks. Enough pagelocked-memory leaks
    exhaust the kernel's pinned-memory pool and eventually SEGV in pycuda.

Design:
    1. Build a pool of `pool_size` fully-initialized Encoder objects while
       no contention exists. Each encoder allocates inputBuffer +
       cudaOutputBuffer on the GPU.
    2. Main thread enters `with cdc:` — pushes cdc.context AND acquires
       cdc.lock. Matches the production scenario where encode_thread is
       inside compress_image when cleanup fires.
    3. A cleanup thread calls `.clean()` on each encoder in the pool;
       each call invokes `do_clean` whose `cdc.lock.acquire(timeout=5)`
       times out since main holds the lock. Force-release fires; buffers
       are NOT nulled in any code path.
    4. Cleanup thread drops all pool references. Cython releases
       inputBuffer / cudaOutputBuffer from the cleanup thread, which
       has NO context pushed. Meanwhile main has cdc.context PUSHED.
       pycuda's __del__ can't activate the context from cleanup thread
       (it's current in main thread) → emits the out-of-thread warning.
    5. Main thread exits `with cdc:` once cleanup signals done.
    6. Parent process counts "out-of-thread" warnings captured via
       subprocess stderr. Non-zero count = bug fires, 0 count = fix works.

Usage:
    /usr/bin/python3 tests/scripts/nvenc_cleanup_repro.py
    /usr/bin/python3 tests/scripts/nvenc_cleanup_repro.py --pool-size=8 --cycles=3
"""

import argparse
import os
import re
import subprocess
import sys
import threading
import time
from typing import Optional

WARNING_PATTERN = re.compile(
    r"(pagelocked_host_allocation|device_allocation|host_allocation|module|array|stream|event)"
    r" in out-of-thread context could not be cleaned up"
)

CLEANUP_TIMEOUT = 5.0  # matches encoder.pyx:1141 `cdc.lock.acquire(timeout=5)`


# --------------------------- WORKER (subprocess) ---------------------------

def worker_main(args: argparse.Namespace) -> int:
    """Runs inside the subprocess. Drives the actual repro."""
    # pycuda emits the out-of-thread-context message via PyErr_WarnEx, which
    # goes through Python's warnings module. Default filter dedupes same
    # (file:line, message), masking the leak count.
    import warnings
    warnings.simplefilter("always")

    from xpra.codecs.nvidia.cuda.context import (
        init_all_devices, load_device, cuda_device_context,
    )
    from xpra.codecs.nvidia.nvenc import encoder as nvenc_encoder
    from xpra.codecs.image import ImageWrapper
    from xpra.util.objects import typedict

    nvenc_encoder.init_module({})
    devices = init_all_devices()
    if not devices:
        print("FAIL: no CUDA devices", file=sys.stderr)
        return 2
    device_id = devices[0]
    device = load_device(device_id)
    cdc = cuda_device_context(device_id, device)
    # Prime cdc: create + push/pop once so subsequent operations are warm.
    with cdc:
        pass

    # 256x256 BGRX is reliably accepted by NVENC on A2000. The incident was
    # at 1489x909 HEVC 4:4:4 BGRX-native; the cleanup bug is dimension-
    # agnostic, so smaller frames keep per-encoder GPU memory under 1 MiB.
    W = H = 256
    pixels = bytes(W * H * 4)

    def make_image() -> ImageWrapper:
        return ImageWrapper(
            0, 0, W, H, pixels, "BGRX", 32, W * 4,
            planes=ImageWrapper.PACKED, thread_safe=True,
        )

    def build_encoder() -> Optional[object]:
        enc = nvenc_encoder.Encoder()
        try:
            options = typedict({
                "cuda-device-context": cdc,
                "dst-formats": ("YUV420P", "YUV444P"),
                "quality": 50, "speed": 50,
                "threaded-init": False,
            })
            enc.init_context("h264", W, H, "BGRX", options)
            enc.compress_image(make_image(), typedict({"cuda-device-context": cdc}))
            return enc
        except Exception as e:
            print(f"[build] failed: {e!r}", file=sys.stderr)
            try:
                enc.clean()
            except Exception:
                pass
            return None

    total_created = 0
    total_force_released = 0
    for cycle in range(args.cycles):
        print(f"[cycle {cycle + 1}/{args.cycles}] building pool of {args.pool_size}",
              file=sys.stderr)
        pool: list = []
        while len(pool) < args.pool_size:
            built = build_encoder()
            if built is None:
                break
            pool.append(built)
            total_created += 1
            # Don't leave `built` bound to the last encoder — if we do, that
            # encoder retains an extra ref past the `with cdc:` exit and its
            # __dealloc__ then fires with no pushed context elsewhere, losing
            # the warning signal we're trying to observe.
            del built
        if len(pool) < args.pool_size:
            # Partial pool means the reproducer couldn't set up the scenario
            # as requested (usually resource exhaustion or NVENC init error).
            # This is infrastructure failure, not a valid fix-verification
            # run, so signal it distinctly.
            print(f"[cycle] FAIL: built only {len(pool)}/{args.pool_size} encoders",
                  file=sys.stderr)
            # Drop whatever we did build before returning.
            for e in pool:
                try:
                    e.clean()
                except Exception:
                    pass
            pool.clear()
            sys.stderr.flush()
            os._exit(4)

        # Cleanup thread: clean + drop pool refs.
        # Each clean() -> do_clean() waits CLEANUP_TIMEOUT seconds for the
        # lock, times out, falls into _force_context_release().
        # Then the cleanup thread drops all pool refs, triggering Cython
        # __dealloc__ on THIS thread, releasing inputBuffer/cudaOutputBuffer
        # from pycuda. Main thread holds cdc.context pushed in `with cdc:`
        # below, so pycuda sees the context as out-of-thread and warns.
        cleanup_done = threading.Event()
        import gc

        def cleanup_worker(local_pool: list) -> None:
            nonlocal total_force_released
            # Pop-and-clean so no loop variable ends up holding the last
            # encoder's ref past the `del local_pool[:]`. If we used
            # `for e in local_pool`, `e` would retain the last element
            # until function exit — past cleanup_done.set() — so main
            # would exit `with cdc:` before that __dealloc__ fires,
            # turning one encoder (all of them at pool_size=1) into a
            # false negative.
            while local_pool:
                enc = local_pool.pop(0)
                try:
                    enc.clean()
                    total_force_released += 1
                except Exception as ex:
                    print(f"[cleanup] clean() raised: {ex!r}", file=sys.stderr)
                del enc  # drop this encoder's ref immediately
            gc.collect()
            cleanup_done.set()

        # Transfer pool ownership to a local the cleanup thread will clear.
        cleanup_pool = list(pool)
        pool.clear()

        t = threading.Thread(
            target=cleanup_worker, args=(cleanup_pool,),
            name="cleanup", daemon=True,
        )

        print(f"[cycle] entering `with cdc:` — push context + hold lock",
              file=sys.stderr)
        with cdc:
            t.start()
            # Wait inside the with-block so cdc.context stays pushed here
            # AND cdc.lock stays held, while cleanup thread times out.
            hold = CLEANUP_TIMEOUT * args.pool_size + 3.0
            if not cleanup_done.wait(timeout=hold):
                print(f"[cycle] cleanup thread hasn't finished after {hold:.1f}s, "
                      f"releasing anyway", file=sys.stderr)
        print("[cycle] exited `with cdc:`", file=sys.stderr)

        t.join(timeout=10)
        time.sleep(0.5)

    print(f"[summary] encoders_created={total_created} force_released={total_force_released}",
          file=sys.stderr)
    # Skip atexit / pycuda cleanup — by design we have leaked pycuda
    # allocations (the whole point of this repro), and pycuda's own
    # shutdown path hangs trying to reconcile them with a half-torn-down
    # CUDA context. The parent already has what it needs via stderr.
    sys.stderr.flush()
    sys.stdout.flush()
    os._exit(0)


# --------------------------- PARENT (driver) ---------------------------

def parent_main(args: argparse.Namespace) -> int:
    """Runs the worker as a subprocess and counts warnings."""
    env = dict(os.environ)
    env["XPRA_NVENC_CLEANUP_REPRO_CHILD"] = "1"
    cmd = [sys.executable, os.path.abspath(__file__),
           f"--pool-size={args.pool_size}",
           f"--cycles={args.cycles}"]
    print(f"[parent] launching child: {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd, env=env,
        stdout=sys.stdout, stderr=subprocess.PIPE, text=True,
    )
    warning_counts: dict[str, int] = {}
    saw_summary = False
    assert proc.stderr is not None
    for line in proc.stderr:
        sys.stderr.write(line)
        sys.stderr.flush()
        m = WARNING_PATTERN.search(line)
        if m:
            warning_counts[m.group(1)] = warning_counts.get(m.group(1), 0) + 1
        if "[summary] encoders_created=" in line:
            saw_summary = True
    rc = proc.wait()

    print()
    print("=" * 60)
    print(f"[parent] child exit code: {rc}")
    # rc=4 is the partial-pool infra signal. rc!=0 catches crashes.
    # saw_summary catches the case where the child died before finishing
    # all cycles. Any of these = no valid scenario run.
    if rc != 0 or not saw_summary:
        print("[parent] INFRASTRUCTURE ERROR — child did not complete the")
        print(f"[parent] reproducer scenario (rc={rc}, saw_summary={saw_summary}).")
        print("[parent] This is NOT a valid fix-verification result.")
        return 2
    if warning_counts:
        print("[parent] DETECTED out-of-thread context warnings:")
        for kind, count in sorted(warning_counts.items()):
            print(f"    {kind}: {count}")
        print("[parent] REPRO CONFIRMED — the bug fires under this workload.")
        return 1
    print("[parent] no out-of-thread context warnings observed.")
    print("[parent] REPRO NEGATIVE — the fix appears to be effective.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pool-size", type=int, default=4,
                    help="encoders per cycle (each allocates ~0.5 MiB pinned + GPU)")
    ap.add_argument("--cycles", type=int, default=2,
                    help="number of build+contend-teardown cycles to run")
    args = ap.parse_args()

    if os.environ.get("XPRA_NVENC_CLEANUP_REPRO_CHILD"):
        return worker_main(args)
    return parent_main(args)


if __name__ == "__main__":
    sys.exit(main())
