# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific code for Mac OS X.
# This is to support a native build without server support
# Although it is possible to build the xpra server on OS X, it is particularly
# useful. So if you want to do that, use xposix instead.


def do_init():
    from xpra.gtk_common.quit import gtk_main_quit_really
    def quit_launcher(*args):
        gtk_main_quit_really()
    from gui import get_OSXApplication
    from osx_menu import setup_menubar, osx_ready
    from xpra.platform.paths import get_icon
    setup_menubar(quit_launcher)
    osxapp = get_OSXApplication()
    icon = get_icon("xpra.png")
    if icon:
        osxapp.set_dock_icon_pixbuf(icon)
    osx_ready()
