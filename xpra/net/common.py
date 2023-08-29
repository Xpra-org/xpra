# This file is part of Xpra.
# Copyright (C) 2013-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import threading
from typing import Tuple, Callable, List, Dict, Any, ByteString, Union

from xpra.net.compression import Compressed, Compressible, LargeStructure
from xpra.util import repr_ellipsized, envint, envbool
from xpra.log import Logger
log = Logger("network")


DEFAULT_PORT : int = 14500

DEFAULT_PORTS : Dict[str,int] = {
    "ws"    : 80,
    "wss"   : 443,
    "ssl"   : DEFAULT_PORT, #could also default to 443?
    "ssh"   : 22,
    "tcp"   : DEFAULT_PORT,
    "vnc"   : 5900,
    "quic"  : 20000,
    }


# packet type followed by attributes:
# in 3.11: tuple[str, *tuple[int, ...]]
# tuple[str, Unpack[tuple[int, ...]] for older versions

try:
    from typing_extensions import TypeAlias
    from typing import Unpack
    PacketElement : TypeAlias = Union[Tuple,List,Dict,int,bool,str,bytes,memoryview,Compressible,Compressed,LargeStructure]
    PacketType : TypeAlias = Tuple[str, Unpack[Tuple[PacketElement, ...]]]
    NetPacketType : TypeAlias = Tuple[int, int, int, ByteString]
except ImportError:
    PacketElement = Any
    PacketType = Tuple
    NetPacketType = Tuple

# client packet handler:
PacketHandlerType = Callable[[PacketType], None]
# server packet handler:
ServerPacketHandlerType = Callable[[Any, PacketType], None]


class ConnectionClosedException(Exception):
    pass

MAX_PACKET_SIZE : int = envint("XPRA_MAX_PACKET_SIZE", 16*1024*1024)
FLUSH_HEADER : bool = envbool("XPRA_FLUSH_HEADER", True)
SSL_UPGRADE : bool = envbool("XPRA_SSL_UPGRADE", True)

SOCKET_TYPES : Tuple[str, ...] = ("tcp", "ws", "wss", "ssl", "ssh", "rfb", "vsock", "socket", "named-pipe", "quic")

IP_SOCKTYPES : Tuple[str, ...] = ("tcp", "ssl", "ws", "wss", "ssh", "quic")
TCP_SOCKTYPES : Tuple[str, ...] = ("tcp", "ssl", "ws", "wss", "ssh")

URL_MODES : Dict[str,str] = {
    "xpra"      : "tcp",
    "xpras"     : "ssl",
    "xpra+tcp"  : "tcp",
    "xpratcp"   : "tcp",
    "xpra+tls"  : "ssl",
    "xpratls"   : "ssl",
    "xpra+ssl"  : "ssl",
    "xprassl"   : "ssl",
    "xpra+ssh"  : "ssh",
    "xprassh"   : "ssh",
    "xpra+ws"   : "ws",
    "xpraws"    : "ws",
    "xpra+wss"  : "wss",
    "xprawss"   : "wss",
    "rfb"       : "vnc",
    }


#this is used for generating aliases:
PACKET_TYPES : List[str] = [
    #generic:
    "hello",
    "challenge",
    "ssl-upgrade",
    "info", "info-response",
    #server state:
    "server-event", "startup-complete",
    "setting-change", "control",
    #network layer:
    "disconnect", "set_deflate", "connection-lost", "gibberish", "invalid",
    #pings:
    "ping", "ping_echo",
    #file transfers:
    "open-url", "send-file", "send-data-request", "send-data-response", "ack-file-chunk", "send-file-chunk",
    #audio:
    "sound-data", "new-stream", "state-changed", "new-buffer", "cleanup", "add_data", "stop",
    #display:
    "show-desktop", "desktop_size",
    #windows and trays:
    "new-window", "new-override-redirect", "new-tray",
    "raise-window", "initiate-moveresize", "window-move-resize", "window-resized", "window-metadata",
    "configure-override-redirect", "lost-window", "window-icon",
    "draw",
    "encodings",
    "eos", "cursor", "bell",
    #pointer motion and events:
    "pointer-position", "pointer",
    "button-action", "pointer-button",
    "pointer-grab", "pointer-ungrab",
    "input-devices",
    #keyboard:
    "set-keyboard-sync-enabled",
    "key-action", "key-repeat",
    "layout-changed", "keymap-changed",
    #webcam:
    "webcam-stop", "webcam-ack",
    #clipboard:
    "set-clipboard-enabled", "clipboard-token", "clipboard-request",
    "clipboard-contents", "clipboard-contents-none", "clipboard-pending-requests", "clipboard-enable-selections",
    #notifications:
    "notify_show", "notify_close",
    #rpc:
    "rpc-reply",
    ]

def get_log_packets(exclude=False) -> Tuple[str, ...]:
    lp = os.environ.get("XPRA_LOG_PACKETS")
    if not lp:
        return ()
    pt = []
    for x in lp.split(","):
        if x.startswith("-")==exclude:
            pt.append(x[int(exclude):])
    return tuple(pt)

def _may_log_packet(sending, packet_type, packet) -> None:
    if LOG_PACKET_TYPE:
        log.info("%s %s (thread=%s)", "sending  " if sending else "receiving", packet_type, threading.current_thread())
    if LOG_PACKETS or NOLOG_PACKETS:
        if packet_type in NOLOG_PACKETS:
            return
        if packet_type in LOG_PACKETS or "*" in LOG_PACKETS:
            s = str(packet)
            if len(s)>PACKET_LOG_MAX_SIZE:
                s = repr_ellipsized(s, PACKET_LOG_MAX_SIZE)
            log.info(s)

LOG_PACKETS : Tuple[str, ...] = ()
NOLOG_PACKETS : Tuple[str, ...] = ()
LOG_PACKET_TYPE : bool = False
PACKET_LOG_MAX_SIZE : int = 500

def noop(*_args) -> None:
    """ the default implementation is to do nothing """
may_log_packet : Callable = noop

def init() -> None:
    global LOG_PACKETS, NOLOG_PACKETS, LOG_PACKET_TYPE, PACKET_LOG_MAX_SIZE
    LOG_PACKETS = get_log_packets()
    NOLOG_PACKETS = get_log_packets(True)
    LOG_PACKET_TYPE = envbool("XPRA_LOG_PACKET_TYPE", False)
    PACKET_LOG_MAX_SIZE = envint("XPRA_PACKET_LOG_MAX_SIZE", 500)

    global may_log_packet
    if LOG_PACKETS or NOLOG_PACKETS or LOG_PACKET_TYPE:
        may_log_packet = _may_log_packet
    else:
        may_log_packet = noop

init()
