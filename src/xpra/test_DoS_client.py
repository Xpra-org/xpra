#!/usr/bin/env python
# This file is part of Parti.
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject

from wimpiggy.log import Logger
log = Logger()

from wimpiggy.util import AdHocStruct
from xpra.client_base import GLibXpraClient

class TestTimeoutClient(GLibXpraClient):

    def __init__(self, conn, opts):
        GLibXpraClient.__init__(self, conn, opts)
        def check_connection_timeout(*args):
            log.error("timeout did not fire: we are still connected!")
            self.quit()
        gobject.timeout_add(20*1000, check_connection_timeout)

    def _process_challenge(self, packet):
        log.info("got challenge - which we shall ignore!")

    def _process_hello(self, packet):
        log.error("cannot try to DoS this server: it has no password protection!")
        self.quit()

    def quit(self, *args):
        log.info("server correctly terminated the connection")
        GLibXpraClient.quit(self)

def main(args):
    assert len(args)==2, "usage: test_DoS_client :DISPLAY"
    import socket
    from xpra.dotxpra import DotXpra
    from xpra.protocol import SocketConnection
    import logging
    logging.root.setLevel(logging.DEBUG)
    logging.root.addHandler(logging.StreamHandler(sys.stderr))
    opts = AdHocStruct()
    opts.password_file = ""
    opts.encoding = "rgb24"
    opts.jpegquality = 0
    display = sys.argv[1]
    target = DotXpra().socket_path(display)
    print("will attempt to connect to socket: %s" % target)
    sock = socket.socket(socket.AF_UNIX)
    sock.connect(target)
    conn = SocketConnection(sock)
    print("socket connection=%s" % conn)
    app = TestTimeoutClient(conn, opts)
    try:
        app.run()
    finally:
        app.cleanup()

if __name__ == "__main__":
    import sys
    main(sys.argv)
