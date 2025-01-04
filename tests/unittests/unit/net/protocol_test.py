#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time
import unittest

from xpra.os_util import gi_import
from xpra.util.str_fn import csv
from xpra.util.env import envint, envbool
from xpra.common import noop, SizedBuffer
from xpra.net.protocol import socket_handler, check
from xpra.net.protocol.constants import CONNECTION_LOST
from xpra.net.bytestreams import Connection
from xpra.net.compression import Compressed
from xpra.net.common import PacketType
from xpra.log import Logger

from unit.test_util import silence_error

log = socket_handler.log

GLib = gi_import("GLib")  # @UnresolvedImport

TIMEOUT = envint("XPRA_PROTOCOL_TEST_TIMEOUT", 20)
PROFILING = envbool("XPRA_PROTOCOL_PROFILING", False)
SHOW_PERF = envbool("XPRA_SHOW_PERF", False)


class FastMemoryConnection(Connection):
    def __init__(self, read_buffers, socktype="tcp"):
        self.read_buffers = read_buffers
        self.pos = 0
        self.write_data = []
        Connection.__init__(self, "local", socktype, {})

    def read(self, n) -> SizedBuffer:
        if self.read_buffers is None:
            while self.active:
                time.sleep(0.1)
            return b""
        if not self.read_buffers:
            logger = Logger("network")
            logger("read(%i) EOF", n)
            return b""
        b = self.read_buffers[0]
        if len(b) <= n:
            return self.read_buffers.pop(0)
        self.read_buffers[0] = b[n:]
        return b[:n]

    def write(self, buf, packet_type: str = "") -> int:
        self.write_data.append(buf)
        return len(buf)

    def __repr__(self):
        return "FastMemoryConnection"


def make_profiling_protocol_class(protocol_class):

    class ProfileProtocol(protocol_class):
        def profiling_context(self, basename):
            from pycallgraph import PyCallGraph, Config     #@UnresolvedImport
            from pycallgraph.output import GraphvizOutput   #@UnresolvedImport
            config = Config()
            graphviz = GraphvizOutput(output_file='%s-%i.png' % (basename, time.monotonic()))
            return PyCallGraph(output=graphviz, config=config)

        def write_format_thread_loop(self) -> None:
            with self.profiling_context("%s-format-thread" % protocol_class.TYPE):
                socket_handler.SocketProtocol.write_format_thread_loop(self)

        def do_read_parse_thread_loop(self) -> None:
            with self.profiling_context("%s-read-parse-thread" % protocol_class.TYPE):
                socket_handler.SocketProtocol.do_read_parse_thread_loop(self)

    return ProfileProtocol


class ProtocolTest(unittest.TestCase):
    protocol_class = socket_handler.SocketProtocol

    @classmethod
    def setUpClass(cls):
        unittest.TestCase.setUpClass()
        from xpra.net import packet_encoding
        packet_encoding.init_all()
        from xpra.net import compression
        compression.init_all()

    def make_memory_protocol(self, data=(b"", ), read_buffer_size=1, hangup_delay=0,
                             process_packet_cb=noop, get_packet_cb=socket_handler.no_packet):
        conn = FastMemoryConnection(data)
        if PROFILING:
            pc = make_profiling_protocol_class(self.protocol_class)
        else:
            pc = self.protocol_class
        p = pc(conn, process_packet_cb, get_packet_cb=get_packet_cb)
        p.read_buffer_size = read_buffer_size
        p.hangup_delay = hangup_delay
        assert p.get_info()
        assert repr(p)
        p.enable_default_compressor()
        p.enable_default_encoder()
        return p

    def test_verify_packet(self) -> None:
        verify_packet = check.verify_packet

        def nok(packet) -> None:
            assert verify_packet(packet) is False, f"packet {packet} should fail verification"

        def ok(packet) -> None:
            assert verify_packet(packet) is True, f"packet {packet} should not fail verification"

        # packets are iterable, so this should fail:
        for x in (True, 1, "hello", {}, None):
            nok(x)
        ok(("foo", 1))
        ok(("foo", [1,2,3], {1:2}))
        with silence_error(socket_handler):
            try:
                saved_verify_error_fn = check.verify_error
                check.verify_error = noop
                nok(["no-floats test", 1.1])
                nok(["no-None-values", [None], {1:2}])
                nok(["no-generic-objects", [1,2,3], {object() : 2}])
                nok(["no-nested-floats", [1,2,3], {1 : 2.2}])
            finally:
                check.verify_error = saved_verify_error_fn

    def test_invalid_data(self) -> None:
        self.do_test_invalid_data([b"\0"*1])
        self.do_test_invalid_data([b"P"*8])

    def do_test_invalid_data(self, data: SizedBuffer) -> None:
        errs = []
        proto = self.make_memory_protocol(data)

        def check_failed() -> None:
            if not proto.is_closed():
                errs.append("protocol not closed")
            if proto.input_packetcount > 0:
                errs.append("processed %i packets" % proto.input_packetcount)
            if proto.input_raw_packetcount == 0:
                errs.append("not read any raw packets")
            loop.quit()

        loop = GLib.MainLoop()
        GLib.timeout_add(500, check_failed)
        GLib.timeout_add(TIMEOUT*1000, loop.quit)
        proto.start()
        loop.run()
        assert not errs, csv(errs)

    def test_encoders_and_compressors(self) -> None:
        for encoder in ("rencodeplus", ):
            for compressor in ("lz4", ):
                p = self.make_memory_protocol()
                p.enable_encoder(encoder)
                p.enable_compressor(compressor)
                packet = ("test", 1, 2, 3)
                items = p.encode(packet)
                assert items

    def test_read_speed(self) -> None:
        if not SHOW_PERF:
            return
        total_size = 0
        total_elapsed = 0
        n_packets = 0
        for i in range(15, 19):
            n, size, elapsed = self.do_test_read_speed(2**i)
            total_size += size
            total_elapsed += elapsed
            n_packets += n
        print("%-9s incoming packet processing speed:\t%iMB/s" % (
            self.protocol_class.TYPE, total_size/total_elapsed//1024//1024)
        )
        print("%-9s packets parsed per second:\t\t%i" % (
            self.protocol_class.TYPE, n_packets/elapsed)
        )

    def do_test_read_speed(self, pixel_data_size=2**18, N=100) -> None:
        # prepare some packets to parse:
        p = self.make_memory_protocol()
        # use optimal setup:
        p.enable_encoder("rencodeplus")
        p.enable_compressor("lz4")
        # catch network packets before we write them:
        data = []

        def raw_write(_packet_type, items, *_args) -> None:
            for item in items:
                data.append(item)

        p.raw_write = raw_write
        packets = self.make_test_packets(pixel_data_size)
        for packet in packets:
            p._add_packet_to_queue(packet)
        ldata = self.repeat_list(data, N)
        total_size = sum(len(item) for item in ldata)
        # catch parsed packets:
        parsed_packets = []

        def process_packet_cb(proto, packet: PacketType) -> None:
            # log.info("process_packet_cb%s", packet[0])
            if packet[0] == CONNECTION_LOST:
                loop.quit()
            else:
                parsed_packets.append(packet[0])

        # run the protocol on this data:
        loop = GLib.MainLoop()
        GLib.timeout_add(TIMEOUT*1000, loop.quit)
        proto = self.make_memory_protocol(ldata, read_buffer_size=65536, process_packet_cb=process_packet_cb)
        start = time.monotonic()
        proto.start()
        loop.run()
        end = time.monotonic()
        assert len(parsed_packets)==N*3, "expected to parse %i packets but got %i" % (N*3, len(parsed_packets))
        elapsed = (end-start)
        log("do_test_read_speed(%i) %iMB in %ims", pixel_data_size, total_size, elapsed*1000)
        return N*len(packets), total_size, elapsed

    def make_test_packets(self, pixel_data_size=2**18) -> tuple:
        pixel_data = os.urandom(pixel_data_size)
        return (
            ("test", 1, 2, 3),
            ("ping", 100, 200, 300, 0),
            ("draw", 100, 100, 640, 480, Compressed("pixel-data", pixel_data), {}),
        )

    def repeat_list(self, items, N=100) -> list:
        #repeat the same pattern N times:
        l = []
        for _ in range(N):
            for item in items:
                assert item
                l.append(item)
        return l

    def test_format_thread(self) -> None:
        packets = self.make_test_packets()
        N = 10 if not SHOW_PERF else 1000
        many = self.repeat_list(packets, N)

        def get_packet_cb() -> tuple[PacketType, bool, bool]:
            try:
                packet = many.pop(0)
                return packet, False, True
            except IndexError:
                proto.close()
                return (), False, False

        def process_packet_cb(proto, packet: PacketType):
            if packet[0] == CONNECTION_LOST:
                GLib.timeout_add(1000, loop.quit)

        proto = self.make_memory_protocol(None, process_packet_cb=process_packet_cb, get_packet_cb=get_packet_cb)
        conn = proto._conn
        loop = GLib.MainLoop()
        GLib.timeout_add(TIMEOUT*1000, loop.quit)
        proto.enable_compressor("lz4")
        proto.enable_encoder("rencodeplus")
        proto.start()
        proto.source_has_more()
        start = time.monotonic()
        loop.run()
        end = time.monotonic()
        assert proto.is_closed()
        log("protocol: %s", socket_handler.SocketProtocol)
        log("%s write-data=%s", conn, len(conn.write_data))
        total_size = sum(len(packet) for packet in conn.write_data)
        elapsed = end-start
        log("bytes=%s, elapsed=%s", total_size, elapsed)
        if SHOW_PERF:
            print("\n")
            print("%-9s format thread:\t\t\t%iMB/s" % (proto.TYPE, int(total_size/elapsed//1024//1024)))
            n_packets = len(packets)*N
            print("%-9s packets formatted per second:\t\t%i" % (proto.TYPE, int(n_packets/elapsed)))
        assert conn.write_data


try:
    from xpra.net.websockets.protocol import WebSocketProtocol

    class WebsocketProtocolTest(ProtocolTest):
        protocol_class = WebSocketProtocol
except ImportError as e:
    log.warn("Warning: skipped websocket test")
    log.warn(" %s", e)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
