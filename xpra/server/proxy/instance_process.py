# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import signal
from typing import Any
from queue import SimpleQueue
from multiprocessing import Process

from xpra.server.proxy.instance_base import ProxyInstance
from xpra.server.proxy.queue_scheduler import QueueScheduler
from xpra.server.util import setuidgid
from xpra.server.mixins.control import ControlHandler
from xpra.server import features
from xpra.scripts.server import deadly_signal
from xpra.net.protocol.factory import get_client_protocol_class, get_server_protocol_class
from xpra.net.protocol.constants import CONNECTION_LOST
from xpra.net.protocol.socket_handler import SocketProtocol
from xpra.net.socket_util import SOCKET_DIR_MODE, create_unix_domain_socket, handle_socket_error
from xpra.net.bytestreams import SocketConnection, SOCKET_TIMEOUT
from xpra.net.common import PacketType
from xpra.os_util import POSIX, getuid, getgid, get_username_for_uid, get_machine_id
from xpra.util.env import osexpand
from xpra.exit_codes import ExitValue, ExitCode
from xpra.scripts.config import str_to_bool
from xpra.util.system import SIGNAMES, register_SIGUSR_signals, set_proc_title
from xpra.util.objects import typedict
from xpra.util.str_fn import Ellipsizer
from xpra.util.version import XPRA_VERSION
from xpra.util.thread import start_thread
from xpra.util.version import full_version_str
from xpra.common import ConnectionMessage, SocketState, noerr, FULL_INFO
from xpra.platform.dotxpra import DotXpra
from xpra.log import Logger

log = Logger("proxy")

MAX_CONCURRENT_CONNECTIONS = 20


def set_blocking(conn) -> None:
    # Note: importing set_socket_timeout from xpra.net.bytestreams
    # fails in mysterious ways, so we duplicate the code here instead
    log("set_blocking(%s)", conn)
    try:
        sock = conn._socket
        log("calling %s.setblocking(1)", sock)
        sock.setblocking(1)
    except OSError:
        log("cannot set %s to blocking mode", conn)


class ProxyInstanceProcess(ProxyInstance, QueueScheduler, ControlHandler, Process):

    def __init__(self, uid: int, gid: int, env_options: dict[str, str], session_options: dict[str, str],
                 socket_dir: str,
                 pings: int,
                 client_conn, disp_desc: dict[str, Any], client_state: dict[str, Any],
                 cipher: str, cipher_mode: str, encryption_key: bytes, server_conn, caps: typedict, message_queue):
        ProxyInstance.__init__(self, session_options,
                               pings,
                               disp_desc, cipher, cipher_mode, encryption_key, caps)
        QueueScheduler.__init__(self)
        ControlHandler.__init__(self)
        Process.__init__(self, name=str(client_conn), daemon=False)
        self.client_conn = client_conn
        self.server_conn = server_conn
        self.uid = uid
        self.gid = gid
        self.env_options = env_options
        self.socket_dir = socket_dir
        self.client_state = client_state
        log("ProxyProcess%s", (uid, gid, env_options, session_options, socket_dir,
                               client_conn, disp_desc, Ellipsizer(client_state),
                               cipher, cipher_mode, encryption_key, server_conn,
                               "%s: %s.." % (type(caps), Ellipsizer(caps)), message_queue))
        self.message_queue = message_queue
        # for handling the local unix domain socket:
        self.control_socket_cleanup = None
        self.control_socket = None
        self.control_socket_thread = None
        self.control_socket_path = None
        self.potential_protocols = []
        self.max_connections = MAX_CONCURRENT_CONNECTIONS

    def __repr__(self):
        return f"proxy instance pid {os.getpid()}"

    def server_message_queue(self) -> None:
        while not self.exit and self.message_queue:
            log("waiting for server message on %s", self.message_queue)
            m = self.message_queue.get()
            log("received proxy server message: %s", m)
            if m is None:
                break
            if m == "stop":
                self.stop(None, "proxy server request")
                return
            if m == "socket-handover-complete":
                log("setting sockets to blocking mode: %s", (self.client_conn, self.server_conn))
                # set sockets to blocking mode:
                set_blocking(self.client_conn)
                set_blocking(self.server_conn)
            else:
                log.error("unexpected proxy server message: %s", m)
                log.warn("Warning: unexpected proxy server message:")
                log.warn(" '%s'", m)

    def signal_quit(self, signum, _frame=None) -> None:
        log.info("")
        log.info("proxy process pid %s got signal %s, exiting", os.getpid(), SIGNAMES.get(signum, signum))
        signal.signal(signal.SIGINT, deadly_signal)
        signal.signal(signal.SIGTERM, deadly_signal)
        self.stop(None, SIGNAMES.get(signum, signum))
        # from now on, we can't rely on the main loop:
        register_SIGUSR_signals()
        # log.info("instance frames:")
        # from xpra.util import dump_all_frames
        # dump_all_frames(log.info)

    ################################################################################

    def run(self) -> ExitValue:
        register_SIGUSR_signals(self.idle_add)
        ControlHandler.add_default_control_commands(self, features.control)
        client_protocol_class = get_client_protocol_class(self.client_conn.socktype)
        server_protocol_class = get_server_protocol_class(self.server_conn.socktype)
        self.client_protocol = client_protocol_class(self.client_conn,
                                                     self.process_client_packet,
                                                     self.get_client_packet,
                                                     scheduler=self)
        self.client_protocol.restore_state(self.client_state)
        self.server_protocol = server_protocol_class(self.server_conn,
                                                     self.process_server_packet,
                                                     self.get_server_packet,
                                                     scheduler=self)
        self.log_start()

        log("ProxyProcessProcess.run() pid=%s, uid=%s, gid=%s", os.getpid(), getuid(), getgid())
        set_proc_title(f"Xpra Proxy Instance for {self.server_conn}")
        if POSIX and (getuid() != self.uid or getgid() != self.gid):
            # do we need a valid XDG_RUNTIME_DIR for the socket-dir?
            username = get_username_for_uid(self.uid)
            socket_dir = osexpand(self.socket_dir, username, self.uid, self.gid)
            if not os.path.exists(socket_dir):
                log("the socket directory '%s' does not exist, checking for $XDG_RUNTIME_DIR path", socket_dir)
                for prefix in ("/run/user/", "/var/run/user/"):
                    if socket_dir.startswith(prefix):
                        from xpra.scripts.server import create_runtime_dir  # pylint: disable=import-outside-toplevel
                        xrd = os.path.join(prefix, str(self.uid))  # ie: /run/user/99
                        log("creating XDG_RUNTIME_DIR=%s for uid=%i, gid=%i", xrd, self.uid, self.gid)
                        create_runtime_dir(xrd, self.uid, self.gid)
                        break
            # change uid or gid:
            setuidgid(self.uid, self.gid)
        if self.env_options:
            # TODO: whitelist env update?
            os.environ.update(self.env_options)

        signal.signal(signal.SIGTERM, self.signal_quit)
        signal.signal(signal.SIGINT, self.signal_quit)
        log("registered signal handler %s", self.signal_quit)

        start_thread(self.server_message_queue, "server message queue")

        if not self.create_control_socket():
            return ExitCode.FAILURE
        self.control_socket_thread = start_thread(self.control_socket_loop, "control", daemon=True)

        self.main_queue = SimpleQueue()

        ProxyInstance.run(self)

        try:
            QueueScheduler.run(self)
        except KeyboardInterrupt as e:
            self.stop(None, str(e))
            return 128 + int(signal.SIGINT)
        finally:
            log("ProxyProcess.run() ending %s", os.getpid())
        return 0

    def start_network_threads(self) -> None:
        log("start_network_threads()")
        self.server_protocol.start()
        self.client_protocol.start()

    ################################################################################
    # control socket:

    def create_control_socket(self) -> bool:
        assert self.socket_dir

        def stop(msg) -> None:
            self.stop(None, f"cannot create the proxy control socket: {msg}")

        username = get_username_for_uid(self.uid)
        dotxpra = DotXpra(self.socket_dir, actual_username=username, uid=self.uid, gid=self.gid)
        sockname = f":proxy-{os.getpid()}"
        sockpath = dotxpra.socket_path(sockname)
        log("%s.socket_path(%s)=%s", dotxpra, sockname, sockpath)
        state = dotxpra.get_server_state(sockpath)
        log("create_control_socket: socket path='%s', uid=%i, gid=%i, state=%s", sockpath, getuid(), getgid(), state)
        if state in (SocketState.LIVE, SocketState.UNKNOWN, SocketState.INACCESSIBLE):
            log.error("Error: you already have a proxy server running at '%s'", sockpath)
            log.error(" the control socket will not be created")
            stop("socket already exists")
            return False
        d = os.path.dirname(sockpath)
        try:
            dotxpra.mksockdir(d, SOCKET_DIR_MODE)
        except Exception as e:
            log.warn("Warning: failed to create socket directory '%s'", d)
            log.warn(" %s", e)
        sock = None
        try:
            sock, self.control_socket_cleanup = create_unix_domain_socket(sockpath, 0o600)
            sock.listen(5)
        except Exception as e:
            log("create_unix_domain_socket failed for '%s'", sockpath, exc_info=True)
            log.error("Error: failed to setup control socket '%s':", sockpath)
            if sock:
                noerr(sock.close)
            handle_socket_error(sockpath, 0o600, e)
            stop(e)
            return False
        self.control_socket = sock
        self.control_socket_path = sockpath
        log.info("proxy instance now also available using unix domain socket:")
        log.info(" %s", self.control_socket_path)
        return True

    def stop_control_socket(self) -> None:
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

    def control_socket_loop(self) -> None:
        while not self.exit:
            log("waiting for connection on %s", self.control_socket_path)
            try:
                sock, address = self.control_socket.accept()
            except OSError as e:
                log("control_socket=%s", self.control_socket, exc_info=True)
                log.error("Error accepting socket connection on %s", self.control_socket)
                log.estr(e)
            else:
                self.new_control_connection(sock, address)
        self.control_socket_thread = None

    def new_control_connection(self, sock, address) -> None:
        if len(self.potential_protocols) >= self.max_connections:
            log.error("too many connections (%s), ignoring new one", len(self.potential_protocols))
            sock.close()
            return
        try:
            peername = sock.getpeername()
        except OSError:
            peername = str(address)
        sockname = sock.getsockname()
        target = peername or sockname
        # sock.settimeout(0)
        log("new_control_connection() sock=%s, sockname=%s, address=%s, peername=%s", sock, sockname, address, peername)
        sc = SocketConnection(sock, sockname, address, target, "socket")
        log.info("New proxy instance control connection received:")
        log.info(" '%s'", sc)
        protocol = SocketProtocol(sc, self.process_control_packet, scheduler=self)
        protocol.large_packets.append("info-response")
        self.potential_protocols.append(protocol)
        protocol.enable_default_encoder()
        protocol.start()
        self.timeout_add(SOCKET_TIMEOUT * 1000, self.verify_connection_accepted, protocol)

    def verify_connection_accepted(self, protocol) -> None:
        if not protocol.is_closed() and protocol in self.potential_protocols:
            log.error("connection timedout: %s", protocol)
            self.send_disconnect(protocol, ConnectionMessage.LOGIN_TIMEOUT)

    def process_control_packet(self, proto, packet: PacketType) -> None:
        try:
            self.do_process_control_packet(proto, packet)
        except Exception as e:
            log.error("error processing control packet", exc_info=True)
            self.send_disconnect(proto, ConnectionMessage.CONTROL_COMMAND_ERROR, str(e))

    def do_process_control_packet(self, proto, packet: PacketType) -> None:
        log("process_control_packet(%s, %s)", proto, packet)
        packet_type = str(packet[0])
        if packet_type == CONNECTION_LOST:
            log.info("Connection lost")
            if proto in self.potential_protocols:
                self.potential_protocols.remove(proto)
            return
        if packet_type == "hello":
            caps = typedict(packet[1])
            if caps.boolget("challenge"):
                self.send_disconnect(proto, ConnectionMessage.AUTHENTICATION_ERROR,
                                     "this socket does not use authentication")
                return
            request = caps.strget("request")
            if request and self.handle_hello_request(request, proto, caps):
                return
            log.warn("Warning: invalid hello packet,")
            log.warn(" not a supported control channel request")
        else:
            log.warn("Warning: invalid packet type for control channel")
            log.warn(" '%s' is not supported, only 'hello' is", packet_type)
        self.send_disconnect(proto, ConnectionMessage.CONTROL_COMMAND_ERROR,
                             "this socket only handles 'info', 'version' and 'stop' requests")

    def handle_hello_request(self, request: str, proto, caps: typedict) -> bool:
        def is_req_allowed(mode) -> bool:
            try:
                options = proto._conn.options
                req_option = options.get(mode, "yes")
            except AttributeError:
                req_option = "yes"
            return str_to_bool(req_option)

        if request == "info":
            if is_req_allowed("info"):
                info = self.get_proxy_info(proto)
                info.setdefault("connection", {}).update(self.get_connection_info())
            else:
                info = {"error": "`info` requests are not enabled for this connection"}
            proto.send_now(("hello", info))
            self.timeout_add(5 * 1000, self.send_disconnect, proto, ConnectionMessage.CLIENT_EXIT_TIMEOUT,
                             "info sent")
            return True
        if request == "stop":
            if is_req_allowed("stop"):
                self.stop(None, "socket request")
            else:
                log.warn("Warning: `stop` requests are not allowed for this connection")
            return True
        if request == "command":
            command_req = tuple(str(x) for x in caps.tupleget("command_request"))
            self.idle_add(self.handle_command_request, proto, *command_req)
            return True
        if request == "version":
            version = XPRA_VERSION
            if caps.boolget("full-version-request") and FULL_INFO:
                version = full_version_str()
            proto.send_now(("hello", {"version": version}))
            self.timeout_add(5 * 1000, self.send_disconnect, proto, ConnectionMessage.CLIENT_EXIT_TIMEOUT,
                             "version sent")
            return True
        if request == "id":
            proto._log_stats = False
            proto.send_now(("hello", self.get_session_id_info()))
            self.timeout_add(5 * 1000, self.send_disconnect, proto, ConnectionMessage.CLIENT_EXIT_TIMEOUT,
                             "id info sent")
            return True
        return False

    def get_session_id_info(self) -> dict[str, Any]:
        # minimal information for identifying the session
        return {
            "session-type": "proxy-instance",
            "uuid": self.uuid,
            "platform": sys.platform,
            "pid": os.getpid(),
            "machine-id": get_machine_id(),
        }

    ################################################################################

    def stop(self, skip_proto, *reasons) -> None:
        QueueScheduler.stop(self)
        self.message_queue.put_nowait(None)
        super().stop(skip_proto, *reasons)
        self.stop_control_socket()
