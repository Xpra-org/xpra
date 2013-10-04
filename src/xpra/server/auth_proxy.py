# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject
gobject.threads_init()

from xpra.log import Logger
log = Logger()

from xpra.server.server_core import ServerCore
from xpra.scripts.config import make_defaults_struct
from xpra.scripts.main import parse_display_name, connect_to
from xpra.net.protocol import Protocol
from xpra.os_util import Queue


class ProxyServer(ServerCore):

    def __init__(self):
        self.main_loop = None
        self.client_to_server = Queue(10)
        self.server_to_client = Queue(10)
        self.client_protocol = None
        self.server_protocol = None
        log("AuthProxy.__init__()")
        ServerCore.__init__(self)
        self.idle_add = gobject.idle_add
        self.timeout_add = gobject.timeout_add
        self.source_remove = gobject.source_remove

    def do_run(self):
        self.main_loop = gobject.MainLoop()
        self.main_loop.run()

    def do_quit(self):
        for x in (self.client_protocol, self.server_protocol):
            if x:
                x.close()
        self.client_protocol = None
        self.server_protocol = None
        self.main_loop.quit()

    def add_listen_socket(self, socktype, sock):
        sock.listen(5)
        gobject.io_add_watch(sock, gobject.IO_IN, self._new_connection, sock)
        self.socket_types[sock] = socktype

    def verify_connection_accepted(self, protocol):
        pass

    def hello_oked(self, proto, packet, c, auth_caps):
        if c.boolget("info_request"):
            log.info("sending response to info request")
            self.send_info(proto)
            return
        self.start_proxy(proto, packet)

    def send_info(self, proto):
        caps = self.make_hello()
        caps["server_type"] = "proxy"
        proto.send_now(["hello", caps])

    def start_proxy(self, proto, packet):
        log.info("start_proxy(%s, %s)", proto, packet)
        #from now on, we forward client packets:
        self.client_protocol = proto
        self.client_protocol.set_packet_source(self.get_client_packet)
        proto._process_packet_cb = self.process_client_packet
        #figure out where the real server lives:
        #FIXME: hardcoded
        #FIXME: forward hello to server: need to remove auth and encoding params
        target = "tcp:192.168.1.100:10000"
        def parse_error(*args):
            log.warn("parse error on %s: %s", target, args)
        opts = make_defaults_struct()
        disp_desc = parse_display_name(parse_error, opts, target)
        log.info("display description(%s) = %s", target, disp_desc)
        conn = connect_to(disp_desc)
        log.info("server connection=%s", conn)
        self.server_protocol = Protocol(self, conn, self.process_server_packet, self.get_server_packet)
        log.info("server protocol=%s", self.server_protocol)
        self.server_protocol.large_packets.append("keymap-changed")
        self.server_protocol.large_packets.append("server-settings")
        self.server_protocol.set_compression_level(0)
        self.server_protocol.start()
        #forward the hello packet:
        self.client_to_server.put(packet)
        self.server_protocol.source_has_more()

    def get_server_packet(self):
        #server wants a packet
        return self.client_to_server.get(),

    def get_client_packet(self):
        #server wants a packet
        return self.server_to_client.get(),

    def process_server_packet(self, proto, packet):
        log.info("process_server_packet: %s", packet[0])
        #forward  packet received from server to the client
        self.server_to_client.put(packet)
        self.client_protocol.source_has_more()

    def process_client_packet(self, proto, packet):
        log.info("process_client_packet: %s", packet[0])
        #forward  packet received from client to the server
        self.client_to_server.put(packet)
        self.server_protocol.source_has_more()
