# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket
import os
import signal
import gobject
gobject.threads_init()
from threading import Timer

from xpra.log import Logger, debug_if_env
log = Logger()
debug = debug_if_env(log, "XPRA_PROXY_DEBUG")

from xpra.server.server_core import ServerCore, get_server_info, get_thread_info
from xpra.scripts.config import make_defaults_struct
from xpra.scripts.main import parse_display_name, connect_to
from xpra.scripts.server import deadly_signal
from xpra.net.protocol import Protocol, Compressed, compressed_wrapper, new_cipher_caps, get_network_caps
from xpra.os_util import Queue, SIGNAMES
from xpra.util import typedict
from xpra.daemon_thread import make_daemon_thread
from xpra.scripts.config import parse_number, parse_bool


PROXY_SOCKET_TIMEOUT = float(os.environ.get("XPRA_PROXY_SOCKET_TIMEOUT", "0.1"))
assert PROXY_SOCKET_TIMEOUT>0, "invalid proxy socket timeout"
PROXY_QUEUE_SIZE = int(os.environ.get("XPRA_PROXY_QUEUE_SIZE", "10"))
USE_THREADING = os.environ.get("XPRA_USE_THREADING", "0")=="1"
if USE_THREADING:
    #use threads
    from threading import Thread as Process     #@UnusedImport
    MQueue = Queue
else:
    #use processes:
    from multiprocessing import Process         #@Reimport
    from multiprocessing import Queue as MQueue #@Reimport


MAX_CONCURRENT_CONNECTIONS = 200


class ProxyServer(ServerCore):
    """
        This is the proxy server you can launch with "xpra proxy",
        once authenticated, it will dispatch the connection
        to the session found using the authenticator's
        get_sessions() function.
    """

    def __init__(self):
        log("ProxyServer.__init__()")
        ServerCore.__init__(self)
        self._max_connections = MAX_CONCURRENT_CONNECTIONS
        self.main_loop = None
        #keep track of the proxy process instances
        #the display they're on and the message queue we can
        # use to communicate with them
        self.processes = {}
        self.idle_add = gobject.idle_add
        self.timeout_add = gobject.timeout_add
        self.source_remove = gobject.source_remove
        self._socket_timeout = PROXY_SOCKET_TIMEOUT
        signal.signal(signal.SIGCHLD, self.sigchld)

    def init(self, opts):
        log("ProxyServer.init(%s)", opts)
        if not opts.auth:
            raise Exception("The proxy server requires an authentication mode")
        ServerCore.init(self, opts)

    def get_server_mode(self):
        return "proxy"

    def init_aliases(self):
        pass

    def do_run(self):
        self.main_loop = gobject.MainLoop()
        self.main_loop.run()

    def stop_all_proxies(self):
        processes = self.processes
        self.processes = {}
        log("stop_all_proxies() will stop proxy processes: %s", processes)
        for process, v in processes.items():
            disp,mq = v
            log("stop_all_proxies() stopping process %s for display %s", process, disp)
            mq.put("stop")
        log("stop_all_proxies() done")

    def cleanup(self):
        self.stop_all_proxies()
        ServerCore.cleanup(self)

    def do_quit(self):
        self.main_loop.quit()
        log.info("Proxy Server process ended")

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
        if c.boolget("stop_request"):
            self.clean_quit()
            return
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
        debug("start_proxy(%s, {..}, %s) found sessions: %s", client_proto, auth_caps, sessions)
        uid, gid, displays, env_options, session_options = sessions
        #debug("unused options: %s, %s", env_options, session_options)
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

        debug("start_proxy(%s, {..}, %s) using server display at: %s", client_proto, auth_caps, display)
        def parse_error(*args):
            disconnect("invalid display string")
            log.warn("parse error on %s: %s", display, args)
            raise Exception("parse error on %s: %s" % (display, args))
        opts = make_defaults_struct()
        opts.username = c.strget("username")
        disp_desc = parse_display_name(parse_error, opts, display)
        debug("display description(%s) = %s", display, disp_desc)
        try:
            server_conn = connect_to(disp_desc)
        except Exception, e:
            log.error("cannot start proxy connection to %s: %s", disp_desc, e)
            disconnect("failed to connect to display")
            return
        debug("server connection=%s", server_conn)

        client_conn = client_proto.steal_connection()
        client_state = client_proto.save_state()
        cipher = None
        encryption_key = None
        if auth_caps:
            cipher = auth_caps.get("cipher")
            if cipher:
                encryption_key = self.get_encryption_key(client_proto.authenticator)
        debug("start_proxy(..) client connection=%s", client_conn)
        debug("start_proxy(..) client state=%s", client_state)

        #this may block, so run it in a thread:
        def do_start_proxy():
            debug("do_start_proxy()")
            try:
                #stop IO in proxy:
                #(it may take up to _socket_timeout until the thread exits)
                client_conn.set_active(False)
                ioe = client_proto.wait_for_io_threads_exit(0.1+self._socket_timeout)
                if not ioe:
                    log.error("IO threads have failed to terminate!")
                    return
                #now we can go back to using blocking sockets:
                self.set_socket_timeout(client_conn, None)
                client_conn.set_active(True)

                assert uid!=0 and gid!=0
                message_queue = MQueue()
                process = ProxyProcess(uid, gid, env_options, session_options, client_conn, client_state, cipher, encryption_key, server_conn, c, message_queue)
                debug("starting %s from pid=%s", process, os.getpid())
                process.start()
                debug("process started")
                #FIXME: remove processes that have terminated
                self.processes[process] = (display, message_queue)
            finally:
                #now we can close our handle on the connection:
                client_conn.close()
                server_conn.close()
        make_daemon_thread(do_start_proxy, "start_proxy(%s)" % client_conn).start()


    def reap(self):
        dead = []
        for p in self.processes.keys():
            live = p.is_alive()
            if not live:
                dead.append(p)
        for p in dead:
            del self.processes[p]

    def sigchld(self, *args):
        debug("sigchld(%s)", args)
        self.reap()
        debug("processes: %s", self.processes)

    def get_info(self, proto, *args):
        info = {"server.type" : "Python/GObject/proxy"}
        #only show more info if we have authenticated
        #as the user running the proxy server process:
        sessions = proto.authenticator.get_sessions()
        if sessions:
            uid, gid = sessions[:2]
            if uid==os.getuid() and gid==os.getgid():
                info.update(ServerCore.get_info(self, proto))
                self.reap()
                i = 0
                for p,v in self.processes.items():
                    d,_ = v
                    info["proxy[%s].display" % i] = d
                    info["proxy[%s].live" % i] = p.is_alive()
                    info["proxy[%s].pid" % i] = p.pid
                    i += 1
                info["proxies"] = len(self.processes)
        return info


class ProxyProcess(Process):

    def __init__(self, uid, gid, env_options, session_options, client_conn, client_state, cipher, encryption_key, server_conn, caps, message_queue):
        Process.__init__(self, name=str(client_conn))
        self.uid = uid
        self.gid = gid
        self.env_options = env_options
        self.session_options = self.sanitize_session_options(session_options)
        self.client_conn = client_conn
        self.client_state = client_state
        self.cipher = cipher
        self.encryption_key = encryption_key
        self.server_conn = server_conn
        self.caps = caps
        debug("ProxyProcess%s", (uid, gid, client_conn, client_state, cipher, encryption_key, server_conn, "{..}"))
        self.client_protocol = None
        self.server_protocol = None
        self.main_queue = None
        self.message_queue = message_queue

    def server_message_queue(self):
        while True:
            log.info("waiting for server message on %s", self.message_queue)
            m = self.message_queue.get()
            log.info("proxy server message: %s", m)
            if m=="stop":
                self.stop("proxy server request")
                return

    def signal_quit(self, signum, frame):
        log.info("")
        log.info("proxy process pid %s got signal %s, exiting", os.getpid(), SIGNAMES.get(signum, signum))
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
        debug("ProxyProcess.run() pid=%s, uid=%s, gid=%s", os.getpid(), os.getuid(), os.getgid())
        #change uid and gid:
        if os.getgid()!=self.gid:
            os.setgid(self.gid)
        if os.getuid()!=self.uid:
            os.setuid(self.uid)
        debug("ProxyProcess.run() new uid=%s, gid=%s", os.getuid(), os.getgid())

        if self.env_options:
            #TODO: whitelist env update?
            os.environ.update(self.env_options)

        log.info("new proxy started for client %s and server %s", self.client_conn, self.server_conn)

        if not USE_THREADING:
            signal.signal(signal.SIGTERM, self.signal_quit)
            signal.signal(signal.SIGINT, self.signal_quit)
            debug("registered signal handler %s", self.signal_quit)

        make_daemon_thread(self.server_message_queue, "server message queue").start()

        self.main_queue = Queue()
        #setup protocol wrappers:
        self.server_packets = Queue(PROXY_QUEUE_SIZE)
        self.client_packets = Queue(PROXY_QUEUE_SIZE)
        self.client_protocol = Protocol(self, self.client_conn, self.process_client_packet, self.get_client_packet)
        self.client_protocol.restore_state(self.client_state)
        self.server_protocol = Protocol(self, self.server_conn, self.process_server_packet, self.get_server_packet)
        #server connection tweaks:
        self.server_protocol.large_packets.append("draw")
        self.server_protocol.large_packets.append("keymap-changed")
        self.server_protocol.large_packets.append("server-settings")
        self.server_protocol.set_compression_level(self.session_options.get("compression_level", 0))

        debug("starting network threads")
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
            debug("ProxyProcess.run() ending %s", os.getpid())


    def sanitize_session_options(self, options):
        d = {}
        def number(k, v):
            return parse_number(int, k, v)
        OPTION_WHITELIST = {"compression_level" : number,
                            "lz4"               : parse_bool}
        for k,v in options.items():
            parser = OPTION_WHITELIST.get(k)
            if parser:
                log("trying to add %s=%s using %s", k, v, parser)
                try:
                    d[k] = parser(k, v)
                except Exception, e:
                    log.warn("failed to parse value %s for %s using %s: %s", v, k, parser, e)
        return d

    def filter_client_caps(self, caps):
        fc = self.filter_caps(caps, ("cipher", "digest", "aliases", "compression", "lz4"))
        #update with options provided via config if any:
        fc.update(self.session_options)
        return fc

    def filter_server_caps(self, caps):
        if caps.get("rencode", False):
            self.server_protocol.enable_rencode()
        return self.filter_caps(caps, ("aliases", ))

    def filter_caps(self, caps, prefixes):
        #removes caps that the proxy overrides / does not use:
        #(not very pythonic!)
        pcaps = {}
        removed = []
        for k in caps.keys():
            skip = len([e for e in prefixes if k.startswith(e)])
            if skip==0:
                pcaps[k] = caps[k]
            else:
                removed.append(k)
        log("filtered out %s matching %s", removed, prefixes)
        #replace the network caps with the proxy's own:
        pcaps.update(get_network_caps())
        #then add the proxy info:
        pcaps.update(get_server_info("proxy."))
        pcaps["proxy"] = True
        pcaps["proxy.hostname"] = socket.gethostname()
        return pcaps


    def run_queue(self):
        debug("run_queue() queue has %s items already in it", self.main_queue.qsize())
        #process "idle_add"/"timeout_add" events in the main loop:
        while True:
            debug("run_queue() size=%s", self.main_queue.qsize())
            v = self.main_queue.get()
            debug("run_queue() item=%s", v)
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
        debug("stop(%s, %s)", reason, skip_proto)
        self.main_queue.put(None)
        #empty the main queue:
        q = Queue()
        q.put(None)
        self.main_queue = q
        for proto in (self.client_protocol, self.server_protocol):
            if proto and proto!=skip_proto:
                proto.flush_then_close(["disconnect", reason])


    def queue_server_packet(self, packet):
        debug("queueing server packet: %s", packet[0])
        self.server_packets.put(packet)
        self.server_protocol.source_has_more()

    def get_server_packet(self):
        #server wants a packet
        p = self.server_packets.get()
        debug("sending to server: %s", p[0])
        return p, None, None, self.server_packets.qsize()>0

    def queue_client_packet(self, packet):
        debug("queueing client packet: %s", packet[0])
        self.client_packets.put(packet)
        self.client_protocol.source_has_more()

    def get_client_packet(self):
        #server wants a packet
        p = self.client_packets.get()
        debug("sending to client: %s", p[0])
        return p, None, None, self.client_packets.qsize()>0

    def process_server_packet(self, proto, packet):
        packet_type = packet[0]
        debug("process_server_packet: %s", packet_type)
        if packet_type==Protocol.CONNECTION_LOST:
            self.stop("server connection lost", proto)
            return
        elif packet_type=="hello":
            c = typedict(packet[1])
            maxw, maxh = c.intpair("max_desktop_size", (4096, 4096))
            proto.max_packet_size = maxw*maxh*4

            caps = self.filter_server_caps(c)
            #add new encryption caps:
            if self.cipher:
                auth_caps = new_cipher_caps(self.client_protocol, self.cipher, self.encryption_key)
                caps.update(auth_caps)
            packet = ("hello", caps)
        elif packet_type=="info-response":
            #adds proxy info:
            info = packet[1]
            info.update(get_server_info("proxy."))
            info.update(get_thread_info("proxy.", proto))
        elif packet_type=="draw":
            #packet = ["draw", wid, x, y, outw, outh, coding, data, self._damage_packet_sequence, outstride, client_options]
            #ensure we don't try to re-compress the pixel data in the network layer:
            #(re-add the "compressed" marker that gets lost when we re-assemble packets)
            coding = packet[6]
            if coding!="mmap":
                data = packet[7]
                packet[7] = Compressed("%s pixels" % coding, data)
        elif packet_type=="cursor":
            #packet = ["cursor", x, y, width, height, xhot, yhot, serial, pixels, name]
            #or:
            #packet = ["cursor", ""]
            if len(packet)>=9:
                pixels = packet[8]
                if len(pixels)<64:
                    packet[8] = str(pixels)
                else:
                    packet[8] = compressed_wrapper("cursor", pixels)
        self.queue_client_packet(packet)

    def process_client_packet(self, proto, packet):
        packet_type = packet[0]
        debug("process_client_packet: %s", packet_type)
        if packet_type==Protocol.CONNECTION_LOST:
            self.stop("client connection lost", proto)
            return
        elif packet_type=="set_deflate":
            #echo it back to the client:
            self.client_packets.put(packet)
            self.client_protocol.source_has_more()
            return
        elif packet_type=="hello":
            log.warn("invalid hello packet received after initial authentication (dropped)")
            return
        self.queue_server_packet(packet)
