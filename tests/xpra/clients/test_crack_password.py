#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010-2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import socket
import glib

from xpra.log import Logger
log = Logger()

from xpra.scripts.config import make_defaults_struct
from xpra.client.client_base import XpraClientBase
from xpra.client.gobject_client_base import CommandConnectClient
from xpra.net.bytestreams import SocketConnection


class TryLogin(CommandConnectClient):

    def __init__(self, conn, opts, password="", stop_cb=None, cracked_cb=None):
        CommandConnectClient.__init__(self, conn, opts)
        self.password = password
        self.password_file = "fakeone"
        self.ended = False
        self.stop_cb = stop_cb
        self.cracked_cb = cracked_cb

    def run(self):
        XpraClientBase.run(self)

    def _process_disconnect(self, packet):
        self.quit()

    def warn_and_quit(self, *args):
        self.quit()
    def quit(self, *args):
        self.ended = True
        if self.stop_cb:
            self.stop_cb(self)

    def do_command(self):
        if self.ended:
            return
        print("CRACKED!")
        print("password is %s" % self.password)
        if self.cracked_cb:
            self.cracked_cb(self.password)
        self.quit()

i = -1
def gen_password():
    global i
    i += 1
    return "%s" % i

def main():
    target = sys.argv[1]
    opts = make_defaults_struct()
    MAX_CLIENTS = 10
    clients = []
    def start_try():
        sock = socket.socket(socket.AF_UNIX)
        sock.connect(target)
        conn = SocketConnection(sock, sock.getsockname(), sock.getpeername(), target, "trylogin")
        def stop_cb(client):
            try:
                clients.remove(client)
            except:
                pass
            if len(clients)<MAX_CLIENTS:
                start_try()
        def cracked_cb(password):
            sys.exit(0)
        tl = TryLogin(conn, opts, gen_password(), stop_cb, cracked_cb)
        clients.append(tl)
        tl.run()
    for _ in range(MAX_CLIENTS):
        glib.idle_add(start_try)
    glib_mainloop = glib.MainLoop()
    glib_mainloop.run()


if __name__ == "__main__":
    main()
