# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import signal
import time
import subprocess
import binascii

from xpra.gtk_common.gobject_compat import import_gobject
gobject = import_gobject()
gobject.threads_init()

from xpra.net.bytestreams import TwoFileConnection
from xpra.net.protocol import Protocol
from xpra.os_util import Queue, setbinarymode, SIGNAMES
from xpra.log import Logger
log = Logger("util")


#this wrapper allows us to interact with a subprocess as if it was
#a normal class with gobject signals
#so that we can interact with it using a standard xpra protocol layer
#there is a wrapper for the caller
#and one for the class
#they talk to each other through stdin / stdout,
#using the protocol for encoding the data


DEBUG_WRAPPER = os.environ.get("XPRA_WRAPPER_DEBUG", "0")=="1"
#to make it possible to inspect files (more human readable):
HEXLIFY_PACKETS = os.environ.get("XPRA_HEXLIFY_PACKETS", "0")=="1"


class subprocess_callee(object):
    """
    This is the callee side, wrapping the gobject we want to interact with.
    All the input received will be converted to method calls on the wrapped object.
    Subclasses should register the signal handlers they want to see exported back to the caller.
    The convenience connect_export(signal-name, *args) can be used to forward signals unmodified.
    You can also call send() to pass packets back to the caller.
    (there is no validation of which signals are valid or not)
    """
    def __init__(self, input_filename="-", output_filename="-", wrapped_object=None, method_whitelist=None):
        self.mainloop = gobject.MainLoop()
        self.name = ""
        self.input_filename = input_filename
        self.output_filename = output_filename
        self.method_whitelist = None
        #the gobject instance which is wrapped:
        self.wrapped_object = wrapped_object
        self.send_queue = Queue()
        self.protocol = None
        signal.signal(signal.SIGINT, self.handle_signal)
        signal.signal(signal.SIGTERM, self.handle_signal)


    def connect_export(self, signal_name, *user_data):
        """ gobject style signal registration for the wrapped object,
            the signals will automatically be forwarded to the wrapper process
            using send(signal_name, *signal_args, *user_data)
        """
        log("connect_export%s", [signal_name] + list(user_data))
        args = list(user_data) + [signal_name]
        self.wrapped_object.connect(signal_name, self.export, *args)

    def export(self, *args):
        signal_name = args[-1]
        log("export(%s, ...)", signal_name)
        data = args[1:-1]
        self.send(signal_name, *list(data))


    def start(self):
        self.protocol = self.make_protocol()
        self.protocol.start()
        try:
            self.run()
            return 0
        except KeyboardInterrupt as e:
            log.warn("%s", e)
            return 0
        except Exception:
            log.error("error in main loop", exc_info=True)
            return 1
        finally:
            if self.protocol:
                self.protocol.close()
                self.protocol = None
            if self.input_filename=="-":
                try:
                    self._input.close()
                except:
                    pass
            if self.output_filename=="-":
                try:
                    self._output.close()
                except:
                    pass

    def make_protocol(self):
        #figure out where we read from and write to:
        if self.input_filename=="-":
            #disable stdin buffering:
            self._input = os.fdopen(sys.stdin.fileno(), 'r', 0)
            setbinarymode(self._input.fileno())
        else:
            self._input = open(self.input_filename, 'rb')
        if self.output_filename=="-":
            #disable stdout buffering:
            self._output = os.fdopen(sys.stdout.fileno(), 'w', 0)
            setbinarymode(self._output.fileno())
        else:
            self._output = open(self.output_filename, 'wb')
        #stdin and stdout wrapper:
        conn = TwoFileConnection(self._output, self._input, abort_test=None, target=self.name, info=self.name, close_cb=self.stop)
        conn.timeout = 0
        protocol = Protocol(gobject, conn, self.process_packet, get_packet_cb=self.get_packet)
        try:
            protocol.enable_encoder("rencode")
        except Exception as e:
            log.warn("failed to enable rencode: %s", e)
        protocol.enable_compressor("none")
        return protocol


    def run(self):
        self.mainloop.run()


    def stop(self):
        if self.protocol:
            self.protocol.close()
            self.protocol = None
        self.mainloop.quit()


    def handle_signal(self, sig, frame):
        """ This is for OS signals SIGINT and SIGTERM """
        signame = SIGNAMES.get(sig, sig)
        log("handle_signal(%s, %s) calling stop", signame, frame)
        self.send("signal", signame)
        #give time for the network layer to send the signal message
        time.sleep(0.1)
        self.stop()


    def send(self, *args):
        if HEXLIFY_PACKETS:
            args = args[:1]+[binascii.hexlify(str(x)[:32]) for x in args[1:]]
        log("send: adding '%s' message (%s items already in queue)", args[0], self.send_queue.qsize())
        self.send_queue.put(args)
        p = self.protocol
        if p:
            p.source_has_more()

    def get_packet(self):
        try:
            item = self.send_queue.get(False)
        except:
            item = None
        return (item, None, None, self.send_queue.qsize()>0)

    def process_packet(self, proto, packet):
        command = packet[0]
        if command==Protocol.CONNECTION_LOST:
            log("connection-lost: %s, calling stop", packet[1:])
            self.stop()
            return
        #make it easier to hookup signals to methods:
        attr = command.replace("-", "_")
        if self.method_whitelist is not None and attr not in self.method_whitelist:
            log.warn("invalid command: %s (not in whitelist: %s)", attr, self.method_whitelist)
            return
        method = getattr(self.wrapped_object, attr, None)
        if not method:
            log.warn("unknown command: %s", command)
            return
        if DEBUG_WRAPPER:
            log("calling %s.%s%s", self.wrapped_object, attr, str(tuple(packet[1:]))[:128])
        gobject.idle_add(method, *packet[1:])


class subprocess_caller(object):
    """
    This is the caller side, wrapping the subprocess.
    You can call send() to pass packets to it
     which will get converted to method calls on the receiving end,
    You can register for signals, in which case your callbacks will be called
     when those signals are forwarded back.
    (there is no validation of which signals are valid or not)
    """

    def __init__(self, description="wrapper"):
        self.process = None
        self.protocol = None
        self.command = None
        self.description = description
        self.send_queue = Queue()
        self.signal_callbacks = {}
        #hook a default packet handlers:
        self.connect(Protocol.CONNECTION_LOST, self.connection_lost)


    def connect(self, signal, cb, *args):
        """ gobject style signal registration """
        self.signal_callbacks.setdefault(signal, []).append((cb, list(args)))


    def subprocess_exit(self, *args):
        log("subprocess_exit%s command=%s", args, self.command)

    def start(self):
        self.process = self.exec_subprocess()
        self.protocol = self.make_protocol()
        self.protocol.start()

    def make_protocol(self):
        #make a connection using the process stdin / stdout
        conn = TwoFileConnection(self.process.stdin, self.process.stdout, abort_test=None, target=self.description, info=self.description, close_cb=self.subprocess_exit)
        conn.timeout = 0
        protocol = Protocol(gobject, conn, self.process_packet, get_packet_cb=self.get_packet)
        #we assume the other end has the same encoders (which is reasonable):
        #TODO: fallback to bencoder
        protocol.enable_encoder("rencode")
        #we assume this is local, so no compression:
        protocol.enable_compressor("none")
        return protocol


    def exec_subprocess(self):
        kwargs = self.exec_kwargs()
        log("exec_subprocess() command=%s, kwargs=%s", self.command, kwargs)
        return subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr.fileno(), **kwargs)

    def exec_kwargs(self):
        if os.name=="posix":
            return {"close_fds" : True}
        return {}


    def cleanup(self):
        self.stop()

    def stop(self):
        log("%s.stop()", self)
        proc = self.process
        if proc:
            try:
                proc.terminate()
                self.process = None
            except Exception as e:
                log.warn("failed to stop the wrapped subprocess %s: %s", proc, e)
        p = self.protocol
        if p:
            try:
                p.close()
                self.protocol = None
            except Exception as e:
                log.warn("failed to close the subprocess connection: %s", p, e)


    def connection_lost(self, *args):
        log("connection_lost%s", args)
        self.stop()


    def get_packet(self):
        try:
            item = self.send_queue.get(False)
        except:
            item = None
        return (item, None, None, self.send_queue.qsize()>0)

    def send(self, *packet_data):
        self.send_queue.put(packet_data)
        p = self.protocol
        if p:
            p.source_has_more()

    def process_packet(self, proto, packet):
        if DEBUG_WRAPPER:
            log("process_packet(%s, %s)", proto, [str(x)[:32] for x in packet])
        command = packet[0]
        callbacks = self.signal_callbacks.get(command)
        log("process_packet callbacks(%s)=%s", command, callbacks)
        if callbacks:
            for cb, args in callbacks:
                try:
                    all_args = list(packet[1:]) + args
                    cb(self, *all_args)
                except Exception:
                    log.error("error processing callback %s for %s packet", cb, command, exc_info=True)
