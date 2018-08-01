# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import websocket

from xpra.net.bytestreams import Connection, ConnectionClosedException, SOCKET_TIMEOUT
from xpra.scripts.main import InitException
from xpra.util import envbool

from xpra.log import Logger
log = Logger("network", "websocket")

if envbool("XPRA_WEBSOCKET_DEBUG"):
    websocket.enableTrace(True)


class WebSocketClientConnection(Connection):
    def __init__(self, ws, target, socktype):
        Connection.__init__(self, target, socktype)
        self._socket = ws

    def peek(self, _n):
        return None

    def untilConcludes(self, *args):
        try:
            return Connection.untilConcludes(self, *args)
        except websocket.WebSocketTimeoutException as e:
            raise ConnectionClosedException(e)

    def read(self, n):
        #FIXME: we should try to honour n
        return self._read(self._socket.recv)

    def write(self, buf):
        return self._write(self._socket.send, buf)

    def close(self):
        try:
            i = self.get_socket_info()
        except:
            i = self._socket
        log("%s.close() for socket=%s", self, i)
        Connection.close(self)
        self._socket.close()
        self._socket = None
        log("%s.close() done", self)

    def __repr__(self):
        return "%s %s" % (self.socktype, self.target)

    def get_info(self):
        d = Connection.get_info(self)
        d["protocol-type"] = "websocket"
        ws = self._socket
        if ws:
            d.update({
                      "sub-protocol"    : ws.getsubprotocol() or "",
                      "headers"         : ws.getheaders() or {},
                      "fileno"          : ws.fileno(),
                      "status"          : ws.getstatus(),
                      "connected"       : ws.connected,
                      })
        return d


def websocket_client_connection(host, port, conn, dtype="ws"):
    url = "%s://%s/" % (dtype, host)
    if port>0:
        host += ":%i" % port
    subprotocols = ["binary", "base64"]
    sock = conn._socket
    try:
        ws = websocket.create_connection(url, SOCKET_TIMEOUT, subprotocols=subprotocols, socket=sock)
    except (IndexError, ValueError) as e:
        log("websocket.create_connection%s", (url, SOCKET_TIMEOUT, subprotocols, sock), exc_info=True)
        raise InitException("websocket connection failed, not a websocket capable server port: %s" % e)
    return WebSocketClientConnection(ws, conn.target, {"ws" : "websocket", "wss" : "secure websocket"}.get(dtype, dtype))
