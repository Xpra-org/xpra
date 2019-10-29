# This file is part of Xpra.
# Copyright (C) 2011-2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from threading import Lock

from xpra.log import Logger

log = Logger("network", "protocol")


class FakeJitter:

    def __init__(self, timeout_add, process_packet_cb, delay):
        self.timeout_add = timeout_add
        self.real_process_packet_cb = process_packet_cb
        self.delay = delay
        self.ok_delay = 10*1000
        self.delaying = False
        self.pending = []
        self.lock = Lock()
        self.flush()

    def start_buffering(self):
        log.info("FakeJitter.start_buffering() will buffer for %s ms", self.delay)
        self.delaying = True
        self.timeout_add(self.delay, self.flush)

    def flush(self):
        log.info("FakeJitter.flush() processing %s delayed packets", len(self.pending))
        with self.lock:
            for proto, packet in self.pending:
                self.real_process_packet_cb(proto, packet)
            self.pending = []
            self.delaying = False
        self.timeout_add(self.ok_delay, self.start_buffering)
        log.info("FakeJitter.flush() will start buffering again in %s ms", self.ok_delay)

    def process_packet_cb(self, proto, packet):
        with self.lock:
            if self.delaying:
                self.pending.append((proto, packet))
            else:
                self.real_process_packet_cb(proto, packet)
