# This file is part of Xpra.
# Copyright (C) 2011-2015 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import sys
import os
import errno
import socket

from xpra.log import Logger
log = Logger("network", "protocol")

#on some platforms (ie: OpenBSD), reading and writing from sockets
#raises an IOError but we should continue if the error code is EINTR
#this wrapper takes care of it.
#EWOULDBLOCK can also be hit with the proxy server when we handover the socket
CONTINUE = {errno.EINTR         : "EINTR",
            errno.EWOULDBLOCK   : "EWOULDBLOCK"
            }
ABORT = {
    errno.ECONNRESET    : "ECONNRESET",
    errno.EPIPE         : "EPIPE"}
continue_wait = 0

#default to using os.read and os.write for both tty devices and regular streams
#(but overriden for win32 below for tty devices to workaround an OS "feature")
OS_READ = os.read
OS_WRITE = os.write
TTY_READ = os.read
TTY_WRITE = os.write


if sys.platform.startswith("win"):
    #on win32, we have to deal with a few more odd error codes:
    #(it would be nicer if those were wrapped using errno instead..)
    WSAEWOULDBLOCK = 10035
    CONTINUE[WSAEWOULDBLOCK] = "WSAEWOULDBLOCK"

    #some of these may be redundant or impossible to hit? (does not hurt I think)
    WSAENETDOWN     = 10050
    WSAENETUNREACH  = 10051
    WSAECONNABORTED = 10053         #this one has been seen, see ticket #492
    WSAECONNRESET   = 10054
    WSAENOTCONN     = 10057
    WSAESHUTDOWN    = 10058
    ABORT.update({
        WSAECONNABORTED     : "WSAECONNABORTED",
        WSAECONNRESET       : "WSAECONNRESET",
        WSAENETDOWN         : "WSAENETDOWN",
        WSAENETUNREACH      : "WSAENETUNREACH",
        WSAENOTCONN         : "WSAENOTCONN",
        WSAESHUTDOWN        : "WSAESHUTDOWN",
        })
    #on win32, we want to wait just a little while,
    #to prevent servers spinning wildly on non-blocking sockets:
    continue_wait = 5
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


def untilConcludes(is_active_cb, f, *a, **kw):
    wait = 0
    while is_active_cb():
        try:
            return f(*a, **kw)
        except socket.timeout as e:
            log("untilConcludes(%s, %s, %s, %s) %s", is_active_cb, f, a, kw, e)
            continue
        except TypeError:
            log.warn("untilConcludes error calling %s with %s", f, a)
            raise
        except (IOError, OSError) as e:
            code = e.args[0]
            can_continue = CONTINUE.get(code)
            if can_continue:
                log("untilConcludes(%s, %s, %s, %s) %s / %s (continue)", is_active_cb, f, a, kw, can_continue, e)
                time.sleep(wait/1000.0)     #wait is in milliseconds, sleep takes seconds
                if wait<continue_wait:
                    wait += 1
                continue
            log("untilConcludes(%s, %s, %s, %s) %s / %s (raised)", is_active_cb, f, a, kw, ABORT.get(code, code), e)
            raise

def pretty_socket(s):
    try:
        assert len(s)==2
        return "%s:%s" % (s[0], s[1])
    except:
        return str(s)


class Connection(object):
    def __init__(self, target, info):
        if type(target)==tuple:
            target = ":".join([str(x) for x in target])
        self.target = target
        self.info = info
        self.input_bytecount = 0
        self.output_bytecount = 0
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

    def _write(self, *args):
        w = self.untilConcludes(*args)
        self.output_bytecount += w or 0
        return w

    def _read(self, *args):
        r = self.untilConcludes(*args)
        self.input_bytecount += len(r or "")
        return r

    def get_info(self):
        return {
                "type"              : self.info or "",
                "endpoint"          : self.target or "",
                "info"              : self.info or "",
                "active"            : self.active,
                "input.bytecount"   : self.input_bytecount,
                "output.bytecount"  : self.output_bytecount,
                }


# A simple, portable abstraction for a blocking, low-level
# (os.read/os.write-style interface) two-way byte stream:
# client.py relies on self.filename to locate the unix domain
# socket (if it exists)
class TwoFileConnection(Connection):
    def __init__(self, writeable, readable, abort_test=None, target=None, info="", close_cb=None):
        Connection.__init__(self, target, info)
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
            d["pipe.read.fd"] = self._read_fd
            d["pipe.write.fd"] = self._write_fd
        except:
            pass
        return d


class SocketConnection(Connection):
    def __init__(self, socket, local, remote, target, info):
        Connection.__init__(self, target, info)
        self._socket = socket
        self.local = local
        self.remote = remote
        if type(remote)==str:
            self.filename = remote

    def read(self, n):
        return self._read(self._socket.recv, n)

    def write(self, buf):
        return self._write(self._socket.send, buf)

    def close(self):
        log("%s.close() for socket=%s", self, self._socket)
        Connection.close(self)
        self._socket.settimeout(0)
        self._socket.close()
        log("%s.close() done", self)

    def __repr__(self):
        if self.remote:
            return "%s socket: %s <- %s" % (self.info, pretty_socket(self.local), pretty_socket(self.remote))
        return "%s socket:%s" % (self.info, pretty_socket(self.local))

    def get_info(self):
        d = Connection.get_info(self)
        try:
            d["type"] = "socket"
            s = self._socket
            if s:
                from xpra.util import updict
                updict(d, "socket", {
                        "fileno"        : s.fileno(),
                        "timeout"       : int(1000*(s.gettimeout() or 0)),
                        "family"        : s.family,
                        "proto"         : s.proto,
                        "type"          : s.type})
        except:
            log.warn("failed to get socket information", exc_info=True)
        return d

def set_socket_timeout(self, conn, timeout=None):
    #FIXME: this is ugly, but less intrusive than the alternative?
    log("set_socket_timeout(%s, %s)", conn, timeout)
    if isinstance(conn, SocketConnection):
        conn._socket.settimeout(timeout)
