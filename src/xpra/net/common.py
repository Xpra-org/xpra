# This file is part of Xpra.
# Copyright (C) 2013-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import threading

from xpra.util import repr_ellipsized, envint, envbool
from xpra.log import Logger
log = Logger("network")

class ConnectionClosedException(Exception):
    pass

SOCKET_TYPES = ("tcp", "ws", "wss", "ssl", "ssh", "rfb", "vsock", "udp")

#this is used for generating aliases:
PACKET_TYPES = [
    "hello", "info",
    "open-url", "send-file", "send-data-request", "send-data-response", "ack-file-chunk", "send-file-chunk",
    "sound-data", "new-stream", "state-changed", "new-buffer", "cleanup", "add_data", "stop",
    "ping", "ping_echo",
    "info-response", "server-event",
    "disconnect", "set_deflate", "connection-lost", "gibberish", "invalid",
    "show-desktop", "desktop_size",
    "new-window", "new-override-redirect", "new-tray",
    "raise-window", "initiate-moveresize", "window-move-resize", "window-resized", "window-metadata",
    "configure-override-redirect", "lost-window", "window-icon",
    "draw",
    "eos", "cursor", "bell",
    "pointer-position", "pointer-grab", "pointer-ungrab",
    "webcam-stop", "webcam-ack",
    "set-clipboard-enabled", "clipboard-token", "clipboard-request",
    "clipboard-contents", "clipboard-contents-none", "clipboard-pending-requests", "clipboard-enable-selections",
    "notify_show", "notify_close",
    "rpc-reply", "startup-complete", "setting-change", "control",
    "encodings",
    "udp-control",
    ]

def get_log_packets(exclude=False):
    lp = os.environ.get("XPRA_LOG_PACKETS")
    if not lp:
        return None
    pt = []
    for x in lp.split(","):
        if x.startswith("-")==exclude:
            pt.append(x[int(exclude):])
    return tuple(pt)

LOG_PACKETS = get_log_packets()
NOLOG_PACKETS = get_log_packets(True)
LOG_PACKET_TYPE = envbool("XPRA_LOG_PACKET_TYPE", False)

PACKET_LOG_MAX_SIZE = envint("XPRA_PACKET_LOG_MAX_SIZE", 500)

def _may_log_packet(sending, packet_type, packet):
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

def noop(*_args):
    pass

if LOG_PACKETS or NOLOG_PACKETS or LOG_PACKET_TYPE:
    may_log_packet = _may_log_packet
else:
    may_log_packet = noop
