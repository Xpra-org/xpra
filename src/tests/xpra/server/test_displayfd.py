#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys

def main():
    from xpra.util import nonl
    from xpra.os_util import close_fds
    from xpra.platform.displayfd import read_displayfd, parse_displayfd
    import subprocess
    r_pipe, w_pipe = os.pipe()
    cmd = [
        "xpra",
        "start",
        "--daemon=yes",
        "--systemd-run=no",
        "--start-via-proxy=no",
       "--displayfd=%s" % w_pipe,
       ]
    def preexec_fn():
        close_fds([0, 1, 2, r_pipe, w_pipe])
    proc = subprocess.Popen(cmd, stdin=None, stdout=None, stderr=None, close_fds=False, preexec_fn=preexec_fn)
    print("Popen(%s)=%s" % (cmd, proc))
    buf = read_displayfd(r_pipe, timeout=30, proc=proc)
    print("read_displayfd(%i)='%s'" % (r_pipe, nonl(buf)))
    os.close(r_pipe)
    os.close(w_pipe)
    def displayfd_err(msg):
        print("Error: displayfd failed")
        print(" %s" % msg)
        sys.exit(1)
    n = parse_displayfd(buf, displayfd_err)
    print("Success: display='%s'" % n)

if __name__ == "__main__":
    main()
