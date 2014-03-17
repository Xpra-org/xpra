#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform.darwin.osx_menu import getOSXMenuHelper
from xpra.platform.paths import get_icon

from xpra.log import Logger
log = Logger("osx")


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


try:
    import Foundation                           #@UnresolvedImport
    import AppKit                               #@UnresolvedImport
    import PyObjCTools.AppHelper as AppHelper   #@UnresolvedImport
    NSObject = Foundation.NSObject
    NSWorkspace = AppKit.NSWorkspace
except Exception, e:
    log.warn("failed to load critical modules for sleep notification support: %s", e)
    NSObject = object
    NSWorkspace = None

class NotificationHandler(NSObject):
    """Class that handles the sleep notifications."""

    def handleSleepNotification_(self, aNotification):
        log("handleSleepNotification(%s)", aNotification)
        self.sleep_callback()

    def handleWakeNotification_(self, aNotification):
        log("handleWakeNotification(%s)", aNotification)
        self.wake_callback()


class ClientExtras(object):
    def __init__(self, client, blocking=False):
        self.client = client
        self.blocking = blocking
        self.setup_event_loop()

    def cleanup(self):
        self.client = None
        self.stop_event_loop()

    def stop_event_loop(self):
        if self.notificationCenter:
            self.notificationCenter = None
            if self.blocking:
                AppHelper.stopEventLoop()
        if self.handler:
            self.handler = None

    def setup_event_loop(self):
        if NSWorkspace is None:
            return
        ws = NSWorkspace.sharedWorkspace()
        self.notificationCenter = ws.notificationCenter()
        self.handler = NotificationHandler.new()
        self.handler.sleep_callback = self.client.suspend
        self.handler.wake_callback = self.client.resume
        self.notificationCenter.addObserver_selector_name_object_(
                 self.handler, "handleSleepNotification:",
                 AppKit.NSWorkspaceWillSleepNotification, None)
        self.notificationCenter.addObserver_selector_name_object_(
                 self.handler, "handleWakeNotification:",
                 AppKit.NSWorkspaceDidWakeNotification, None)
        log("starting console event loop with notifcation center=%s and handler=%s", self.notificationCenter, self.handler)
        if self.blocking:
            #this is for running standalone
            AppHelper.runConsoleEventLoop(installInterrupt=self.blocking)
        #when not blocking, we rely on another part of the code
        #to run the event loop for us


def main():
    from xpra.platform import init
    init("OSX Extras")
    ClientExtras(None, True)


if __name__ == "__main__":
    main()
