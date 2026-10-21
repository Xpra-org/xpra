# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import errno
from weakref import WeakKeyDictionary
from typing import Any, TYPE_CHECKING
from collections.abc import Callable, Sequence, Iterable

from xpra.net.packet_type import INFO_RESPONSE, CONNECTION_LOST, GIBBERISH, INVALID
from xpra.server import ServerExitMode
from xpra.util.parsing import TRUE_OPTIONS, FALSE_OPTIONS
from xpra.net.common import pretty_socket, has_websocket_handler, connection_close_info, HttpResponse, Packet
from xpra.net.constants import MAX_PACKET_SIZE, IP_SOCKTYPES, ConnectionMessage
from xpra.net.socket_util import (
    setup_local_sockets, add_listen_socket, accept_connection, guess_packet_type,
    peek_connection, close_sockets, SocketListener, socket_fast_read,
    parse_bind_options, create_sockets, check_ssh_upgrades,
)
from xpra.net.bytestreams import (
    Connection, SocketConnection,
    set_socket_timeout, log_new_connection, SOCKET_TIMEOUT
)
if TYPE_CHECKING:
    # imported lazily at runtime (pulls in `ssl`); only needed here for type hints:
    from xpra.net.tls.connection import SSLSocketConnection
from xpra.net.net_util import get_all_ips
from xpra.net.protocol.factory import get_server_protocol_class
from xpra.net.protocol.socket_handler import SocketProtocol
from xpra.server import network_util
from xpra.server.network_util import (
    force_close_connection, parse_html_option, find_www_dir, get_vsock_endpoint, new_conn_err,
    peek_new_connection, log_guess_packet_type, ssl_conn_handshake, wrap_ssl_socket,
    ssh_password_authenticate, log_connection_timeout, get_protocol_info,
)
from xpra.server.subsystem.stub import StubSubsystem
from xpra.platform.dotxpra import DotXpra
from xpra.os_util import POSIX, WIN32, OSX, get_username_for_uid, gi_import
from xpra.util.io import find_libexec_command
from xpra.util.thread import start_thread
from xpra.util.objects import typedict
from xpra.util.str_fn import csv, Ellipsizer, hexstr
from xpra.util.env import envint, envbool, envfloat
from xpra.scripts.config import InitExit
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("server")
netlog = Logger("network")
ssllog = Logger("ssl")
httplog = Logger("http")
wslog = Logger("websocket")

MAX_CONCURRENT_CONNECTIONS = envint("XPRA_MAX_CONCURRENT_CONNECTIONS", 100)
SERVER_SOCKET_TIMEOUT = envfloat("XPRA_SERVER_SOCKET_TIMEOUT", 0.1)
HTTP_HTTPS_REDIRECT = envbool("XPRA_HTTP_HTTPS_REDIRECT", True)
SSL_PEEK = envbool("XPRA_SSL_PEEK", True)
VSOCK_MDNS = envbool("XPRA_VSOCK_MDNS", True)


class NetworkServer(StubSubsystem):
    """
    The server's connection layer:
    the listening sockets, accepting new connections and identifying them,
    wrapping and upgrading them (ssl, websocket, ssh, rfb, rdp, http),
    creating the protocol instances and disconnecting them.
    The `hello` handshake and authentication are handled by the server.
    """
    __slots__ = (
        "_accept_timeout", "_html", "_http_headers_dirs", "_max_connections", "_potential_protocols",
        "_socket_timeout", "_ssl_attributes", "_www_dir", "_ws_timeout",
        "bind_options", "dotxpra", "http", "http_origin", "rdp_upgrade",
        "socket_verify_timer", "sockets", "ssh_upgrade", "ssl_mode", "ssl_upgrade",
        "touch_timer", "unix_socket_paths", "websocket_upgrade",
    )
    PREFIX = "network"

    def __init__(self, server=None):
        StubSubsystem.__init__(self, server)
        self.sockets: list[SocketListener] = []
        self.bind_options: dict[str, Any] = {}
        self._potential_protocols: list[SocketProtocol] = []
        self._ssl_attributes: dict = {}
        self._accept_timeout: int = SOCKET_TIMEOUT + 1
        self.ssl_mode: str = ""
        self.ssl_upgrade = False
        self.websocket_upgrade = has_websocket_handler()
        self.ssh_upgrade = False
        self.rdp_upgrade = False
        self.http = False
        self.http_origin = "auto"
        self._html: bool | None = False
        self._www_dir: str = ""
        self._http_headers_dirs: list[str] = []
        self.socket_verify_timer: WeakKeyDictionary[SocketProtocol, int] = WeakKeyDictionary()
        self._max_connections: int = MAX_CONCURRENT_CONNECTIONS
        self._socket_timeout: float = SERVER_SOCKET_TIMEOUT
        self._ws_timeout: float = 5.0
        self.dotxpra: DotXpra | None = None
        self.unix_socket_paths: list[str] = []
        self.touch_timer: int = 0

    def init(self, opts) -> None:
        self.unix_socket_paths = []
        self.dotxpra = DotXpra(opts.socket_dirs + opts.client_socket_dirs)
        self.http = opts.http
        self.http_origin = opts.http_origin
        self.websocket_upgrade = opts.websocket_upgrade
        self.ssh_upgrade = opts.ssh_upgrade
        self.rdp_upgrade = opts.rdp_upgrade
        if self.http:
            self.init_html_proxy(opts)
        self.init_ssl(opts)

    def init_packet_handlers(self) -> None:
        # these packets are not prefixed and must be handled before authentication:
        self.server._default_packet_handlers |= {
            "connection-close": self._process_connection_close,
            "ssl-upgrade": self._process_ssl_upgrade,
            CONNECTION_LOST: self._process_connection_lost,
            GIBBERISH: self._process_gibberish,
            INVALID: self._process_invalid,
        }

    def init_ssl(self, opts) -> None:
        self.ssl_mode = opts.ssl
        try:
            from xpra.net.tls.file import get_ssl_attributes
        except ImportError as e:
            ssllog("init_ssl(..) no ssl: %s", e)
            self.ssl_upgrade = False
            return
        self._ssl_attributes = get_ssl_attributes(opts, True)
        ssllog("init_ssl(..) ssl attributes=%s", self._ssl_attributes)
        self.ssl_upgrade = opts.ssl.lower() not in FALSE_OPTIONS and opts.ssl_upgrade is not False
        log("ssl-upgrade(%s, %s)=%s", opts.ssl, opts.ssl_upgrade, self.ssl_upgrade)

    def init_html_proxy(self, opts) -> None:
        httplog(f"init_html_proxy(..) options: html={opts.html!r}")
        html, www_dir = parse_html_option(opts)
        if not has_websocket_handler():
            self.websocket_upgrade = False
        self._html, self._www_dir, self._http_headers_dirs = find_www_dir(html, www_dir)

    def parse_socket_options(self, opts) -> None:
        from xpra.scripts.main import validate_encryption
        validate_encryption(opts)
        opts.ssh_upgrade = check_ssh_upgrades(opts.ssh_upgrade)
        if opts.mode not in ("shadow", "desktop", "monitor"):
            opts.rfb_upgrade = 0
            if opts.bind_rfb:
                log.warn(f"Warning: bind-rfb sockets cannot be used with {opts.mode!r} mode")
                opts.bind_rfb = ()
            if opts.bind_rdp:
                log.warn(f"Warning: bind-rdp sockets cannot be used with {opts.mode!r} mode")
                opts.bind_rdp = ()

        self.bind_options = parse_bind_options(opts)

    def init_sockets(self, retry: int = 0) -> None:
        sockets = create_sockets(self.bind_options, retry=retry, sd_listen=POSIX and not OSX)
        self.sockets += sockets

    def init_local_sockets(self, opts, display_name: str, clobber: bool) -> None:
        uid = int(opts.uid)
        gid = int(opts.gid)
        username = get_username_for_uid(uid)
        session_dir = os.environ.get("XPRA_SESSION_DIR", "")
        netlog(f"init_local_sockets(.., {clobber}) {uid=}, {gid=}, {username=!r}, {session_dir=!r}")
        # setup unix domain socket:
        local_sockets = setup_local_sockets(
            opts.bind,  # noqa: F821
            opts.socket_dirs, session_dir,  # noqa: F821
            display_name, clobber,  # noqa: F821
            opts.mmap_group, opts.socket_permissions,  # noqa: F821
            username, uid, gid)
        netlog(f"done setting up local sockets: {local_sockets}")
        self.sockets += local_sockets

        # all unix domain sockets:
        if ud_paths := [sock.address for sock in local_sockets if sock.socktype in ("socket", "named-pipe")]:
            os.environ["XPRA_SERVER_SOCKET"] = ud_paths[0]
            if opts.forward_xdg_open:
                if xdg_open := find_libexec_command("xdg-open"):
                    libexec_dir = os.path.dirname(xdg_open)
                    os.environ["PATH"] = libexec_dir + os.pathsep + os.environ.get("PATH", "")
        else:
            log.warn("Warning: no local server sockets,")
            if opts.forward_xdg_open:
                log.warn(" forward-xdg-open cannot be enabled")
            log.warn(" non-embedded ssh connections will not be available")

    def can_upgrade(self, socktype: str, tosocktype: str, options: dict[str, str]) -> bool:
        # rfb upgrades are only available with the RFBServer subsystem:
        rfb = self.get_subsystem("rfb")
        return network_util.can_upgrade(socktype, tosocktype, options,
                                        ssl=self.ssl_upgrade, websocket=self.websocket_upgrade,
                                        ssh=self.ssh_upgrade, rdp=self.rdp_upgrade,
                                        rfb=rfb is not None and rfb._rfb_upgrade > 0)

    def start_listen_sockets(self) -> None:
        # All right, we're ready to accept customers:
        netlog("start_listen_sockets() sockets=%s", self.sockets)
        for listener in self.sockets:
            netlog(" add_listen_socket: %s", listener)
            GLib.idle_add(self.add_listen_socket, listener)
            address = listener.address
            socktype = listener.socktype
            if socktype in IP_SOCKTYPES and isinstance(address, (tuple, list)) and len(address) >= 2:
                host, port = address[0], address[1]
                log.info("listening on %s at %s:%s", socktype, host or "*", port)
                if host in ("", "*", "0.0.0.0", "::", "::/0"):
                    # wildcard address: show every interface address it resolved to
                    for ip in get_all_ips():
                        log.info("  %s://%s:%s", socktype, ip, port)
            if socktype == "vsock" and isinstance(address, (tuple, list)) and len(address) >= 2:
                cid, port = get_vsock_endpoint(address)
                log.info("listening on %s at %s:%s", socktype, cid, port)
                log.info("  %s://%s:%s", socktype, cid, port)
                if VSOCK_MDNS and (mdns := self.get_subsystem("mdns")):
                    mdns.extra_info["vsock"] = f"{cid}:{port}"
            if socktype == "socket" and address:
                if address.startswith("@"):
                    # abstract sockets can't be 'touch'ed
                    continue
                path = os.path.abspath(address)
                self.unix_socket_paths.append(path)
                netlog("added unix socket path: %s", path)
        if self.unix_socket_paths:
            self.touch_sockets()
            self.touch_timer = GLib.timeout_add(60 * 1000, self.touch_sockets)

    def cancel_touch_timer(self) -> None:
        if tt := self.touch_timer:
            self.touch_timer = 0
            GLib.source_remove(tt)

    def touch_sockets(self) -> bool:
        network_util.touch_sockets(self.unix_socket_paths)
        return True

    def cleanup_all_protocols(self, reason: str | ConnectionMessage = "", force=False) -> None:
        protocols = self.get_all_protocols()
        self.cleanup_protocols(protocols, reason=reason, force=force)

    def get_all_protocols(self) -> Sequence[SocketProtocol]:
        protocols = list(self._potential_protocols)
        if client_session := self.get_subsystem("client-session"):
            protocols += list(client_session.sources)
        return tuple(protocols)

    def cleanup_protocols(self, protocols, reason: str | ConnectionMessage = "", force=False) -> None:
        if not reason:
            reason = {
                ServerExitMode.EXIT: ConnectionMessage.SERVER_EXIT,
                ServerExitMode.UPGRADE: ConnectionMessage.SERVER_UPGRADE,
            }.get(self.server._exit_mode, ConnectionMessage.SERVER_SHUTDOWN)
        netlog("cleanup_protocols(%s, %s, %s)", protocols, reason, force)
        for protocol in protocols:
            if force:
                self.force_disconnect(protocol)
            else:
                self.disconnect_protocol(protocol, reason)

    def add_listen_socket(self, listener: SocketListener) -> None:
        netlog("add_listen_socket(%s)", listener)
        add_listen_socket(listener, self, self._new_connection)

    def _new_connection(self, listener: SocketListener) -> bool:
        """
            Accept the new connection,
            verify that there aren't too many,
            start a thread to dispatch it to the correct handler.
        """
        log("_new_connection(%s)", listener)
        if self.server._closing:
            netlog("ignoring new connection during shutdown")
            return False
        socktype = listener.socktype
        if socktype == "named-pipe":
            from xpra.platform.win32.namedpipes.connection import NamedPipeConnection, log_new_pipe_connection
            handle = listener.socket.pending_handle
            conn: Connection = NamedPipeConnection(listener.socket.pipe_name, handle, listener.options,
                                                   server_side=True)
            log_new_pipe_connection(conn, conn.target)
            self.make_protocol(socktype, conn, listener.options)
            return True

        conn = accept_connection(listener, self._socket_timeout)
        if conn is None:
            return True
        # limit number of concurrent network connections:
        if socktype != "socket" and len(self._potential_protocols) >= self._max_connections:
            netlog.error("Error: too many connections (%i)", len(self._potential_protocols))
            netlog.error(" ignoring new one: %s", conn.endpoint)
            force_close_connection(conn)
            return True
        # from here on, we run in a thread, so we can poll (peek does)
        start_thread(self.handle_new_connection, f"new-{socktype}-connection", True,
                     args=(listener, conn))
        return True

    def handle_new_connection(self, listener: SocketListener, conn) -> None:
        try:
            self.do_handle_new_connection(listener, conn)
        except InitExit as e:
            netlog("handle_new_connection(%s, %s) failed: %s", listener, conn, e, exc_info=True)
            force_close_connection(conn)
        except ValueError as e:
            sock = conn._socket
            new_conn_err(conn, sock, conn.socktype, conn.remote, "", str(e))
        except OSError as e:
            netlog("handle_new_connection(%s, %s) socket wrapping failed", listener, conn, exc_info=True)
            sock = conn._socket
            new_conn_err(conn, sock, conn.socktype, conn.remote, "", str(e))

    def do_handle_new_connection(self, listener: SocketListener, conn) -> None:
        """
            Use peek to decide what sort of connection this is,
            and start the appropriate handler for it.
        """
        socket_options = listener.options
        sock = conn._socket
        address = conn.remote
        socktype = conn.socktype
        peername = conn.endpoint

        sockname = sock.getsockname()
        target = peername or sockname
        sock.settimeout(self._socket_timeout)

        netlog("handle_new_connection%s sockname=%s, target=%s", (listener, conn), sockname, target)
        # peek so we can detect invalid clients early,
        # or handle non-xpra / wrapped traffic:
        peek_data = peek_new_connection(conn)
        netlog("socket peek=%s", Ellipsizer(peek_data, limit=512))
        packet_type = log_guess_packet_type(peek_data)

        def can_upgrade_to(to_socktype: str) -> bool:
            return self.can_upgrade(socktype, to_socktype, socket_options)

        def conn_err(msg: str) -> tuple[bool, Any, bytes]:
            new_conn_err(conn, conn._socket, socktype, address, packet_type, msg)
            return False, None, b""

        if socktype in ("ssl", "wss"):
            # verify that this isn't plain HTTP / xpra:
            if packet_type not in ("ssl", ""):
                conn_err(f"packet is {packet_type!r} and not ssl")
                return
            # always start by wrapping with SSL:
            ssl_conn = self.ssl_wrap(conn, socket_options)
            if not ssl_conn:
                return
            # complete the TLS handshake on the connection-handler thread
            # before peeking or handing off: the lazy handshake inside recv()
            # would otherwise eat into the peek timeout budget (and with
            # TLS 1.3 can race with post-handshake writes like NewSessionTickets
            # and block the read thread):
            ssl_conn_handshake(ssl_conn)
            http = socktype == "wss"
            can_peek = SSL_PEEK and (self.ssl_mode.lower() in TRUE_OPTIONS or self.ssl_mode == "auto")
            if can_peek and socktype == "ssl" and can_upgrade_to("wss"):
                # look for HTTPS request to handle:
                line1 = peek_data.split(b"\n")[0]
                if line1.find(b"HTTP/") > 0 or peek_data.find(b"\x08http/") > 0:
                    http = True
                else:
                    ssl_conn.enable_peek()
                    peek_data = peek_connection(ssl_conn)
                    line1 = peek_data.split(b"\n")[0]
                    http = line1.find(b"HTTP/") > 0
                    netlog("looking for 'HTTP' in %r: %s", line1, http)
            if http:
                if not self.http:
                    conn_err("the builtin http server is not enabled")
                    return
                self.start_http_socket(socktype, ssl_conn, socket_options, True, peek_data)
                return
            ssl_conn._socket.settimeout(self._socket_timeout)
            log_new_connection(ssl_conn, address)
            self.make_protocol(socktype, ssl_conn, socket_options)
            return

        if socktype == "ws":
            self.handle_ws_socket(conn, socket_options, peek_data)
            return

        if socktype == "rfb":
            self.handle_rfb_connection(conn)
            return

        if socktype == "rdp":
            self.handle_rdp_connection(conn)
            return

        if socktype == "ssh":
            conn = self.handle_ssh_connection(conn, socket_options)
            if not conn:
                return
            peek_data, packet_type = b"", ""

        if socktype in ("tcp", "socket", "named-pipe") and peek_data:
            # see if the packet data is actually xpra or something else
            # that we need to handle via a SSL wrapper or the websocket adapter:
            cont, conn, peek_data = self.may_wrap_socket(conn, socktype, address, socket_options, peek_data)
            netlog("may_wrap_socket(..)=(%s, %s, %r)", cont, conn, Ellipsizer(peek_data))
            if not cont:
                return
            packet_type = guess_packet_type(peek_data)

        pre_read = []
        if socktype == "socket" and not peek_data:
            # try to read from this socket,
            # so short-lived probes don't go through the whole protocol instantiation
            pre = socket_fast_read(conn)
            if pre is None:
                # still connected, just nothing to read yet:
                # clients can take a while to send their `hello` packet
                # (see `socket_fast_read`), so carry on without a pre-read
                netlog("%s connection has not sent anything yet", socktype)
            elif not pre:
                netlog("closing %s connection: no data", socktype)
                force_close_connection(conn)
                return
            else:
                pre_read.append(pre)
                packet_type = guess_packet_type(pre)

        if packet_type not in ("xpra", ""):
            conn_err("packet type is not xpra")
            return

        # get the new socket object as we may have wrapped it with ssl:
        sock = getattr(conn, "_socket", sock)
        sock.settimeout(self._socket_timeout)
        log_new_connection(conn, address)
        proto = self.make_protocol(socktype, conn, socket_options, pre_read=pre_read)
        rfb = self.get_subsystem("rfb")
        rfb_upgrade = getattr(rfb, "_rfb_upgrade", 0)
        if socktype == "tcp" and not peek_data and rfb_upgrade > 0:
            t = GLib.timeout_add(rfb_upgrade * 1000, rfb.try_upgrade_to_rfb, proto)
            rfb.socket_rfb_upgrade_timer[proto] = t

    def ssl_wrap(self, conn, socket_options: dict[str, Any]) -> "SSLSocketConnection | None":
        from xpra.net.tls.connection import SSLSocketConnection
        sock = conn._socket
        socktype = conn.socktype
        ssl_sock = wrap_ssl_socket(socktype, sock, socket_options, self._ssl_attributes)
        ssllog("ssl wrapped socket(%s)=%s", sock, ssl_sock)
        if ssl_sock is None:
            return None
        address = conn.remote
        peername = conn.endpoint
        sockname = ssl_sock.getsockname()
        target = peername or sockname
        ssl_conn = SSLSocketConnection(ssl_sock, sockname, address, target, socktype, socket_options=socket_options)
        ssllog("ssl_wrap(%s, %s)=%s", conn, socket_options, ssl_conn)
        return ssl_conn

    def get_ssl_socket_options(self, socket_options: dict) -> dict[str, Any]:
        return network_util.get_ssl_socket_options(self._ssl_attributes, socket_options)

    def handle_ws_socket(self, conn, socket_options: dict[str, Any], peek_data: bytes) -> None:
        packet_type = log_guess_packet_type(peek_data)
        if peek_data:
            if packet_type == "ssl" and self.can_upgrade(conn.socktype, "wss", socket_options):
                ssllog("ws socket receiving ssl, upgrading to wss")
                conn = self.ssl_wrap(conn, socket_options)
                if conn is None:
                    return
            elif packet_type not in (None, "http"):
                raise ValueError(f"packet type is {packet_type!r} and not http")
        self.start_http_socket(conn.socktype, conn, socket_options, False, peek_data)

    def handle_ssh_connection(self, conn, socket_options: dict[str, Any]):
        from xpra.server.ssh import make_ssh_server_connection, log as sshlog
        socktype = conn.socktype_wrapped
        auth_module = self.get_subsystem("auth")
        auth_classes = auth_module.auth_classes if auth_module else {}
        none_auth = not auth_classes.get(socktype)
        sshlog("handle_ssh_connection(%s, %s) socktype wrapped=%s", conn, socket_options, socktype)

        def password_auth(username: str, password: str) -> bool:
            return ssh_password_authenticate(auth_module, socktype, conn, username, password)

        display = self.get_subsystem("display")
        display_name = display.get_display_name() if display else os.environ.get("DISPLAY", "")

        return make_ssh_server_connection(
            conn, socket_options,
            none_auth=none_auth,
            password_auth=password_auth,
            display_name=display_name,
        )

    def cancel_upgrade_to_rfb_timer(self, protocol) -> None:
        if rfb := self.get_subsystem("rfb"):
            rfb.cancel_upgrade_to_rfb_timer(protocol)

    def make_protocol(self, socktype: str, conn, socket_options, protocol_class=SocketProtocol, pre_read=()):
        """ create a new xpra Protocol instance and start it """
        log("make_protocol%s", (socktype, conn, socket_options, protocol_class, pre_read))

        def xpra_protocol_class(conn):
            """ adds xpra protocol tweaks after creating the instance """
            protocol = protocol_class(conn, self.server.process_packet)
            protocol.large_packets.append(INFO_RESPONSE)
            return protocol

        return self.do_make_protocol(socktype, conn, socket_options, xpra_protocol_class, pre_read)

    def do_make_protocol(self, socktype: str, conn, socket_options: dict[str, Any], protocol_class,
                         pre_read: Iterable[bytes] = ()) -> SocketProtocol:
        """ create a new Protocol instance and start it """
        netlog("make_protocol%s", (socktype, conn, socket_options, protocol_class, pre_read))
        socktype = socktype.lower()
        protocol = protocol_class(conn)
        protocol._pre_read = list(pre_read)
        protocol.socket_type = socktype
        self._potential_protocols.append(protocol)
        protocol.authenticators = ()
        protocol.invalid_header = self.invalid_header
        if enc := self.get_subsystem("encryption"):
            enc.parse_encryption(protocol, socket_options)
        netlog(f"starting {socktype} protocol")
        protocol.start()
        self.schedule_verify_connection_accepted(protocol, self._accept_timeout)
        return protocol

    def may_wrap_socket(self, conn, socktype: str, address, socket_options: dict, peek_data=b"") \
            -> tuple[bool, Any, bytes]:
        """
            Returns:
            * a flag indicating if we should continue processing this connection
            *  (False for webosocket and tcp proxies as they take over the socket)
            * the connection object (which may now be wrapped, ie: for ssl)
            * new peek data (which may now be empty),
        """
        if not peek_data:
            netlog("may_wrap_socket: no data, not wrapping")
            return True, conn, peek_data
        line1 = peek_data.split(b"\n")[0]
        packet_type = log_guess_packet_type(peek_data)
        if packet_type == "xpra":
            netlog("may_wrap_socket: xpra protocol header '%s', not wrapping", peek_data[0])
            # xpra packet header, no need to wrap this connection
            return True, conn, peek_data
        frominfo = pretty_socket(conn.remote)
        netlog("may_wrap_socket(..) peek_data=%s from %s", Ellipsizer(peek_data), frominfo)
        netlog("may_wrap_socket(..) peek_data got %i bytes", len(peek_data))
        netlog("may_wrap_socket(..) packet_type=%s", packet_type)

        def can_upgrade_to(to_socktype: str) -> bool:
            return self.can_upgrade(socktype, to_socktype, socket_options)

        def conn_err(msg: str) -> tuple[bool, Any, bytes]:
            new_conn_err(conn, conn._socket, socktype, address, packet_type, msg)
            return False, None, b""

        if packet_type == "ssh":
            if not can_upgrade_to("ssh"):
                conn_err("ssh upgrades are not enabled")
                return False, None, b""
            conn = self.handle_ssh_connection(conn, socket_options)
            return conn is not None, conn, b""
        if packet_type == "ssl":
            ssl_peek_data = peek_data
            sock, sockname, address, endpoint = conn._socket, conn.local, conn.remote, conn.endpoint
            sock = wrap_ssl_socket(socktype, sock, socket_options, self._ssl_attributes)
            if sock is None:
                return False, None, b""
            from xpra.net.tls.connection import SSLSocketConnection
            conn = SSLSocketConnection(sock, sockname, address, endpoint, "ssl", socket_options=socket_options)
            conn.socktype_wrapped = socktype
            ssl_conn_handshake(conn)
            # Clear the pre-upgrade encrypted peek data: after wrapping, only
            # decrypted bytes peeked from `conn` may be passed on.
            peek_data = b""
            http = False
            ssl_mode = (socket_options.get("ssl-mode", "") or self.ssl_mode).lower()
            if ssl_mode == "tcp":
                http = False
            elif ssl_mode == "www":
                http = True
            elif ssl_mode == "auto" or ssl_mode in TRUE_OPTIONS and can_upgrade_to("wss"):
                # use the header to guess:
                if line1.find(b"HTTP/") > 0 or ssl_peek_data.find(b"\x08http/1.1") > 0:
                    http = True
                else:
                    conn.enable_peek()
                    peek_data = peek_connection(conn)
                    line1 = peek_data.split(b"\n")[0]
                    http = line1.find(b"HTTP/") > 0
            ssllog("may_wrap_socket SSL: %s, ssl mode=%s, http=%s", conn, ssl_mode, http)
            to_socktype = "wss" if http else "ssl"
            if not can_upgrade_to(to_socktype):
                conn_err(f"{to_socktype} upgrades are not enabled for this socket")
                return False, None, b""
            is_ssl = True
        else:
            http = line1.find(b"HTTP/") > 0
            is_ssl = False
        if http:
            if not has_websocket_handler():
                conn_err("websocket module is not installed")
                return False, None, b""
            ws_protocol = "wss" if is_ssl else "ws"
            if not can_upgrade_to(ws_protocol):
                conn_err(f"{ws_protocol} upgrades are not enabled for this socket")
                return False, None, b""
            self.start_http_socket(socktype, conn, socket_options, is_ssl, peek_data)
            return False, conn, b""
        return True, conn, peek_data

    def invalid_header(self, proto: SocketProtocol, data: bytes, msg="") -> None:
        netlog("invalid header: %s, input_packetcount=%s, websocket_upgrade=%s, ssl=%s",
               Ellipsizer(data), proto.input_packetcount, self.websocket_upgrade, bool(self._ssl_attributes))
        rfb = self.get_subsystem("rfb")
        if data == b"RFB " and getattr(rfb, "_rfb_upgrade", 0) > 0:
            netlog("RFB header, trying to upgrade protocol")
            rfb.cancel_upgrade_to_rfb_timer(proto)
            rfb.upgrade_protocol_to_rfb(proto, data)
            return
        packet_type = log_guess_packet_type(data)
        # RFBServerProtocol doesn't support `steal_connection`:
        if packet_type == "http" and hasattr(proto, "steal_connection"):
            # try again to wrap this socket:
            bufs = [data]

            def addbuf(buf) -> None:
                bufs.append(buf)

            conn = proto.steal_connection(addbuf)
            self.cancel_verify_connection_accepted(proto)
            self.cancel_upgrade_to_rfb_timer(proto)
            netlog(f"stole connection: {type(conn)}")
            # verify that it is not wrapped yet:
            if isinstance(conn, SocketConnection) and conn.socktype_wrapped == conn.socktype:
                conn.enable_peek(b"".join(bufs))
                conn.set_active(True)
                cont, conn, peek_data = self.may_wrap_socket(conn, conn.socktype, conn.info, conn.options,
                                                             b"".join(bufs))
                netlog("wrap : may_wrap_socket(..)=(%s, %s, %r)", cont, conn, Ellipsizer(peek_data))
                if not cont:
                    return
            if conn:
                # the connection object is now removed from the protocol object,
                # so we have to close it explicitly if we have not wrapped it successfully:
                force_close_connection(conn)
        proto._invalid_header(proto, data, msg)

    def start_http_socket(self, socktype: str, conn, socket_options: dict[str, Any], is_ssl: bool = False,
                          peek_data: bytes = b""):
        frominfo = pretty_socket(conn.remote)
        line1 = peek_data.split(b"\n")[0]
        http_proto = "http" + ["", "s"][int(is_ssl)]
        netlog("start_http_socket(%s, %s, %s, %s, ..) http proto=%s, line1=%r",
               socktype, conn, socket_options, is_ssl, http_proto, line1)
        if line1.startswith(b"GET ") or line1.startswith(b"POST "):
            parts = line1.decode("latin1").split(" ")
            httplog("New %s %s request received from %s for '%s'", http_proto, parts[0], frominfo, parts[1])
            tname = parts[0] + "-request"
            req_info = http_proto + " " + parts[0]
        else:
            httplog("New %s connection received from %s", http_proto, frominfo)
            req_info = "wss" if is_ssl else "ws"
            tname = f"{req_info}-proxy"
        # we start a new thread,
        # only so that the websocket handler thread is named correctly:
        start_thread(self.start_http, f"{tname}-for-{frominfo}",
                     daemon=True, args=(socktype, conn, socket_options, is_ssl, req_info, line1, conn.remote))

    def start_http(self, socktype: str, conn, socket_options: dict[str, Any], is_ssl: bool, req_info: str,
                   line1: bytes, frominfo) -> None:
        httplog("start_http(%s, %s, %s, %s, %s, %r, %s) www dir=%s, headers dir=%s",
                socktype, conn, socket_options, is_ssl, req_info, line1, frominfo,
                self._www_dir, self._http_headers_dirs)
        try:
            from xpra.net.websockets.handler import WebSocketRequestHandler
            sock = conn._socket
            sock.settimeout(self._ws_timeout)

            def new_websocket_client(wsh) -> None:
                from xpra.net.websockets.protocol import WebSocketProtocol
                wslog("new_websocket_client(%s) socket=%s, headers=%s", wsh, sock, wsh.headers)
                newsocktype = "wss" if is_ssl else "ws"
                socket_options["http-headers"] = dict(wsh.headers)
                self.make_protocol(newsocktype, conn, socket_options, WebSocketProtocol)

            scripts = self.get_http_scripts()
            conn.socktype = "wss" if is_ssl else "ws"
            redirect_https = False
            if HTTP_HTTPS_REDIRECT and req_info not in ("ws", "wss"):
                ssl_mode = (socket_options.get("ssl-mode", "") or self.ssl_mode).lower()
                redirect_https = not is_ssl and ssl_mode in TRUE_OPTIONS
            WebSocketRequestHandler(sock, frominfo, new_websocket_client,
                                    self._www_dir, self._http_headers_dirs, scripts,
                                    redirect_https, self.http_origin)
            return
        except (OSError, ValueError) as e:
            # don't log a full backtrace for `SSLV3_ALERT_CERTIFICATE_UNKNOWN`
            # and detect it without importing the ssl module
            exc_info = True
            if type(e).__name__ == "SSLError":
                reason = getattr(e, "reason", "")
                log(f"ssl socket error: {e}, library=%s, reason=%s", getattr(e, "library", ""), reason)
                if reason == "SSLV3_ALERT_CERTIFICATE_UNKNOWN":
                    exc_info = False
            httplog("start_http%s", (socktype, conn, is_ssl, req_info, frominfo), exc_info=exc_info)
            err = e.args[0]
            if err == 1 and line1 and line1[0] == 0x16:
                log_fn = httplog.debug
            elif err in (errno.EPIPE, errno.ECONNRESET):
                log_fn = httplog.debug
            else:
                log_fn = httplog.error
                log_fn("Error: %s request failure", req_info)
                log_fn(" errno=%s", err)
            log_fn(" for client %s:", pretty_socket(frominfo))
            if line1 and line1[0] >= 128 or line1[0] == 0x16:
                log_fn(" request as hex: '%s'", hexstr(line1))
            else:
                log_fn(" request: %r", line1)
            log_fn(" %s", e)
        force_close_connection(conn)

    def get_http_scripts(self) -> dict[str, Callable[[str], HttpResponse]]:
        # loose coupling with xpra.server.subsystem.http:
        http = self.get_subsystem("http")
        return getattr(http, "scripts", {})

    def is_timedout(self, protocol: SocketProtocol) -> bool:
        v = not protocol.is_closed() and protocol in self._potential_protocols
        if client_session := self.get_subsystem("client-session"):
            v = v and not client_session.is_authenticated(protocol)
        netlog("is_timedout(%s)=%s", protocol, v)
        return v

    def schedule_verify_connection_accepted(self, protocol: SocketProtocol, timeout: int = 60) -> None:
        t = GLib.timeout_add(timeout * 1000, self.verify_connection_accepted, protocol)
        self.socket_verify_timer[protocol] = t

    def verify_connection_accepted(self, protocol: SocketProtocol) -> None:
        self.cancel_verify_connection_accepted(protocol)
        if self.is_timedout(protocol):
            log_connection_timeout(protocol)
            self.send_disconnect(protocol, ConnectionMessage.LOGIN_TIMEOUT)

    def cancel_verify_connection_accepted(self, protocol: SocketProtocol) -> None:
        if t := self.socket_verify_timer.pop(protocol, None):
            GLib.source_remove(t)

    def send_disconnect(self, proto: SocketProtocol, *reasons) -> None:
        netlog("send_disconnect(%s, %s)", proto, reasons)
        self.cancel_verify_connection_accepted(proto)
        self.cancel_upgrade_to_rfb_timer(proto)
        if proto.is_closed():
            return
        proto.send_disconnect(reasons)
        GLib.timeout_add(1000, self.force_disconnect, proto)

    def force_disconnect(self, proto: SocketProtocol) -> None:
        netlog("force_disconnect(%s)", proto)
        self.server.cleanup_protocol(proto)
        self.cancel_verify_connection_accepted(proto)
        self.cancel_upgrade_to_rfb_timer(proto)
        proto.close()

    def disconnect_client(self, protocol: SocketProtocol, reason: str | ConnectionMessage, *extra) -> None:
        netlog("disconnect_client(%s, %s, %s)", protocol, reason, extra)
        if protocol and not protocol.is_closed():
            self.disconnect_protocol(protocol, reason, *extra)

    def disconnect_protocol(self, protocol: SocketProtocol, *reasons) -> None:
        netlog("disconnect_protocol(%s, %s)", protocol, reasons)
        i = str(reasons[0])
        if len(reasons) > 1:
            i += " (%s)" % csv(reasons[1:])
        proto_info = get_protocol_info(protocol)
        self.cancel_verify_connection_accepted(protocol)
        self.cancel_upgrade_to_rfb_timer(protocol)
        if not protocol.is_closed():
            self._log_disconnect(protocol, "Disconnecting client%s:", proto_info)
            self._log_disconnect(protocol, " %s", i)
            protocol.send_disconnect(reasons)
        self.server.cleanup_protocol(protocol)

    def _process_connection_close(self, proto: SocketProtocol, packet: Packet) -> None:
        reason, *extra = connection_close_info(packet) or ("", )
        info = reason
        if extra:
            info += " (%s)" % csv(extra)
        # only log protocol info if there is more than one client:
        proto_info = self._disconnect_proto_info(proto)
        self._log_disconnect(proto, "client%s has requested disconnection: %s", proto_info, info)
        self.disconnect_protocol(proto, ConnectionMessage.CLIENT_REQUEST)

    def _log_disconnect(self, _proto: SocketProtocol, *args) -> None:
        netlog.info(*args)

    def _disconnect_proto_info(self, proto) -> str:
        # only log protocol info if there is more than one client:
        client_session = self.get_subsystem("client-session")
        if client_session and len(client_session.sources) > 1:
            return f" {proto}"
        return ""

    def _process_connection_lost(self, proto: SocketProtocol, packet: Packet) -> None:
        netlog("process_connection_lost(%s, %s)", proto, packet)
        self.cancel_verify_connection_accepted(proto)
        self.cancel_upgrade_to_rfb_timer(proto)
        if proto in self._potential_protocols:
            if not proto.is_closed():
                self._log_disconnect(proto, "Connection lost")
                for extra in connection_close_info(packet):
                    self._log_disconnect(proto, " %s", extra)
            self._potential_protocols.remove(proto)
        self.server.cleanup_protocol(proto)

    def _process_gibberish(self, proto: SocketProtocol, packet: Packet) -> None:
        message = packet.get_str(1)
        data = packet.get_bytes(2)
        netlog("Received uninterpretable nonsense from %s: %s", proto, message)
        netlog(" data: %s", Ellipsizer(data))
        self.disconnect_client(proto, message)

    def _process_invalid(self, protocol: SocketProtocol, packet: Packet) -> None:
        message = packet.get_str(1)
        data = packet.get_bytes(2)
        netlog(f"Received invalid packet: {message}")
        netlog(" data: %s", Ellipsizer(data))
        self.disconnect_client(protocol, message)

    def _process_ssl_upgrade(self, proto: SocketProtocol, packet: Packet) -> None:
        socktype = proto._conn.socktype
        new_socktype = {"tcp": "ssl", "ws": "wss"}.get(socktype)
        if not new_socktype:
            raise ValueError(f"cannot upgrade {socktype} to ssl")
        self.cancel_verify_connection_accepted(proto)
        self.cancel_upgrade_to_rfb_timer(proto)
        if proto in self._potential_protocols:
            self._potential_protocols.remove(proto)
        ssllog("ssl-upgrade: %s", packet[1:])
        conn = proto.steal_connection()
        # threads should be able to terminate immediately
        # as there's no traffic yet:
        ioe = proto.wait_for_io_threads_exit(1)
        if not ioe:
            self.disconnect_protocol(proto, "failed to terminate network threads for ssl upgrade")
            force_close_connection(conn)
            return
        options = conn.options
        socktype = conn.socktype
        ssl_sock = wrap_ssl_socket(socktype, conn._socket, options, self._ssl_attributes)
        if not ssl_sock:
            self.disconnect_protocol(proto, "failed to upgrade socket to ssl")
            force_close_connection(conn)
            return
        from xpra.net.tls.connection import SSLSocketConnection
        ssl_conn = SSLSocketConnection(ssl_sock, conn.local, conn.remote, conn.endpoint, "ssl", socket_options=options)
        ssl_conn.socktype_wrapped = socktype
        protocol_class = get_server_protocol_class(new_socktype)
        self.make_protocol(new_socktype, ssl_conn, options, protocol_class)
        ssllog.info("upgraded %s to %s", conn, new_socktype)

    def accept_protocol(self, proto: SocketProtocol, c: typedict) -> None:
        netlog("accept_protocol(%s, %s)", proto, c)
        self.accept_connection(proto)
        proto.parse_remote_caps(c)

    def accept_connection(self, proto: SocketProtocol) -> None:
        netlog("accept_connection(%s)", proto)
        if proto in self._potential_protocols:
            self._potential_protocols.remove(proto)
        self.cancel_verify_connection_accepted(proto)
        self.cancel_upgrade_to_rfb_timer(proto)
        # note: when uploading files, we send them in chunks smaller than this size
        proto.max_packet_size = MAX_PACKET_SIZE
        # use blocking sockets from now on:
        if not WIN32:
            set_socket_timeout(proto._conn, None)

    def get_socket_info(self) -> dict[str, Any]:
        si = network_util.get_socket_info(self.sockets, websocket=self.websocket_upgrade,
                                          ssl=bool(self._ssl_attributes), ssh=self.ssh_upgrade)
        if auth := self.get_subsystem("auth"):
            auth.get_authenticator_info(si)
        return si

    def handle_rfb_connection(self, conn, data: bytes = b"") -> None:
        if rfb := self.get_subsystem("rfb"):
            rfb.handle_rfb_connection(conn, data)
            return
        log.error("Error: RFB protocol is not supported by this server")
        log("handle_rfb_connection%s", (conn, data))
        force_close_connection(conn)

    def handle_rdp_connection(self, conn, data: bytes = b"") -> None:
        if rdp := self.get_subsystem("rdp"):
            rdp.handle_rdp_connection(conn, data)
            return
        if data and data[:2] != b"\x03\x00":
            raise ValueError("packet is not valid RDP")
        log.error("Error: RDP protocol is not supported by this server")
        log("handle_rdp_connection%s", (conn, data))
        force_close_connection(conn)

    def cleanup_sockets(self) -> None:
        sockets = self.sockets
        self.sockets = []
        close_sockets(sockets)
