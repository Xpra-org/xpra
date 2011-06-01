# This file is part of Parti.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import threading

from wimpiggy.log import Logger
log = Logger()

class XpraProxy(object):
    def __init__(self, client_conn, server_conn):
        self._client_conn = client_conn
        self._server_conn = server_conn
        self._to_client = threading.Thread(target=self._to_client_loop)
        self._to_server = threading.Thread(target=self._to_server_loop)

    def run(self):
        self._to_client.start()
        self._to_server.start()
        self._to_client.join()
        self._to_server.join()

    def _to_client_loop(self):
        self._copy_loop("<-server", self._server_conn, self._client_conn)

    def _to_server_loop(self):
        self._copy_loop("->server", self._client_conn, self._server_conn)

    def _copy_loop(self, log_name, from_conn, to_conn):
        while True:
            log("%s: waiting for data", log_name)
            buf = from_conn.read(4096)
            if not buf:
                log("%s: connection lost", log_name)
                self._quit()
                return
            while buf:
                log("%s: writing %s bytes", log_name, len(buf))
                buf = buf[to_conn.write(buf):]

    def _quit(self):
        log("closing proxy connections")
        self._client_conn.close()
        self._server_conn.close()
