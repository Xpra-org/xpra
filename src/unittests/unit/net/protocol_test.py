#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

from xpra.util import csv
from xpra.os_util import monotonic_time
from xpra.net.protocol import Protocol
from xpra.net.bytestreams import Connection
from xpra.net.compression import Compressed
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
        #log("read(%i)=%r", n, buf)
        return buf

    def write(self, buf):
        #log("write(%r)", buf)
        self.write_data.append(buf)
        return len(buf)


def noop(*args):
    pass

def nodata(*args):
    return None


class ProtocolTest(unittest.TestCase):

    def run_memory_protocol(self, data=b"", read_buffer_size=1, hangup_delay=0, process_packet_cb=noop, get_packet_cb=nodata):
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
        def check_failed():
            if not protocol._closed:
                errs.append("protocol not closed")
            if protocol.input_packetcount>0:
                errs.append("processed %i packets" % protocol.input_packetcount)
            if protocol.input_raw_packetcount==0:
                errs.append("not read any raw packets")
        loop = glib.MainLoop()
        glib.timeout_add(200, check_failed)
        glib.timeout_add(400, loop.quit)
        loop.run()
        assert not errs, "%s" % csv(errs)

    def test_encoders_and_compressors(self):
        for encoder in ("rencode", "bencode"):
            for compressor in ("lz4", "zlib"):
                p = self.run_memory_protocol()
                p.enable_encoder(encoder)
                p.enable_compressor(compressor)
                packet = ("test", 1, 2, 3)
                items = p.encode(packet)
                assert items

    def test_read_speed(self):
        #prepare some packets to parse:
        p = self.run_memory_protocol()
        #use optimal setup:
        p.enable_encoder("rencode")
        p.enable_compressor("lz4")
        data = []
        def raw_write(items, *args):
            for item in items:
                data.append(item)
        p.raw_write = raw_write
        pixel_data = os.urandom(2**17)
        for packet in (
            ("test", 1, 2, 3),
            ("ping", 1),
            ("draw", Compressed("pixel-data", pixel_data)),
            ):
            p._add_packet_to_queue(packet)
        #print("data=%r" % csv(data))
        N = 100
        buf = (b"".join(data))*N
        parsed_packets = []
        def process_packet_cb(proto, packet):
            #log.info("process_packet_cb%s", packet[0])
            if packet[0]==Protocol.CONNECTION_LOST:
                loop.quit()
            else:
                parsed_packets.append(packet[0])
        start = monotonic_time()
        p = self.run_memory_protocol(buf, read_buffer_size=65536, process_packet_cb=process_packet_cb)
        loop = glib.MainLoop()
        glib.timeout_add(5000, loop.quit)
        loop.run()
        end = monotonic_time()
        assert len(parsed_packets)==N*3, "expected to parse %i packets but got %i" % (N*3, len(parsed_packets))
        log("elapsed: %ims", (end-start)*1000)
        log.info("incoming packet processing speed: %iMB/s", len(buf)/(end-start)//1024//1024)
        

def main():
    unittest.main()

if __name__ == '__main__':
    main()
