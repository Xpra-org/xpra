#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk
import glib

from xpra.log import Logger
from tests.xpra.clients.fake_client import FakeClient
from xpra.client.gtk_base.statusicon_tray import GTKStatusIconTray

def main():
    log = Logger("client")
    from xpra.client.gtk2.tray_menu import GTK2TrayMenu
    client = FakeClient()
    log.info("creating tray menu")
    tray = GTK2TrayMenu(client)
    client.menu = tray.build()
    client.fire_handshake_callbacks()
    log.info("creating tray widget")
    def tray_click(button, pressed, time=0):
        log.info("tray_click(%s, %s, %s)", button, pressed, time)
        if button==1 and pressed:
            glib.idle_add(tray.activate, button, time)
        elif button==3 and not pressed:
            glib.idle_add(tray.popup, button, time)
    def tray_mouseover(*args):
        log.info("tray_mouseover(%s)", args)
    def tray_exit(*args):
        log.info("tray_exit(%s)", args)
        gtk.main_quit()
    def tray_geometry(*args):
        log.info("tray_geometry%s", args)
    GTKStatusIconTray(client, client.menu, "test", None, size_changed_cb=tray_geometry(), click_cb=tray_click, mouseover_cb=tray_mouseover, exit_cb=tray_exit)
    log.info("running main loop")
    gtk.main()


if __name__ == "__main__":
    main()
