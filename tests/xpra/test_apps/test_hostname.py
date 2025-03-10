#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import platform
import time
import socket
import sys

def measure(cb):
    start = time.time()
    v = cb()
    print("%s()=%s" % (cb, v))
    end = time.time()
    elapsed = 1000*(end-start)
    if elapsed>1000:
        sys.exit(1)
    print("elapsed time: %sms" % int(elapsed))

def main():
    measure(platform.node)
    measure(socket.gethostname)
    measure(socket.getfqdn)

if __name__ == "__main__":
    main()
