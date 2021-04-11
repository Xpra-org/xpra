# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

def get_client_protocol_class(socktype):
    if socktype=="udp":
        from xpra.net.udp_protocol import UDPClientProtocol
        return UDPClientProtocol
    if socktype in ("ws", "wss"):
        from xpra.net.websockets.protocol import WebSocketProtocol
        return WebSocketProtocol
    from xpra.net.protocol import Protocol
    return Protocol

def get_server_protocol_class(socktype):
    if socktype=="udp":
        from xpra.net.udp_protocol import UDPServerProtocol
        return UDPServerProtocol
    if socktype in ("ws", "wss"):
        from xpra.net.websockets.protocol import WebSocketProtocol
        return WebSocketProtocol
    from xpra.net.protocol import Protocol
    return Protocol
