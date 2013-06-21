# This file is part of Xpra.
# Copyright (C) 2012-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from threading import Thread

"""
This is only here so we can intercept the creation
of all deamon threads and inject some code.
This is used by the pycallgraph test wrapper.
"""

def make_daemon_thread(target, name):
    daemon_thread = Thread(target=target, name=name)
    daemon_thread.setDaemon(True)
    return daemon_thread
