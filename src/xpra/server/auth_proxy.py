# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import signal
import gobject
gobject.threads_init()
from threading import Timer

from xpra.log import Logger
log = Logger()

from xpra.server.server_core import ServerCore
from xpra.scripts.config import make_defaults_struct
from xpra.scripts.main import parse_display_name, connect_to
from xpra.scripts.server import deadly_signal
from xpra.net.protocol import Protocol, new_cipher_caps
from xpra.os_util import Queue, SIGNAMES


PROXY_QUEUE_SIZE = int(os.environ.get("XPRA_PROXY_QUEUE_SIZE", "10"))
USE_THREADING = os.environ.get("XPRA_USE_THREADING", "0")=="1"
if USE_THREADING:
    #use threads
    from threading import Thread as Process     #@UnusedImport
else:
    #use processes:
    from multiprocessing import Process         #@Reimport


class ProxyServer(ServerCore):

    def __init__(self):
        log("ProxyServer.__init__()")
        ServerCore.__init__(self)
        self.main_loop = None
        self.processes = []
        self.idle_add = gobject.idle_add
        self.timeout_add = gobject.timeout_add
        self.source_remove = gobject.source_remove

    def init(self, opts):
        log("ProxyServer.init(%s)", opts)
        if not opts.auth:
            raise Exception("The proxy server requires an authentication mode")
        ServerCore.init(self, opts)

    def init_aliases(self):
        pass

    def do_run(self):
        self.main_loop = gobject.MainLoop()
        self.main_loop.run()

    def do_quit(self):
        processes = self.processes
        self.processes = []
        for process in processes:
            process.stop()
        self.main_loop.quit()

    def add_listen_socket(self, socktype, sock):
        sock.listen(5)
        gobject.io_add_watch(sock, gobject.IO_IN, self._new_connection, sock)
        self.socket_types[sock] = socktype

    def verify_connection_accepted(self, protocol):
        #if we start a proxy, the protocol will be closed
        #(a new one is created in the proxy process)
        if not protocol._closed:
            self.send_disconnect(protocol, "connection timeout")

    def hello_oked(self, proto, packet, c, auth_caps):
        self.accept_client(proto, c)
        self.start_proxy(proto, c, auth_caps)

    def start_proxy(self, client_proto, c, auth_caps):
        assert client_proto.authenticator is not None
        #find the target server session:
        def disconnect(msg):
            self.send_disconnect(client_proto, msg)
        sessions = client_proto.authenticator.get_sessions()
        if sessions is None:
            disconnect("no sessions found")
            return
        log.info("start_proxy(%s, {..}, %s) found sessions: %s", client_proto, auth_caps, sessions)
        uid, gid, displays, env_options, session_options = sessions
        #log.debug("unused options: %s, %s", env_options, session_options)
        if len(displays)==0:
            disconnect("no displays found")
            return
        display = c.strget("display")
        proxy_virtual_display = os.environ["DISPLAY"]
        #ensure we don't loop back to the proxy:
        if proxy_virtual_display in displays:
            displays.remove(proxy_virtual_display)
        if display==proxy_virtual_display:
            disconnect("invalid display")
            return
        if display:
            if display not in displays:
                disconnect("display not found")
                return
        else:
            if len(displays)!=1:
                disconnect("please specify a display (more than one available)")
                return
            display = displays[0]

        log.info("start_proxy(%s, {..}, %s) using server display at: %s", client_proto, auth_caps, display)
        def parse_error(*args):
            disconnect("invalid display string")
            log.warn("parse error on %s: %s", display, args)
            raise Exception("parse error on %s: %s" % (display, args))
        opts = make_defaults_struct()
        opts.username = c.strget("username")
        disp_desc = parse_display_name(parse_error, opts, display)
        log.info("display description(%s) = %s", display, disp_desc)
        try:
            server_conn = connect_to(disp_desc)
        except Exception, e:
            log.error("cannot start proxy connection to %s: %s", disp_desc, e)
            disconnect("failed to connect to display")
            return
        log.info("server connection=%s", server_conn)

        #grab client connection so we can pass it to the ProxyProcess:
        client_conn = client_proto.steal_connection()
        client_state = client_proto.save_state()
        cipher = None
        encryption_key = None
        if auth_caps:
            cipher = auth_caps.get("cipher")
            if cipher:
                encryption_key = self.get_encryption_key(client_proto.authenticator)
        log.info("start_proxy(%s, {..}) client connection=%s", client_proto, client_conn)
        log.info("start_proxy(%s, {..}) client state=%s", client_proto, client_state)

        process = ProxyProcess(uid, gid, client_conn, client_state, cipher, encryption_key, server_conn, c, self.proxy_ended)
        log.info("starting %s from pid=%s", process, os.getpid())
        process.start()
        log.info("process started")
        #FIXME: remove processes that have terminated
        self.processes.append(process)
        #now we can close our handle on the connection:
        client_conn.close()
        server_conn.close()

    def proxy_ended(self, proxy_process):
        log.info("proxy_ended(%s)", proxy_process)
        if proxy_process in self.processes:
            self.processes.remove(proxy_process)
        log.info("processes: %s", self.processes)

    def get_info(self, proto, *args):
        info = ServerCore.get_info(self, proto)
        info["proxies"] = len(self.processes)
        i = 0
        for p in self.processes:
            info["proxy[%s]" % i] = str(p)
            i += 1
        return info


class ProxyProcess(Process):

    def __init__(self, uid, gid, client_conn, client_state, cipher, encryption_key, server_conn, caps, exit_cb):
        Process.__init__(self, name=str(client_conn))
        assert uid!=0 and gid!=0
        self.uid = uid
        self.gid = gid
        self.client_conn = client_conn
        self.client_state = client_state
        self.cipher = cipher
        self.encryption_key = encryption_key
        self.server_conn = server_conn
        self.caps = caps
        self.exit_cb = exit_cb
        log.info("ProxyProcess%s pid=%s", (uid, gid, client_conn, client_state, cipher, encryption_key, server_conn, "{..}"), os.getpid())
        self.client_protocol = None
        self.server_protocol = None
        self.main_queue = None

    def signal_quit(self, signum, frame):
        log.info("")
        log.info("proxy process got signal %s, exiting", SIGNAMES.get(signum, signum))
        signal.signal(signal.SIGINT, deadly_signal)
        signal.signal(signal.SIGTERM, deadly_signal)
        self.stop(SIGNAMES.get(signum, signum))

    def idle_add(self, fn, *args, **kwargs):
        #we emulate gobject's idle_add using a simple queue
        self.main_queue.put((fn, args, kwargs))

    def timeout_add(self, timeout, fn, *args, **kwargs):
        #emulate gobject's timeout_add using idle add and a Timer
        #using custom functions to cancel() the timer when needed
        timer = None
        def idle_exec():
            v = fn(*args, **kwargs)
            if not bool(v):
                timer.cancel()
            return False
        def timer_exec():
            #just run via idle_add:
            self.idle_add(idle_exec)
        timer = Timer(timeout*1000.0, timer_exec)
        timer.start()

    def run(self):
        log.info("ProxyProcess.run() pid=%s", os.getpid())
        #change uid and gid:
        if os.getgid()!=self.gid:
            os.setgid(self.gid)
        if os.getuid()!=self.uid:
            os.setuid(self.uid)
        if not USE_THREADING:
            #signal.signal(signal.SIGTERM, self.signal_quit)
            #signal.signal(signal.SIGINT, self.signal_quit)
            pass
            #assert os.getuid()!=0

        self.main_queue = Queue()
        #setup protocol wrappers:
        self.server_packets = Queue(PROXY_QUEUE_SIZE)
        self.client_packets = Queue(PROXY_QUEUE_SIZE)
        self.client_protocol = Protocol(self, self.client_conn, self.process_client_packet, self.get_client_packet)
        self.client_protocol.restore_state(self.client_state)
        self.server_protocol = Protocol(self, self.server_conn, self.process_server_packet, self.get_server_packet)

        #server connection tweaks:
        self.server_protocol.large_packets.append("keymap-changed")
        self.server_protocol.large_packets.append("server-settings")
        self.server_protocol.set_compression_level(0)

        self.server_protocol.start()
        self.client_protocol.start()

        #forward the hello packet:
        hello_packet = ("hello", self.filter_client_caps(self.caps))
        self.queue_server_packet(hello_packet)

        try:
            try:
                self.run_queue()
            except KeyboardInterrupt, e:
                self.stop(str(e))
        finally:
            self.exit_cb(self)

    def filter_client_caps(self, caps):
        #remove caps that the proxy intercepts
        #FIXME: more filtering needed
        #hello_packet["encodings"]=("rgb", )
        pcaps = self.filter_caps(caps, ("cipher", "mmap", "aliases"))
        pcaps["proxy"] = True
        return pcaps

    def filter_server_caps(self, caps):
        return self.filter_caps(caps, "aliases")

    def filter_caps(self, caps, prefixes):
        #not very pythonic!
        pcaps = {}
        for k,v in caps.items():
            skip = len([e for e in prefixes if k.startswith(e)])
            if skip==0:
                pcaps[k] = v
        return pcaps


    def run_queue(self):
        #process "idle_add"/"timeout_add" events in the main loop:
        while True:
            v = self.main_queue.get()
            if v is None:
                break
            fn, args, kwargs = v
            try:
                v = fn(*args, **kwargs)
                if bool(v):
                    #re-run it
                    self.main_queue.put(v)
            except:
                log.error("error during main loop callback %s", fn, exc_info=True)

    def stop(self, reason="proxy terminating", skip_proto=None):
        log.info("stop(%s, %s)", reason, skip_proto)
        #empty the main queue:
        q = Queue()
        q.put(None)
        self.main_queue = q
        for proto in (self.client_protocol, self.server_protocol):
            if proto and proto!=skip_proto:
                proto.flush_then_close(["disconnect", reason])


    def queue_server_packet(self, packet):
        self.client_packets.put(packet)
        self.server_protocol.source_has_more()

    def get_server_packet(self):
        #server wants a packet
        p = self.server_packets.get()
        log.info("sending to server: %s", p[0])
        return p,

    def queue_client_packet(self, packet):
        self.client_packets.put(packet)
        self.client_protocol.source_has_more()

    def get_client_packet(self):
        #server wants a packet
        p = self.client_packets.get()
        log.info("sending to client: %s", p[0])
        return p,

    def process_server_packet(self, proto, packet):
        packet_type = packet[0]
        log.info("process_server_packet: %s", packet_type)
        #log.info("process_server_packet: %s", packet)
        if packet_type==Protocol.CONNECTION_LOST:
            self.stop("server connection lost", proto)
            return
        elif packet_type=="hello":
            caps = self.filter_server_caps(packet[1])
            #add new encryption caps:
            auth_caps = new_cipher_caps(self.client_protocol, self.cipher, self.encryption_key)
            caps.update(auth_caps)
            packet = ("hello", caps)
        self.queue_client_packet(packet)

    def process_client_packet(self, proto, packet):
        packet_type = packet[0]
        log.info("process_client_packet: %s", packet_type)
        if packet_type==Protocol.CONNECTION_LOST:
            self.stop("client connection lost", proto)
            return
        elif packet_type=="set_deflate":
            #echo it back to the client:
            self.client_packets.put(packet)
            self.client_protocol.source_has_more()
            return
        self.queue_server_packet(packet)
