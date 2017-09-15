# This file is part of Xpra.
# Copyright (C) 2015, 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import signal
import subprocess
import binascii

from xpra.gtk_common.gobject_compat import import_glib
from xpra.util import repr_ellipsized, envint, envbool

from xpra.net.bytestreams import TwoFileConnection
from xpra.net import ConnectionClosedException
from xpra.net.protocol import Protocol
from xpra.os_util import Queue, setbinarymode, SIGNAMES, bytestostr
from xpra.child_reaper import getChildReaper
from xpra.log import Logger
log = Logger("util")


#this wrapper allows us to interact with a subprocess as if it was
#a normal class with gobject signals
#so that we can interact with it using a standard xpra protocol layer
#there is a wrapper for the caller
#and one for the class
#they talk to each other through stdin / stdout,
#using the protocol for encoding the data


WIN32 = sys.platform.startswith("win")

DEBUG_WRAPPER = envbool("XPRA_WRAPPER_DEBUG", False)
#to make it possible to inspect files (more human readable):
HEXLIFY_PACKETS = envbool("XPRA_HEXLIFY_PACKETS", False)
#avoids showing a new console window on win32:
WIN32_SHOWWINDOW = envbool("XPRA_WIN32_SHOWWINDOW", False)
#this used to cause problems with py3k / gi bindings?
HANDLE_SIGINT = envbool("XPRA_WRAPPER_SIGINT", True)

FAULT_RATE = envint("XPRA_WRAPPER_FAULT_INJECTION_RATE")
if FAULT_RATE>0:
    _counter = 0
    def INJECT_FAULT(p):
        global _counter
        _counter += 1
        if (_counter % FAULT_RATE)==0:
            log.warn("injecting fault in %s", p)
            p.raw_write("Wrapper JUNK! added by fault injection code")
else:
    def INJECT_FAULT(p):
        pass


def setup_fastencoder_nocompression(protocol):
    from xpra.net.packet_encoding import get_enabled_encoders, PERFORMANCE_ORDER
    encoders = get_enabled_encoders(PERFORMANCE_ORDER)
    assert len(encoders)>0, "no packet encoders available!?"
    for encoder in encoders:
        try:
            protocol.enable_encoder(encoder)
            log("protocol using %s", encoder)
            break
        except Exception as e:
            log("failed to enable %s: %s", encoder, e)
    #we assume this is local, so no compression:
    protocol.enable_compressor("none")


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
        self.name = ""
        self.input_filename = input_filename
        self.output_filename = output_filename
        self.method_whitelist = method_whitelist
        self.large_packets = []
        #the gobject instance which is wrapped:
        self.wrapped_object = wrapped_object
        self.send_queue = Queue()
        self.protocol = None
        if HANDLE_SIGINT:
            #this breaks gobject3!
            signal.signal(signal.SIGINT, self.handle_signal)
        signal.signal(signal.SIGTERM, self.handle_signal)
        self.setup_mainloop()

    def setup_mainloop(self):
        glib = import_glib()
        self.mainloop = glib.MainLoop()
        self.idle_add = glib.idle_add
        self.timeout_add = glib.timeout_add
        self.source_remove = glib.source_remove


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
            if str(e):
                log.warn("%s", e)
            return 0
        except Exception:
            log.error("error in main loop", exc_info=True)
            return 1
        finally:
            self.cleanup()
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
        conn = TwoFileConnection(self._output, self._input, abort_test=None, target=self.name, socktype=self.name, close_cb=self.net_stop)
        conn.timeout = 0
        protocol = Protocol(self, conn, self.process_packet, get_packet_cb=self.get_packet)
        setup_fastencoder_nocompression(protocol)
        protocol.large_packets = self.large_packets
        return protocol


    def run(self):
        self.mainloop.run()


    def net_stop(self):
        #this is called from the network thread,
        #we use idle add to ensure we clean things up from the main thread
        log("net_stop() will call stop from main thread")
        self.idle_add(self.stop)


    def cleanup(self):
        pass

    def stop(self):
        self.cleanup()
        p = self.protocol
        log("stop() protocol=%s", p)
        if p:
            self.protocol = None
            p.close()
        self.do_stop()

    def do_stop(self):
        log("stop() stopping mainloop %s", self.mainloop)
        self.mainloop.quit()

    def handle_signal(self, sig, frame):
        """ This is for OS signals SIGINT and SIGTERM """
        #next time, just stop:
        signal.signal(signal.SIGINT, self.signal_stop)
        signal.signal(signal.SIGTERM, self.signal_stop)
        signame = SIGNAMES.get(sig, sig)
        try:
            log("handle_signal(%s, %s) calling stop from main thread", signame, frame)
        except:
            pass        #may fail if we were doing IO logging when the signal was received
        self.send("signal", signame)
        self.timeout_add(0, self.cleanup)
        #give time for the network layer to send the signal message
        self.timeout_add(150, self.stop)

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
        INJECT_FAULT(p)

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
            self.net_stop()
            return
        elif command==Protocol.GIBBERISH:
            log.warn("gibberish received:")
            log.warn(" %s", repr_ellipsized(packet[1], limit=80))
            log.warn(" stopping")
            self.net_stop()
            return
        elif command=="stop":
            log("received stop message")
            self.net_stop()
            return
        elif command=="exit":
            log("received exit message")
            sys.exit(0)
            return
        #make it easier to hookup signals to methods:
        attr = command.replace("-", "_")
        if self.method_whitelist is not None and attr not in self.method_whitelist:
            log.warn("invalid command: %s (not in whitelist: %s)", attr, self.method_whitelist)
            return
        wo = self.wrapped_object
        if not wo:
            log("wrapped object is no more, ignoring method call '%s'", attr)
            return
        method = getattr(wo, attr, None)
        if not method:
            log.warn("unknown command: '%s'", attr)
            log.warn(" packet: '%s'", repr_ellipsized(str(packet)))
            return
        if DEBUG_WRAPPER:
            log("calling %s.%s%s", wo, attr, str(tuple(packet[1:]))[:128])
        self.idle_add(method, *packet[1:])
        INJECT_FAULT(proto)


def exec_kwargs():
    kwargs = {}
    stderr = sys.stderr.fileno()
    if os.name=="posix":
        kwargs["close_fds"] = True
    elif WIN32:
        from xpra.platform.win32 import REDIRECT_OUTPUT
        if REDIRECT_OUTPUT:
            #stderr is not valid and would give us this error:
            # WindowsError: [Errno 6] The handle is invalid
            stderr = open(os.devnull, 'w')
        if not WIN32_SHOWWINDOW:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0     #aka win32.con.SW_HIDE
            kwargs["startupinfo"] = startupinfo
    kwargs["stderr"] = stderr
    return kwargs

def exec_env(blacklist=["LS_COLORS", ]):
    env = os.environ.copy()
    env["XPRA_SKIP_UI"] = "1"
    env["XPRA_FORCE_COLOR_LOG"] = "1"
    #let's make things more complicated than they should be:
    #on win32, the environment can end up containing unicode, and subprocess chokes on it
    for k,v in env.items():
        if k in blacklist:
            continue
        try:
            env[k] = bytestostr(v.encode("utf8"))
        except:
            env[k] = bytestostr(v)
    return env


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
        self.connect(Protocol.GIBBERISH, self.gibberish)
        glib = import_glib()
        self.idle_add = glib.idle_add
        self.timeout_add = glib.timeout_add
        self.source_remove = glib.source_remove


    def connect(self, signal, cb, *args):
        """ gobject style signal registration """
        self.signal_callbacks.setdefault(signal, []).append((cb, list(args)))


    def subprocess_exit(self, *args):
        #beware: this may fire more than once!
        log("subprocess_exit%s command=%s", args, self.command)
        self._fire_callback("exit")

    def start(self):
        self.start = self.fail_start
        self.process = self.exec_subprocess()
        self.protocol = self.make_protocol()
        self.protocol.start()

    def fail_start(self):
        raise Exception("this wrapper has already been started")

    def abort_test(self, action):
        p = self.process
        if p is None or p.poll():
            raise ConnectionClosedException("cannot %s: subprocess has terminated" % action)

    def make_protocol(self):
        #make a connection using the process stdin / stdout
        conn = TwoFileConnection(self.process.stdin, self.process.stdout, abort_test=self.abort_test, target=self.description, socktype=self.description, close_cb=self.subprocess_exit)
        conn.timeout = 0
        protocol = Protocol(self, conn, self.process_packet, get_packet_cb=self.get_packet)
        setup_fastencoder_nocompression(protocol)
        protocol.large_packets = self.large_packets
        return protocol


    def exec_subprocess(self):
        kwargs = exec_kwargs()
        env = self.get_env()
        log("exec_subprocess() command=%s, env=%s, kwargs=%s", self.command, env, kwargs)
        proc = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env, **kwargs)
        getChildReaper().add_process(proc, self.description, self.command, True, True, callback=self.subprocess_exit)
        return proc

    def get_env(self):
        env = exec_env()
        env["XPRA_LOG_PREFIX"] = "%s " % self.description
        env["XPRA_FIX_UNICODE_OUT"] = "0"
        return env

    def cleanup(self):
        self.stop()

    def stop(self):
        self.stop_process()
        self.stop_protocol()

    def stop_process(self):
        log("%s.stop_process() sending stop request to %s", self, self.description)
        proc = self.process
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                self.process = None
            except Exception as e:
                log.warn("failed to stop the wrapped subprocess %s: %s", proc, e)

    def stop_protocol(self):
        p = self.protocol
        if p:
            self.protocol = None
            log("%s.stop_protocol() calling %s", self, p.close)
            try:
                p.close()
            except Exception as e:
                log.warn("failed to close the subprocess connection: %s", p, e)


    def connection_lost(self, *args):
        log("connection_lost%s", args)
        self.stop()

    def gibberish(self, *args):
        log.warn("%s stopping on gibberish:", self.description)
        log.warn(" %s", repr_ellipsized(args[1], limit=80))
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
        INJECT_FAULT(p)

    def process_packet(self, proto, packet):
        if DEBUG_WRAPPER:
            log("process_packet(%s, %s)", proto, [str(x)[:32] for x in packet])
        signal_name = bytestostr(packet[0])
        self._fire_callback(signal_name, packet[1:])
        INJECT_FAULT(proto)

    def _fire_callback(self, signal_name, extra_args=[]):
        callbacks = self.signal_callbacks.get(signal_name)
        log("firing callback for '%s': %s", signal_name, callbacks)
        if callbacks:
            for cb, args in callbacks:
                try:
                    all_args = list(args) + extra_args
                    self.idle_add(cb, self, *all_args)
                except Exception:
                    log.error("error processing callback %s for %s packet", cb, signal_name, exc_info=True)
