# This file is part of Xpra.
# Copyright (C) 2011-2019 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os
import time
import errno
import socket

from xpra.net.common import ConnectionClosedException
from xpra.util import envint, envbool, csv
from xpra.os_util import WIN32, PYTHON2, POSIX, LINUX
from xpra.platform.features import TCP_OPTIONS, IP_OPTIONS, SOCKET_OPTIONS
from xpra.log import Logger

log = Logger("network", "protocol")

SOCKET_CORK = envbool("XPRA_SOCKET_CORK", LINUX)
if SOCKET_CORK:
    try:
        assert socket.TCP_CORK>0
    except (AttributeError, AssertionError) as cork_e:
        log.warn("Warning: unable to use TCP_CORK on %s", sys.platform)
        log.warn(" %s", cork_e)
        SOCKET_CORK = False
SOCKET_NODELAY = envbool("XPRA_SOCKET_NODELAY", None)
VSOCK_TIMEOUT = envint("XPRA_VSOCK_TIMEOUT", 5)
SOCKET_TIMEOUT = envint("XPRA_SOCKET_TIMEOUT", 20)
SSL_PEEK = envbool("XPRA_SSL_PEEK", True)
#this is more proper but would break the proxy server:
SOCKET_SHUTDOWN = envbool("XPRA_SOCKET_SHUTDOWN", False)
LOG_TIMEOUTS = envint("XPRA_LOG_TIMEOUTS", 1)

#on some platforms (ie: OpenBSD), reading and writing from sockets
#raises an IOError but we should continue if the error code is EINTR
#this wrapper takes care of it.
#EWOULDBLOCK can also be hit with the proxy server when we handover the socket
CONTINUE_ERRNO = {
            errno.EINTR         : "EINTR",
            errno.EWOULDBLOCK   : "EWOULDBLOCK"
            }
ABORT = {
         errno.ENXIO            : "ENXIO",
         errno.ECONNRESET       : "ECONNRESET",
         errno.EPIPE            : "EPIPE",
         }
continue_wait = 0

#default to using os.read and os.write for both tty devices and regular streams
#(but overriden for win32 below for tty devices to workaround an OS "feature")
OS_READ = os.read
OS_WRITE = os.write
TTY_READ = os.read
TTY_WRITE = os.write
if WIN32 and PYTHON2:
    #win32 has problems writing more than 32767 characters to stdout!
    #see: http://bugs.python.org/issue11395
    #(this is fixed in python 3.2 and we don't care about 3.0 or 3.1)
    def win32ttywrite(fd, buf):
        #this awful limitation only applies to tty devices:
        if len(buf)>32767:
            buf = buf[:32767]
        return os.write(fd, buf)
    TTY_WRITE = win32ttywrite


PROTOCOL_STR = {}
FAMILY_STR = {}
for x in dir(socket):
    if x.startswith("AF_"):
        PROTOCOL_STR[getattr(socket, x)] = x
    if x.startswith("SOCK_"):
        FAMILY_STR[getattr(socket, x)] = x


def set_continue_wait(v):
    global continue_wait
    continue_wait = v

CAN_RETRY_EXCEPTIONS = ()
CLOSED_EXCEPTIONS = ()

if PYTHON2:
    from io import BlockingIOError
else:
    assert BlockingIOError

def can_retry(e):
    if isinstance(e, socket.timeout):
        return "socket.timeout"
    if isinstance(e, BlockingIOError):
        return True
    if isinstance(e, (IOError, OSError)):
        global CONTINUE_ERRNO
        code = e.args[0]
        can_continue = CONTINUE_ERRNO.get(code)
        if can_continue:
            return can_continue

        #SSL pollution - see ticket #1927
        if code=="The read operation timed out":
            return str(code)

        if isinstance(e, CAN_RETRY_EXCEPTIONS):
            return str(e)

        abort = ABORT.get(code, code)
        if abort is not None:
            err = getattr(e, "errno", None)
            log("can_retry: %s, args=%s, errno=%s, code=%s, abort=%s", type(e), e.args, err, code, abort)
            raise ConnectionClosedException(e)
    if isinstance(e, CLOSED_EXCEPTIONS):
        raise ConnectionClosedException(e)
    return False

def untilConcludes(is_active_cb, can_retry_cb, f, *a, **kw):
    global continue_wait
    wait = 0
    while is_active_cb():
        try:
            return f(*a, **kw)
        except Exception as e:
            retry = can_retry_cb(e)
            if LOG_TIMEOUTS>0:
                log("untilConcludes(%s, %s, %s, %s, %s) %s, retry=%s",
                    is_active_cb, can_retry_cb, f, a, kw, e, retry, exc_info=LOG_TIMEOUTS>=2)
            e = None
            if not retry:
                raise
            if wait>0:
                time.sleep(wait/1000.0)     #wait is in milliseconds, sleep takes seconds
            if wait<continue_wait:
                wait += 1


def pretty_socket(s):
    try:
        if isinstance(s, str):
            return s
        if len(s)==2:
            return "%s:%s" % (s[0], s[1])
        if len(s)==4:
            return csv(str(x) for x in s)
    except (ValueError, TypeError):
        pass
    return str(s)


class Connection(object):
    def __init__(self, endpoint, socktype, info=None):
        log("Connection%s", (endpoint, socktype, info))
        self.endpoint = endpoint
        try:
            assert isinstance(endpoint, (tuple, list))
            self.target = ":".join(str(x) for x in endpoint)
        except Exception:
            self.target = str(endpoint)
        self.socktype_wrapped = socktype
        self.socktype = socktype
        self.info = info or {}
        self.input_bytecount = 0
        self.input_readcount = 0
        self.output_bytecount = 0
        self.output_writecount = 0
        self.filename = None            #only used for unix domain sockets!
        self.active = True
        self.timeout = 0

    def set_nodelay(self, nodelay):
        pass

    def set_cork(self, cork):
        pass

    def is_active(self):
        return self.active

    def set_active(self, active):
        self.active = active

    def close(self):
        self.set_active(False)

    def can_retry(self, e):
        return can_retry(e)

    def untilConcludes(self, *args):
        return untilConcludes(self.is_active, self.can_retry, *args)

    def peek(self, _n):
        #not implemented
        return None

    def _write(self, *args):
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

    def get_info(self):
        info = self.info.copy()
        if self.socktype_wrapped!=self.socktype:
            info["wrapped"] = self.socktype_wrapped
        info.update({
                "type"              : self.socktype or "",
                "endpoint"          : self.endpoint or (),
                "active"            : self.active,
                "input"             : {
                                       "bytecount"      : self.input_bytecount,
                                       "readcount"      : self.input_readcount,
                                       },
                "output"            : {
                                       "bytecount"      : self.output_bytecount,
                                       "writecount"     : self.output_writecount,
                                       },
                })
        return info


# A simple, portable abstraction for a blocking, low-level
# (os.read/os.write-style interface) two-way byte stream:
# client.py relies on self.filename to locate the unix domain
# socket (if it exists)
class TwoFileConnection(Connection):
    def __init__(self, writeable, readable, abort_test=None, target=None, socktype="", close_cb=None, info=None):
        Connection.__init__(self, target, socktype, info)
        self._writeable = writeable
        self._readable = readable
        self._read_fd = self._readable.fileno()
        self._write_fd = self._writeable.fileno()
        if os.isatty(self._read_fd):
            self._osread = TTY_READ
        else:
            self._osread = OS_READ
        if os.isatty(self._write_fd):
            self._oswrite = TTY_WRITE
        else:
            self._oswrite = OS_WRITE
        self._abort_test = abort_test
        self._close_cb = close_cb

    def may_abort(self, action):
        """ if abort_test is defined, run it """
        if self._abort_test:
            self._abort_test(action)

    def read(self, n):
        self.may_abort("read")
        return self._read(self._osread, self._read_fd, n)

    def write(self, buf):
        self.may_abort("write")
        return self._write(self._oswrite, self._write_fd, buf)

    def close(self):
        log("%s.close() close callback=%s, readable=%s, writeable=%s",
            self, self._close_cb, self._readable, self._writeable)
        Connection.close(self)
        cc = self._close_cb
        if cc:
            self._close_cb = None
            log("%s.close() calling %s", self, cc)
            cc()
        try:
            self._readable.close()
        except IOError as e:
            log("%s.close() %s", self._readable, e)
        try:
            self._writeable.close()
        except IOError as e:
            log("%s.close() %s", self._writeable, e)
        log("%s.close() done", self)

    def __repr__(self):
        return "Pipe(%s)" % str(self.target)

    def get_info(self):
        d = Connection.get_info(self)
        d.update({
            "type"  : "pipe",
            "pipe"  : {
                "read"     : {"fd" : self._read_fd},
                "write"    : {"fd" : self._write_fd},
                }
            })
        return d


TCP_SOCKTYPES = ("tcp", "ssl", "ws", "wss")

class SocketConnection(Connection):
    def __init__(self, sock, local, remote, target, socktype, info=None):
        log("SocketConnection%s", (sock, local, remote, target, socktype, info))
        Connection.__init__(self, target, socktype, info)
        self._socket = sock
        self.local = local
        self.remote = remote
        self.protocol_type = "socket"
        self.nodelay = None
        self.cork = None
        if isinstance(remote, str):
            self.filename = remote
        if SOCKET_NODELAY is not None and self.socktype in TCP_SOCKTYPES:
            self.do_set_nodelay(SOCKET_NODELAY)

    def set_nodelay(self, nodelay):
        if SOCKET_NODELAY is None and self.socktype_wrapped in TCP_SOCKTYPES and self.nodelay!=nodelay:
            self.do_set_nodelay(nodelay)

    def do_set_nodelay(self, nodelay):
        self._socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, nodelay)
        self.nodelay = nodelay
        log("changed %s socket to nodelay=%s", self.socktype, nodelay)

    def set_cork(self, cork):
        if SOCKET_CORK and self.socktype_wrapped in TCP_SOCKTYPES and self.cork!=cork:
            self._socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_CORK, cork)
            self.cork = cork
            log("changed %s socket to cork=%s", self.socktype, cork)

    def peek(self, n):
        return self._socket.recv(n, socket.MSG_PEEK)

    def read(self, n):
        return self._read(self._socket.recv, n)

    def write(self, buf):
        return self._write(self._socket.send, buf)

    def close(self):
        s = self._socket
        try:
            i = self.get_socket_info()
        except IOError:
            i = s
        log("%s.close() for socket=%s", self, i)
        Connection.close(self)
        #meaningless for udp:
        try:
            s.settimeout(0)
        except IOError:
            pass
        if SOCKET_SHUTDOWN:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except IOError:
                log("%s.shutdown(SHUT_RDWR)", s, exc_info=True)
        try:
            s.close()
        except EOFError:
            log("%s.close()", s, exc_info=True)
        except IOError as e:
            if self.error_is_closed(e):
                log("%s.close() already closed!", s)
            else:
                raise
        log("%s.close() done", self)

    def error_is_closed(self, e):
        return isinstance(e, CLOSED_EXCEPTIONS)

    def __repr__(self):
        if self.remote:
            return "%s %s: %s <- %s" % (
                self.socktype, self.protocol_type,
                pretty_socket(self.local), pretty_socket(self.remote),
                )
        return "%s %s:%s" % (self.socktype, self.protocol_type, pretty_socket(self.local))

    def get_info(self):
        d = Connection.get_info(self)
        try:
            d["remote"] = self.remote or ""
            d["protocol-type"] = self.protocol_type
            si = self.get_socket_info()
            if si:
                d["socket"] = si
        except socket.error:
            log.error("Error accessing socket information", exc_info=True)
        return d

    def get_socket_info(self):
        return self.do_get_socket_info(self._socket)

    def do_get_socket_info(self, s):
        if not s:
            return None
        info = {}
        try:
            info.update({
                "proto"         : s.proto,
                "family"        : FAMILY_STR.get(s.family, int(s.family)),
                "type"          : PROTOCOL_STR.get(s.type, int(s.type)),
                })
        except AttributeError:
            log("do_get_socket_info()", exc_info=True)
        if self.nodelay is not None:
            info["nodelay"] = self.nodelay
        try:
            info["timeout"] = int(1000*(s.gettimeout() or 0))
        except socket.error:
            pass
        try:
            if POSIX:
                fd = s.fileno()
            else:
                fd = 0
            if fd:
                info["fileno"] = fd
            from xpra.platform.netdev_query import get_interface_info
            #ie: self.local = ("192.168.1.7", "14500")
            if self.local and len(self.local)==2:
                from xpra.net.net_util import get_interface
                iface = get_interface(self.local[0])
                #ie: iface = "eth0"
                if iface and iface!="lo":
                    i = get_interface_info(fd, iface)
                    if i:
                        info["device"] = i
        except OSError as e:
            log("do_get_socket_info() error querying socket speed", exc_info=True)
            log.error("Error querying socket speed:")
            log.error(" %s", e)
        else:
            opts = {
                    "SOCKET" : get_socket_options(s, socket.SOL_SOCKET, SOCKET_OPTIONS),
                    }
            if self.socktype_wrapped in ("tcp", "udp", "ws", "wss", "ssl"):
                opts["IP"] = get_socket_options(s, socket.SOL_IP, IP_OPTIONS)
            if self.socktype_wrapped in ("tcp", "ws", "wss", "ssl"):
                opts["TCP"] = get_socket_options(s, socket.IPPROTO_TCP, TCP_OPTIONS)
            #ipv6:  IPV6_ADDR_PREFERENCES, IPV6_CHECKSUM, IPV6_DONTFRAG, IPV6_DSTOPTS, IPV6_HOPOPTS,
            # IPV6_MULTICAST_HOPS, IPV6_MULTICAST_IF, IPV6_MULTICAST_LOOP, IPV6_NEXTHOP, IPV6_PATHMTU,
            # IPV6_PKTINFO, IPV6_PREFER_TEMPADDR, IPV6_RECVDSTOPTS, IPV6_RECVHOPLIMIT, IPV6_RECVHOPOPTS,
            # IPV6_RECVPATHMTU, IPV6_RECVPKTINFO, IPV6_RECVRTHDR, IPV6_RECVTCLASS, IPV6_RTHDR,
            # IPV6_RTHDRDSTOPTS, IPV6_TCLASS, IPV6_UNICAST_HOPS, IPV6_USE_MIN_MTU, IPV6_V6ONLY
            info["options"] = opts
        return info


def get_socket_options(sock, level, options):
    opts = {}
    errs = []
    for k in options:
        opt = getattr(socket, k, None)
        if opt is None:
            continue
        try:
            v = sock.getsockopt(level, opt)
        except socket.error:
            log("sock.getsockopt(%i, %s)", level, k, exc_info=True)
            errs.append(k)
        else:
            if v is not None:
                opts[k] = v
    if errs:
        log.warn("Warning: failed to query %s", csv(errs))
    return opts


class SSLPeekFile(object):
    def __init__(self, fileobj, peeked, update_peek):
        self.fileobj = fileobj
        self.peeked = peeked
        self.update_peek = update_peek

    def __getattr__(self, attr):
        if attr=="readline" and self.peeked:
            return self.readline
        return getattr(self.fileobj, attr)

    def readline(self, limit=-1):
        if self.peeked:
            newline = self.peeked.find(b"\n")
            peeked = self.peeked
            l = len(peeked)
            if newline==-1:
                if limit==-1 or limit>l:
                    #we need to read more until we hit a newline:
                    if limit==-1:
                        more = self.fileobj.readline(limit)
                    else:
                        more = self.fileobj.readline(limit-len(self.peeked))
                    self.peeked = b""
                    self.update_peek(self.peeked)
                    return peeked+more
                read = limit
            else:
                if limit<0 or limit>=newline:
                    read = newline+1
                else:
                    read = limit
            self.peeked = peeked[read:]
            self.update_peek(self.peeked)
            return peeked[:read]
        return self.fileobj.readline(limit)

class SSLSocketWrapper(object):
    def __init__(self, sock):
        self.socket = sock
        self.peeked = b""

    def __getattr__(self, attr):
        if attr=="makefile":
            return self.makefile
        if attr=="recv":
            return self.recv
        return getattr(self.socket, attr)

    def makefile(self, mode, bufsize=None):
        fileobj = self.socket.makefile(mode, bufsize)
        if self.peeked and mode and mode.startswith("r"):
            return SSLPeekFile(fileobj, self.peeked, self._update_peek)
        return fileobj

    def _update_peek(self, peeked):
        self.peeked = peeked

    def recv(self, bufsize, flags=0):
        if flags & socket.MSG_PEEK:
            l = len(self.peeked)
            if l>=bufsize:
                log("patched_recv() peeking using existing data: %i bytes", bufsize)
                return self.peeked[:bufsize]
            v = self.socket.recv(bufsize-l)
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

    def can_retry(self, e):
        if getattr(e, "library", None)=="SSL":
            reason = getattr(e, "reason", None)
            if reason in ("WRONG_VERSION_NUMBER", "UNEXPECTED_RECORD"):
                return False
        message = e.args[0]
        if message in SSLSocketConnection.SSL_TIMEOUT_MESSAGES:
            return True
        code = getattr(e, "code", None)
        if code in SSLSocketConnection.SSL_TIMEOUT_MESSAGES:
            return True
        return SocketConnection.can_retry(self, e)

    def enable_peek(self):
        assert not isinstance(self._socket, SSLSocketWrapper)
        self._socket = SSLSocketWrapper(self._socket)

    def get_info(self):
        i = SocketConnection.get_info(self)
        i["ssl"] = True
        for k,fn in {
                     "compression"      : "compression",
                     "alpn-protocol"    : "selected_alpn_protocol",
                     "npn-protocol"     : "selected_npn_protocol",
                     "version"          : "version",
                     }.items():
            sfn = getattr(self._socket, fn, None)
            if sfn:
                v = sfn()
                if v is not None:
                    i[k] = v
        cipher_fn = getattr(self._socket, "cipher", None)
        if cipher_fn:
            cipher = cipher_fn()
            if cipher:
                i["cipher"] = {
                               "name"       : cipher[0],
                               "protocol"   : cipher[1],
                               "bits"       : cipher[2],
                               }
        return i


def set_socket_timeout(conn, timeout=None):
    #FIXME: this is ugly, but less intrusive than the alternative?
    log("set_socket_timeout(%s, %s)", conn, timeout)
    if isinstance(conn, SocketConnection):
        conn._socket.settimeout(timeout)


def log_new_connection(conn, socket_info=""):
    """ logs the new connection message """
    sock = conn._socket
    address = conn.remote
    socktype = conn.socktype
    try:
        peername = sock.getpeername()
    except socket.error:
        peername = address
    try:
        sockname = sock.getsockname()
    except AttributeError:
        #ie: ssh channel
        sockname = ""
    log("log_new_connection(%s, %s) type=%s, sock=%s, sockname=%s, address=%s, peername=%s",
        conn, socket_info, type(conn), sock, sockname, address, peername)
    if peername:
        frominfo = pretty_socket(peername)
        log.info("New %s connection received", socktype)
        log.info(" from '%s'", pretty_socket(frominfo))
        if socket_info:
            log.info(" on '%s'", pretty_socket(socket_info))
    elif socktype=="unix-domain":
        frominfo = sockname
        log.info("New %s connection received", socktype)
        log.info(" on '%s'", frominfo)
    else:
        log.info("New %s connection received")
        if socket_info:
            log.info(" on %s", pretty_socket(socket_info))
