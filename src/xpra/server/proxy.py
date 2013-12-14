# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import threading

from xpra.log import Logger, debug_if_env
log = Logger()
debug = debug_if_env(log, "XPRA_PROXY_DEBUG")
from xpra.net.bytestreams import untilConcludes


class XpraProxy(object):
    """
        This is the proxy command that runs
        when one uses the hidden subcommand
        "xpra _proxy"
        It simply forwards stdin/stdout to
        the server socket.
    """

    def __init__(self, client_conn, server_conn):
        self._client_conn = client_conn
        self._server_conn = server_conn
        self._closed = False
        self._to_client = threading.Thread(target=self._to_client_loop)
        self._to_server = threading.Thread(target=self._to_server_loop)

    def run(self):
        debug("XpraProxy.run()")
        self._to_client.start()
        self._to_server.start()
        self._to_client.join()
        self._to_server.join()
        debug("XpraProxy.run() ended")

    def _to_client_loop(self):
        self._copy_loop("<-server", self._server_conn, self._client_conn)
        self._to_server._Thread__stop()

    def _to_server_loop(self):
        self._copy_loop("->server", self._client_conn, self._server_conn)
        self._to_client._Thread__stop()

    def _copy_loop(self, log_name, from_conn, to_conn):
        debug("XpraProxy._copy_loop(%s, %s, %s)", log_name, from_conn, to_conn)
        try:
            while not self._closed:
                debug("%s: waiting for data", log_name)
                buf = untilConcludes(self.is_active, from_conn.read, 4096)
                if not buf:
                    debug("%s: connection lost", log_name)
                    self.quit()
                    return
                while buf and not self._closed:
                    debug("%s: writing %s bytes", log_name, len(buf))
                    written = untilConcludes(self.is_active, to_conn.write, buf)
                    buf = buf[written:]
        except Exception, e:
            debug("%s: %s", log_name, e)
            self.quit()

    def is_active(self):
        return not self._closed

    def quit(self, *args):
        debug("XpraProxy.quit(%s) closing connections", args)
        self._closed = True
        try:
            self._client_conn.close()
        except:
            pass
        try:
            self._server_conn.close()
        except:
            pass
