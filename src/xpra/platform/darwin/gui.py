# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform.darwin.osx_menu import getOSXMenuHelper
from xpra.platform.paths import get_icon

from xpra.log import Logger
log = Logger()

#for attention_request:
CRITICAL_REQUEST = 0
INFO_REQUEST = 10

exit_cb = None
def quit_handler(*args):
    global exit_cb
    if exit_cb:
        exit_cb()
    else:
        from xpra.gtk_common.quit import gtk_main_quit_really
        gtk_main_quit_really()
    return True

def set_exit_cb(ecb):
    global exit_cb
    exit_cb = ecb


macapp = None
def get_OSXApplication():
    global macapp
    if macapp is None:
        try:
            import gtkosx_application        #@UnresolvedImport
            macapp = gtkosx_application.Application()
            macapp.connect("NSApplicationBlockTermination", quit_handler)
        except:
            pass
    return macapp

try:
    from Carbon import Snd      #@UnresolvedImport
except:
    Snd = None




def do_init():
    osxapp = get_OSXApplication()
    icon = get_icon("xpra.png")
    if icon:
        osxapp.set_dock_icon_pixbuf(icon)
    mh = getOSXMenuHelper(None)
    osxapp.set_dock_menu(mh.build_dock_menu())
    osxapp.set_menu_bar(mh.rebuild())


def do_ready():
    osxapp = get_OSXApplication()
    osxapp.ready()


def get_native_tray_menu_helper_classes():
    return [getOSXMenuHelper]

def get_native_tray_classes():
    from xpra.platform.darwin.osx_tray import OSXTray
    return [OSXTray]

def system_bell(*args):
    if Snd is None:
        return False
    Snd.SysBeep(1)
    return True
