#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.platform import init
from tests.xpra.net.test_protocol_base import SimpleServer
import gobject
import os.path
import socket

GTK = True
PLATFORM_INIT = True
if PLATFORM_INIT:
    from xpra.platform.features import LOCAL_SERVERS_SUPPORTED, SHADOW_SUPPORTED
    from xpra.platform import init as platform_init
    platform_init()
    nones = [x for x in (LOCAL_SERVERS_SUPPORTED, SHADOW_SUPPORTED) if x is None]
    assert len([])==0

PLATFORM_GUI_INIT = PLATFORM_INIT and True
if PLATFORM_GUI_INIT:
    from xpra.platform.gui import init as gui_init
    gui_init()

#from xpra.platform.shadow_server import ShadowServer
#from xpra.server.source import ServerSource
#from xpra.server.server_base import ServerBase


def main():
    init("Fake-Server-Test", "Xpra Fake Server Test Tool")
    if GTK:
        import gtk
        loop_exit = gtk.main_quit
        loop_run = gtk.main
    else:
        mainloop = gobject.MainLoop()
        loop_run = mainloop.run
        loop_exit = mainloop.quit
    XPRA_DISPLAY = ":10"
    sockfile = "~/.xpra/%s-%s" % (socket.gethostname(), XPRA_DISPLAY[1:])
    def server_timeout(*args):
        loop_exit()
        return False
    def server_start(*args):
        ss = SimpleServer()
        ss.init(loop_exit, os.path.expanduser(sockfile))
    gobject.timeout_add(1000, server_start)
    gobject.timeout_add(1000*120, server_timeout)
    loop_run()

if __name__ == "__main__":
    main()
