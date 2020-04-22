# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
#pylint: disable-msg=E1101

from xpra import __version__ as VERSION
from xpra.util import envint, envfloat, typedict, DETACH_REQUEST, PROTOCOL_ERROR
from xpra.net.bytestreams import log_new_connection
from xpra.net.socket_util import create_sockets, add_listen_socket, accept_connection
from xpra.net.net_util import get_network_caps
from xpra.net.protocol import Protocol
from xpra.exit_codes import EXIT_OK
from xpra.client.mixins.stub_client_mixin import StubClientMixin
from xpra.scripts.config import InitException
from xpra.log import Logger

log = Logger("network")

SOCKET_TIMEOUT = envfloat("XPRA_CLIENT_SOCKET_TIMEOUT", "0.1")
MAX_CONCURRENT_CONNECTIONS = envint("XPRA_MAX_CONCURRENT_CONNECTIONS", 5)
REQUEST_TIMEOUT = envint("XPRA_CLIENT_REQUEST_TIMEOUT", 10)


"""
Mixin for adding listening sockets to the client,
those can be used for
- requesting disconnection
- info request
"""
class NetworkListener(StubClientMixin):

    def __init__(self):
        self.sockets = {}
        self.socket_info = {}
        self.socket_options = {}
        self.socket_cleanup = []
        self._potential_protocols = []
        self._close_timers = {}


    def init(self, opts):
        def err(msg):
            raise InitException(msg)
        #don't create regular local sockets or udp sockets for now:
        opts.bind = ()
        opts.bind_udp = ()
        self.sockets = create_sockets(opts, err)

    def run(self):
        self.start_listen_sockets()

    def cleanup(self):
        self.cleanup_sockets()


    def cleanup_sockets(self):
        ct = dict(self._close_timers)
        self._close_timers = {}
        for proto, tid in ct.items():
            self.source_remove(tid)
            proto.close()
        for c in self.socket_cleanup:
            try:
                c()
            except Exception:
                log.error("Error during socket cleanup", exc_info=True)


    def start_listen_sockets(self):
        for sock_def, options in self.sockets.items():
            socktype, sock, info, _ = sock_def
            log("start_listen_sockets() will add %s socket %s (%s)", socktype, sock, info)
            self.socket_info[sock] = info
            self.socket_options[sock] = options
            self.idle_add(self.add_listen_socket, socktype, sock)

    def add_listen_socket(self, socktype, sock):
        info = self.socket_info.get(sock)
        log("add_listen_socket(%s, %s) info=%s", socktype, sock, info)
        cleanup = add_listen_socket(socktype, sock, info, self._new_connection, None)
        if cleanup:
            self.socket_cleanup.append(cleanup)

    def _new_connection(self, socktype, listener, handle=0):
        """
            Accept the new connection,
            verify that there aren't too many,
            start a thread to dispatch it to the correct handler.
        """
        log("_new_connection%s", (listener, socktype, handle))
        if self.exit_code is not None:
            log("ignoring new connection during shutdown")
            return False
        try:
            self.handle_new_connection(socktype, listener, handle)
        except Exception:
            log.error("Error handling new connection", exc_info=True)
        return self.exit_code is None

    def handle_new_connection(self, socktype, listener, _handle):
        socket_info = self.socket_info.get(listener)
        assert socktype, "cannot find socket type for %s" % listener
        socket_options = self.socket_options.get(listener, {})
        assert socktype!="named-pipe"
        conn = accept_connection(socktype, listener, SOCKET_TIMEOUT, socket_options)
        if conn is None:
            return
        #limit number of concurrent network connections:
        if len(self._potential_protocols)>=MAX_CONCURRENT_CONNECTIONS:
            log.error("Error: too many connections (%i)", len(self._potential_protocols))
            log.error(" ignoring new one: %s", conn.endpoint)
            conn.close()
            return
        sock = conn._socket
        socktype = conn.socktype
        peername = conn.endpoint
        sockname = sock.getsockname()
        target = peername or sockname
        log("handle_new_connection%s sockname=%s, target=%s",
               (conn, socket_info, socket_options), sockname, target)
        sock.settimeout(SOCKET_TIMEOUT)
        log_new_connection(conn, socket_info)

        socktype = socktype.lower()
        protocol = Protocol(self, conn, self.process_network_packet)
        #protocol.large_packets.append(b"info-response")
        protocol.socket_type = socktype
        self._potential_protocols.append(protocol)
        protocol.authenticators = ()
        protocol.start()
        #self.schedule_verify_connection_accepted(protocol, self._accept_timeout)

    def process_network_packet(self, proto, packet):
        log("process_network_packet: %s", packet)
        if packet[0]==b"hello":
            caps = typedict(packet[1])
            proto.parse_remote_caps(caps)
            proto.enable_compressor_from_caps(caps)
            proto.enable_encoder_from_caps(caps)
            request = caps.strget("request")
            if request=="info":
                def send_info():
                    info = self.get_info()
                    info["network"] = get_network_caps()
                    proto.send_now(["hello", info])
                #run in UI thread:
                self.idle_add(send_info)
            elif request=="detach":
                def protocol_closed():
                    self.disconnect_and_quit(EXIT_OK, "network request")
                proto.send_disconnect([DETACH_REQUEST], done_callback=protocol_closed)
                return
            elif request=="version":
                proto.send_now(["hello", {"version" : VERSION}])
            else:
                proto.send_disconnect([PROTOCOL_ERROR])
        else:
            proto.send_disconnect([PROTOCOL_ERROR])
        #make sure the connection is closed:
        def close():
            try:
                self._close_timers.pop(proto)
            except KeyError:
                pass
            else:
                proto.close()
        tid = self.timeout_add(REQUEST_TIMEOUT*1000, close)
        self._close_timers[proto] = tid
