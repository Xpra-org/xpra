#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import csv
from xpra.net.protocol import Protocol
from xpra.net.bytestreams import Connection
from xpra.gtk_common.gobject_compat import import_glib
from xpra.log import Logger

glib = import_glib()
glib.threads_init()

log = Logger("network")

class FastMemoryConnection(Connection):
    def __init__(self, read_data, socktype="tcp"):
        self.read_data = read_data
        self.write_data = []
        Connection.__init__(self, "local", socktype, {})

    def read(self, n):
        buf = self.read_data[:n]
        self.read_data = self.read_data[n:]
        log("read(%i)=%r", n, buf)
        return buf

    def write(self, buf):
        log("write(%r)", buf)
        self.write_data.append(buf)
        return len(buf)


class ProtocolTest(unittest.TestCase):

    def run_memory_protocol(self, data=b"", read_buffer_size=1, hangup_delay=0):
        def process_packet_cb(*args):
            pass
        def get_packet_cb(*args):
            return None
        conn = FastMemoryConnection(data)
        p = Protocol(glib, conn, process_packet_cb, get_packet_cb=get_packet_cb)
        p.read_buffer_size = read_buffer_size
        p.hangup_delay = hangup_delay
        p.start()
        return p

    def test_invalid_data(self):
        self.do_test_invalid_data(b"\0"*1)
        self.do_test_invalid_data(b"P"*8)

    def do_test_invalid_data(self, data):
        errs = []
        protocol = self.run_memory_protocol(data)
        loop = glib.MainLoop()
        def check_failed():
            if not protocol._closed:
                errs.append("protocol not closed")
            if protocol.input_packetcount>0:
                errs.append("processed %i packets" % protocol.input_packetcount)
            if protocol.input_raw_packetcount==0:
                errs.append("not read any raw packets")
        glib.timeout_add(200, check_failed)
        glib.timeout_add(400, loop.quit)
        loop.run()
        assert not errs, "%s" % csv(errs)

    def test_read(self):
        pass


def main():
    unittest.main()

if __name__ == '__main__':
    main()
