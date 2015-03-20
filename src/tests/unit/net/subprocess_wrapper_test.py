#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

import gobject
gobject.threads_init()

from xpra.log import enable_debug_for
enable_debug_for("all")

from xpra.gtk_common.gobject_util import one_arg_signal
from xpra.net.protocol import Protocol
from xpra.net.subprocess_wrapper import subprocess_caller, subprocess_callee
from xpra.net.bytestreams import Connection
from xpra.os_util import Queue


class fake_subprocess():
    """ defined just so the protocol layer can call terminate() on it """
    def terminate(self):
        pass

class loopback_connection(Connection):
    """ a fake connection which just writes back whatever is sent to it """
    def __init__(self, *args):
        Connection.__init__(self, *args)
        self.queue = Queue()

    def read(self, n):
        self.may_abort("read")
        #FIXME: we don't handle n...
        return self.queue.get(True)

    def write(self, buf):
        self.may_abort("write")
        self.queue.put(buf)
        return len(buf)

    def may_abort(self, action):
        return False

def loopback_protocol(process_packet_cb, get_packet_cb):
    conn = loopback_connection("fake", "fake")
    protocol = Protocol(gobject, conn, process_packet_cb, get_packet_cb=get_packet_cb)
    protocol.enable_encoder("rencode")
    protocol.enable_compressor("none")
    return protocol


class loopback_process(subprocess_caller):
    """ a fake subprocess which uses the loopback connection """
    def exec_subprocess(self):
        return fake_subprocess()
    def make_protocol(self):
        return loopback_protocol(self.process_packet, self.get_packet)


class loopback_callee(subprocess_callee):

    def make_protocol(self):
        return loopback_protocol(self.process_packet, self.get_packet)


class TestCallee(gobject.GObject):
    __gsignals__ = {
        "test-signal": one_arg_signal,
        }

gobject.type_register(TestCallee)


class SubprocessWrapperTest(unittest.TestCase):

    def test_loopback_caller(self):
        mainloop = gobject.MainLoop()
        lp = loopback_process()
        readback = []
        def record_packet(self, *args):
            readback.append(args)
        lp.connect("foo", record_packet)
        def end(*args):
            mainloop.quit()
        lp.connect("end", end)
        self.timeout = False
        def timeout_error():    
            self.timeout = True
            mainloop.quit()
        gobject.timeout_add(500, timeout_error)
        gobject.idle_add(lp.send, "foo", "hello foo")
        gobject.idle_add(lp.send, "bar", "hello bar")
        gobject.idle_add(lp.send, "end")
        lp.stop = mainloop.quit
        #run!
        lp.start()
        mainloop.run()
        assert len(readback)==1, "expected 1 record in loopback but got %s" % len(readback)
        assert readback[0][0] == "hello foo"
        assert self.timeout is False, "the test did not exit cleanly (not received the 'end' packet?)"

    def test_loopback_callee(self):
        callee = TestCallee()
        lc = loopback_callee(wrapped_object=callee, method_whitelist=["test-signal", "stop", "unused"])
        #this will cause the "test-signal" to be sent via the loopback connection
        lc.connect_export("test-signal")
        readback = []
        def test_signal_function(*args):
            #print("test_signal_function%s" % str(args))
            readback.append(args)
        #hook up a function which will be called when the wrapper converts the packet into a method call:
        callee.test_signal = test_signal_function
        #lc.connect_export("test-signal", hello)
        self.timeout = False
        def timeout_error():    
            self.timeout = True
            lc.stop()
        gobject.timeout_add(500, timeout_error)
        gobject.idle_add(callee.emit, "test-signal", "hello foo")
        #hook up a stop function call which ends this test cleanly
        def stop(*args):
            lc.stop()
        callee.stop = stop
        gobject.idle_add(lc.send, "stop")
        #run!
        lc.start()
        assert len(readback)==1, "expected 1 record in loopback but got %s" % len(readback)
        assert readback[0][0] == "hello foo"
        assert self.timeout is False, "the test did not exit cleanly (not received the 'end' packet?)"

def main():
    unittest.main()

if __name__ == '__main__':
    main()
