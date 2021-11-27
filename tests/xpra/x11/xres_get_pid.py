#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys


def main(args):
    from xpra.x11.bindings.posix_display_source import init_posix_display_source
    init_posix_display_source()
    from xpra.x11.bindings.res_bindings import ResBindings
    res = ResBindings()
    for x in args[1:]:
        try:
            if x.startswith("0x"):
                w = int(x[2:], 16)
            else:
                w = int(x)
        except Exception:
            print("cannot parse window number: %r" % x)
            continue
        pid = res.get_pid(w)
        cmdline = ""
        if pid:
            from xpra.os_util import load_binary_file
            cmdline = (load_binary_file("/proc/%i/cmdline" % pid) or b"").decode()
        print("pid(%#x)=%s      %s" % (w, pid, cmdline))

if __name__ == "__main__":
    main(sys.argv)
