#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import threading
import resource

def dump_threads(prefix=""):
    try:
        cur = threading.currentThread()
        print(prefix+"current_thread=%s" % cur)
        count = 1
        for t in threading.enumerate():
            if t!=cur:
                print("found thread: %s, alive=%s" % (t, t.isAlive()))
                count += 1
        print("total number of threads=%s" % count)
    except:
        import traceback
        traceback.print_stack()

def dump_resource_usage(prefix=""):
    ru = resource.getrusage(resource.RUSAGE_SELF)
    if prefix:
        prefix = prefix.ljust(40)
    print(prefix+"user=%.3f sys=%.3f mem=%sMB" % (ru[0], ru[1], (ru[2]*resource.getpagesize())/1000000))
    #import time
    #time.sleep(0.2)

def main():
    dump_threads()


if __name__ == "__main__":
    main()
