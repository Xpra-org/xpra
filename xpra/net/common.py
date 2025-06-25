# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import socket
import struct
import threading
from typing import Any, Union, TypeAlias, Final
from collections.abc import Callable, Sequence

from xpra.exit_codes import ExitCode
from xpra.net.compression import Compressed, Compressible, LargeStructure
from xpra.common import noop, SizedBuffer
from xpra.os_util import LINUX, FREEBSD, WIN32
from xpra.scripts.config import str_to_bool, InitExit
from xpra.util.str_fn import repr_ellipsized
from xpra.util.env import envint, envbool

logger = None


def get_logger():
    global logger
    if logger is None:
        from xpra.log import Logger
        logger = Logger("network")
    return logger


DEFAULT_PORT: Final[int] = 14500

DEFAULT_PORTS: dict[str, int] = {
    "ws": 80,
    "wss": 443,
    "ssl": DEFAULT_PORT,  # could also default to 443?
    "ssh": 22,
    "tcp": DEFAULT_PORT,
    "vnc": 5900,
    "quic": 20000,
}

HttpResponse: TypeAlias = tuple[int, dict, bytes]

PacketElement: TypeAlias = Union[
    tuple, list, dict, int, bool, str, bytes, memoryview,
    Compressible, Compressed, LargeStructure,
]

# packet type followed by attributes:
# in 3.11: tuple[str, *tuple[int, ...]]
# tuple[str, Unpack[tuple[int, ...]] for older versions

try:
    from typing import Unpack
    PacketType: TypeAlias = tuple[str, Unpack[tuple[PacketElement, ...]]]
except ImportError:  # pragma: no cover
    PacketType: TypeAlias = tuple[PacketElement, ...]

# client packet handler:
PacketHandlerType = Callable[[PacketType], None]
# server packet handler:
ServerPacketHandlerType = Callable[[Any, PacketType], None]

NetPacketType: TypeAlias = tuple[int, int, int, SizedBuffer]


class ConnectionClosedException(Exception):
    pass


MAX_PACKET_SIZE: int = envint("XPRA_MAX_PACKET_SIZE", 16 * 1024 * 1024)
FLUSH_HEADER: bool = envbool("XPRA_FLUSH_HEADER", True)
SSL_UPGRADE: bool = envbool("XPRA_SSL_UPGRADE", False)

AUTO_ABSTRACT_SOCKET = envbool("XPRA_AUTO_ABSTRACT_SOCKET", LINUX)
ABSTRACT_SOCKET_PREFIX: Final[str] = "xpra/"

SOCKET_TYPES: Sequence[str] = (
    "tcp", "ws", "wss", "ssl", "ssh", "rfb",
    "vsock", "hyperv", "socket",
    "named-pipe",
    "quic",
)

IP_SOCKTYPES: Sequence[str] = ("tcp", "ssl", "ws", "wss", "ssh", "quic")
TCP_SOCKTYPES: Sequence[str] = ("tcp", "ssl", "ws", "wss", "ssh")

URL_MODES: dict[str, str] = {
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

PACKET_TYPES: list[str] = [
    # generic:
    "hello",
    "challenge",
    "ssl-upgrade",
    "info", "info-response",
    # server state:
    "server-event", "startup-complete",
    "setting-change", "control",
    # network layer:
    "disconnect", "connection-lost", "gibberish", "invalid",
    # pings:
    "ping", "ping_echo",
    # file transfers:
    "open-url", "send-file", "send-data-request", "send-data-response", "ack-file-chunk", "send-file-chunk",
    # audio:
    "sound-data", "new-stream", "state-changed", "new-buffer", "cleanup", "add_data", "stop",
    # display:
    "show-desktop",
    # windows and trays:
    "new-window", "new-override-redirect", "new-tray",
    "raise-window", "initiate-moveresize", "window-move-resize", "window-resized", "window-metadata",
    "configure-override-redirect", "lost-window", "window-icon",
    "draw",
    "encodings",
    "eos", "cursor", "bell",
    # pointer motion and events:
    "pointer-position", "pointer",
    "button-action", "pointer-button",
    "pointer-grab", "pointer-ungrab",
    "input-devices",
    # keyboard:
    "set-keyboard-sync-enabled",
    "key-action", "key-repeat",
    "layout-changed", "keymap-changed",
    # webcam:
    "webcam-stop", "webcam-ack",
    # clipboard:
    "set-clipboard-enabled", "clipboard-token", "clipboard-request",
    "clipboard-contents", "clipboard-contents-none", "clipboard-pending-requests", "clipboard-enable-selections",
    # notifications:
    "notify_show", "notify_close",
]


def get_log_packets(exclude=False) -> Sequence[str]:
    lp = os.environ.get("XPRA_LOG_PACKETS")
    if not lp:
        return ()
    pt = []
    for x in lp.split(","):
        if x.startswith("-") == exclude:
            pt.append(x[int(exclude):])
    return tuple(pt)


def _may_log_packet(sending, packet_type, packet) -> None:
    if LOG_PACKET_TYPE:
        get_logger().info("%s %s (thread=%s)", "sending  " if sending else "receiving", packet_type,
                          threading.current_thread())
    if LOG_PACKETS or NOLOG_PACKETS:
        if packet_type in NOLOG_PACKETS:
            return
        if packet_type in LOG_PACKETS or "*" in LOG_PACKETS:
            s = str(packet)
            if len(s) > PACKET_LOG_MAX_SIZE:
                s = repr_ellipsized(s, PACKET_LOG_MAX_SIZE)
            get_logger().info(s)


LOG_PACKETS: Sequence[str] = ()
NOLOG_PACKETS: Sequence[str] = ()
LOG_PACKET_TYPE: bool = False
PACKET_LOG_MAX_SIZE: int = 500

may_log_packet: Callable = noop


def get_peercred(sock) -> tuple[int, int, int] | None:
    log = get_logger()
    if LINUX:
        SO_PEERCRED = 17
        try:
            creds = sock.getsockopt(socket.SOL_SOCKET, SO_PEERCRED, struct.calcsize(b'3i'))
            pid, uid, gid = struct.unpack(b'3i', creds)
            log("peer: %s", (pid, uid, gid))
            return pid, uid, gid
        except OSError as e:
            log("getsockopt", exc_info=True)
            log.error(f"Error getting peer credentials: {e}")
            return None
    elif FREEBSD:
        log.warn("Warning: peercred is not yet implemented for FreeBSD")
        # use getpeereid
        # then pwd to get the gid?
    return None


def is_request_allowed(proto, request="info", default=True) -> bool:
    try:
        options = proto._conn.options
        req_option = options.get(request, default)
    except AttributeError:
        return default
    r = str_to_bool(req_option, default)
    get_logger().debug(f"is_request_allowed%s={r}", (proto, request, default))
    return r


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


def get_ssh_port() -> int:
    port = envint("XPRA_SSH_PORT", 0)
    if 0 < port < 2**16:
        return port
    # on Linux, we can run "ssh -T | grep port"
    # but this usually requires root permissions to access /etc/ssh/sshd_config
    if WIN32:
        return 0
    return 22


def has_websocket_handler() -> bool:
    try:
        from xpra.net.websockets.handler import WebSocketRequestHandler
        assert WebSocketRequestHandler
        return True
    except ImportError:
        get_logger().debug("importing WebSocketRequestHandler", exc_info=True)
    return False


HTTP_UNSUPORTED = b"""HTTP/1.1 400 Bad request syntax or unsupported method

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


def verify_hyperv_available() -> None:
    try:
        import socket
        s = socket.socket(socket.AF_HYPERV, socket.SOCK_STREAM, socket.HV_PROTOCOL_RAW)
    except (AttributeError, OSError) as e:
        raise InitExit(ExitCode.UNSUPPORTED,
                       f"hyperv sockets are not supported on this platform: {e}") from None
    else:
        s.close()


def open_html_url(html: str = "open", mode: str = "tcp", bind: str = "127.0.0.1") -> None:
    from xpra.log import Logger
    log = Logger("http", "network")
    log("open_html_url%s", (html, mode, bind))
    import urllib
    result = urllib.parse.urlsplit(f"//{bind}")
    host = result.hostname
    if host in ("0.0.0.0", "*"):
        host = "localhost"
    elif host == "::":
        host = "::1"
    port = result.port or DEFAULT_PORTS.get(mode)
    ssl = mode in ("wss", "ssl")
    url = "https" if ssl else "http"
    url += f"://{host}"
    if (ssl and port != 443) or (not ssl and port != 80):
        url += f":{port}"
    url += "/"
    from subprocess import Popen, SubprocessError
    from xpra.util.env import get_saved_env

    def exec_open(*cmd) -> None:
        log(f"exec_open{cmd}")
        proc = Popen(args=cmd, env=get_saved_env())
        from xpra.util.child_reaper import getChildReaper
        getChildReaper().add_process(proc, "open-html5-client", " ".join(cmd), True, True)

    def webbrowser_open() -> None:
        log.info(f"opening html5 client using URL {url!r}")
        from xpra.os_util import POSIX, OSX
        if POSIX and not OSX:
            saved_env = get_saved_env()
            if not (saved_env.get("DISPLAY") or saved_env.get("WAYLAND_DISPLAY")):
                log.warn(" no display, cannot open a browser window")
                return
            # run using a subprocess,
            # so we can specify the environment:
            # (which will run it against the correct X11 display!)
            try:
                exec_open(f"python{sys.version_info.major}", "-m", "webbrowser", "-t", url)
            except SubprocessError:
                log("failed exec_open:", exc_info=True)
            else:
                return
        import webbrowser
        webbrowser.open_new_tab(url)

    if html.lower() not in ("open", "connect"):
        # is a command?
        from xpra.util.io import which
        open_cmd = which(html)
        if open_cmd:
            log.info(f"opening html5 client using {html!r} at URL {url!r}")
            exec_open(open_cmd, url)
            return
        # fall through to webbrowser:
        log.warn(f"Warning: {html!r} is not a valid command")
    webbrowser_open()
