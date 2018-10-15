# This file is part of Xpra.
# Copyright (C) 2012-2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from threading import Thread

"""
This is only here so we can intercept the creation
of all deamon threads and inject some code.
This is used by the pycallgraph test wrapper.
(this is cleaner than overriding the threading module directly
 as only our code will be affected)
"""

def make_thread(target, name, daemon=False, args=()):
    t = Thread(target=target, name=name, args=args)
    t.daemon = daemon
    return t

def start_thread(target, name, daemon=False, args=()):
    t = make_thread(target, name, daemon, args=args)
    t.start()
    return t
