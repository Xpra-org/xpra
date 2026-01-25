# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from enum import Enum
try:
    # Python 3.11 and later:
    from enum import StrEnum
except ImportError:     # pragma: no cover
    StrEnum = Enum      # type: ignore
from typing import Final, Sequence

from xpra.os_util import LINUX
from xpra.util.env import envint, envbool

SSL_UPGRADE: bool = envbool("XPRA_SSL_UPGRADE", False)
AUTO_ABSTRACT_SOCKET = envbool("XPRA_AUTO_ABSTRACT_SOCKET", LINUX)

DEFAULT_PORT: Final[int] = 14500
DEFAULT_PORTS: Final[dict[str, int]] = {
    "ws": 80,
    "wss": 443,
    "ssl": 443,
    "ssh": 22,
    "tcp": DEFAULT_PORT,
    "rfb": 5900,
    "vnc": 5900,
    "rdp": 3389,
    "quic": DEFAULT_PORT,
    "vsock": DEFAULT_PORT,
}

SOCKET_TYPES: Final[Sequence[str]] = (
    "tcp", "ws", "wss", "ssl", "ssh", "rfb",
    "vsock", "hyperv", "socket",
    "named-pipe",
    "quic",
)
IP_SOCKTYPES: Final[Sequence[str]] = ("tcp", "ssl", "ws", "wss", "ssh", "quic")
TCP_SOCKTYPES: Final[Sequence[str]] = ("tcp", "ssl", "ws", "wss", "ssh")
URL_MODES: Final[dict[str, str]] = {
    "xpra": "tcp",
    "xpras": "ssl",
    "xpra+tcp": "tcp",
    "xpratcp": "tcp",
    "xpra+tls": "ssl",
    "xpratls": "ssl",
    "xpra+ssl": "ssl",
    "xprassl": "ssl",
    "xpra+ssh": "ssh",
    "xprassh": "ssh",
    "xpra+ws": "ws",
    "xpraws": "ws",
    "xpra+wss": "wss",
    "xprawss": "wss",
    "xpra+hyperv": "hyperv",
    "xprahyperv": "hyperv",
    "rfb": "vnc",
}

ABSTRACT_SOCKET_PREFIX: Final[str] = "xpra/"
MAX_PACKET_SIZE: int = envint("XPRA_MAX_PACKET_SIZE", 16 * 1024 * 1024)

HTTP_UNSUPORTED: Final[bytes] = b"""HTTP/1.1 400 Bad request syntax or unsupported method

<head>
<title>Server Error</title>
</head>
<body>
<h1>Server Error</h1>
<p>Error code 400.
<p>Message: this port does not support HTTP requests.
<p>Error code explanation: 400 = Bad request syntax or unsupported method.
</body>
"""


class SocketState(StrEnum):
    LIVE = "LIVE"
    DEAD = "DEAD"
    UNKNOWN = "UNKNOWN"
    INACCESSIBLE = "INACCESSIBLE"


# constants shared between client and server:
# (do not modify the values, see also disconnect_is_an_error)
# noinspection PyPep8
class ConnectionMessage(StrEnum):
    # timeouts:
    CLIENT_PING_TIMEOUT     = "client ping timeout"
    LOGIN_TIMEOUT           = "login timeout"
    CLIENT_EXIT_TIMEOUT     = "client exit timeout"
    # errors:
    PROTOCOL_ERROR          = "protocol error"
    VERSION_ERROR           = "version error"
    CONTROL_COMMAND_ERROR   = "control command error"
    AUTHENTICATION_FAILED   = "authentication failed"
    AUTHENTICATION_ERROR    = "authentication error"
    PERMISSION_ERROR        = "permission error"
    SERVER_ERROR            = "server error"
    CONNECTION_ERROR        = "connection error"
    SESSION_NOT_FOUND       = "session not found error"
    # informational (not a problem):
    DONE                    = "done"
    SERVER_EXIT             = "server exit"
    SERVER_UPGRADE          = "server upgrade"
    SERVER_SHUTDOWN         = "server shutdown"
    CLIENT_REQUEST          = "client request"
    DETACH_REQUEST          = "detach request"
    NEW_CLIENT              = "new client"
    IDLE_TIMEOUT            = "idle timeout"
    SESSION_BUSY            = "session busy"
    # client telling the server:
    CLIENT_EXIT             = "client exit"
