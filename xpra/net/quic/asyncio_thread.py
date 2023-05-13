# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import asyncio
from queue import Queue
from collections import namedtuple
from collections.abc import Coroutine, Generator

from time import monotonic
from xpra.make_thread import start_thread
from xpra.util import envbool
from xpra.os_util import WIN32
from xpra.log import Logger
log = Logger("quic")


UVLOOP = envbool("XPRA_UVLOOP", not WIN32)


singleton = None
def get_threaded_loop():
    global singleton
    if not singleton:
        singleton = threaded_asyncio_loop()
    return singleton


ExceptionWrapper = namedtuple("ExceptionWrapper", "exception")


class threaded_asyncio_loop:
    """
    shim for quic asyncio sockets,
    this runs the asyncio main loop in a thread
    and provides methods for:
    * calling functions as tasks
    * turning an async function into a sync function
     (for calling async functions from regular threads)
    """
    def __init__(self):
        self.loop = None
        start_thread(self.run_forever, "asyncio-thread", True)
        self.wait_for_loop()

    def run_forever(self):
        if UVLOOP:
            try:
                import uvloop  # pylint: disable=import-outside-toplevel
            except ImportError:
                log.info("no uvloop")
            else:
                log("installing uvloop")
                uvloop.install()
                log.info("uvloop installed")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop
        self.loop.run_forever()
        self.loop.close()

    def wait_for_loop(self):
        now = monotonic()
        while monotonic()-now<1 and self.loop is None:
            log("waiting for asyncio event loop")
            time.sleep(0.01)
        if self.loop is None:
            raise RuntimeError("no asyncio main loop")

    def call(self, f):
        log(f"call({f})")
        def tsafe():
            log(f"creating task for {f}")
            self.loop.create_task(f)
        log("call_soon_threadsafe")
        if isinstance(f, (Coroutine, Generator)):
            self.loop.call_soon_threadsafe(tsafe)
        else:
            self.loop.call_soon_threadsafe(f)


    def sync(self, async_fn, *args):
        response = Queue()
        async def awaitable():
            log("awaitable()")
            try:
                r = await async_fn(*args)
                response.put(r)
            except Exception as e:
                log(f"error calling async function {async_fn} with {args}", exc_info=True)
                response.put(ExceptionWrapper(e))
        def tsafe():
            r = awaitable()
            log(f"awaitable={r}")
            f = asyncio.run_coroutine_threadsafe(r, self.loop)
            log(f"run_coroutine_threadsafe({r}, {self.loop})={f}")
        self.loop.call_soon_threadsafe(tsafe)
        log("sync: waiting for response")
        r = response.get()
        if isinstance(r, ExceptionWrapper):
            e = r.exception
            raise Exception(str(e) or type(e))
        log(f"sync: response={r}")
        return r
