# This file is part of Xpra.
# Copyright (C) 2017-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.log import Logger
from xpra.os_util import monotonic_time, POSIX
from xpra.util import envint

DISPLAY_FD_TIMEOUT = envint("XPRA_DISPLAY_FD_TIMEOUT", 20)


def write_displayfd(w_pipe, display, timeout=10):
    import select   #@UnresolvedImport
    import errno
    buf = ("%s\n" % display).encode("ascii")
    limit = monotonic_time()+timeout
    log = Logger("util")
    log("write_displayfd%s", (w_pipe, display, timeout))
    while buf and monotonic_time()<limit:
        try:
            timeout = max(0, limit-monotonic_time())
            if POSIX:
                w = select.select([], [w_pipe], [], timeout)[1]
                log("select.select(..) writeable=%s", w)
            else:
                w = [w_pipe]
            if w_pipe in w:
                count = os.write(w_pipe, buf)
                buf = buf[count:]
                log("wrote %i bytes, remains %s", count, buf)
        except (select.error, OSError) as e:
            if e.errno!=errno.EINTR:
                raise
    if not buf:
        try:
            os.fsync(w_pipe)
        except OSError:
            log("os.fsync(%i)", w_pipe, exc_info=True)
        if w_pipe>2:
            try:
                os.close(w_pipe)
            except OSError:
                log("os.close(%i)", w_pipe, exc_info=True)
    return len(buf)==0

def read_displayfd(r_pipe, timeout=DISPLAY_FD_TIMEOUT, proc=None):
    import select   #@UnresolvedImport
    import errno
    # Read the display number from the pipe we gave to Xvfb
    # waiting up to 10 seconds for it to show up
    limit = monotonic_time()+timeout
    buf = b""
    log = Logger("util")
    log("read_displayfd%s", (r_pipe, timeout, proc))
    while monotonic_time()<limit and len(buf)<8 and (proc is None or proc.poll() is None):
        try:
            timeout = max(0, limit-monotonic_time())
            if POSIX:
                r = select.select([r_pipe], [], [], timeout)[0]
                log("readable=%s", r)
            else:
                r = [r_pipe]
            if r_pipe in r:
                v = os.read(r_pipe, 8)
                buf += v
                log("read=%s", v)
                if buf and (buf.endswith(b'\n') or len(buf)>=8):
                    break
        except (select.error, OSError) as e:
            if e.errno!=errno.EINTR:
                raise
    return buf

def parse_displayfd(buf, err):
    if not buf:
        err("did not provide a display number using displayfd")
        return None
    if not buf.endswith(b"\n"):
        err("output not terminated by newline: '%s'" % buf)
        return None
    buf = buf.rstrip(b"\n\r")
    try:
        n = int(buf)
    except ValueError:
        err("display number is not a valid number: %s" % buf)
    if n<0 or n>=2**16:
        err("provided an invalid display number: %s" % n)
    return n
