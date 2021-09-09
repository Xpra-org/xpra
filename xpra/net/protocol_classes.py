# This file is part of Xpra.
# Copyright (C) 2019-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pylint: disable=import-outside-toplevel

def get_client_protocol_class(socktype):
    if socktype in ("ws", "wss"):
        from xpra.net.websockets.protocol import WebSocketProtocol
        return WebSocketProtocol
    if socktype == "vnc":
        from xpra.client.rfb_protocol import RFBClientProtocol
        return RFBClientProtocol
    from xpra.net.protocol import Protocol
    return Protocol

def get_server_protocol_class(socktype):
    if socktype in ("ws", "wss"):
        from xpra.net.websockets.protocol import WebSocketProtocol
        return WebSocketProtocol
    if socktype == "vnc":
        from xpra.server.rfb.rfb_protocol import RFBServerProtocol
        return RFBServerProtocol
    from xpra.net.protocol import Protocol
    return Protocol
