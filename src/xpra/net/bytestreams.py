# This file is part of Xpra.
# Copyright (C) 2011-2017 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import sys
import os
import errno
import socket
import types

from xpra.log import Logger
log = Logger("network", "protocol")
from xpra.net import ConnectionClosedException
from xpra.util import envint, envbool
from xpra.os_util import WIN32


TCP_NODELAY = envbool("XPRA_TCP_NODELAY", True)
VSOCK_TIMEOUT = envint("XPRA_VSOCK_TIMEOUT", 5)
SOCKET_TIMEOUT = envint("XPRA_SOCKET_TIMEOUT", 20)


#on some platforms (ie: OpenBSD), reading and writing from sockets
#raises an IOError but we should continue if the error code is EINTR
#this wrapper takes care of it.
#EWOULDBLOCK can also be hit with the proxy server when we handover the socket
CONTINUE = {
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


PROTOCOL_STR = {}
for x in ("UNIX", "INET", "INET6"):
    try:
        PROTOCOL_STR[getattr(socket, "AF_%s" % x)] = x
    except:
        pass
FAMILY_STR = {}
for x in ("STREAM", "DGRAM", "RAW", "RDM", "SEQPACKET"):
    try:
        FAMILY_STR[getattr(socket, "SOCK_%s" % x)] = x
    except:
        pass


if WIN32:
    #on win32, we have to deal with a few more odd error codes:
    CONTINUE[errno.WSAEWOULDBLOCK] = "WSAEWOULDBLOCK"       #@UndefinedVariable

    #some of these may be redundant or impossible to hit? (does not hurt I think)
    for x in ("WSAENETDOWN", "WSAENETUNREACH", "WSAECONNABORTED", "WSAECONNRESET",
              "WSAENOTCONN", "WSAESHUTDOWN", "WSAETIMEDOUT", "WSAETIMEDOUT",
              "WSAEHOSTUNREACH", "WSAEDISCON"):
        ABORT[getattr(errno, x)] = x
    #duplicated from winerror module:
    ERROR_BROKEN_PIPE = 109
    ERROR_PIPE_NOT_CONNECTED = 233
    ABORT[ERROR_BROKEN_PIPE] = "BROKENPIPE"
    ABORT[ERROR_PIPE_NOT_CONNECTED] = "PIPE_NOT_CONNECTED"
    if sys.version[0]<"3":
        #win32 has problems writing more than 32767 characters to stdout!
        #see: http://bugs.python.org/issue11395
        #(this is fixed in python 3.2 and we don't care about 3.0 or 3.1)
        def win32ttywrite(fd, buf):
            #this awful limitation only applies to tty devices:
            if len(buf)>32767:
                buf = buf[:32767]
            return os.write(fd, buf)
        TTY_WRITE = win32ttywrite

def set_continue_wait(v):
    global continue_wait
    continue_wait = v


#so we can inject ssl.SSLError:
CONTINUE_EXCEPTIONS = {
                       socket.timeout   : "socket.timeout",
                       }

def init_ssl():
    import ssl
    assert ssl
    global CONTINUE_EXCEPTIONS
    CONTINUE_EXCEPTIONS[ssl.SSLError] = "SSLError"
    CONTINUE_EXCEPTIONS[ssl.SSLWantReadError] = "SSLWantReadError"
    CONTINUE_EXCEPTIONS[ssl.SSLWantWriteError] = "SSLWantWriteError"
    return ssl


def can_retry(e):
    continue_exception = CONTINUE_EXCEPTIONS.get(type(e))
    if continue_exception:
        return continue_exception
    if isinstance(e, (IOError, OSError)):
        global CONTINUE
        code = e.args[0]
        can_continue = CONTINUE.get(code)
        if can_continue:
            return can_continue

        abort = ABORT.get(code, code)
        if abort is not None:
            log("untilConcludes: %s, args=%s, code=%s, abort=%s", type(e), e.args, code, abort)
            raise ConnectionClosedException(e)
    return False

def untilConcludes(is_active_cb, f, *a, **kw):
    global continue_wait
    wait = 0
    while is_active_cb():
        try:
            return f(*a, **kw)
        except Exception as e:
            retry = can_retry(e)
            log("untilConcludes(%s, %s, %s, %s) %s, retry=%s", is_active_cb, f, a, kw, e, retry)
            if retry:
                if wait>0:
                    time.sleep(wait/1000.0)     #wait is in milliseconds, sleep takes seconds
                if wait<continue_wait:
                    wait += 1
                continue
            raise


def pretty_socket(s):
    try:
        if len(s)==2:
            return "%s:%s" % (s[0], s[1])
        assert len(s)==4
        return ", ".join(str(x) for x in s)
    except:
        return str(s)


class Connection(object):
    def __init__(self, target, socktype):
        if type(target)==tuple:
            target = ":".join([str(x) for x in target])
        self.target = target
        self.socktype = socktype
        self.input_bytecount = 0
        self.input_readcount = 0
        self.output_bytecount = 0
        self.output_writecount = 0
        self.filename = None            #only used for unix domain sockets!
        self.active = True
        self.timeout = 0

    def is_active(self):
        return self.active

    def set_active(self, active):
        self.active = active

    def close(self):
        self.set_active(False)

    def untilConcludes(self, *args):
        return untilConcludes(self.is_active, *args)

    def peek(self, n):
        #not implemented
        return None

    def _write(self, *args):
        """ wraps do_write with packet accounting """
        w = self.untilConcludes(*args)
        self.output_bytecount += w or 0
        self.output_writecount += 1
        return w

    def _read(self, *args):
        """ wraps do_read with packet accounting """
        r = self.untilConcludes(*args)
        self.input_bytecount += len(r or "")
        self.input_readcount += 1
        return r

    def get_info(self):
        return {
                "type"              : self.socktype or "",
                "endpoint"          : self.target or "",
                "active"            : self.active,
                "input"             : {
                                       "bytecount"      : self.input_bytecount,
                                       "readcount"      : self.input_readcount,
                                       },
                "output"            : {
                                       "bytecount"      : self.output_bytecount,
                                       "writecount"     : self.output_writecount,
                                       },
                }


# A simple, portable abstraction for a blocking, low-level
# (os.read/os.write-style interface) two-way byte stream:
# client.py relies on self.filename to locate the unix domain
# socket (if it exists)
class TwoFileConnection(Connection):
    def __init__(self, writeable, readable, abort_test=None, target=None, socktype="", close_cb=None):
        Connection.__init__(self, target, socktype)
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
        log("%s.close() close callback=%s, readable=%s, writeable=%s", self, self._close_cb, self._readable, self._writeable)
        Connection.close(self)
        cc = self._close_cb
        if cc:
            self._close_cb = None
            log("%s.close() calling %s", self, cc)
            cc()
        try:
            self._readable.close()
        except Exception as e:
            log("%s.close() %s", self._readable, e)
        try:
            self._writeable.close()
        except:
            log("%s.close() %s", self._writeable, e)
        log("%s.close() done", self)

    def __repr__(self):
        return "Pipe(%s)" % str(self.target)

    def get_info(self):
        d = Connection.get_info(self)
        try:
            d["type"] = "pipe"
            d["pipe"] = {
                         "read"     : {"fd" : self._read_fd},
                         "write"    : {"fd" : self._write_fd},
                         }
        except:
            pass
        return d


class SocketConnection(Connection):
    def __init__(self, socket, local, remote, target, socktype):
        Connection.__init__(self, target, socktype)
        self._socket = socket
        self.local = local
        self.remote = remote
        self.protocol_type = "socket"
        if type(remote)==str:
            self.filename = remote

    def peek(self, n):
        return self.untilConcludes(self._socket.recv, n, socket.MSG_PEEK)

    def read(self, n):
        return self._read(self._socket.recv, n)

    def write(self, buf):
        return self._write(self._socket.send, buf)

    def close(self):
        s = self._socket
        try:
            i = self.get_socket_info()
        except:
            i = s
        log("%s.close() for socket=%s", self, i)
        Connection.close(self)
        s.settimeout(0)
        #this is more proper but would break the proxy server:
        #s.shutdown(socket.SHUT_RDWR)
        s.close()
        log("%s.close() done", self)

    def __repr__(self):
        if self.remote:
            return "%s %s: %s <- %s" % (self.socktype, self.protocol_type, pretty_socket(self.local), pretty_socket(self.remote))
        return "%s %s:%s" % (self.socktype, self.protocol_type, pretty_socket(self.local))

    def get_info(self):
        d = Connection.get_info(self)
        try:
            d["protocol-type"] = self.protocol_type
            si = self.get_socket_info()
            if si:
                d["socket"] = si
        except:
            log.error("Error accessing socket information", exc_info=True)
        return d

    def get_socket_info(self):
        return self.do_get_socket_info()

    def do_get_socket_info(self):
        s = self._socket
        if not s:
            return None
        return {
                #"class"         : str(type(s)),
                "fileno"        : s.fileno(),
                "timeout"       : int(1000*(s.gettimeout() or 0)),
                "family"        : FAMILY_STR.get(s.family, s.family),
                "proto"         : s.proto,
                "type"          : PROTOCOL_STR.get(s.type, s.type),
                }



def set_socket_timeout(conn, timeout=None):
    #FIXME: this is ugly, but less intrusive than the alternative?
    log("set_socket_timeout(%s, %s)", conn, timeout)
    if isinstance(conn, SocketConnection):
        conn._socket.settimeout(timeout)


def inject_ssl_socket_info(conn):
    """
        If the socket is an SSLSocket,
        we patch the Connection's get_info method
        to return additional ssl data.
        This method does not load the 'ssl' module.
    """
    sock = conn._socket
    ssl = sys.modules.get("ssl")
    log("ssl=%s, socket class=%s", ssl, type(sock))
    if ssl and isinstance(sock, ssl.SSLSocket):
        #inject extra ssl info into the socket class:
        def get_ssl_socket_info(sock):
            d = sock.do_get_socket_info()
            d["ssl"] = True
            s = sock._socket
            if not s:
                return d
            for k,fn in {
                         "compression"      : "compression",
                         "alpn-protocol"    : "selected_alpn_protocol",
                         "npn-protocol"     : "selected_npn_protocol",
                         "version"          : "version",
                         }.items():
                sfn = getattr(s, fn, None)
                if sfn:
                    v = sfn()
                    if v is not None:
                        d[k] = v
            cipher_fn = getattr(s, "cipher", None)
            if cipher_fn:
                cipher = cipher_fn()
                if cipher:
                    d["cipher"] = {
                                   "name"       : cipher[0],
                                   "protocol"   : cipher[1],
                                   "bits"       : cipher[2],
                                   }
            return d
        conn.get_socket_info = types.MethodType(get_ssl_socket_info, conn)

def log_new_connection(conn):
    """ logs the new connection message """
    sock = conn._socket
    address = conn.remote
    socktype = conn.socktype
    try:
        peername = sock.getpeername()
    except:
        peername = str(address)
    sockname = sock.getsockname()
    log("log_new_connection(%s) sock=%s, sockname=%s, address=%s, peername=%s", conn, sock, sockname, address, peername)
    if peername:
        frominfo = pretty_socket(peername)
        info_msg = "New %s connection received from %s" % (socktype, frominfo)
    elif socktype=="unix-domain":
        frominfo = sockname
        info_msg = "New %s connection received on %s" % (socktype, frominfo)
    else:
        frominfo = ""
        info_msg = "New %s connection received"
    log.info(info_msg)
