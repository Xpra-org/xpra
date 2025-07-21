# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import asyncio
from typing import Any
from collections.abc import Awaitable, Callable

from queue import SimpleQueue
from collections import namedtuple
from collections.abc import Coroutine, Generator

from time import monotonic
from xpra.scripts.config import InitExit
from xpra.util.thread import start_thread
from xpra.util.str_fn import csv
from xpra.util.env import envbool
from xpra.os_util import WIN32
from xpra.log import Logger

log = Logger("asyncio")

WINLOOP = envbool("XPRA_WINLOOP", WIN32)
UVLOOP = envbool("XPRA_UVLOOP", not WIN32)

ExceptionWrapper = namedtuple("ExceptionWrapper", ("exception", "args"))

RETHROW = (ValueError, RuntimeError, TypeError, KeyError, IndexError, AttributeError, ImportError)


def install_winloop() -> None:
    try:
        # noinspection PyPackageRequirements
        import winloop  # pylint: disable=import-outside-toplevel
    except ImportError:
        log("install_winloop()", exc_info=True)
        log.warn("Warning: winloop not found")
        return
    log("installing winloop")
    winloop.install()
    log.info(f"winloop {winloop.__version__} installed")


def install_uvloop() -> None:
    try:
        # noinspection PyPackageRequirements
        import uvloop  # pylint: disable=import-outside-toplevel
    except ImportError:
        log("install_uvloop()", exc_info=True)
        log.warn("Warning: uvloop not found")
        return
    log("installing uvloop")
    # there's nothing we can do about this deprecation warning, so silence it:
    from xpra.util.env import SilenceWarningsContext
    with SilenceWarningsContext(DeprecationWarning):
        uvloop.install()
    log.info(f"uvloop {uvloop.__version__} installed")


class ThreadedAsyncioLoop:
    """
    shim for quic asyncio sockets,
    this runs the asyncio main loop in a thread
    and provides methods for:
    * calling functions as tasks
    * turning an async function into a sync function
     (for calling async functions from regular threads)
    """

    def __init__(self):
        self.loop: asyncio.AbstractEventLoop | None = None
        start_thread(self.run_forever, "asyncio-thread", True)
        self.wait_for_loop()

    def run_forever(self) -> None:
        if UVLOOP:
            install_uvloop()
        if WINLOOP:
            install_winloop()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop
        self.loop.run_forever()
        self.loop.close()

    def wait_for_loop(self) -> None:
        now = monotonic()
        while monotonic() - now < 1 and self.loop is None:
            log("waiting for asyncio event loop")
            time.sleep(0.01)
        if self.loop is None:
            raise RuntimeError("no asyncio main loop")

    def call_later(self, timeout: int, f: Callable, *args):
        log(f"call_later({f})")
        if not self.loop:
            raise RuntimeError("no main loop")
        return self.loop.call_later(timeout, f, *args)

    def call(self, f: Callable | Coroutine | Generator) -> None:
        log(f"call({f})")
        if not self.loop:
            raise RuntimeError("no main loop")
        if isinstance(f, (Coroutine, Generator)):

            def tsafe() -> None:
                log(f"creating task for {f}")
                assert self.loop
                self.loop.create_task(f)

            self.loop.call_soon_threadsafe(tsafe)
        else:
            self.loop.call_soon_threadsafe(f)

    def sync(self, async_fn: Callable[..., Awaitable[Any]], *args) -> Any:
        response: SimpleQueue[Any] = SimpleQueue()

        async def awaitable():
            log("awaitable()")
            try:
                a = await async_fn(*args)
                response.put(a)
            except InitExit as e:
                log(f"error calling async function {async_fn} with {args}", exc_info=True)
                response.put(ExceptionWrapper(InitExit, (e.status, str(e))))
            except Exception as e:
                log(f"error calling async function {async_fn} with {args}", exc_info=True)
                etype = type(e) if isinstance(e, RETHROW) else RuntimeError
                response.put(ExceptionWrapper(etype, (str(e),)))

        def tsafe() -> None:
            a = awaitable()
            log(f"awaitable={a}")
            assert self.loop
            f = asyncio.run_coroutine_threadsafe(a, self.loop)
            log(f"run_coroutine_threadsafe({a}, {self.loop})={f}")

        assert self.loop
        self.loop.call_soon_threadsafe(tsafe)
        log("sync: waiting for response")
        r = response.get()
        if isinstance(r, ExceptionWrapper):
            log(f"sync: re-throwing {r}")
            try:
                instance = r.exception(*r.args)
            except Exception:
                log(f"failed to re-throw {r.exception}{r.args}", exc_info=True)
                raise RuntimeError(csv(r.args)) from None
            else:
                raise instance
        log(f"sync: response={r}")
        return r


singleton: ThreadedAsyncioLoop | None = None


def get_threaded_loop() -> ThreadedAsyncioLoop:
    global singleton
    if not singleton:
        singleton = ThreadedAsyncioLoop()
    return singleton
