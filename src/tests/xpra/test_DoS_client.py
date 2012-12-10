#!/usr/bin/env python
# This file is part of Parti.
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from wimpiggy.log import Logger
log = Logger()

from wimpiggy.util import AdHocStruct

def test_DoS(client_class_constructor, args):
    """ utility method for running DoS tests
        See: test_DoS_*_client.py
    """

    assert len(args)==2, "usage: test_DoS_client :DISPLAY"
    import socket
    from xpra.dotxpra import DotXpra
    from xpra.bytestreams import SocketConnection
    import logging
    logging.root.setLevel(logging.DEBUG)
    logging.root.addHandler(logging.StreamHandler(sys.stderr))
    opts = AdHocStruct()
    opts.password_file = ""
    opts.encoding = "rgb24"
    opts.jpegquality = 70
    opts.quality = 70
    opts.compression_level = 1
    opts.encryption = ""
    display = sys.argv[1]
    target = DotXpra().socket_path(display)
    print("will attempt to connect to socket: %s" % target)
    sock = socket.socket(socket.AF_UNIX)
    sock.connect(target)
    conn = SocketConnection(sock, sock.getsockname(), sock.getpeername(), "test_DoS")
    print("socket connection=%s" % conn)
    app = client_class_constructor(conn, opts)
    try:
        app.run()
    finally:
        app.cleanup()
    print("ended")
    print("")
