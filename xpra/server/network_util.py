# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Server side connection helpers which do not need the server instance.
"""

import os
from typing import Any
from collections.abc import Sequence
from time import monotonic

from xpra.net.common import pretty_socket, has_websocket_handler
from xpra.net.constants import HTTP_UNSUPORTED
from xpra.net.packet_type import CONNECTION_CLOSE
from xpra.net.socket_util import (
    PEEK_TIMEOUT_MS, SOCKET_PEEK_TIMEOUT_MS, SocketListener,
    peek_connection, guess_packet_type,
)
from xpra.net.digest import get_salt, gendigest
from xpra.platform.paths import get_app_dir, get_system_conf_dirs, get_user_conf_dirs
from xpra.os_util import POSIX, getuid, gi_import
from xpra.util.parsing import TRUE_OPTIONS, FALSE_OPTIONS, parse_bool_or
from xpra.util.str_fn import csv, Ellipsizer, strtobytes, hexstr
from xpra.util.env import envbool, first_time
from xpra.common import noerr
from xpra.constants import DEFAULT_XDG_DATA_DIRS
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("server")
netlog = Logger("network")
ssllog = Logger("ssl")
httplog = Logger("http")

SHOW_NETWORK_ADDRESSES = envbool("XPRA_SHOW_NETWORK_ADDRESSES", True)


def force_close_connection(conn) -> None:
    try:
        conn.close()
    except OSError:
        netlog("close_connection()", exc_info=True)


# noinspection PySimplifyBooleanCheck
def parse_html_option(opts) -> tuple[bool | None, str]:
    """
    Returns the html flag (`None` for "auto") and the web root, if one was specified
    """
    # opts.html can contain a boolean, "auto" or the path to the webroot
    www_dir = ""
    html_flag: bool | None = False
    html = opts.html or ""
    if html and os.path.isabs(html):
        www_dir = html
        html_flag = True
    elif not html or (html.lower() in FALSE_OPTIONS or html.lower() in TRUE_OPTIONS or html.lower() == "auto"):
        html_flag = parse_bool_or("html", html)
    else:
        # assume that the html option is a request to open a browser
        html_flag = True
        # find a socket we can connect the browser to:
        for mode, bind in {
            "ws": opts.bind_ws,
            "wss": opts.bind_wss,
            "tcp": opts.bind_tcp,
            "ssl": opts.bind_ssl,
        }.items():
            if bind:  # ie: ["0.0.0.0:10000", "127.0.0.1:20000"]
                from xpra.net.common import open_html_url
                # open via timeout_add so that the server is running by then,
                # plus a slight delay so that it can settle down:
                GLib.timeout_add(1000, open_html_url, html, mode, bind[0])
                break
        else:
            log.warn("Warning: cannot open html client in a browser")
            log.warn(" no compatible socket found")
    if html_flag is not False:  # True or None (for "auto")
        if not (opts.bind_tcp or opts.bind_ws or opts.bind_wss or opts.bind or opts.bind_ssl):
            # we need a socket!
            if html_flag:
                # html was enabled, so log an error:
                httplog.error("Error: cannot use the html server without a socket")
            html_flag = False
    httplog("init_html_proxy(..) html=%s", html_flag)
    if not has_websocket_handler():
        if html_flag is None:  # auto mode
            httplog.info("html server unavailable, cannot find websocket module")
        elif html_flag:
            httplog.error("Error: cannot import websocket connection handler:")
            httplog.error(" the html server will not be available")
        html_flag = False
    return html_flag, www_dir


# noinspection simplify-boolean-check
def find_www_dir(html: bool | None, www_dir: str) -> tuple[bool, str, list[str]]:
    """
    Locate the web root,
    returns the updated html flag, the web root and the http headers directories
    """
    from xpra.platform.paths import get_resources_dir
    if html is False:
        www_dir = ""
    elif www_dir:
        www_dir = str(www_dir)
    else:
        # this is the default value which will be shown in the warning if we don't find a valid one:
        www_dir = os.path.abspath(os.path.join(get_resources_dir(), "www"))
        www_dirs: list[tuple[str, ...]] = [
            (get_resources_dir(), "html5"),
            (get_resources_dir(), "www"),
            (get_app_dir(), "www"),
        ]
        if POSIX:
            xdg_data_dirs = os.environ.get("XDG_DATA_DIRS", DEFAULT_XDG_DATA_DIRS)
            for d in xdg_data_dirs.split(":"):
                www_dirs.append((d, "www"))
            for d in ("/usr/share/xpra", "/usr/local/share/xpra"):
                www_dirs.append((d, "www"))
            www_dirs.append(("/var/www/xpra/www", ))
        for parts in www_dirs:
            path = os.path.abspath(os.path.join(*parts))
            if os.path.exists(path):
                www_dir = path
                httplog("found html5 client in '%s'", www_dir)
                break
    if not os.path.exists(www_dir) and html is not False:
        httplog.error("Error: cannot find the html web root")
        httplog.error(f" {www_dir!r} does not exist")
        httplog.error(" install the `xpra-html5` package")
        httplog.error(" or turn off the builtin web server using `html=no`")
        www_dir = "/usr/share/xpra/www/"
        html = False
    http_headers_dirs: list[str] = []
    if html is not False:
        httplog.info(f"serving html content from {www_dir!r}")
        for d in get_system_conf_dirs():
            http_headers_dirs.append(os.path.join(d, "http-headers"))
        if not POSIX or getuid() > 0:
            for d in get_user_conf_dirs():
                http_headers_dirs.append(os.path.join(d, "http-headers"))
        http_headers_dirs.append(os.path.abspath(os.path.join(www_dir, "../http-headers")))
        html = True
    return bool(html), www_dir, http_headers_dirs


def can_upgrade(socktype: str, tosocktype: str, options: dict[str, str],
                ssl=False, websocket=False, ssh=False, rdp=False, rfb=False) -> bool:
    """
    Can a `socktype` connection be upgraded to `tosocktype`?
    The socket `options` take precedence over the server wide upgrade flags.
    """
    to_option_str = options.get(tosocktype, "")
    to_option = to_option_str.lower() in TRUE_OPTIONS
    netlog(f"can_upgrade%s {to_option_str=}, {to_option}", (socktype, tosocktype, options))
    if tosocktype in ("ws", "wss") and not has_websocket_handler():
        return False
    if tosocktype == "rfb":
        return rfb
    if tosocktype == "rdp":
        return rdp
    if socktype in ("tcp", "socket", "vsock", "named-pipe"):
        if tosocktype == "ssl":
            if to_option_str:
                return to_option
            return ssl
        if tosocktype == "ws":
            if to_option_str:
                return to_option
            return websocket
        if tosocktype == "wss":
            if to_option_str:
                return to_option
            return websocket and ssl
    if socktype == "ws" and tosocktype == "wss":
        if to_option_str:
            return to_option
        return ssl
    if socktype == "ssl" and tosocktype == "wss":
        if to_option_str:
            return to_option
        return websocket
    if tosocktype == "ssh":
        if to_option_str:
            return to_option
        return ssh
    return False


def get_vsock_endpoint(address) -> tuple:
    cid, port = address[0], address[1]
    try:
        from xpra.net.vsock.vsock import CID_ANY, CID_TYPES, get_local_cid  # pylint: disable=no-name-in-module
    except ImportError:
        return cid, port
    if cid == CID_ANY:
        local_cid = get_local_cid()
        if local_cid >= 0:
            cid = local_cid
    return CID_TYPES.get(cid, cid), port


def touch_sockets(paths: Sequence[str]) -> None:
    netlog("touch_sockets() unix socket paths=%s", paths)
    for sockpath in paths:
        if sockpath.startswith("@"):
            continue
        if not os.path.exists(sockpath):
            if first_time(f"missing-socket-{sockpath}"):
                log.warn("Warning: the unix domain socket cannot be found:")
                log.warn(" '%s'", sockpath)
                log.warn(" was it deleted by mistake?")
            continue
        try:
            os.utime(sockpath, None)
        except OSError as e:
            if first_time(f"touch-{sockpath}"):
                netlog.warn(f"Warning: unable to set modified time on {sockpath!r}: {e}")
            netlog("touch_sockets() error on %s", sockpath, exc_info=True)


def new_conn_err(conn, sock, socktype: str, address, packet_type: str, msg="") -> None:
    # not an xpra client
    netlog("new_conn_err", exc_info=True)
    log_fn = netlog.debug if packet_type == "http" else netlog.error
    log_fn("Error: %s connection failed:", socktype)
    if conn.remote:
        log_fn(" packet from %s", pretty_socket(conn.remote))
    if address:
        log_fn(" received on %s", pretty_socket(address))
    if packet_type:
        log_fn(" this packet looks like a %r packet", packet_type)
    else:
        log_fn(" invalid packet format, not an xpra client?")
    if msg:
        log_fn(" %s", msg)

    if packet_type == "xpra":
        # try xpra packet format:
        from xpra.net.packet_encoding import pack_one_packet
        packet_data = pack_one_packet((CONNECTION_CLOSE, "invalid protocol for this port"))
    elif packet_type == "http":
        # HTTP 400 error:
        packet_data = HTTP_UNSUPORTED
    else:
        packet_data = b"disconnect: connection setup failed"
        if msg:
            packet_data += b", %s?" % strtobytes(msg)
        packet_data += b"\n"
    try:
        # default to plain text:
        sock.settimeout(1)
        conn.write(packet_data)
    except OSError as e:
        netlog("error sending %r: %s", packet_data, e)
    GLib.timeout_add(500, force_close_connection, conn)


def peek_new_connection(conn) -> bytes:
    timeout = PEEK_TIMEOUT_MS
    if conn.socktype == "rfb":
        # rfb does not send any data, waits for a server packet
        # so don't bother waiting for something that should never come:
        timeout = 0
    elif conn.socktype == "socket":
        timeout = SOCKET_PEEK_TIMEOUT_MS
    peek_data = b""
    if timeout > 0:
        peek_data = peek_connection(conn, timeout)
    return peek_data


def log_guess_packet_type(peek_data: bytes) -> str:
    if peek_data:
        line1 = peek_data.split(b"\n")[0]
        netlog("socket peek hex=%s", hexstr(peek_data[:128]))
        netlog("socket peek line1=%s", Ellipsizer(line1))
    packet_type = guess_packet_type(peek_data)
    netlog("guess_packet_type(..)=%s", packet_type)
    return packet_type


def ssl_conn_handshake(ssl_conn) -> None:
    from xpra.net.tls.socket import ssl_handshake
    try:
        ssl_handshake(ssl_conn._socket)
    except BaseException:
        # the original socket has been detached by the ssl wrapper,
        # so closing the original connection would not close anything:
        force_close_connection(ssl_conn)
        raise


def get_ssl_socket_options(ssl_attributes: dict, socket_options: dict) -> dict[str, Any]:
    ssllog(f"get_ssl_socket_options({socket_options})")
    kwargs = {k.replace("-", "_"): v for k, v in ssl_attributes.items()}
    for k, v in socket_options.items():
        # options use '-' but attributes and parameters use '_':
        k = k.replace("-", "_")
        if k.startswith("ssl_"):
            k = k[4:]
            kwargs[k] = v
    ssllog(f"get_ssl_socket_options({socket_options})={kwargs}")
    return kwargs


def wrap_ssl_socket(socktype: str, sock, socket_options: dict, ssl_attributes: dict):
    ssllog("ssl_wrap_socket(%s, %s, %s)", socktype, sock, socket_options)
    kwargs = get_ssl_socket_options(ssl_attributes, socket_options)
    try:
        from xpra.net.tls.socket import ssl_wrap_socket
        ssl_sock = ssl_wrap_socket(sock, **kwargs)
        ssllog("_ssl_wrap_socket(%s, %s)=%s", sock, kwargs, ssl_sock)
        if ssl_sock is None:
            # None means EOF! (we don't want to import ssl bits here)
            ssllog("ignoring SSL EOF error")
        return ssl_sock
    except Exception as e:
        ssllog("SSL error", exc_info=True)
        ssl_paths = [socket_options.get(x, kwargs.get(x)) for x in ("ssl-cert", "ssl-key")]
        cpaths = csv(f"{x!r}" for x in ssl_paths if x)
        log_fn = log.error if first_time(f"ssl-wrap-{socktype}-{socket_options}") else log.debug
        log_fn("Error: failed to create SSL socket")
        log_fn(" from %s socket: %s", socktype, sock)
        if not cpaths:
            log_fn(" no certificate paths specified")
        else:
            log_fn(" check your certificate paths: %s", cpaths)
        log_fn(" %s", e)
        noerr(sock.close)
        return None


def ssh_password_authenticate(auth_module, socktype: str, conn, username: str, password: str) -> bool:
    from xpra.server.ssh import log as sshlog
    if not POSIX or getuid() != 0:
        import getpass
        sysusername = getpass.getuser()
        if sysusername != username:
            sshlog.warn("Warning: ssh password authentication failed,")
            sshlog.warn(" username does not match:")
            sshlog.warn(" expected '%s', got '%s'", sysusername, username)
            return False
    if not auth_module:
        return False
    auth_modules = auth_module.make_authenticators(socktype, {"username": username}, conn)
    sshlog("ssh_password_authenticate auth_modules(%s, %s)=%s", username, "*" * len(password), auth_modules)
    for auth in auth_modules:
        # mimic a client challenge:
        digests = ("xor", )
        try:
            salt, digest = auth.get_challenge(digests)
            salt_digest = auth.choose_salt_digest(digests)
            if digest != "xor":
                raise ValueError(f"unexpected digest {digest}")
            if salt_digest != "xor":
                raise ValueError(f"unexpected salt digest {salt_digest}")
        except ValueError as e:
            sshlog("authentication with %s", auth, exc_info=True)
            sshlog.warn("Warning: ssh transport cannot use %r authentication:", auth)
            sshlog.warn(" %s", e)
            return False
        else:
            client_salt = get_salt(len(salt))
            combined_salt = gendigest("xor", client_salt, salt)
            xored_password = gendigest("xor", password, combined_salt)
            r = auth.authenticate(xored_password, client_salt)
            sshlog("%s.authenticate(..)=%s", auth, r)
            if not r:
                return False
    return True


def log_connection_timeout(protocol) -> None:
    conn = getattr(protocol, "_conn", None)
    elapsed = round(monotonic() - protocol.start_time)
    messages = [
        "Error: connection timed out",
        " " + str(conn or protocol),
        f" after {elapsed} seconds",
    ]
    if conn:
        messages += [
            f" sent {conn.output_bytecount} bytes",
            f" received {conn.input_bytecount} bytes",
        ]
        if conn.input_bytecount == 0:
            try:
                data = conn.peek(200)
            except (OSError, ValueError):
                log("cannot peek on %s", conn)
                data = b""
            if data:
                messages.append(f" read buffer={data!r}")
                if packet_type := log_guess_packet_type(data):
                    messages.append(f" looks like {packet_type!r}")
            else:
                # no data was ever received,
                # this can happen with probes or browser connections,
                # log at debug level only to avoid spamming the log:
                for msg in messages:
                    netlog(msg)
                messages = []
    for msg in messages:
        netlog.error(msg)


def get_protocol_info(protocol) -> str:
    proto_info = f" {protocol}"
    try:
        conn = protocol._conn
        info = conn.get_info()
        endpoint = info.get("endpoint")
        if endpoint:
            proto_info = " " + pretty_socket(endpoint)
        else:
            proto_info = " " + pretty_socket(conn.local)
    except (KeyError, AttributeError):
        pass
    return proto_info


def get_socket_info(sockets: Sequence[SocketListener], websocket=False, ssl=False, ssh=False) -> dict[str, Any]:
    from xpra.net.net_util import import_netifaces, get_all_ips
    si: dict[str, Any] = {}

    def add_listener(socktype: str, info) -> None:
        si.setdefault(socktype, {}).setdefault("listeners", []).append(info)

    def add_address(socktype: str, address, port: int) -> None:
        addresses = si.setdefault(socktype, {}).setdefault("addresses", [])
        if (address, port) not in addresses:
            addresses.append((address, port))
        if socktype == "tcp":
            if websocket:
                add_address("ws", address, port)
            if ssl:
                add_address("ssl", address, port)
            if ssh:
                add_address("ssh", address, port)
        if socktype == "ws" and ssl:
            add_address("wss", address, port)

    netifaces = import_netifaces()
    for sock in sockets:
        socktype = sock.socktype
        address = sock.address
        if not address:
            continue
        add_listener(socktype, address)
        if not SHOW_NETWORK_ADDRESSES:
            continue
        if socktype not in ("tcp", "ssl", "ws", "wss", "ssh"):
            # we expose addresses only for TCP sockets
            continue
        upnp_address = sock.options.get("upnp-address", ())
        if upnp_address:
            add_address(socktype, *upnp_address)
        if len(address) != 2 or not isinstance(address[0], str) or not isinstance(address[1], int):
            # unsupported listener info format
            continue
        host, port = address
        if host not in ("0.0.0.0", "::/0", "::"):
            # not a wildcard address, use it as-is:
            add_address(socktype, host, port)
            continue
        if not netifaces:
            if first_time("netifaces-socket-address"):
                netlog("get_socket_info()", backtrace=True)
                netlog.warn("Warning: netifaces is missing")
                netlog.warn(" socket addresses cannot be queried")
        else:
            for ip in get_all_ips():
                add_address(socktype, ip, port)
    return si
