#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket
import os

from xpra.net.protocol import Protocol
from xpra.net.bytestreams import SocketConnection
from xpra.log import Logger
log = Logger()
log.enable_debug()

import gobject
gobject.threads_init()
import glib

TEST_SOCKFILE = "./test-socket"


def makeSocketConnection(sock, name):
    try:
        peername = sock.getpeername()
    except:
        peername = str(sock)
    sockname = sock.getsockname()
    target = peername or sockname
    return SocketConnection(sock, sockname, peername, target, "test-client-socket")


class SimpleServer(object):

    def init(self, exit_cb, sockfile=TEST_SOCKFILE):
        log.info("SimpleServer(%s, %s)", exit_cb, sockfile)
        if os.path.exists(sockfile):
            os.unlink(sockfile)
        self.exit_cb = exit_cb
        sock = socket.socket(socket.AF_UNIX)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setblocking(1)
        orig_umask = os.umask(127) #600
        sock.bind(sockfile)
        os.umask(orig_umask)
        sock.listen(5)
        self.listener = sock
        gobject.io_add_watch(sock, gobject.IO_IN, self.new_connection, sock)
        log.info("SimpleServer() on %s", sock)

    def new_connection(self, *args):
        log.info("new_connection(%s)", args)
        sock, address = self.listener.accept()
        log.info("new_connection(%s) sock=%s, address=%s", args, sock, address)
        sock.settimeout(None)
        sock.setblocking(1)
        sc = makeSocketConnection(sock, str(address)+"server")
        protocol = Protocol(glib, sc, self.process_packet)
        protocol.salt = None
        protocol.set_compression_level(1)
        protocol.start()
        return True

    def process_packet(self, proto, packet):
        log.info("process_packet(%s, %s)", proto, packet)
        if packet and packet[0]=="disconnect":
            self.exit_cb()


class SimpleClient(object):

    def init(self, exit_cb, packets=[]):
        self.packets = packets
        sock = socket.socket(socket.AF_UNIX)
        sock.settimeout(5)
        sock.connect(TEST_SOCKFILE)
        sock.settimeout(None)
        sc = makeSocketConnection(sock, "test-client-socket")
        self.protocol = Protocol(glib, sc, self.process_packet, None)
        self.protocol.start()
        if len(self.packets)>0:
            gobject.timeout_add(1000, self.send_packet)

    def send_packet(self):
        self.protocol.send_now(self.packets[0])
        self.packets = self.packets[1:]
        return len(self.packets)>0

    def process_packet(self, proto, packet):
        log.info("process_packet(%s, %s)", proto, packet)

    def get_packet(self, *args):
        log.info("get_packet(%s)", args)
        return None
