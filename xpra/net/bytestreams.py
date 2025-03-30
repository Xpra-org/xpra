# This file is part of Xpra.
# Copyright (C) 2011-2024 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os
import errno
import socket
from typing import Any
from collections.abc import Callable

from xpra.net.common import ConnectionClosedException, IP_SOCKTYPES, TCP_SOCKTYPES
from xpra.util.str_fn import csv
from xpra.util.env import hasenv, envint, envbool, SilenceWarningsContext
from xpra.common import FULL_INFO
from xpra.util.thread import start_thread
from xpra.os_util import POSIX, LINUX, WIN32, OSX
from xpra.platform.features import TCP_OPTIONS, IP_OPTIONS, SOCKET_OPTIONS
from xpra.log import Logger

log = Logger("network", "protocol")

SOCKET_CORK: bool = envbool("XPRA_SOCKET_CORK", LINUX)
if SOCKET_CORK:
    try:
        assert socket.TCP_CORK > 0  # @UndefinedVariable
    except (AttributeError, AssertionError) as cork_e:
        log.warn("Warning: unable to use TCP_CORK on %s", sys.platform)
        log.warn(" %s", cork_e)
        SOCKET_CORK = False
SOCKET_NODELAY: bool | None = None
if hasenv("XPRA_SOCKET_NODELAY"):
    SOCKET_NODELAY = envbool("XPRA_SOCKET_NODELAY")
SOCKET_KEEPALIVE: bool = envbool("XPRA_SOCKET_KEEPALIVE", True)
VSOCK_TIMEOUT: int = envint("XPRA_VSOCK_TIMEOUT", 5)
SOCKET_TIMEOUT: int = envint("XPRA_SOCKET_TIMEOUT", 20)
# this is more proper but would break the proxy server:
SOCKET_SHUTDOWN: bool = envbool("XPRA_SOCKET_SHUTDOWN", False)
LOG_TIMEOUTS: int = envint("XPRA_LOG_TIMEOUTS", 1)

ABORT: dict[int, str] = {
    errno.ENXIO: "ENXIO",
    errno.ECONNRESET: "ECONNRESET",
    errno.EPIPE: "EPIPE",
}

PROTOCOL_STR = {}
FAMILY_STR = {}
for x in dir(socket):
    if x.startswith("AF_"):
        PROTOCOL_STR[getattr(socket, x)] = x
    if x.startswith("SOCK_"):
        FAMILY_STR[getattr(socket, x)] = x
del x

CAN_RETRY_EXCEPTIONS = ()
CLOSED_EXCEPTIONS = ()


def can_retry(e) -> bool | str:
    if isinstance(e, socket.timeout):
        return "socket.timeout"
    if isinstance(e, BlockingIOError):
        return True
    if isinstance(e, BrokenPipeError):
        raise ConnectionClosedException(e) from None
    if isinstance(e, OSError):
        if isinstance(e, CAN_RETRY_EXCEPTIONS):
            return str(e)
        code = e.args[0]
        abort = ABORT.get(code, code)
        if abort is not None:
            err = getattr(e, "errno", None)
            log("can_retry: %s, args=%s, errno=%s, code=%s, abort=%s", type(e), e.args, err, code, abort)
            raise ConnectionClosedException(e) from None
    if isinstance(e, CLOSED_EXCEPTIONS):
        raise ConnectionClosedException(e) from None
    return False


def untilConcludes(is_active_cb: Callable[[], bool], can_retry_cb: Callable[[Any], bool], f: Callable, *a, **kw):
    while is_active_cb():
        try:
            return f(*a, **kw)
        except Exception as e:
            retry = can_retry_cb(e)
            if not retry:
                raise
            if LOG_TIMEOUTS > 0:
                log("untilConcludes(%s, %s, %s, %s, %s) %s, retry=%s",
                    is_active_cb, can_retry_cb, f, a, kw, e, retry, exc_info=LOG_TIMEOUTS >= 2)


def pretty_socket(s) -> str:
    try:
        if isinstance(s, bytes):
            if len(s) >= 2 and s[0] == 0:
                return "@" + s[1:].decode("latin1")
            return s.decode("latin1")
        if isinstance(s, str):
            if s and s[0] == "\0":
                return "@" + s[1:]
            return s
        if len(s) == 2:
            if str(s[0]).find(":") >= 0:
                # IPv6
                return "[%s]:%s" % (s[0], s[1])
            return "%s:%s" % (s[0], s[1])
        if len(s) == 4:
            return csv(str(x) for x in s)
    except (ValueError, TypeError):
        pass
    return str(s)


class Connection:
    def __init__(self, endpoint, socktype, info=None, options=None):
        log("Connection%s", (endpoint, socktype, info, options))
        self.endpoint = endpoint
        try:
            assert isinstance(endpoint, (tuple, list))
            self.target = ":".join(str(x) for x in endpoint)
        except Exception:
            self.target = str(endpoint)
        self.socktype_wrapped = socktype
        self.socktype = socktype
        self.info = info or {}
        self.options = options or {}
        self.input_bytecount = 0
        self.input_readcount = 0
        self.output_bytecount = 0
        self.output_writecount = 0
        self.filename = None  # only used for unix domain sockets!
        self.active = True
        self.timeout = 0

    def set_nodelay(self, nodelay: bool) -> None:
        """ TCP sockets override this method  """

    def set_cork(self, cork: bool) -> None:
        """ TCP sockets override this method  """

    def is_active(self) -> bool:
        return self.active

    def set_active(self, active: bool) -> None:
        self.active = active

    def close(self) -> None:
        self.set_active(False)

    def can_retry(self, e) -> bool | str:
        return can_retry(e)

    def untilConcludes(self, *args):
        return untilConcludes(self.is_active, self.can_retry, *args)

    def peek(self, _n: int) -> bytes:
        # not implemented
        return b""

    def _write(self, *args) -> int:
        """ wraps do_write with packet accounting """
        w = self.untilConcludes(*args)
        self.output_bytecount += w or 0
        self.output_writecount += int(w is not None)
        return w

    def _read(self, *args):
        """ wraps do_read with packet accounting """
        r = self.untilConcludes(*args)
        self.input_bytecount += len(r or "")
        self.input_readcount += 1
        return r

    def get_info(self) -> dict[str, Any]:
        info = self.info.copy()
        if self.socktype_wrapped != self.socktype:
            info["wrapped"] = self.socktype_wrapped
        info |= {
            "type": self.socktype or "",
            "endpoint": self.endpoint or (),
            "active": self.active,
            "input": {
                "bytecount": self.input_bytecount,
                "readcount": self.input_readcount,
            },
            "output": {
                "bytecount": self.output_bytecount,
                "writecount": self.output_writecount,
            },
        }
        return info


# A simple, portable abstraction for a blocking, low-level
# (os.read/os.write-style interface) two-way byte stream:
# client.py relies on self.filename to locate the unix domain
# socket (if it exists)
class TwoFileConnection(Connection):
    def __init__(self, writeable, readable, abort_test=None, target=None, socktype="", close_cb=None, info=None):
        super().__init__(target, socktype, info)
        self._writeable = writeable
        self._readable = readable
        self._read_fd = self._readable.fileno()
        self._write_fd = self._writeable.fileno()
        self._abort_test = abort_test
        self._close_cb = close_cb

    def may_abort(self, action):
        """ if abort_test is defined, run it """
        if self._abort_test:
            self._abort_test(action)

    def flush(self) -> None:
        r = self._readable
        if r:
            r.flush()
        w = self._writeable
        if w:
            w.flush()

    def read(self, n):
        self.may_abort("read")
        return self._read(os.read, self._read_fd, n)

    def write(self, buf, _packet_type: str = "") -> int:
        self.may_abort("write")
        return self._write(os.write, self._write_fd, buf)

    def close(self) -> None:
        log("%s.close() close callback=%s, readable=%s, writeable=%s",
            self, self._close_cb, self._readable, self._writeable)
        super().close()
        cc = self._close_cb
        if cc:
            self._close_cb = None
            log("%s.close() calling %s", self, cc)
            with log.trap_error(f"{self}.close() error on callback {cc}"):
                cc()

        def close_files_thread() -> None:
            log("close_files_thread() _readable=%s", self._readable)
            log("close_files_thread() calling %s", self._readable.close)
            try:
                self._readable.close()
            except OSError as e:
                log("close_files_thread() %s", self._readable, e)
            log("close_files_thread() _writeable=%s", self._writeable)
            log("close_files_thread() calling %s", self._writeable.close)
            try:
                self._writeable.close()
            except OSError as e:
                log("close_files_thread() %s", self._writeable, e)

        start_thread(close_files_thread, "close-files-thread", daemon=True)
        log("%s.close() done", self)

    def __repr__(self):
        return f"Pipe({self.target})"

    def get_info(self) -> dict[str, Any]:
        d = super().get_info()
        d |= {
            "type": "pipe",
            "pipe": {
                "read": {"fd": self._read_fd},
                "write": {"fd": self._write_fd},
            },
        }
        return d


class SocketConnection(Connection):
    def __init__(self, sock, local, remote, target, socktype, info=None, socket_options=None):
        log("SocketConnection%s", (sock, local, remote, target, socktype, info, socket_options))
        super().__init__(target, socktype, info, socket_options)
        self._socket = sock
        self.local = local
        self.remote = remote
        self.protocol_type = "socket"
        if self.socktype_wrapped in TCP_SOCKTYPES:
            def boolget(k, default_value):
                v = self.options.get(k)
                if v is None:
                    return default_value
                try:
                    return bool(int(v))
                except ValueError:
                    return default_value

            self.cork = boolget("cork", SOCKET_CORK)
            self.nodelay = boolget("nodelay", SOCKET_NODELAY)
            log("%s options: cork=%s, nodelay=%s", self.socktype_wrapped, self.cork, self.nodelay)
            if self.nodelay:
                self.do_set_nodelay(self.nodelay)
            keepalive = boolget("keepalive", SOCKET_KEEPALIVE)
            try:
                self._setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, int(keepalive))
                if keepalive:
                    idletime = 10
                    interval = 3
                    kmax = 5
                    if WIN32:
                        sock = self.get_raw_socket()
                        if sock:
                            # @UndefinedVariable pylint: disable=no-member
                            sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, idletime * 1000, interval * 1000))
                    elif OSX:
                        TCP_KEEPALIVE = 0x10
                        self._setsockopt(socket.IPPROTO_TCP, TCP_KEEPALIVE, interval)
                    elif LINUX:
                        self._setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, idletime)
                        self._setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, interval)
                        self._setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, kmax)
            except OSError:
                log("cannot set KEEPALIVE", exc_info=True)
        else:
            self.cork = False
            self.nodelay = False
        self.nodelay_value = None
        self.cork_value = None
        if isinstance(remote, str):
            self.filename = remote

    def enable_peek(self, peeked=b""):
        if isinstance(self._socket, SocketPeekWrapper):
            raise RuntimeError("`peek` has already been enabled")
        self._socket = SocketPeekWrapper(self._socket, peeked)

    def get_raw_socket(self):
        return self._socket

    def _setsockopt(self, *args) -> None:
        if self.active:
            sock = self.get_raw_socket()
            if sock:
                sock.setsockopt(*args)

    def set_nodelay(self, nodelay: bool) -> None:
        if self.nodelay is None and self.nodelay_value != nodelay:
            self.do_set_nodelay(nodelay)

    def do_set_nodelay(self, nodelay: bool) -> None:
        self._setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, nodelay)
        self.nodelay_value = nodelay
        log("changed %s socket to nodelay=%s", self.socktype, nodelay)

    def set_cork(self, cork: bool) -> None:
        if self.cork and self.cork_value != cork:
            self._setsockopt(socket.IPPROTO_TCP, socket.TCP_CORK, cork)  # @UndefinedVariable
            self.cork_value = cork
            log("changed %s socket to cork=%s", self.socktype, cork)

    def peek(self, n: int) -> bytes:
        log("%s(%s, MSG_PEEK)", self._socket.recv, n)
        return self._socket.recv(n, socket.MSG_PEEK)

    def read(self, n: int) -> bytes:
        return self._read(self._socket.recv, n)

    def write(self, buf, _packet_type: str = "") -> int:
        return self._write(self._socket.send, buf)

    def close(self) -> None:
        s = self._socket
        log(f"{self}.close() socket={s}")
        super().close()
        try:
            s.settimeout(0)
        except OSError:
            pass
        if SOCKET_SHUTDOWN:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                log("%s.shutdown(SHUT_RDWR)", s, exc_info=True)
        try:
            s.close()
        except EOFError:
            log("%s.close()", s, exc_info=True)
        except OSError as e:
            if self.error_is_closed(e):
                log("%s.close() already closed!", s)
            else:
                raise
        log("%s.close() done", self)

    def error_is_closed(self, e) -> bool:
        return isinstance(e, CLOSED_EXCEPTIONS)

    def __repr__(self):
        if self.remote:
            return "%s %s: %s <- %s" % (
                self.socktype, self.protocol_type,
                pretty_socket(self.local), pretty_socket(self.remote),
            )
        return f"{self.socktype} {self.protocol_type}:{pretty_socket(self.local)}"

    def get_info(self) -> dict[str, Any]:
        d = super().get_info()
        try:
            d["remote"] = self.remote or ""
            d["protocol-type"] = self.protocol_type
            if FULL_INFO > 0:
                si = self.get_socket_info()
                if si:
                    d["socket"] = si
        except OSError:
            log.error("Error accessing socket information", exc_info=True)
        return d

    def get_socket_info(self) -> dict[str, Any]:
        return self.do_get_socket_info(self._socket)

    def do_get_socket_info(self, s) -> dict[str, Any]:
        if not s:
            return {}
        info: dict[str, Any] = {}
        try:
            info |= {
                "proto": s.proto,
                "family": FAMILY_STR.get(s.family, int(s.family)),
                "type": PROTOCOL_STR.get(s.type, int(s.type)),
                "cork": self.cork,
            }
        except AttributeError:
            log("do_get_socket_info()", exc_info=True)
        if self.nodelay is not None:
            info["nodelay"] = self.nodelay
        try:
            info["timeout"] = int(1000 * (s.gettimeout() or 0))
        except OSError:
            pass
        try:
            if POSIX:
                fd = s.fileno()
            else:
                fd = 0
            if fd:
                info["fileno"] = fd
            # ie: self.local = ("192.168.1.7", "14500")
            log("do_get_socket_info(%s) fd=%s, local=%s", s, fd, self.local)
            if self.local and len(self.local) == 2 and FULL_INFO > 1:
                from xpra.net.net_util import get_interface
                iface = get_interface(self.local[0])
                # ie: iface = "eth0"
                device_info = {}
                if iface:
                    device_info["name"] = iface
                if iface and iface != "lo":
                    try:
                        from xpra.platform.netdev_query import get_interface_info
                    except ImportError as e:
                        log("do_get_socket_info() no netdev_query: %s", e)
                    else:
                        device_info.update(get_interface_info(fd, iface))
                if device_info:
                    info["device"] = device_info
        except (OSError, ValueError) as e:
            log("do_get_socket_info() error querying socket speed", exc_info=True)
            log.error("Error querying socket speed:")
            log.estr(e)
        else:
            opts = {
                "SOCKET": get_socket_options(s, socket.SOL_SOCKET, SOCKET_OPTIONS),
            }
            if self.socktype_wrapped in IP_SOCKTYPES:
                opts["IP"] = get_socket_options(s, socket.SOL_IP, IP_OPTIONS)
            if self.socktype_wrapped in TCP_SOCKTYPES:
                opts["TCP"] = get_socket_options(s, socket.IPPROTO_TCP, TCP_OPTIONS)
                from xpra.platform.netdev_query import get_tcp_info
                try:
                    opts["TCP_INFO"] = get_tcp_info(s)
                except (OSError, ValueError) as e:
                    log(f"get_tcp_info({s})", exc_info=True)
                    if self.is_active() and not self.error_is_closed(e):
                        log.warn("Warning: failed to get tcp information")
                        log.warn(f" from {self.socktype} socket {self}")
            # ipv6:  IPV6_ADDR_PREFERENCES, IPV6_CHECKSUM, IPV6_DONTFRAG, IPV6_DSTOPTS, IPV6_HOPOPTS,
            #        IPV6_MULTICAST_HOPS, IPV6_MULTICAST_IF, IPV6_MULTICAST_LOOP, IPV6_NEXTHOP, IPV6_PATHMTU,
            #        IPV6_PKTINFO, IPV6_PREFER_TEMPADDR, IPV6_RECVDSTOPTS, IPV6_RECVHOPLIMIT, IPV6_RECVHOPOPTS,
            #        IPV6_RECVPATHMTU, IPV6_RECVPKTINFO, IPV6_RECVRTHDR, IPV6_RECVTCLASS, IPV6_RTHDR,
            #        IPV6_RTHDRDSTOPTS, IPV6_TCLASS, IPV6_UNICAST_HOPS, IPV6_USE_MIN_MTU, IPV6_V6ONLY
            info["options"] = opts
        return info


def get_socket_options(sock, level, options) -> dict:
    opts = {}
    errs = []
    for k in options:
        opt = getattr(socket, k, None)
        if opt is None:
            continue
        try:
            v = sock.getsockopt(level, opt)
        except OSError:
            log("sock.getsockopt(%i, %s)", level, k, exc_info=True)
            errs.append(k)
        else:
            if v is not None:
                opts[k] = v
    if errs:
        fileno = getattr(sock, "fileno", None)
        if fileno and fileno() == -1:
            log("socket is closed, ignoring: %s", csv(errs))
        else:
            log.warn("Warning: failed to query %s", csv(errs))
            log.warn(" on %s", sock)
    return opts


class SocketPeekFile:
    def __init__(self, fileobj, peeked, update_peek):
        self.fileobj = fileobj
        self.peeked: bytes = peeked
        self.update_peek = update_peek

    def __getattr__(self, attr):
        if attr == "readline" and self.peeked:
            return self.readline
        return getattr(self.fileobj, attr)

    def readline(self, limit: int = -1):
        if self.peeked:
            newline = self.peeked.find(b"\n")
            peeked = self.peeked
            length = len(peeked)
            if newline == -1:
                if limit == -1 or limit > length:
                    # we need to read more until we hit a newline:
                    if limit == -1:
                        more = self.fileobj.readline(limit)
                    else:
                        more = self.fileobj.readline(limit - length)
                    self.peeked = b""
                    self.update_peek(self.peeked)
                    return peeked + more
                read = limit
            else:
                if limit < 0 or limit >= newline:
                    read = newline + 1
                else:
                    read = limit
            self.peeked = peeked[read:]
            self.update_peek(self.peeked)
            return peeked[:read]
        return self.fileobj.readline(limit)


class SocketPeekWrapper:
    def __init__(self, sock, peeked=b""):
        self.socket = sock
        self.peeked = peeked

    def __getattr__(self, attr):
        if attr == "makefile":
            return self.makefile
        if attr == "recv":
            return self.recv
        return getattr(self.socket, attr)

    def makefile(self, mode, bufsize=None):
        fileobj = self.socket.makefile(mode, bufsize)
        if self.peeked and mode and mode.startswith("r"):
            return SocketPeekFile(fileobj, self.peeked, self._update_peek)
        return fileobj

    def _update_peek(self, peeked: bytes):
        self.peeked = peeked

    def recv(self, bufsize, flags=0) -> bytes:
        if flags & socket.MSG_PEEK:
            length = len(self.peeked)
            if length >= bufsize:
                log("patched_recv() peeking using existing data: %i bytes", bufsize)
                return self.peeked[:bufsize]
            v = self.socket.recv(bufsize - length)
            if v:
                log("patched_recv() peeked more: %i bytes", len(v))
                self.peeked += v
            return self.peeked
        if self.peeked:
            peeked = self.peeked[:bufsize]
            self.peeked = self.peeked[bufsize:]
            log("patched_recv() non peek, returned already read data")
            return peeked
        return self.socket.recv(bufsize, flags)


class SSLSocketConnection(SocketConnection):
    SSL_TIMEOUT_MESSAGES = ("The read operation timed out", "The write operation timed out")

    def can_retry(self, e) -> bool | str:
        if getattr(e, "library", None) == "SSL":
            reason = getattr(e, "reason", None)
            if reason in ("WRONG_VERSION_NUMBER", "UNEXPECTED_RECORD"):
                return False
        message = e.args[0]
        if message in SSLSocketConnection.SSL_TIMEOUT_MESSAGES:
            return True
        code = getattr(e, "code", None)
        if code in SSLSocketConnection.SSL_TIMEOUT_MESSAGES:
            return True
        return super().can_retry(e)

    def get_info(self) -> dict[str, Any]:
        i = super().get_info()
        i["ssl"] = True
        for k, fn in {
            "compression": "compression",
            "alpn-protocol": "selected_alpn_protocol",
            "npn-protocol": "selected_npn_protocol",
            "version": "version",
        }.items():
            sfn = getattr(self._socket, fn, None)
            if sfn:
                with SilenceWarningsContext(DeprecationWarning):
                    v = sfn()
                if v is not None:
                    i[k] = v
        cipher_fn = getattr(self._socket, "cipher", None)
        if cipher_fn:
            cipher = cipher_fn()
            if cipher:
                i["cipher"] = {
                    "name": cipher[0],
                    "protocol": cipher[1],
                    "bits": cipher[2],
                }
        return i


def set_socket_timeout(conn, timeout=None) -> None:
    # FIXME: this is ugly, but less intrusive than the alternative?
    if isinstance(conn, SocketConnection):
        sock = conn._socket
        log("set_socket_timeout(%s, %s) applied to %s", conn, timeout, sock)
        conn._socket.settimeout(timeout)
    else:
        log("set_socket_timeout(%s, %s) ignored for %s", conn, timeout, type(conn))


def log_new_connection(conn, socket_info="") -> None:
    """ logs the new connection message """
    sock = conn._socket
    address = conn.remote
    socktype = conn.socktype
    try:
        peername = sock.getpeername()
    except OSError:
        peername = address
    try:
        sockname = sock.getsockname()
    except AttributeError:
        # ie: ssh channel
        sockname = ""
    log("log_new_connection(%s, %s) type=%s, sock=%s, sockname=%s, address=%s, peername=%s",
        conn, socket_info, type(conn), sock, sockname, address, peername)
    log.info("New %s connection received", socktype)
    if peername:
        frominfo = pretty_socket(peername)
        log.info(" from '%s'", pretty_socket(frominfo))
        if socket_info:
            log.info(" on '%s'", pretty_socket(socket_info))
    elif socktype == "socket":
        frominfo = sockname
        log.info(" on '%s'", pretty_socket(frominfo))
    else:
        if socket_info:
            log.info(" on %s", pretty_socket(socket_info))


def get_socket_config() -> dict[str, Any]:
    config = {}
    try:
        config = {
            "vsocket.timeout": VSOCK_TIMEOUT,
            "socket.timeout": SOCKET_TIMEOUT,
        }
        if SOCKET_NODELAY is not None:
            config["socket.nodelay"] = SOCKET_NODELAY
    except Exception:  # pragma: no cover
        log("get_net_config()", exc_info=True)
    return config
