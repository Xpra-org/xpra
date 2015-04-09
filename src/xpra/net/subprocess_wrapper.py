# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import signal
import subprocess
import binascii

from xpra.gtk_common.gobject_compat import import_gobject
gobject = import_gobject()
gobject.threads_init()

from xpra.net.bytestreams import TwoFileConnection
from xpra.net.protocol import Protocol
from xpra.os_util import Queue, setbinarymode, SIGNAMES, bytestostr
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
#avoids showing a new console window on win32:
WIN32_SHOWWINDOW = os.environ.get("XPRA_WIN32_SHOWWINDOW", "0")=="1"


#this allows us to use the gtk main loop instead:
#import gtk
#gtk.threads_init()
#class mainloop(object):
#    def run(self):
#        gtk.main()
#    def quit(self):
#        gtk.main_quit()
mainloop = gobject.MainLoop


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
        self.mainloop = mainloop()
        self.name = ""
        self.input_filename = input_filename
        self.output_filename = output_filename
        self.method_whitelist = None
        self.large_packets = []
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
            self._input = os.fdopen(sys.stdin.fileno(), 'rb', 0)
            setbinarymode(self._input.fileno())
        else:
            self._input = open(self.input_filename, 'rb')
        if self.output_filename=="-":
            #disable stdout buffering:
            self._output = os.fdopen(sys.stdout.fileno(), 'wb', 0)
            setbinarymode(self._output.fileno())
        else:
            self._output = open(self.output_filename, 'wb')
        #stdin and stdout wrapper:
        conn = TwoFileConnection(self._output, self._input, abort_test=None, target=self.name, info=self.name, close_cb=self.net_stop)
        conn.timeout = 0
        protocol = Protocol(gobject, conn, self.process_packet, get_packet_cb=self.get_packet)
        try:
            protocol.enable_encoder("rencode")
        except Exception as e:
            log.warn("failed to enable rencode: %s", e)
        protocol.enable_compressor("none")
        protocol.large_packets = self.large_packets
        return protocol


    def run(self):
        self.mainloop.run()


    def net_stop(self):
        #this is called from the network thread,
        #we use idle add to ensure we clean things up from the main thread
        log("net_stop() will call stop from main thread")
        gobject.idle_add(self.stop)

    def stop(self):
        p = self.protocol
        log("stop() protocol=%s", p)
        if p:
            self.protocol = None
            p.close()
        log("stop() stopping mainloop %s", self.mainloop)
        self.mainloop.quit()

    def handle_signal(self, sig, frame):
        """ This is for OS signals SIGINT and SIGTERM """
        #next time, just stop:
        signal.signal(signal.SIGINT, self.signal_stop)
        signal.signal(signal.SIGTERM, self.signal_stop)        
        signame = SIGNAMES.get(sig, sig)
        log("handle_signal(%s, %s) calling stop from main thread", signame, frame)
        self.send("signal", signame)
        #give time for the network layer to send the signal message
        gobject.timeout_add(150, self.stop)

    def signal_stop(self, sig, frame):
        """ This time we really want to exit without waiting """
        signame = SIGNAMES.get(sig, sig)
        log("signal_stop(%s, %s) calling stop", signame, frame)
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
        command = bytestostr(packet[0])
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
        self.large_packets = []
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
        protocol.large_packets = self.large_packets
        return protocol


    def exec_subprocess(self):
        kwargs = self.exec_kwargs()
        log("exec_subprocess() command=%s, kwargs=%s", self.command, kwargs)
        return subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr.fileno(), env=self.get_env(), **kwargs)

    def get_env(self):
        env = os.environ.copy()
        env["XPRA_SKIP_UI"] = "1"
        env["XPRA_LOG_PREFIX"] = "%s " % self.description
        #let's make things more complicated than they should be:
        #on win32, the environment can end up containing unicode, and subprocess chokes on it
        for k,v in env.items():
            try:
                env[k] = bytestostr(v.encode("utf8"))
            except:
                env[k] = bytestostr(v)
        return env

    def exec_kwargs(self):
        if os.name=="posix":
            return {"close_fds" : True}
        elif sys.platform.startswith("win"):
            if not WIN32_SHOWWINDOW:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                return {"startupinfo" : startupinfo}
        return {}


    def cleanup(self):
        self.stop()

    def stop(self):
        log("stop() sending stop request to %s", self.description)
        proc = self.process
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                self.process = None
            except Exception as e:
                log.warn("failed to stop the wrapped subprocess %s: %s", proc, e)
        p = self.protocol
        if p:
            self.protocol = None
            log("%s.stop() calling %s", self, p.close)
            try:
                p.close()
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
        command = bytestostr(packet[0])
        callbacks = self.signal_callbacks.get(command)
        log("process_packet callbacks(%s)=%s", command, callbacks)
        if callbacks:
            for cb, args in callbacks:
                try:
                    all_args = list(packet[1:]) + args
                    cb(self, *all_args)
                except Exception:
                    log.error("error processing callback %s for %s packet", cb, command, exc_info=True)
