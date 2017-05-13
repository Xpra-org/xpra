#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def main():
    from xpra.os_util import close_all_fds
    import subprocess
    #proc = subprocess.Popen(["xpra", "start", "--no-daemon", "--systemd-run=no", ":100"], stdin=None, stdout=None, stderr=None, close_fds=True, preexec_fn=close_all_fds)
    proc = subprocess.Popen(["xpra", "attach"], stdin=None, stdout=None, stderr=None, close_fds=True, preexec_fn=close_all_fds)
    print("proc=%s" % proc)
    import time
    while proc.poll() is None:
        print("poll()=%s" % proc.poll())
        time.sleep(1)
    print("exit code=%s" % proc.poll())

if __name__ == "__main__":
    main()
