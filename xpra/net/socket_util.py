# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import socket
from time import sleep, monotonic
from ctypes import Structure, c_uint8, sizeof
from typing import Any, Iterable
from importlib.util import find_spec
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from xpra.common import GROUP, SocketState, noerr, SizedBuffer, noop
from xpra.scripts.config import InitException, InitExit
from xpra.exit_codes import ExitCode
from xpra.net.common import DEFAULT_PORT, AUTO_ABSTRACT_SOCKET, ABSTRACT_SOCKET_PREFIX
from xpra.net.bytestreams import set_socket_timeout, pretty_socket, SocketConnection, SOCKET_TIMEOUT
from xpra.os_util import getuid, get_username_for_uid, get_groups, get_group_id, gi_import, WIN32, OSX, POSIX
from xpra.util.io import path_permission_info, umask_context, is_writable
from xpra.util.str_fn import csv, memoryview_to_bytes
from xpra.util.parsing import parse_simple_dict, TRUE_OPTIONS
from xpra.util.env import envint, envbool, SilenceWarningsContext
from xpra.util.thread import start_thread

# pylint: disable=import-outside-toplevel

# what timeout value to use on the socket probe attempt:
WAIT_PROBE_TIMEOUT = envint("XPRA_WAIT_PROBE_TIMEOUT", 6)
PEEK_TIMEOUT = envint("XPRA_PEEK_TIMEOUT", 1)
PEEK_TIMEOUT_MS = envint("XPRA_PEEK_TIMEOUT_MS", PEEK_TIMEOUT * 1000)
UNIXDOMAIN_PEEK_TIMEOUT_MS = envint("XPRA_UNIX_DOMAIN_PEEK_TIMEOUT_MS", 100)
SOCKET_PEEK_TIMEOUT_MS = envint("XPRA_SOCKET_PEEK_TIMEOUT_MS", UNIXDOMAIN_PEEK_TIMEOUT_MS)
PEEK_SIZE = envint("XPRA_PEEK_SIZE", 8192)
WIN32_LOCAL_SOCKETS = envbool("XPRA_WIN32_LOCAL_SOCKETS", True)
ABSTRACT_SOCKET_AUTH = os.environ.get("XPRA_ABSTRACT_SOCKET_AUTH", "peercred")

SOCKET_DIR_MODE = num = int(os.environ.get("XPRA_SOCKET_DIR_MODE", "775"), 8)
SOCKET_DIR_GROUP = os.environ.get("XPRA_SOCKET_DIR_GROUP", GROUP)

network_logger = None


def get_network_logger():
    global network_logger
    if not network_logger:
        from xpra.log import Logger
        network_logger = Logger("network")
    return network_logger


@dataclass
class SocketListener:
    socktype: str
    socket: object            # ie: socket.socket instance
    address: tuple | str        # ie: (127.0.0.1, 10000) or "/run/xpra/socket"
    options: dict[str, Any]
    cleanup: Callable
    close: Callable

    def __str__(self):
        return f"{self.socktype}:{self.address}"


def close_sockets(sockets: Sequence[SocketListener]) -> None:
    log = get_network_logger()
    log("close_sockets() sockets=%s", sockets)
    # stop listening for IO events (ie: GLib io_add_watch):
    for sl in sockets:
        try:
            sl.close()
        except OSError:
            log("close error on %s", sl, exc_info=True)

    # actually close the underlying socket:
    for sl in sockets:
        log("cleanup_sockets() calling %s for %s %s", sl.cleanup, sl.socktype, sl.address)
        try:
            sl.cleanup()
        except OSError:
            log("cleanup error on %s", sl, exc_info=True)


def validate_abstract_socketpath(sockpath: str) -> bool:
    return all((str.isalnum(c) or c in ("-", "_")) for c in sockpath)


def create_socket(sockpath: str, sperms: int) -> tuple[Any, Callable]:
    if sockpath.startswith("@"):
        return create_abstract_socket(sockpath)
    return create_unix_domain_socket(sockpath, sperms)


def create_abstract_socket(sockpath: str) -> tuple[socket.socket, Callable]:
    log = get_network_logger()
    log(f"create_abstract_socket({sockpath!r})")
    if not POSIX:
        raise RuntimeError(f"cannot use abstract sockets on {os.name}")
    if sockpath[:1] != "@":
        raise ValueError(f"missing '@' prefix in abstract socket path: {sockpath}")
    validate = sockpath[1:]
    if sockpath[1:].startswith(ABSTRACT_SOCKET_PREFIX):
        validate = sockpath[1 + len(ABSTRACT_SOCKET_PREFIX):]
    if not validate_abstract_socketpath(validate):
        raise ValueError(f"illegal characters found in abstract socket path {validate!r} of {sockpath!r}")
    asockpath = "\0" + sockpath[1:]
    sock = socket.socket(socket.AF_UNIX)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(asockpath)

    def cleanup_socket() -> None:
        log.info("removing abstract socket '%s'", sockpath)
        close_socket_listener(sock)

    return sock, cleanup_socket


def create_unix_domain_socket(sockpath: str, socket_permissions: int = 0o600) -> tuple[socket.socket, Callable]:
    log = get_network_logger()
    log(f"create_unix_domain_socket({sockpath!r}, {socket_permissions:o})")
    assert POSIX
    sock = socket.socket(socket.AF_UNIX)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # bind the socket, using umask to set the correct permissions
    # convert this to a `umask`!
    umask = (0o777 - socket_permissions) & 0o777
    try:
        with umask_context(umask):
            sock.bind(sockpath)
    except OSError:
        sock.close()
        raise
    try:
        inode = os.stat(sockpath).st_ino
    except OSError:
        inode = -1
    # set to the "xpra" group if we are a member of it, or if running as root:
    uid = getuid()
    username = get_username_for_uid(uid)
    groups = get_groups(username)
    if uid == 0 or GROUP in groups:
        group_id = get_group_id(GROUP)
        if group_id >= 0:
            try:
                os.lchown(sockpath, -1, group_id)
            except Exception as e:
                log.warn("Warning: failed to set '%s' group ownership", GROUP)
                log.warn(" on socket '%s':", sockpath)
                log.warn(" %s", e)
            # don't know why this doesn't work:
            # os.fchown(listener.fileno(), -1, group_id)

    def cleanup_socket() -> None:
        close_socket_listener(sock)
        try:
            cur_inode = os.stat(sockpath).st_ino
        except OSError:
            log.info("socket '%s' already deleted", sockpath)
            return
        delpath = sockpath
        log("cleanup_socket '%s', original inode=%s, new inode=%s", sockpath, inode, cur_inode)
        if cur_inode == inode:
            log.info("removing unix domain socket '%s'", delpath)
            try:
                os.unlink(delpath)
            except OSError:
                pass

    return sock, cleanup_socket


def close_socket_listener(sock) -> None:
    try:
        sock.close()
    except OSError:
        log = get_network_logger()
        log(f"close_socket_listener({sock}) {sock.close}()", exc_info=True)


def hosts(host_str: str) -> list[str]:
    if host_str == "*":
        if socket.has_dualstack_ipv6():
            # IPv6 will also listen for IPv4:
            return ["::"]
        if not socket.has_ipv6:
            return ["0.0.0.0"]
        # no dual stack, so we have to listen on both IPv4 and IPv6 explicitly:
        return ["0.0.0.0", "::"]
    return [host_str]


def add_listen_socket(listener: SocketListener, server, new_connection_cb: Callable[[SocketListener], bool]) -> None:
    log = get_network_logger()
    log("add_listen_socket%s", (listener, server, new_connection_cb))
    socktype = listener.socktype
    try:
        # ugly that we have different ways of starting sockets,
        # TODO: abstract this into the socket class
        if socktype == "named-pipe":
            # named pipe listener uses a thread:
            listener.socket.new_connection_cb = new_connection_cb
            listener.socket.start()
            return None
        if socktype == "quic":
            from xpra.net.quic.listener import listen_quic
            assert server, "cannot use quic sockets without a server"
            listen_quic(listener.socket, server, listener.options)
            return None
        listener.socket.listen(5)

        def io_in_cb(iosock, flags) -> bool:
            log("io_in_cb(%s, %s)", iosock, flags)
            return new_connection_cb(listener)

        GLib = gi_import("GLib")
        source = GLib.io_add_watch(listener.socket, GLib.PRIORITY_DEFAULT, GLib.IO_IN, io_in_cb)
        sources = [source]
        upnp_cleanup = []
        if socktype in ("tcp", "ws", "wss", "ssh", "ssl"):
            upnp = (listener.options or {}).get("upnp", "no")
            if upnp.lower() in TRUE_OPTIONS:
                from xpra.net.upnp import upnp_add
                upnp_cleanup.append(upnp_add(socktype, listener.address, listener.options))

        def close() -> None:
            for source in tuple(sources):
                GLib.source_remove(source)
                sources.remove(source)
            for c in upnp_cleanup:
                if c:
                    start_thread(c, f"pnp-cleanup-{c}", daemon=True)

        listener.close = close
    except Exception as e:
        log("add_listen_socket%s", (listener, server, new_connection_cb), exc_info=True)
        log.error("Error: failed to listen on %s socket %s:", socktype, pretty_socket(listener.address))
        log.estr(e)


def accept_connection(listener: SocketListener, timeout: float | int | None = None) -> SocketConnection | None:
    log = get_network_logger()
    try:
        sock, address = listener.socket.accept()
    except OSError as e:
        log("rejecting new connection on %s", listener, exc_info=True)
        log.error("Error: cannot accept new connection:")
        log.estr(e)
        return None
    # log("peercred(%s)=%s", sock, get_peercred(sock))
    try:
        peername = sock.getpeername()
    except OSError:
        peername = address
    sock.settimeout(timeout)
    sockname = sock.getsockname()
    conn = SocketConnection(sock, sockname, address, peername, listener.socktype, None, listener.options)
    log("accept_connection%s=%s", (listener, timeout), conn)
    return conn


def peek_connection(conn, timeout: int = PEEK_TIMEOUT_MS, size: int = PEEK_SIZE) -> bytes:
    log = get_network_logger()
    log("peek_connection(%s, %i, %i)", conn, timeout, size)
    peek_data = b""
    start = monotonic()
    elapsed = 0
    set_socket_timeout(conn, PEEK_TIMEOUT_MS / 1000)
    while elapsed <= timeout:
        try:
            peek_data = conn.peek(size)
            if peek_data:
                break
        except OSError:
            log("peek_connection(%s, %i) failed", conn, timeout, exc_info=True)
        except ValueError:
            log("peek_connection(%s, %i) failed", conn, timeout, exc_info=True)
            break
        sleep(timeout / 4000.0)
        elapsed = int(1000 * (monotonic() - start))
        log("peek: elapsed=%s, timeout=%s", elapsed, timeout)
    log("socket %s peek: got %i bytes", conn, len(peek_data))
    return peek_data


def socket_fast_read(conn, timeout=1) -> bytes:
    def noretry(_err) -> bool:
        return False
    can_retry = conn.can_retry
    conn.can_retry = noretry
    start = monotonic()
    try:
        while monotonic() - start < timeout:
            try:
                conn._socket.settimeout(0.01)
                data = conn.read(1)
                return data or b""
            except TimeoutError:
                log = get_network_logger()
                log("socket_fast_read(%s) timeout", conn)
                continue
    except OSError:
        log = get_network_logger()
        log.error("Error reading from %s", conn, exc_info=True)
        return b""
    finally:
        conn.can_retry = can_retry
    return b""


POSIX_TCP_INFO = (
    ("state", c_uint8),
)


def get_sockopt_tcp_info(sock, sockopt_tcpinfo: int, attributes=POSIX_TCP_INFO) -> dict[str, Any]:
    def get_tcpinfo_class(fields):
        class TCPInfo(Structure):
            _fields_ = tuple(fields)

            def __repr__(self):
                return f"TCPInfo({self.getdict()})"

            def getdict(self) -> dict[str, Any]:
                return {k[0]: getattr(self, k[0]) for k in self._fields_}

        return TCPInfo

    # calculate full structure size with all the fields defined:
    tcpinfo_class = get_tcpinfo_class(attributes)
    tcpinfo_size = sizeof(tcpinfo_class)
    data = sock.getsockopt(socket.SOL_TCP, sockopt_tcpinfo, tcpinfo_size)
    data_size = len(data)
    # but only define fields in the ctypes.Structure
    # if they are actually present in the returned data:
    while tcpinfo_size > data_size:
        # trim it down:
        attributes = attributes[:-1]
        tcpinfo_class = get_tcpinfo_class(attributes)
        tcpinfo_size = sizeof(tcpinfo_class)
    log = get_network_logger()
    if tcpinfo_size == 0:
        log("getsockopt(SOL_TCP, TCP_INFO, %i) no data", tcpinfo_size)
        return {}
    # log("total size=%i for fields: %s", size, csv(fdef[0] for fdef in fields))
    try:
        tcpinfo = tcpinfo_class.from_buffer_copy(data[:tcpinfo_size])
    except ValueError as e:
        log("getsockopt(SOL_TCP, TCP_INFO, %i)", tcpinfo_size, exc_info=True)
        log("TCPInfo fields=%s", csv(attributes))
        log.warn("Warning: failed to get TCP_INFO for %s", sock)
        log.warn(" %s", e)
        return {}
    d = tcpinfo.getdict()
    log("getsockopt(SOL_TCP, TCP_INFO, %i)=%s", tcpinfo_size, d)
    return d


def looks_like_xpra_packet(data: bytes) -> bool:
    if len(data) < 8:
        return False
    if data[0] != ord("P"):
        return False
    from xpra.net.protocol.header import (
        unpack_header, HEADER_SIZE,
        FLAGS_RENCODE, FLAGS_YAML,
        LZ4_FLAG, BROTLI_FLAG,
    )
    header = bytes(data).ljust(HEADER_SIZE, b"\0")
    _, protocol_flags, compression_level, packet_index, data_size = unpack_header(header)
    # this normally used on the first packet, so the packet index should be 0,
    # and I don't think we can make packets smaller than 8 bytes,
    # even with rencode
    if packet_index != 0:
        return False
    if data_size < 8 or data_size >= 256 * 1024 * 1024:
        return False
    rencode = bool(protocol_flags & FLAGS_RENCODE)
    yaml = bool(protocol_flags & FLAGS_YAML)
    lz4 = bool(protocol_flags & LZ4_FLAG)
    brotli = bool(protocol_flags & BROTLI_FLAG)
    compressors = sum((lz4, brotli))
    # only one compressor can be enabled:
    if compressors > 1:
        return False
    if compressors == 1 and compression_level <= 0:
        # if compression is enabled, the compression level must be set:
        return False
    if rencode and yaml:
        # rencode and yaml are mutually exclusive:
        return False
    # we passed all the checks
    return True


def guess_packet_type(buf: SizedBuffer) -> str:
    if not buf:
        return ""
    data = memoryview_to_bytes(buf[:32])
    if looks_like_xpra_packet(data):
        return "xpra"
    if data[:4] == b"SSH-":
        return "ssh"
    if data[0] == 0x16:
        return "ssl"
    if data[:4] == b"RFB ":
        return "vnc"
    if len(data) >= 7 and data[:2] == b"\x03\x00":
        size = data[2] * 256 + data[3]
        if len(data) >= size:
            return "rdp"
    line1 = bytes(data).splitlines()[0]
    if line1.find(b"HTTP/") > 0 or line1.split(b" ")[0] in (b"GET", b"POST"):
        return "http"
    if line1.lower().startswith(b"<!doctype html") or line1.lower().startswith(b"<html"):
        return "http"
    return ""


def create_sockets(opts, error_cb: Callable, retry: int = 0,
                   sd_listen=POSIX and not OSX, ssh_upgrades=True) -> list[SocketListener]:
    bind_tcp = parse_bind_ip(opts.bind_tcp)
    bind_ssl = parse_bind_ip(opts.bind_ssl, 443)
    bind_ssh = parse_bind_ip(opts.bind_ssh, 22)
    bind_ws = parse_bind_ip(opts.bind_ws, 80)
    bind_wss = parse_bind_ip(opts.bind_wss, 443)
    bind_rfb = parse_bind_ip(opts.bind_rfb, 5900)
    bind_rdp = parse_bind_ip(opts.bind_rdp, 3389)
    bind_quic = parse_bind_ip(opts.bind_quic, 14500)
    bind_vsock = parse_bind_vsock(opts.bind_vsock)

    min_port = int(opts.min_port)
    # Initialize the TCP sockets before the display,
    # That way, errors won't make us kill the Xvfb
    # (which may not be ours to kill at that point)
    if ssh_upgrades:
        err = ""
        try:
            with SilenceWarningsContext(DeprecationWarning):
                if not find_spec("paramiko"):
                    err = "`paramiko` module not found"
        except Exception as e:
            err = str(e)
        if err:
            from xpra.log import Logger
            sshlog = Logger("ssh")
            sshlog("import paramiko", exc_info=True)
            sshlog.warn("Error: cannot enable SSH socket upgrades")
            sshlog.warn(" %s", err)
            opts.ssh_upgrade = False
    log = get_network_logger()
    # prepare tcp socket definitions:
    tcp_defs: list[tuple[str, str, int, dict, str]] = []
    for socktype, defs in {
        "tcp": bind_tcp,
        "ssl": bind_ssl,
        "ssh": bind_ssh,
        "ws": bind_ws,
        "wss": bind_wss,
        "rfb": bind_rfb,
        "rdp": bind_rdp,
    }.items():
        log("setting up %s sockets: %s", socktype, csv(defs.items()))
        for (host, iport), options in defs.items():
            if iport != 0 and iport < min_port:
                error_cb(f"invalid {socktype} port number {iport} (minimum value is {min_port})")
            for h in hosts(host):
                tcp_defs.append((socktype, h, iport, options, ""))

    sockets: list[SocketListener] = []

    for attempt in range(retry + 1):
        if not tcp_defs:
            break
        try_list = tuple(tcp_defs)
        tcp_defs = []
        for socktype, host, iport, options, _ in try_list:
            try:
                sockets.append(setup_tcp_socket(host, iport, socktype, options))
            except Exception as e:
                log("setup_tcp_socket%s attempt=%s", (host, iport, options), attempt)
                tcp_defs.append((socktype, host, iport, options, str(e)))
        if tcp_defs:
            sleep(1)

    if tcp_defs:
        # failed to create some sockets:
        for socktype, host, iport, options, exception in tcp_defs:
            log.error("Error creating %s socket", socktype)
            log.error(" on %s:%s", host, iport)
            log.error(" %s", exception)
            raise InitException(f"failed to create {socktype} socket: {exception}")

    log("setting up vsock sockets: %s", csv(bind_vsock.items()))
    for (cid, iport), options in bind_vsock.items():
        sockets.append(setup_vsock_socket(cid, iport, options))

    log("setting up quic sockets: %s", csv(bind_quic.items()))
    for (host, iport), options in bind_quic.items():
        sockets.append(setup_quic_socket(host, iport, options))

    # systemd socket activation:
    if sd_listen:
        try:
            from xpra.platform.posix.sd_listen import get_sd_listen_sockets
        except ImportError as e:
            log("no systemd socket activation: %s", e)
        else:
            sd_sockets = get_sd_listen_sockets()
            log("systemd sockets: %s", sd_sockets)
            for stype, sock, addr in sd_sockets:
                sockets.append(setup_sd_listen_socket(stype, sock, addr))
                log("%s : %s", (stype, [addr]), sock)
    return sockets


def create_tcp_socket(host: str, iport: int) -> socket.socket:
    log = get_network_logger()
    sockaddr: tuple[str, int] | tuple[str, int, int, int] = (host, iport)
    if host.find(":") < 0:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    else:
        if host.startswith("[") and host.endswith("]"):
            host = host[1:-1]
        if not socket.has_ipv6:
            raise RuntimeError("specified an IPv6 address but this is not supported on this system")
        res = socket.getaddrinfo(host, iport, socket.AF_INET6, socket.SOCK_STREAM, 0, socket.SOL_TCP)
        log("socket.getaddrinfo(%s, %s, AF_INET6, SOCK_STREAM, 0, SOL_TCP)=%s", host, iport, res)
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        sockaddr = res[0][-1]
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    log("%s.bind(%s)", sock, sockaddr)
    sock.bind(sockaddr)
    return sock


def setup_tcp_socket(host: str, iport: int, socktype: str, options: dict[str, Any]) -> SocketListener:
    log = get_network_logger()
    try:
        tcp_socket = create_tcp_socket(host, iport)
    except Exception as e:
        log("create_tcp_socket%s", pretty_socket((host, iport)), exc_info=True)
        raise InitExit(ExitCode.SOCKET_CREATION_ERROR,
                       f"failed to setup {socktype} socket on {host}:{iport} {e}") from None

    def cleanup_tcp_socket() -> None:
        log.info("closing %s socket %s", socktype.lower(), pretty_socket((host, iport)))
        try:
            tcp_socket.close()
        except OSError:
            pass

    if iport == 0:
        iport = tcp_socket.getsockname()[1]
        log.info(f"allocated {socktype} port {iport} on {host}")
    log(f"{socktype}: {host}:{iport} : {socket}")
    log.info(f"created {socktype} socket '{host}:{iport}'")
    return SocketListener(socktype, tcp_socket, (host, iport), options, cleanup_tcp_socket, noop)


def create_udp_socket(host: str, iport: int, family: socket.AddressFamily=socket.AF_INET) -> socket.socket:
    if family == socket.AF_INET6:
        if not socket.has_ipv6:
            raise RuntimeError("specified an IPv6 address but this is not supported on this system")
        if host.startswith("[") and host.endswith("]"):
            host = host[1:-1]
    res = socket.getaddrinfo(host, iport, family=family, type=socket.SOCK_DGRAM)
    if res:
        sockaddr = res[0][4]
    else:
        sockaddr = (host, iport)
    sock = socket.socket(family, socket.SOCK_DGRAM)
    try:
        sock.bind(sockaddr)
    except Exception:
        sock.close()
        raise
    return sock


def setup_quic_socket(host: str, port: int, options: dict[str, Any]) -> SocketListener:
    try:
        from xpra.net.quic import common
        import aioquic
        assert common and aioquic
    except ImportError as e:
        raise InitExit(ExitCode.SOCKET_CREATION_ERROR,
                       f"cannot use quic sockets: {e}") from None
    return setup_udp_socket(host, port, "quic", options)


def setup_udp_socket(host: str, iport: int, socktype: str, options: dict[str, Any]) -> SocketListener:
    log = get_network_logger()
    try:
        udp_socket = create_udp_socket(host, iport, family=socket.AF_INET6 if host.find(":") >= 0 else socket.AF_INET)
    except Exception as e:
        log("create_udp_socket%s", pretty_socket((host, iport)), exc_info=True)
        raise InitExit(ExitCode.SOCKET_CREATION_ERROR,
                       f"failed to setup {socktype} socket on {host}:{iport} {e}") from None

    def cleanup_udp_socket() -> None:
        log.info("closing %s socket %s", socktype, pretty_socket((host, iport)))
        try:
            udp_socket.close()
        except OSError:
            pass

    if iport == 0:
        iport = udp_socket.getsockname()[1]
        log.info(f"allocated {socktype} port {iport} on {host}")
    log(f"{socktype}: {host}:{iport} : {socket}")
    log.info(f"created {socktype} socket '{host}:{iport}'")
    return SocketListener(socktype, udp_socket, (host, iport), options, cleanup_udp_socket, noop)


def parse_bind_ip(bind_ip: list[str], default_port: int = DEFAULT_PORT) -> dict[tuple[str, int], dict[str, Any]]:
    ip_sockets: dict[tuple[str, int], dict] = {}
    if bind_ip:
        for spec in bind_ip:
            # ie: "127.0.0.1:10000,someoption=somevalue"
            parts = spec.split(",", 1)
            # ie: "127.0.0.1:10000"
            ip_port = parts[0]
            if ":" not in spec:
                raise InitException("port must be specified as [HOST]:PORT")
            host, port = ip_port.rsplit(":", 1)
            if host == "":
                host = "127.0.0.1"
            if not port:
                iport = default_port
            else:
                try:
                    iport = int(port)
                    assert 0 <= iport < 2 ** 16
                except (TypeError, ValueError):
                    raise InitException(f"invalid port number: {port}") from None
            options = {}
            if len(parts) == 2:
                options = parse_simple_dict(parts[1])
            ip_sockets[(host, iport)] = options
    return ip_sockets


def setup_vsock_socket(cid: int, iport: int, options: dict[str, Any]) -> SocketListener:
    log = get_network_logger()
    try:
        from xpra.net.vsock.vsock import bind_vsocket
        vsock_socket = bind_vsocket(cid=cid, port=iport)
    except Exception as e:
        raise InitExit(ExitCode.SOCKET_CREATION_ERROR,
                       f"failed to setup vsock socket on {cid}:{iport} {e}") from None

    def cleanup_vsock_socket() -> None:
        log.info("closing vsock socket %s:%s", cid, iport)
        try:
            vsock_socket.close()
        except OSError:
            pass

    return SocketListener("vsock", vsock_socket, (cid, iport), options, cleanup_vsock_socket, noop)


def parse_bind_vsock(bind_vsock: list[str]) -> dict[tuple[int, int], dict]:
    vsock_sockets: dict[tuple[int, int], dict] = {}
    if bind_vsock:
        from xpra.scripts.parsing import parse_vsock_cid  # pylint: disable=import-outside-toplevel
        for spec in bind_vsock:
            parts = spec.split(",", 1)
            cid_port = parts[0].split(":")
            if len(cid_port) != 2:
                raise ValueError(f"invalid format for vsock: {parts[0]!r}, use 'CID:PORT' format")
            cid = parse_vsock_cid(cid_port[0])
            try:
                iport = int(cid_port[1])
            except ValueError:
                raise ValueError(f"vsock port must be an integer, {cid_port[0]!r} is not")
            options = {}
            if len(parts) == 2:
                options = parse_simple_dict(parts[1])
            vsock_sockets[(cid, iport)] = options
    return vsock_sockets


def setup_sd_listen_socket(stype: str, sock, addr) -> SocketListener:
    log = get_network_logger()

    def cleanup_sd_listen_socket() -> None:
        log.info(f"closing sd listen socket {pretty_socket(addr)}")
        try:
            sock.close()
        except OSError:
            pass

    return SocketListener(stype, sock, addr, {}, cleanup_sd_listen_socket, noop)


def normalize_local_display_name(local_display_name: str) -> str:
    if local_display_name.startswith("wayland-") or os.path.isabs(local_display_name):
        return local_display_name
    if local_display_name.startswith("runner"):
        return local_display_name
    pos = local_display_name.find(":")
    if pos < 0:
        after_sc = local_display_name
        local_display_name = ":" + local_display_name
    else:
        after_sc = local_display_name[pos + 1:]
    if WIN32 or OSX:
        if after_sc.isalnum():
            return local_display_name
        raise ValueError(f"non alphanumeric character in display name {local_display_name!r}")
    # we used to strip the screen from the display string, ie: ":0.0" -> ":0"
    # but now we allow it.. (untested!)
    for char in after_sc:
        if char not in "0123456789.":
            raise ValueError(f"invalid character in display name {local_display_name!r}: {char!r}")
    return local_display_name


def can_use_socket_path(path: str, uid: int, gid: int) -> bool:
    sockdir = os.path.dirname(path)
    if os.path.exists(sockdir):
        return is_writable(sockdir, uid, gid)
    # recurse until we find a directory:
    return can_use_socket_path(sockdir, uid, gid)


def get_bind_sockpaths(bind: Sequence[str], session_dir: str, display_name, dotxpra,
                       uid: int, gid: int) -> dict[str, dict[str, Any]]:
    from xpra.platform.dotxpra import norm_makepath, strip_display_prefix
    log = get_network_logger()
    sockpaths = {}
    log(f"get_bind_sockpaths: bind={bind}, dotxpra={dotxpra}")
    for b in bind:
        if b in ("none", ""):
            continue
        parts = b.split(",", 1)
        sockpath = parts[0]
        options = {}
        if len(parts) == 2:
            options = parse_simple_dict(parts[1])
        if sockpath in ("auto", "noabstract"):
            assert display_name is not None
            # norm_socket_paths is typically used for sockets in $HOME/.xpra/
            for path in dotxpra.norm_socket_paths(display_name):
                if can_use_socket_path(path, uid, gid):
                    sockpaths[path] = dict(options)
                else:
                    log.info(f"insufficient permissions to use socket path {path!r}")
            # ie: /run/user/$UID/xpra/$DISPLAYNO/socket
            if session_dir and not WIN32:
                path = os.path.join(session_dir, "socket")
                sockpaths[path] = dict(options)
            # automatic abstract sockets:
            if sockpath != "noabstract" and AUTO_ABSTRACT_SOCKET:
                sane_display_name = strip_display_prefix(display_name).replace(":", "-").replace(".", "_")
                path = "@" + ABSTRACT_SOCKET_PREFIX + sane_display_name
                abs_options = dict(options)
                if "auth" not in options:
                    abs_options["auth"] = ABSTRACT_SOCKET_AUTH
                sockpaths[path] = abs_options
            log(f"sockpaths({display_name})={sockpaths} (uid={uid}, gid={gid})")
        elif sockpath.startswith("@"):
            # explicit abstract socket
            if WIN32:
                raise ValueError("abstract sockets are not supported on MS Windows")
            sockpath = dotxpra.osexpand(sockpath)
            if not validate_abstract_socketpath(sockpath[1:]):
                raise ValueError(f"invalid characters in abstract socket name {sockpath!r}")
            sockpaths[sockpath] = options
        else:
            # explicit paths:
            sockpath = dotxpra.osexpand(sockpath)
            if sockpath.endswith("/") or (os.path.exists(sockpath) and os.path.isdir(sockpath)):
                assert display_name is not None
                sockpath = os.path.abspath(sockpath)
                if not os.path.exists(sockpath):
                    os.makedirs(sockpath)
                sockpath = norm_makepath(sockpath, display_name)
            elif not os.path.isabs(sockpath):
                sockpath = dotxpra.socket_path(sockpath)
            sockpaths[sockpath] = options
        if not sockpaths:
            raise ValueError(f"no socket paths to try for {b}")
    return noduplicatepaths(dotxpra, sockpaths)


def noduplicatepaths(dotxpra, sockpaths: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    # expand and remove duplicate paths:
    log = get_network_logger()
    tmp = {}
    for tsp, options in sockpaths.items():
        sockpath = dotxpra.osexpand(tsp)
        if sockpath in tmp:
            log.warn(f"Warning: skipping duplicate bind path {sockpath!r}")
            continue
        tmp[sockpath] = options
    sockpaths = tmp
    log(f"{sockpaths=}")
    return sockpaths


def checkstate(sockpath: str, state: SocketState | str) -> None:
    if state not in (SocketState.DEAD, SocketState.UNKNOWN):
        if state == SocketState.INACCESSIBLE:
            raise InitException(f"An xpra server is already running at {sockpath!r}\n")
        raise InitExit(ExitCode.SERVER_ALREADY_EXISTS,
                       f"You already have an xpra server running at {sockpath!r}\n"
                       "  (did you want 'xpra upgrade'?)")


def setup_local_sockets(bind, socket_dir: str, socket_dirs, session_dir: str,
                        display_name: str, clobber,
                        mmap_group: str = "auto", socket_permissions: str = "600", username: str = "",
                        uid: int = 0, gid: int = 0) -> list[SocketListener]:
    log = get_network_logger()
    log("setup_local_sockets%s",
        (bind, socket_dir, socket_dirs, session_dir, display_name, clobber, mmap_group,
         socket_permissions, username, uid, gid)
        )
    if WIN32 and not WIN32_LOCAL_SOCKETS and csv(bind) in ("auto", "noabstract"):
        return []
    if not bind or csv(bind) == "none":
        return []
    if not socket_dir and (not socket_dirs or (len(socket_dirs) == 1 and not socket_dirs[0])):
        if WIN32:
            socket_dirs = [""]
        elif not session_dir:
            raise InitExit(ExitCode.SOCKET_CREATION_ERROR,
                           "at least one socket directory must be set to use unix domain sockets")
    from xpra.platform.dotxpra import DotXpra
    dotxpra = DotXpra(socket_dir or socket_dirs[0], socket_dirs, username, uid, gid)
    if display_name and not WIN32:
        display_name = normalize_local_display_name(display_name)
    sockpaths = get_bind_sockpaths(bind, session_dir, display_name, dotxpra, uid, gid)
    log(f"{sockpaths=}")
    defs: list[SocketListener] = []
    if not sockpaths:
        return defs

    def abort() -> None:
        # undo what we can
        for sock_def in defs:
            sock_str = f"{sock_def.socktype} {sock_def.address!r}"
            try:
                sock_def.cleanup()
            except (IndexError, ValueError, OSError):
                log(f"error cleaning up socket {sock_str}", exc_info=True)
                log.error(f"Error cleaning up socket {sock_str}:", exc_info=True)

    if WIN32:
        try:
            from xpra.platform.win32.namedpipes.listener import NamedPipeListener
            from xpra.platform.win32.dotxpra import PIPE_PATH
            for sockpath, options in sockpaths.items():
                npl = NamedPipeListener(sockpath)
                ppath = sockpath
                if ppath.startswith(PIPE_PATH):
                    ppath = ppath[len(PIPE_PATH):]
                log.info(f"created named pipe '{ppath}'")
                defs.append(SocketListener("named-pipe", npl, sockpath, options, npl.stop, noop))
            return defs
        except Exception:
            log("unable to create named pipe listeners", exc_info=True)
            abort()
            raise

    sperms = parse_sock_perms(mmap_group, socket_permissions)
    try:
        # remove existing sockets if clobber is set,
        # otherwise verify there isn't a server already running
        # and create the directories for the sockets:
        unknown: list[str] = []
        for sockpath in sockpaths:
            if clobber and not sockpath.startswith("@") and os.path.exists(sockpath):
                os.unlink(sockpath)
            else:
                state = dotxpra.get_server_state(sockpath, 1)
                log(f"state({sockpath})={state}")
                checkstate(sockpath, state)
                if state == SocketState.UNKNOWN:
                    unknown.append(sockpath)
            if not sockpath.startswith("@"):
                mksockdir(dotxpra, sockpath)

        # wait for all the unknown ones:
        log(f"sockets in unknown state: {csv(unknown)}")
        if unknown:
            reprobe(dotxpra, unknown)
        # now we can re-check quickly:
        # (they should all be DEAD or UNKNOWN):
        remove_dead_sockets(dotxpra, sockpaths.keys())
        # create all the sockets:
        for sockpath, options in sockpaths.items():
            try:
                sock, cleanup_socket = create_socket(sockpath, sperms)
            except Exception as e:
                handle_socket_error(sockpath, sperms, e)
                del e
            else:
                defs.append(SocketListener("socket", sock, sockpath, options, cleanup_socket, noop))
        show_sockets(defs)
    except Exception:
        log("unable to create sockets", exc_info=True)
        abort()
        raise
    return defs


def show_sockets(created: list[SocketListener]) -> None:
    addresses = tuple(x.address for x in created)
    unix = [address for address in addresses if not address.startswith("@")]
    log = get_network_logger()
    if unix:
        log.info("created unix domain sockets:")
        for cpath in unix:
            log.info(f" {cpath!r}")
    abstract = [address for address in addresses if address.startswith("@")]
    if abstract:
        log.info("created abstract sockets:")
        for cpath in abstract:
            log.info(f" {cpath!r}")


def mksockdir(dotxpra, sockpath: str):
    d: str = os.path.dirname(sockpath)
    log = get_network_logger()
    try:
        kwargs = {}
        if d in ("/var/run/xpra", "/run/xpra"):
            # this is normally done by tmpfiles.d,
            # but we may need to do it ourselves in some cases:
            kwargs["mode"] = SOCKET_DIR_MODE
            xpra_gid = get_group_id(SOCKET_DIR_GROUP)
            if xpra_gid > 0:
                kwargs["gid"] = xpra_gid
        log(f"creating sockdir={d!r}, kwargs={kwargs}")
        dotxpra.mksockdir(d, **kwargs)
        log(f"{d!r} permission mask: " + oct(os.stat(d).st_mode))
    except Exception as e:
        log.warn(f"Warning: failed to create socket directory {d!r}")
        log.warn(f" {e}")


def parse_sock_perms(mmap_group: str, socket_permissions: str | int) -> int:
    # socket permissions:
    if mmap_group.lower() in TRUE_OPTIONS:
        # when using the mmap group option, use '660'
        return 0o660
    # parse octal mode given as config option:
    try:
        if isinstance(socket_permissions, int):
            value = int(socket_permissions)
        else:
            # assume octal string:
            value = int(socket_permissions, 8)
    except ValueError:
        raise ValueError("invalid socket permissions "
                         f"(must be an octal number): {socket_permissions!r}") from None
    if value < 0 or value > 0o777:
        raise ValueError(f"invalid socket permission value {value:o}")
    return value


def reprobe(dotxpra, unknown: Sequence[str]) -> None:
    # re-probe them using threads,
    # so we can do them in parallel:
    threads = []
    log = get_network_logger()

    def timeout_probe(sockpath: str) -> None:
        # we need a loop because "DEAD" sockets may return immediately
        # (ie: when the server is starting up)
        start = monotonic()
        while monotonic() - start < WAIT_PROBE_TIMEOUT:
            state = dotxpra.get_server_state(sockpath, WAIT_PROBE_TIMEOUT)
            log(f"timeout_probe() get_server_state({sockpath!r})={state}")
            if state not in (SocketState.UNKNOWN, SocketState.DEAD):
                break
            sleep(1)

    log.warn("Warning: some of the sockets are in an unknown state:")
    for sockpath in unknown:
        log.warn(f" {sockpath!r}")
        t = start_thread(timeout_probe, f"probe-{sockpath}", daemon=True, args=(sockpath,))
        threads.append(t)
    log.warn(" please wait as we allow the socket probing to timeout")
    # wait for all the threads to do their job:
    for t in threads:
        t.join(WAIT_PROBE_TIMEOUT + 1)


def remove_dead_sockets(dotxpra, sockpaths: Iterable[str]) -> None:
    log = get_network_logger()
    for sockpath in sockpaths:
        state = dotxpra.get_server_state(sockpath, 1)
        log(f"state({sockpath})={state}")
        checkstate(sockpath, state)
        try:
            if os.path.exists(sockpath):
                os.unlink(sockpath)
        except OSError:
            log(f"error removing {sockpath!r}", exc_info=True)


def handle_socket_error(sockpath: str, sperms: int, e) -> None:
    log = get_network_logger()
    log("socket creation error", exc_info=True)
    if sockpath.startswith("/var/run/xpra") or sockpath.startswith("/run/xpra"):
        log.info(f"cannot create group socket {sockpath!r}")
        log.info(f" {e}")
        dirname = sockpath[:sockpath.find("xpra") + len("xpra")]
        if not os.path.exists(dirname):
            log.info(f" {dirname!r} does not exist")
        # only show extra information if the socket permissions
        # would be accessible by the group:
        elif POSIX and (sperms & 0o40):
            uid = getuid()
            username = get_username_for_uid(uid)
            groups = get_groups(username)
            log.info(f" user {username!r} is a member of groups: " + (csv(groups) or "no groups!"))
            if "xpra" not in groups:
                log.info("  add 'xpra' group membership to enable group socket sharing")
            for x in path_permission_info(dirname):
                log.info(f"  {x}")
    elif sockpath.startswith("/var/run/user") or sockpath.startswith("/run/user"):
        log.warn(f"Warning: cannot create socket {sockpath!r}:")
        log.warn(f" {e}")
        run_user = sockpath.split("/user")[0] + "/user"
        if not os.path.exists(run_user):
            log.warn(f" {run_user} does not exist")
        else:
            log.warn(" ($XDG_RUNTIME_DIR has not been created?)")
    else:
        log.error(f"Error: failed to create socket {sockpath!r}")
        log.estr(e)
        if not sockpath.startswith("@"):
            raise InitExit(ExitCode.SOCKET_CREATION_ERROR, f"failed to create socket {sockpath}")


def socket_connect(host: str, port: int, timeout: float = SOCKET_TIMEOUT) -> socket.socket | None:
    socktype = socket.SOCK_STREAM
    family = 0  # 0 means any
    try:
        addrinfo = socket.getaddrinfo(host, port, family, socktype)
    except OSError as e:
        stypestr = {
            socket.AF_INET6: "IPv6",
            socket.AF_INET: "IPv4",
            0: "any",
        }.get(family, "")
        raise InitException(f"cannot get {stypestr} address for {host}:{port} : {e}") from None
    log = get_network_logger()
    log("socket_connect%s addrinfo=%s", (host, port), addrinfo)
    # try each one:
    for addr in addrinfo:
        sockaddr = addr[-1]
        family = addr[0]
        sock = socket.socket(family, socktype)
        sock.settimeout(timeout)
        try:
            log("socket.connect(%s)", sockaddr)
            sock.connect(sockaddr)
            sock.settimeout(None)
            return sock
        except OSError:
            log("failed to connect using %s%s for %s", sock.connect, sockaddr, addr, exc_info=True)
            noerr(sock.close)
    return None
