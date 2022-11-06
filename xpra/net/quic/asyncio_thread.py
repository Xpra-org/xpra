# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import asyncio

from time import monotonic
from xpra.make_thread import start_thread
from xpra.log import Logger
log = Logger("quic")


singleton = None
def get_threaded_loop():
    global singleton
    if not singleton:
        singleton = threaded_asyncio_loop()
    return singleton


class threaded_asyncio_loop:
    """
    shim for quic asyncio sockets,
    this runs the asyncio main loop in a thread.
    """
    def __init__(self):
        self.loop = None
        start_thread(self.run_forever, "asyncio-thread", True)

    def run_forever(self):
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

    def call(self, f):
        log(f"call({f})")
        now = monotonic()
        while monotonic()-now<1 and self.loop is None:
            log(f"waiting for event loop")
            import time
            time.sleep(0.01)
        def tsafe():
            log("creating task")
            self.loop.create_task(f)
        log("call_soon_threadsafe")
        self.loop.call_soon_threadsafe(tsafe)
