#!/usr/bin/env python3
# Usage: python3 main-thread-flood-DoS-client.py
#
# Demonstrates an authenticated client flooding `main_thread=True` packet handlers.
#
# Many server packet handlers are declared `main_thread=True` (cursor, window,
# pointer, ...): instead of running on the connection's parse thread, they are
# handed to the main loop with `GLib.idle_add` (see `ServerCore.call_in_main_thread`
# -> `GLibServer`). The parse thread never blocks on that hand-off, so a client that
# floods cheap main-thread packets makes the server queue them faster than the single
# main loop can run them: the GLib idle queue grows without bound - a memory + CPU DoS,
# and it starves the server's other idle-priority work.
#
# Unlike the pre-authentication `hello` / `ping` floods, the handlers abused here are
# only reachable once authenticated, so a faithful network reproducer would have to
# complete the whole password handshake first. Instead this drives the *real* server
# dispatch path in-process: a real GLib main loop wired exactly as `GLibServer` wires
# it (`call_in_main_thread = GLib.idle_add`), a real `main_thread=True` handler, and a
# background "parse thread" flooding `dispatch_packet(..., authenticated=True)`. That
# exercises the genuine `PacketDispatcher.call_packet_handler` -> throttle ->
# `GLib.idle_add` path, with `is_main_thread()` really False on the flooding thread.
#
# It runs the flood twice and prints the comparison:
#   - throttle OFF (back-pressure threshold raised out of the way): the one
#     connection's idle-queue depth and the process RSS climb without bound;
#   - throttle ON (the shipped default): the per-connection back-pressure
#     (`XPRA_MAIN_THREAD_BACKLOG`, see `PacketDispatcher.queue_main_call`) pins the
#     queue depth at the threshold and holds RSS flat, by sleeping only the flooding
#     connection's parse thread (never the main loop).

import os
import threading
import time

from xpra.os_util import gi_import
from xpra.net.common import Packet
from xpra.net import dispatch
from xpra.net.dispatch import PacketDispatcher
from xpra.util.glib_scheduler import GLibScheduler

GLib = gi_import("GLib")

DURATION = float(os.environ.get("FLOOD_SECONDS", "3"))


class Proto:
    # a stand-in connection, carrying the two per-connection main-thread
    # back-pressure counters the server sets when it creates the protocol:
    def __init__(self):
        self.main_calls_queued = 0
        self.main_calls_done = 0

    def is_closed(self) -> bool:
        return False

    def __repr__(self):
        return "Proto"


class MiniServer(PacketDispatcher, GLibScheduler):
    def __init__(self):
        PacketDispatcher.__init__(self)
        self.main_loop = GLib.MainLoop()
        self.processed = 0
        # a cheap-but-not-free main-thread handler, like a pointer / cursor update:
        self.add_packet_handler("flood", self._handle, main_thread=True)

    def call_in_main_thread(self, call) -> None:
        self.idle_add(call)

    def _handle(self, _proto, _packet) -> None:
        # a little work, so the single consumer is outrun by the producer
        # (as a real handler touching windows / damage would be):
        s = 0
        for i in range(200):
            s += i
        self.processed += 1


def rss_kb() -> int:
    with open("/proc/self/statm", encoding="latin1") as f:
        pages = int(f.read().split()[1])
    return pages * (os.sysconf("SC_PAGE_SIZE") // 1024)


def run_flood(label: str) -> None:
    server = MiniServer()
    proto = Proto()
    packet = Packet("flood", 1)

    peak_pending = 0
    peak_rss = 0
    base_rss = rss_kb()

    def sample() -> bool:
        nonlocal peak_pending, peak_rss
        peak_pending = max(peak_pending, proto.main_calls_queued - proto.main_calls_done)
        peak_rss = max(peak_rss, rss_kb())
        return True
    # timeouts outrank idle sources, so this still fires under the flood:
    GLib.timeout_add(20, sample)

    sent = [0]

    def flood() -> None:
        # the "parse thread": floods inbound packets as fast as it can
        end = time.monotonic() + DURATION
        while time.monotonic() < end:
            server.dispatch_packet(proto, packet, authenticated=True)
            sent[0] += 1
        # let the backlog drain a moment, then stop the loop:
        GLib.timeout_add(500, server.main_loop.quit)

    start = time.monotonic()
    threading.Thread(target=flood, daemon=True).start()
    server.main_loop.run()
    elapsed = time.monotonic() - start

    print(f"{label}:")
    print(f"  flooded for {DURATION:.0f}s, loop ran {elapsed:.1f}s")
    print(f"  sent         {sent[0]:>9}  ({sent[0] / DURATION:>8.0f}/s)")
    print(f"  processed    {server.processed:>9}  ({server.processed / elapsed:>8.0f}/s)")
    print(f"  peak pending {peak_pending:>9}   <-- idle-queue depth from this one connection")
    print(f"  RSS base {base_rss} KB, peak {peak_rss} KB, growth {peak_rss - base_rss} KB")


def main() -> None:
    # throttle OFF: raise the back-pressure threshold out of the way
    saved = dispatch.MAIN_THREAD_BACKLOG
    dispatch.MAIN_THREAD_BACKLOG = 10 ** 12
    try:
        run_flood("throttle OFF (unbounded idle queue)")
    finally:
        dispatch.MAIN_THREAD_BACKLOG = saved
    print()
    run_flood(f"throttle ON (XPRA_MAIN_THREAD_BACKLOG={dispatch.MAIN_THREAD_BACKLOG})")


if __name__ == "__main__":
    main()
