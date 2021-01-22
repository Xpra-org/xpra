#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010-2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import socket

from xpra.log import Logger
log = Logger()

from xpra.platform.dotxpra import DotXpra
from xpra.net.bytestreams import SocketConnection
from xpra.scripts.config import make_defaults_struct


def test_DoS(client_class_constructor, args):
    """ utility method for running DoS tests
        See: test_DoS_*_client.py
    """

    assert len(args)==2, "usage: test_DoS_client :DISPLAY"
    log.enable_debug()
    opts = make_defaults_struct()
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
    conn = SocketConnection(sock, sock.getsockname(), sock.getpeername(), target, "test_DoS")
    print("socket connection=%s" % conn)
    app = client_class_constructor(conn, opts)
    try:
        app.run()
    finally:
        app.cleanup()
    print("ended")
    print("")
