#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from typing import Any
from queue import SimpleQueue
from collections.abc import Callable

from xpra.util.gobject import one_arg_signal
from xpra.net.protocol.socket_handler import SocketProtocol
from xpra.net.subprocess_wrapper import SubprocessCaller, SubprocessCallee
from xpra.net.bytestreams import Connection
from xpra.net.common import Packet
from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("test")

TEST_TIMEOUT = 10*1000

GObject = gi_import("GObject")
GLib = gi_import("GLib")


class FakeSubprocess:
    """ defined just so the protocol layer can call terminate() on it """
    def __init__(self):
        self.returncode: int | None = None

    def terminate(self) -> None:
        self.returncode = 1

    def poll(self) -> int | None:
        return self.returncode


class LoopbackConnection(Connection):
    """ a fake connection which just writes back whatever is sent to it """
    def __init__(self, *args):
        Connection.__init__(self, *args)
        self.queue = SimpleQueue()

    def read(self, _n):
        self.may_abort("read")
        # FIXME: we don't handle n...
        return self.queue.get(True)

    def write(self, buf, packet_type: str = "") -> int:
        self.may_abort("write")
        self.queue.put(buf)
        return len(buf)

    def close(self) -> None:
        self.queue.put(None)
        Connection.close(self)

    def may_abort(self, _action) -> None:
        assert self.active


def loopback_protocol(process_packet_cb: Callable[[Any, Packet], None],
                      get_packet_cb: Callable[[], [Packet, bool, bool]]) -> SocketProtocol:
    conn = LoopbackConnection("fake", "fake")
    protocol = SocketProtocol(conn, process_packet_cb, get_packet_cb=get_packet_cb)
    protocol.enable_encoder("rencodeplus")
    protocol.enable_compressor("none")
    return protocol


class LoopbackProcess(SubprocessCaller):
    """ a fake subprocess which uses the loopback connection """
    def exec_subprocess(self):
        return FakeSubprocess()

    def make_protocol(self) -> SocketProtocol:
        return loopback_protocol(self.process_packet, self.get_packet)


class LoopbackCallee(SubprocessCallee):

    def make_protocol(self) -> SocketProtocol:
        return loopback_protocol(self.process_packet, self.get_packet)


class TestCallee(GObject.GObject):
    __gsignals__ = {
        "test-signal": one_arg_signal,
    }


GObject.type_register(TestCallee)


class SubprocessWrapperTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        unittest.TestCase.setUpClass()
        from xpra.net import packet_encoding
        packet_encoding.init_all()
        from xpra.net import compression
        compression.init_compressors("none")

    def test_loopback_caller(self) -> None:
        mainloop = GLib.MainLoop()
        lp = LoopbackProcess()
        readback = []

        def record_packet(_lp, *args) -> None:
            readback.append(args)
        lp.connect("foo", record_packet)

        def stop() -> None:
            # this may deadlock on win32..
            lp.stop_protocol()
            lp.stop_process()
            GLib.idle_add(mainloop.quit)

        def end(*_args) -> None:
            stop()

        lp.connect("end", end)
        self.timeout = False

        def timeout_error() -> None:
            self.timeout = True
            stop()
        GLib.timeout_add(TEST_TIMEOUT, timeout_error)
        sent_str = b"hello foo"
        GLib.idle_add(lp.send, "foo", sent_str)
        GLib.idle_add(lp.send, "bar", b"hello bar")
        GLib.idle_add(lp.send, "end")
        lp.stop = stop
        # run!
        lp.start()
        mainloop.run()
        assert len(readback)==1, "expected 1 record in loopback but got %s" % len(readback)
        rss = readback[0][0]
        assert rss== sent_str, "expected message string '%s' but got '%s'" % (sent_str, rss)
        assert self.timeout is False, "the test did not exit cleanly (not received the 'end' packet?)"

    def test_loopback_callee(self) -> None:
        mainloop = GLib.MainLoop()
        callee = TestCallee()
        lc = LoopbackCallee(wrapped_object=callee, method_whitelist=["test_signal", "loop_stop", "unused"])
        # this will cause the "test-signal" to be sent via the loopback connection
        lc.connect_export("test-signal")
        readback = []

        def test_signal_function(*args) -> None:
            log("test_signal_function%s", args)
            readback.append(args)
            GLib.idle_add(lc.send, "loop_stop")
        # hook up a function which will be called when the wrapper converts the packet into a method call:
        callee.test_signal = test_signal_function
        # lc.connect_export("test-signal", hello)
        self.timeout = False
        callee.timeout_fn = None

        def loop_stop(*args) -> None:
            log("loop_stop%s timeout_fn=%s", args, callee.timeout_fn)
            if callee.timeout_fn:
                GLib.source_remove(callee.timeout_fn)
                callee.timeout_fn = None
            lc.stop()
            GLib.idle_add(mainloop.quit)

        def timeout_error() -> None:
            log.warn("timeout_error")
            callee.timeout_fn = None
            self.timeout = True
            loop_stop()
        callee.timeout_fn = GLib.timeout_add(TEST_TIMEOUT, timeout_error)
        signal_string = b"hello foo"
        GLib.idle_add(callee.emit, "test-signal", signal_string)
        # hook up a stop function call which ends this test cleanly
        callee.loop_stop = loop_stop
        # run!
        lc.start()
        mainloop.run()
        lc.stop()
        log("readback=%s", readback)
        assert len(readback) == 1, "expected 1 record in loopback but got %s" % len(readback)
        rss = readback[0][0]
        log("rss=%s, timeout=%s", rss, self.timeout)
        assert rss == signal_string, "expected signal string '%s' but got '%s'" % (signal_string, rss)
        assert self.timeout is False, "the test did not exit cleanly (not received the 'end' packet?)"


def main():
    unittest.main()


if __name__ == '__main__':
    main()
