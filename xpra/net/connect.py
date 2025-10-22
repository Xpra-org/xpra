# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket
import time
from time import monotonic
from typing import Any, NoReturn

from xpra.common import noop, noerr
from xpra.exit_codes import ExitCode
from xpra.log import Logger
from xpra.net.bytestreams import SOCKET_TIMEOUT, SocketConnection, VSOCK_TIMEOUT
from xpra.net.common import verify_hyperv_available, AUTO_ABSTRACT_SOCKET, ABSTRACT_SOCKET_PREFIX, DEFAULT_PORTS
from xpra.os_util import WIN32
from xpra.scripts.config import InitException, InitExit
from xpra.util.parsing import TRUE_OPTIONS
from xpra.scripts.main import CONNECT_TIMEOUT
from xpra.util.objects import typedict


def debug(msg: str, *args) -> None:
    from xpra.log import Logger
    Logger("network").debug(msg, *args)


def connect_to_ssh(display_desc: dict[str, Any], opts, debug_cb=noop, ssh_fail_cb=noop):
    if display_desc.get("is_paramiko", False):
        from xpra.net.ssh.paramiko.client import connect_to
        conn = connect_to(display_desc)
    else:
        from xpra.net.ssh import exec_client
        conn = exec_client.connect_to(display_desc, opts, debug_cb, ssh_fail_cb)
    dtype = display_desc["type"]
    if dtype == "vnc+ssh":
        conn.socktype = "vnc"
        conn.socktype_wrapped = "ssh"
    return conn


def connect_to_namedpipe(display_desc: dict[str, Any]):
    pipe_name = display_desc["named-pipe"]
    if not WIN32:
        raise InitException("named pipes are only supported on MS Windows")
    import errno
    from xpra.platform.win32.dotxpra import PIPE_PATH, PIPE_ROOT
    from xpra.platform.win32.namedpipes.connection import NamedPipeConnection, connect_to_namedpipe
    if pipe_name.startswith(PIPE_ROOT):
        # absolute pipe path already specified
        path = pipe_name
    else:
        path = PIPE_PATH + pipe_name
    try:
        pipe_handle = connect_to_namedpipe(path)
    except Exception as e:
        try:
            if e.args[0] == errno.ENOENT:
                raise InitException(f"the named pipe {pipe_name!r} does not exist: {e}") from None
        except AttributeError:
            pass
        raise InitException(f"failed to connect to the named pipe {pipe_name!r}:\n {e}") from None
    timeout = display_desc.get("timeout", SOCKET_TIMEOUT)
    conn = NamedPipeConnection(pipe_name, pipe_handle, {})
    conn.timeout = timeout
    conn.target = f"namedpipe://{pipe_name}/"
    return conn


def connect_to_vsock(display_desc: dict[str, Any]):
    cid, iport = display_desc["vsock"]
    from xpra.net.vsock.vsock import (  # pylint: disable=no-name-in-module
        connect_vsocket,
        CID_TYPES, CID_ANY, PORT_ANY,
    )
    sock = connect_vsocket(cid=cid, port=iport)
    sock.settimeout(None)
    conn = SocketConnection(sock, "local", "host", (CID_TYPES.get(cid, cid), iport), "vsock")
    conn.timeout = VSOCK_TIMEOUT
    conn.target = "vsock://%s:%s" % (
        "any" if cid == CID_ANY else cid,
        "any" if iport == PORT_ANY else iport,
    )
    return conn


def connect_to_hyperv(display_desc: dict[str, Any]):
    vmid, service = display_desc["hyperv"]
    verify_hyperv_available()
    sock = socket.socket(socket.AF_HYPERV, socket.SOCK_STREAM, socket.HV_PROTOCOL_RAW)
    sock.connect((vmid, service))
    sock.settimeout(None)
    conn = SocketConnection(sock, "local", "host", (vmid, service), "hyperv")
    conn.timeout = VSOCK_TIMEOUT
    conn.target = f"hyperv://{vmid}.{service}"
    return conn


def connect_to_quic(display_desc: dict[str, Any], opts):
    host = display_desc["host"]
    port = display_desc["port"]
    path = "/" + display_desc.get("display", "")
    ssl_options = display_desc.get("ssl-options", {})
    ssl_server_verify_mode = ssl_options.get("server-verify-mode", opts.ssl_server_verify_mode)
    ssl_ca_certs = ssl_options.get("ca-certs", opts.ssl_ca_certs)
    ssl_cert = ssl_options.get("cert", opts.ssl_cert)
    ssl_key = ssl_options.get("key", opts.ssl_key)
    ssl_key_password = ssl_options.get("key-password", opts.ssl_key_password)
    ssl_server_name = ssl_options.get("server-hostname")
    try:
        from xpra.net.quic.client import quic_connect, FAST_OPEN
        import aioquic
        assert aioquic
    except ImportError as e:
        raise InitExit(ExitCode.SOCKET_CREATION_ERROR, f"cannot use quic sockets: {e}") from None
    fast_open = display_desc.get("fast-open", FAST_OPEN)
    conn = quic_connect(host, port, path, fast_open,
                        ssl_cert, ssl_key, ssl_key_password,
                        ssl_ca_certs, ssl_server_verify_mode, ssl_server_name)
    return conn


def connect_to_tcp(display_desc: dict[str, Any]):
    dtype = display_desc["type"]
    display_name = display_desc["display_name"]
    timeout = display_desc.get("timeout", SOCKET_TIMEOUT)
    sock = retry_socket_connect(display_desc)
    # use non-blocking until the connection is finalized
    sock.settimeout(0.1)
    conn = SocketConnection(sock, sock.getsockname(), sock.getpeername(), display_name,
                            dtype, socket_options=display_desc)

    if dtype in ("ssl", "wss"):
        raw_sock = sock
        from xpra.net.ssl.socket import ssl_handshake, ssl_wrap_socket
        # convert option names to function arguments:
        ssl_options = {k.replace("-", "_"): v for k, v in display_desc.get("ssl-options", {}).items()}
        try:
            sock = ssl_wrap_socket(sock, **ssl_options)
        except ValueError as e:
            raise InitExit(ExitCode.SSL_FAILURE, f"ssl setup failed: {e}")
        if not sock:
            raise RuntimeError(f"failed to wrap socket {raw_sock} as {dtype!r}")
        ssl_handshake(sock)
        conn._socket = sock
        conn.timeout = timeout

    # wrap in a websocket:
    if dtype in ("ws", "wss"):
        host = display_desc["host"]
        port = display_desc.get("port", 0)
        # do the websocket upgrade and switch to binary
        try:
            from xpra.net.websockets.common import client_upgrade
        except ImportError as e:  # pragma: no cover
            raise InitExit(ExitCode.UNSUPPORTED, f"cannot handle websocket connection: {e}") from None
        else:
            display_path = display_desc_to_display_path(display_desc)
            client_upgrade(conn.read, conn.write, host, port, display_path)
    conn.target = get_host_target_string(display_desc)
    return conn


def connect_to_socket(display_desc: dict[str, Any]):
    if not hasattr(socket, "AF_UNIX"):  # pragma: no cover
        raise InitExit(ExitCode.UNSUPPORTED, "unix domain sockets are not available on this operating system")

    def sockpathfail_cb(msg) -> NoReturn:
        raise InitException(msg)

    sockpath = ""
    sock = None
    timeout = display_desc.get("timeout", SOCKET_TIMEOUT)
    display_name = display_desc["display_name"]
    if display_name and not display_desc.get("socket_path") and AUTO_ABSTRACT_SOCKET:
        # see if we can just connect to the abstract socket if one exists:
        from xpra.platform.dotxpra import strip_display_prefix
        sockpath = "@" + ABSTRACT_SOCKET_PREFIX + strip_display_prefix(display_name)
        actual_path = "\0" + sockpath[1:] if sockpath.startswith("@") else sockpath
        sock = socket.socket(socket.AF_UNIX)
        sock.settimeout(1.0)
        try:
            sock.connect(actual_path)
        except OSError:
            debug(f"failed to connect to abstract socket {sockpath}")
            noerr(sock.close)
            sock = None
    if not sock:
        from xpra.scripts.main import get_sockpath
        sockpath = get_sockpath(display_desc, sockpathfail_cb)
        display_desc["socket_path"] = sockpath
        actual_path = "\0" + ABSTRACT_SOCKET_PREFIX + sockpath[1:] if sockpath.startswith("@") else sockpath
        sock = socket.socket(socket.AF_UNIX)
        sock.settimeout(timeout)
        start = monotonic()
        while monotonic() - start < timeout:
            try:
                sock.connect(actual_path)
                break
            except ConnectionRefusedError as e:
                elapsed = monotonic() - start
                debug("%s, retrying %i < %i", e, elapsed, timeout)
                time.sleep(0.5)
                continue
            except Exception as e:
                debug(f"failed to connect using {sock.connect}({sockpath})")
                noerr(sock.close)
                raise InitExit(ExitCode.CONNECTION_FAILED, f"failed to connect to {sockpath!r}:\n {e}") from None
    try:
        sock.settimeout(None)
        conn = SocketConnection(sock, sock.getsockname(), sock.getpeername(), display_name, "socket")
        conn.timeout = timeout
        target = "socket://"
        username = display_desc.get("username")
        if username:
            target += f"{username}@"
        target += sockpath
        conn.target = target
        return conn
    except OSError:
        noerr(sock.close)
        raise


def connect_to(display_desc: dict[str, Any], opts, debug_cb=noop, ssh_fail_cb=noop):
    dtype = display_desc["type"]
    if dtype in ("ssh", "vnc+ssh"):
        return connect_to_ssh(display_desc, opts, debug_cb, ssh_fail_cb)
    if dtype == "socket":
        return connect_to_socket(display_desc)
    if dtype == "named-pipe":  # pragma: no cover
        return connect_to_namedpipe(display_desc)
    if dtype == "vsock":
        return connect_to_vsock(display_desc)
    if dtype == "hyperv":
        return connect_to_hyperv(display_desc)
    if dtype == "quic":
        return connect_to_quic(display_desc, opts)
    if dtype in ("tcp", "ssl", "ws", "wss", "vnc"):
        return connect_to_tcp(display_desc)
    raise InitException(f"unsupported display type: {dtype}")


def get_host_target_string(display_desc: dict, port_key="port", prefix="") -> str:
    dtype = display_desc["type"]
    username = display_desc.get(prefix + "username", "")
    host = display_desc[prefix + "host"]
    try:
        port = int(display_desc.get(prefix + port_key))
        if not 0 < port < 2 ** 16:
            port = 0
    except (ValueError, TypeError):
        port = 0
    display = display_desc.get(prefix + "display", "")
    return host_target_string(dtype, username, host, port, display)


def host_target_string(dtype: str, username: str, host: str, port: int, display: str = "") -> str:
    target = f"{dtype}://"
    if username:
        target += f"{username}@"
    target += host
    default_port = DEFAULT_PORTS.get(dtype, 0)
    if port and port != default_port:
        target += f":{port}"
    if display and display.startswith(":"):
        display = display[1:]
    target += "/%s" % (display or "")
    return target


def display_desc_to_uri(display_desc: dict[str, Any]) -> str:
    dtype = display_desc.get("type")
    if not dtype:
        raise InitException("missing display type")
    uri = f"{dtype}://"
    username = display_desc.get("username")
    if username is not None:
        uri += username
    password = display_desc.get("password")
    if password is not None:
        uri += ":" + password
    if username is not None or password is not None:
        uri += "@"
    if dtype in ("ssh", "tcp", "ssl", "ws", "wss", "quic"):
        # TODO: re-add 'proxy_host' arguments here
        host = display_desc.get("host")
        if not host:
            raise InitException("missing host from display parameters")
        uri += host
        port = display_desc.get("port")
        if port and port != DEFAULT_PORTS.get(dtype):
            uri += f":{port:d}"
        elif dtype == "vsock":
            cid, iport = display_desc["vsock"]
            uri += f"{cid}:{iport}"
        elif dtype == "hyperv":
            vmid, service = display_desc["hyperv"]
            uri += f"{vmid}:{service}"
    else:
        raise NotImplementedError(f"{dtype} is not implemented yet")
    uri += "/" + display_desc_to_display_path(display_desc)
    return uri


def display_desc_to_display_path(display_desc: dict[str, Any]) -> str:
    uri = ""
    path = display_desc.get("path")
    if path:
        uri += path
    display = display_desc.get("display")
    if display:
        if path:
            uri += "#"
        uri += display.lstrip(":")
    options_str = display_desc.get("options_str")
    if options_str:
        uri += f"?{options_str}"
    return uri


def retry_socket_connect(options: dict):
    host = options["host"]
    port = options["port"]
    dtype = options["type"]
    if "proxy-host" in options:
        return proxy_connect(options)
    from xpra.net.socket_util import socket_connect
    start = monotonic()
    retry = options.get("retry", True) in TRUE_OPTIONS
    quiet = options.get("quiet", False)
    retry_count = 0
    timeout = options.get("timeout", CONNECT_TIMEOUT)
    while True:
        sock = socket_connect(host, port, timeout=timeout)
        if sock:
            return sock
        if not retry:
            break
        if monotonic() - start >= timeout:
            break
        if not quiet and retry_count == 0:
            log = Logger("network")
            log.info("")
            log.info(f"failed to connect to {dtype}://{host}:{port}/")
            log.info(f" retrying for {timeout} seconds")
            log.info("")
        retry_count += 1
        time.sleep(1)
    raise InitExit(ExitCode.CONNECTION_FAILED, f"failed to connect to {dtype} socket {host}:{port}")


def proxy_connect(options: dict):
    # if is_debug_enabled("proxy"):
    # log = logging.getLogger(__name__)
    try:
        # noinspection PyPackageRequirements
        import socks
    except ImportError as e:
        raise ValueError(f"cannot connect via a proxy: {e}") from None
    to = typedict(options)
    ptype = to.strget("proxy-type")
    proxy_type = {
        "SOCKS5": socks.SOCKS5,
        "SOCKS4": socks.SOCKS4,
        "HTTP": socks.HTTP,
    }.get(ptype, socks.SOCKS5)
    if not proxy_type:
        raise InitExit(ExitCode.UNSUPPORTED, f"unsupported proxy type {ptype!r}")
    host = to.strget("proxy-host")
    port = to.intget("proxy-port", 1080)
    rdns = to.boolget("proxy-rdns", True)
    username = to.strget("proxy-username")
    password = to.strget("proxy-password")
    timeout = to.intget("timeout", CONNECT_TIMEOUT)
    sock = socks.socksocket()
    sock.set_proxy(proxy_type, host, port, rdns, username, password)
    sock.settimeout(timeout)
    sock.connect((host, port))
    return sock
