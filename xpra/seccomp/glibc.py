# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# glibc reads some files lazily, from whichever thread happens to get there first.
# If that is a filtered thread, the `openat` is blocked and the process is killed,
# so `prepare()` gets these reads out of the way before the first filter is installed.

import os
import platform
from threading import Lock

from xpra.util.env import envbool, envint
from xpra.util.thread import start_thread
from xpra.log import Logger

log = Logger("seccomp")

# see `prewarm_malloc_arena`:
PREWARM: bool = envbool("XPRA_MALLOC_PREWARM", True)
PREWARM_CHUNK: int = envint("XPRA_MALLOC_PREWARM_CHUNK", 128 * 1024)
PREWARM_COUNT: int = envint("XPRA_MALLOC_PREWARM_COUNT", 64)
PREWARM_TIMEOUT: int = envint("XPRA_MALLOC_PREWARM_TIMEOUT", 10)
# see `set_arena_max`:
ARENA_MAX: bool = envbool("XPRA_MALLOC_ARENA_MAX", True)
M_ARENA_MAX = -8
# glibc's default limit is 8 arenas per core on 64-bit (2 on 32-bit), see `NARENAS_FROM_NCORES`:
ARENAS_PER_CORE = 8 if platform.architecture()[0] == "64bit" else 2

prepare_lock = Lock()
prepared = False


def is_glibc() -> bool:
    return platform.libc_ver()[0] == "glibc"


def prepare() -> None:
    # only runs once per process, on the first thread installing a filter (still unfiltered):
    global prepared
    with prepare_lock:
        if prepared:
            return
        prepared = True
        if not is_glibc():
            return
        with log.trap_error("Error setting the malloc arena limit"):
            set_arena_max()
        with log.trap_error("Error pre-warming the malloc arena"):
            prewarm_malloc_arena()


def set_arena_max() -> None:
    """
    The first time a thread needs a new malloc arena once there are more than 8 of them,
    glibc computes the arena limit: `tcache_init` -> `arena_get2` -> `get_nprocs`, which reads
    `/sys/devices/system/cpu/online` (and `/proc/stat` if that fails), then caches the result.
    Which thread gets there first depends on lock contention, so this is a random `SIGSYS`.
    Setting `M_ARENA_MAX` makes glibc use our value instead, so it never reads those files.
    We use the same value glibc would have computed, so nothing else changes.
    """
    if not ARENA_MAX:
        log("set_arena_max() disabled")
        return
    from ctypes import CDLL, c_int
    arena_max = ARENAS_PER_CORE * (os.cpu_count() or 1)
    mallopt = CDLL(None).mallopt
    mallopt.argtypes = (c_int, c_int)
    mallopt.restype = c_int
    r = mallopt(M_ARENA_MAX, arena_max)
    log("set_arena_max() mallopt(M_ARENA_MAX, %i)=%i", arena_max, r)


def prewarm_malloc_arena() -> None:
    """
    glibc reads `/proc/sys/vm/overcommit_memory` - and caches the answer for the whole
    process - the first time it trims a thread's malloc arena. That happens when a thread
    *exits*: `__malloc_arena_thread_freeres` -> `_int_free_maybe_trim` -> `heap_trim` ->
    `shrink_heap` -> `check_may_shrink_heap`. If the first thread to get there is a
    filtered one, the `openat` is blocked and the process is killed - not while decoding,
    but at shutdown, when the decode thread finally exits.
    So provoke that read here, from a throwaway thread, while we are still unfiltered.
    (harmless on a libc that does not do this - it is just some allocation churn)

    It has to be a thread *exit*: there is no cheaper way in, and both of the obvious
    shortcuts have been tried and do not work.
    * `check_may_shrink_heap` (and `heap_trim` / `shrink_heap`) are `static` in glibc:
      they are not in the dynamic symbol table, so `ctypes` cannot call them.
    * `malloc_trim(0)` *is* exported, but `mtrim()` consolidates, `madvise`s the free
      chunks and then calls `systrim()` - the main-arena/`sbrk` trim. It never reaches
      `heap_trim`, so it never reads the file. Neither does a plain large `malloc`/`free`
      (nothing left at the top of the heap to shrink). Only the arena teardown does.

    Only worth doing when a filter is actually going to be installed, and it can be turned
    off with `XPRA_MALLOC_PREWARM=0` - at the risk of that `SIGSYS` at shutdown.
    """
    if not PREWARM:
        log("prewarm_malloc_arena() disabled")
        return

    def churn() -> None:
        chunks = [bytes(PREWARM_CHUNK) for _ in range(PREWARM_COUNT)]
        chunks.clear()

    log("prewarm_malloc_arena() %i x %i bytes", PREWARM_COUNT, PREWARM_CHUNK)
    thread = start_thread(churn, "malloc-prewarm", daemon=True)
    thread.join(PREWARM_TIMEOUT)
