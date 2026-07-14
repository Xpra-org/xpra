# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import sleep
from queue import SimpleQueue
from threading import Thread
from typing import Any
from collections.abc import Callable

from xpra.os_util import LINUX
from xpra.exit_codes import ExitCode, ExitValue
from xpra.util.thread import start_thread
from xpra.client.base.stub import StubClientSubsystem
from xpra.log import Logger

log = Logger("client", "decode")

WorkItem = tuple[Callable, tuple]


class Decode(StubClientSubsystem):
    """
    A single worker thread for decoding the untrusted data sent by the server:
    picture and video frames, window icons, cursors.

    Subsystems post work to it with `add_decode_work(method, *args)`
    (see `StubClientSubsystem`), and it runs under a seccomp filter which denies
    all file access - see `docs/Usage/Seccomp.md`.
    Anything a consumer will import from this thread must be imported from its
    `preload_decode()` hook, which runs before the filter is installed.
    """
    PREFIX = "decode"

    def __init__(self, client=None):
        StubClientSubsystem.__init__(self, client)
        self._queue = SimpleQueue[WorkItem | None]()
        self._thread: Thread | None = None
        self._counter: int = 0

    def run(self) -> ExitValue:
        self._thread = start_thread(self._decode_thread_loop, "decode")
        return ExitCode.OK

    def cleanup(self) -> None:
        # tell the decode thread to exit:
        self._queue.put(None)
        thread = self._thread
        log("Decode.cleanup() thread=%s, alive=%s", thread, thread and thread.is_alive())
        if thread and thread.is_alive():
            thread.join(0.1)

    def get_info(self) -> dict[str, Any]:
        return {Decode.PREFIX: {"counter": self._counter}}

    def add_work(self, fn: Callable, *args) -> None:
        self._queue.put((fn, args))

    def _decode_thread_loop(self) -> None:
        self.preload()
        if LINUX:
            self.install_seccomp()
        while self.client.exit_code is None:
            item = self._queue.get()
            if item is None:
                log("decode queue found exit marker")
                break
            fn, args = item
            self._counter += 1
            with log.trap_error("Error in decode work %s%s", fn, args):
                fn(*args)
                sleep(0)
        self._thread = None
        log("decode thread ended")

    def preload(self) -> None:
        # The decode thread is the sole initializer of the codecs it will use: loading them
        # here (before the seccomp filter below, and before any work item is processed)
        # guarantees every codec import / `dlopen` / self-test - and any transient decoder
        # worker thread the self-tests spawn - happens on this thread while it is still
        # unfiltered, and in a well-defined order relative to the filter. Every other
        # consumer waits for this via `Encodings.ensure_codecs_loaded`.
        # The other subsystems then get to import whatever else they will need here:
        # a first-time import once the filter is installed would hit `openat` and be blocked
        # (fatally so - a `SIGSYS` kill is not something `trap_error` can recover from).
        # See `docs/Usage/Seccomp.md`.
        if encoding := self.get_subsystem("encoding"):
            log("preload() loading codecs from the decode thread")
            with log.trap_error("Error loading codecs from the decode thread"):
                encoding.load_all_codecs()
        for subsystem in tuple(getattr(self.client, "subsystems", {}).values()):
            if subsystem is self:
                continue
            with log.trap_error("Error preloading %s", subsystem):
                subsystem.preload_decode()

    @staticmethod
    def install_seccomp() -> None:
        sclog = Logger("seccomp")
        sclog("install_seccomp()")
        try:
            # `xpra.seccomp.draw` is the `decode` filter, under its original file name:
            from xpra.seccomp import draw as seccomp_decode
        except ImportError:
            sclog.warn("Warning: seccomp module is not available")
            return
        try:
            installed = seccomp_decode.install_thread()
            sclog("seccomp installed=%s", installed)
        except Exception:
            sclog.error("Error installing decode thread seccomp filter", exc_info=True)
