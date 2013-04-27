# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import threading

from xpra.log import Logger
log = Logger()
from xpra.net.bytestreams import untilConcludes

class XpraProxy(object):
    def __init__(self, client_conn, server_conn):
        self._client_conn = client_conn
        self._server_conn = server_conn
        self._closed = False
        self._to_client = threading.Thread(target=self._to_client_loop)
        self._to_server = threading.Thread(target=self._to_server_loop)

    def run(self):
        self._to_client.start()
        self._to_server.start()
        self._to_client.join()
        self._to_server.join()

    def _to_client_loop(self):
        self._copy_loop("<-server", self._server_conn, self._client_conn)
        self._to_server._Thread__stop()

    def _to_server_loop(self):
        self._copy_loop("->server", self._client_conn, self._server_conn)
        self._to_client._Thread__stop()

    def _copy_loop(self, log_name, from_conn, to_conn):
        while not self._closed:
            log("%s: waiting for data", log_name)
            buf = untilConcludes(from_conn.read, 4096)
            if not buf:
                log("%s: connection lost", log_name)
                self.quit()
                return
            while buf and not self._closed:
                log("%s: writing %s bytes", log_name, len(buf))
                written = untilConcludes(to_conn.write, buf)
                buf = buf[written:]

    def quit(self, *args):
        log("closing proxy connections")
        self._closed = True
        try:
            self._client_conn.close()
        except:
            pass
        try:
            self._server_conn.close()
        except:
            pass
