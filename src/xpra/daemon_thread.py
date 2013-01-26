# This file is part of Parti.
# Copyright (C) 2012-2013 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from threading import Thread

def make_daemon_thread(target, name):
    daemon_thread = Thread(target=target, name=name)
    daemon_thread.setDaemon(True)
    return daemon_thread
