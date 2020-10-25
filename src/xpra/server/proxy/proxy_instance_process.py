# This file is part of Xpra.
# Copyright (C) 2013-2019 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import signal
from queue import Queue
from multiprocessing import Process

from xpra.server.proxy.proxy_instance import ProxyInstance
from xpra.scripts.server import deadly_signal
from xpra.net.protocol_classes import get_client_protocol_class, get_server_protocol_class
from xpra.net.protocol import Protocol
from xpra.os_util import (
    SIGNAMES, POSIX,
    bytestostr,
    osexpand,
    getuid, getgid, get_username_for_uid, setuidgid,
    register_SIGUSR_signals,
    )
from xpra.util import (
    typedict,
    ellipsizer,
    LOGIN_TIMEOUT, CONTROL_COMMAND_ERROR, AUTHENTICATION_ERROR, CLIENT_EXIT_TIMEOUT
    )
from xpra.queue_scheduler import QueueScheduler
from xpra.version_util import XPRA_VERSION
from xpra.make_thread import start_thread
from xpra.version_util import full_version_str
from xpra.net.socket_util import create_unix_domain_socket
from xpra.platform.dotxpra import DotXpra
from xpra.net.bytestreams import SocketConnection, SOCKET_TIMEOUT
from xpra.log import Logger

log = Logger("proxy")
enclog = Logger("encoding")

MAX_CONCURRENT_CONNECTIONS = 20


def set_proc_title(title):
    try:
        import setproctitle
        setproctitle.setproctitle(title)  #@UndefinedVariable
    except ImportError as e:
        log("setproctitle not installed: %s", e)

def set_blocking(conn):
    #Note: importing set_socket_timeout from xpra.net.bytestreams
    #fails in mysterious ways, so we duplicate the code here instead
    log("set_blocking(%s)", conn)
    try:
        sock = conn._socket
        log("calling %s.setblocking(1)", sock)
        sock.setblocking(1)
    except IOError:
        log("cannot set %s to blocking mode", conn)


class ProxyInstanceProcess(ProxyInstance, QueueScheduler, Process):

    def __init__(self, uid, gid, env_options, session_options, socket_dir,
                 video_encoder_modules, pings,
                 client_conn, disp_desc, client_state, cipher, encryption_key, server_conn, caps, message_queue):
        ProxyInstance.__init__(self, session_options,
                               video_encoder_modules, pings,
                               disp_desc, cipher, encryption_key, caps)
        QueueScheduler.__init__(self)
        Process.__init__(self, name=str(client_conn), daemon=False)
        self.client_conn = client_conn
        self.server_conn = server_conn
        self.uid = uid
        self.gid = gid
        self.env_options = env_options
        self.socket_dir = socket_dir
        self.client_state = client_state
        log("ProxyProcess%s", (uid, gid, env_options, session_options, socket_dir,
                               video_encoder_modules,
                               client_conn, disp_desc, ellipsizer(client_state),
                               cipher, encryption_key, server_conn,
                               "%s: %s.." % (type(caps), ellipsizer(caps)), message_queue))
        self.message_queue = message_queue
        #for handling the local unix domain socket:
        self.control_socket_cleanup = None
        self.control_socket = None
        self.control_socket_thread = None
        self.control_socket_path = None
        self.potential_protocols = []
        self.max_connections = MAX_CONCURRENT_CONNECTIONS


    def __repr__(self):
        return "proxy instance pid %i" % os.getpid()


    def server_message_queue(self):
        while not self.exit:
            log("waiting for server message on %s", self.message_queue)
            m = self.message_queue.get()
            log("received proxy server message: %s", m)
            if m is None:
                break
            if m=="stop":
                self.stop(None, "proxy server request")
                return
            if m=="socket-handover-complete":
                log("setting sockets to blocking mode: %s", (self.client_conn, self.server_conn))
                #set sockets to blocking mode:
                set_blocking(self.client_conn)
                set_blocking(self.server_conn)
            else:
                log.error("unexpected proxy server message: %s", m)

    def signal_quit(self, signum, _frame=None):
        log.info("")
        log.info("proxy process pid %s got signal %s, exiting", os.getpid(), SIGNAMES.get(signum, signum))
        QueueScheduler.stop(self)
        self.message_queue.put_nowait(None)
        signal.signal(signal.SIGINT, deadly_signal)
        signal.signal(signal.SIGTERM, deadly_signal)
        self.stop(None, SIGNAMES.get(signum, signum))
        #from now on, we can't rely on the main loop:
        from xpra.os_util import register_SIGUSR_signals
        register_SIGUSR_signals()
        #log.info("instance frames:")
        #from xpra.util import dump_all_frames
        #dump_all_frames(log.info)


    ################################################################################

    def run(self):
        register_SIGUSR_signals(self.idle_add)
        log.info("started %s", self)
        log.info(" for client %s", self.client_conn)
        log.info(" and server %s", self.server_conn)
        client_protocol_class = get_client_protocol_class(self.client_conn.socktype)
        server_protocol_class = get_server_protocol_class(self.server_conn.socktype)
        self.client_protocol = client_protocol_class(self, self.client_conn,
                                                     self.process_client_packet, self.get_client_packet)
        self.client_protocol.restore_state(self.client_state)
        self.server_protocol = server_protocol_class(self, self.server_conn,
                                                     self.process_server_packet, self.get_server_packet)

        log("ProxyProcessProcess.run() pid=%s, uid=%s, gid=%s", os.getpid(), getuid(), getgid())
        set_proc_title("Xpra Proxy Instance for %s" % self.server_conn)
        if POSIX and (getuid()!=self.uid or getgid()!=self.gid):
            #do we need a valid XDG_RUNTIME_DIR for the socket-dir?
            username = get_username_for_uid(self.uid)
            socket_dir = osexpand(self.socket_dir, username, self.uid, self.gid)
            if not os.path.exists(socket_dir):
                log("the socket directory '%s' does not exist, checking for $XDG_RUNTIME_DIR path", socket_dir)
                for prefix in ("/run/user/", "/var/run/user/"):
                    if socket_dir.startswith(prefix):
                        from xpra.scripts.server import create_runtime_dir
                        xrd = os.path.join(prefix, str(self.uid))   #ie: /run/user/99
                        log("creating XDG_RUNTIME_DIR=%s for uid=%i, gid=%i", xrd, self.uid, self.gid)
                        create_runtime_dir(xrd, self.uid, self.gid)
                        break
            #change uid or gid:
            setuidgid(self.uid, self.gid)
        if self.env_options:
            #TODO: whitelist env update?
            os.environ.update(self.env_options)

        signal.signal(signal.SIGTERM, self.signal_quit)
        signal.signal(signal.SIGINT, self.signal_quit)
        log("registered signal handler %s", self.signal_quit)

        start_thread(self.server_message_queue, "server message queue")

        if not self.create_control_socket():
            self.stop(None, "cannot create the proxy control socket")
            return
        self.control_socket_thread = start_thread(self.control_socket_loop, "control")

        self.main_queue = Queue()

        ProxyInstance.run(self)

        try:
            QueueScheduler.run(self)
        except KeyboardInterrupt as e:
            self.stop(None, str(e))
        finally:
            log("ProxyProcess.run() ending %s", os.getpid())

    def start_network_threads(self):
        log("start_network_threads()")
        self.server_protocol.start()
        self.client_protocol.start()


    ################################################################################
    # control socket:
    def create_control_socket(self):
        assert self.socket_dir
        username = get_username_for_uid(self.uid)
        dotxpra = DotXpra(self.socket_dir, actual_username=username, uid=self.uid, gid=self.gid)
        sockname = ":proxy-%s" % os.getpid()
        sockpath = dotxpra.socket_path(sockname)
        log("%s.socket_path(%s)=%s", dotxpra, sockname, sockpath)
        state = dotxpra.get_server_state(sockpath)
        log("create_control_socket: socket path='%s', uid=%i, gid=%i, state=%s", sockpath, getuid(), getgid(), state)
        if state in (DotXpra.LIVE, DotXpra.UNKNOWN, DotXpra.INACCESSIBLE):
            log.error("Error: you already have a proxy server running at '%s'", sockpath)
            log.error(" the control socket will not be created")
            return False
        d = os.path.dirname(sockpath)
        try:
            dotxpra.mksockdir(d)
        except Exception as e:
            log.warn("Warning: failed to create socket directory '%s'", d)
            log.warn(" %s", e)
        try:
            sock, self.control_socket_cleanup = create_unix_domain_socket(sockpath, 0o600)
            sock.listen(5)
        except Exception as e:
            log("create_unix_domain_socket failed for '%s'", sockpath, exc_info=True)
            log.error("Error: failed to setup control socket '%s':", sockpath)
            log.error(" %s", e)
            return False
        self.control_socket = sock
        self.control_socket_path = sockpath
        log.info("proxy instance now also available using unix domain socket:")
        log.info(" %s", self.control_socket_path)
        return True

    def stop_control_socket(self):
        cs = self.control_socket
        if cs:
            try:
                self.control_socket.close()
            except OSError:
                pass
        csc = self.control_socket_cleanup
        if csc:
            self.control_socket_cleanup = None
            csc()

    def control_socket_loop(self):
        while not self.exit:
            log("waiting for connection on %s", self.control_socket_path)
            try:
                sock, address = self.control_socket.accept()
            except OSError as e:
                log("control_socket=%s", self.control_socket, exc_info=True)
                log.error("Error accepting socket connection on %s", self.control_socket)
                log.error(" %s", e)
            self.new_control_connection(sock, address)

    def new_control_connection(self, sock, address):
        if len(self.potential_protocols)>=self.max_connections:
            log.error("too many connections (%s), ignoring new one", len(self.potential_protocols))
            sock.close()
            return  True
        try:
            peername = sock.getpeername()
        except OSError:
            peername = str(address)
        sockname = sock.getsockname()
        target = peername or sockname
        #sock.settimeout(0)
        log("new_control_connection() sock=%s, sockname=%s, address=%s, peername=%s", sock, sockname, address, peername)
        sc = SocketConnection(sock, sockname, address, target, "unix-domain")
        log.info("New proxy instance control connection received:")
        log.info(" '%s'", sc)
        protocol = Protocol(self, sc, self.process_control_packet)
        protocol.large_packets.append(b"info-response")
        self.potential_protocols.append(protocol)
        protocol.enable_default_encoder()
        protocol.start()
        self.timeout_add(SOCKET_TIMEOUT*1000, self.verify_connection_accepted, protocol)
        return True

    def verify_connection_accepted(self, protocol):
        if not protocol.is_closed() and protocol in self.potential_protocols:
            log.error("connection timedout: %s", protocol)
            self.send_disconnect(protocol, LOGIN_TIMEOUT)

    def process_control_packet(self, proto, packet):
        try:
            self.do_process_control_packet(proto, packet)
        except Exception as e:
            log.error("error processing control packet", exc_info=True)
            self.send_disconnect(proto, CONTROL_COMMAND_ERROR, str(e))

    def do_process_control_packet(self, proto, packet):
        log("process_control_packet(%s, %s)", proto, packet)
        packet_type = bytestostr(packet[0])
        if packet_type==Protocol.CONNECTION_LOST:
            log.info("Connection lost")
            if proto in self.potential_protocols:
                self.potential_protocols.remove(proto)
            return
        if packet_type=="hello":
            caps = typedict(packet[1])
            if caps.boolget("challenge"):
                self.send_disconnect(proto, AUTHENTICATION_ERROR, "this socket does not use authentication")
                return
            generic_request = caps.strget("request")
            def is_req(mode):
                return generic_request==mode or caps.boolget("%s_request" % mode)
            if is_req("info"):
                proto.send_now(("hello", self.get_proxy_info(proto)))
                self.timeout_add(5*1000, self.send_disconnect, proto, CLIENT_EXIT_TIMEOUT, "info sent")
                return
            if is_req("stop"):
                self.stop(None, "socket request")
                return
            if is_req("version"):
                version = XPRA_VERSION
                if caps.boolget("full-version-request"):
                    version = full_version_str()
                proto.send_now(("hello", {"version" : version}))
                self.timeout_add(5*1000, self.send_disconnect, proto, CLIENT_EXIT_TIMEOUT, "version sent")
                return
            log.warn("Warning: invalid hello packet,")
            log.warn(" not a supported control channel request")
        else:
            log.warn("Warning: invalid packet type for control channel")
            log.warn(" '%s' is not supported, only 'hello' is", packet_type)
        self.send_disconnect(proto, CONTROL_COMMAND_ERROR,
                             "this socket only handles 'info', 'version' and 'stop' requests")


    ################################################################################

    def stop(self, skip_proto, *reasons):
        super().stop(skip_proto, *reasons)
        self.stop_control_socket()
        QueueScheduler.stop(self)
