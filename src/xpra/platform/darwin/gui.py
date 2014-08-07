#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform.darwin.osx_menu import getOSXMenuHelper
from xpra.platform.paths import get_icon

from xpra.log import Logger
log = Logger("osx", "events")


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
    import Quartz.CoreGraphics as CG    #@UnresolvedImport
    ALPHA = {
             CG.kCGImageAlphaNone                  : "AlphaNone",
             CG.kCGImageAlphaPremultipliedLast     : "PremultipliedLast",
             CG.kCGImageAlphaPremultipliedFirst    : "PremultipliedFirst",
             CG.kCGImageAlphaLast                  : "Last",
             CG.kCGImageAlphaFirst                 : "First",
             CG.kCGImageAlphaNoneSkipLast          : "SkipLast",
             CG.kCGImageAlphaNoneSkipFirst         : "SkipFirst",
       }
except:
    CG = None


def get_CG_imagewrapper():
    from xpra.codecs.image_wrapper import ImageWrapper
    assert CG, "cannot capture without Quartz.CoreGraphics"
    #region = CG.CGRectMake(0, 0, 100, 100)
    region = CG.CGRectInfinite
    image = CG.CGWindowListCreateImage(region,
                CG.kCGWindowListOptionOnScreenOnly,
                CG.kCGNullWindowID,
                CG.kCGWindowImageDefault)
    width = CG.CGImageGetWidth(image)
    height = CG.CGImageGetHeight(image)
    bpc = CG.CGImageGetBitsPerComponent(image)
    bpp = CG.CGImageGetBitsPerPixel(image)
    rowstride = CG.CGImageGetBytesPerRow(image)
    alpha = CG.CGImageGetAlphaInfo(image)
    alpha_str = ALPHA.get(alpha, alpha)
    log("get_CG_imagewrapper(..) image size: %sx%s, bpc=%s, bpp=%s, rowstride=%s, alpha=%s", width, height, bpc, bpp, rowstride, alpha_str)
    prov = CG.CGImageGetDataProvider(image)
    argb = CG.CGDataProviderCopyData(prov)
    return ImageWrapper(0, 0, width, height, argb, "BGRX", 24, rowstride)

def take_screenshot():
    log("grabbing screenshot")
    from PIL import Image
    from xpra.os_util import StringIOClass
    image = get_CG_imagewrapper()
    w = image.get_width()
    h = image.get_height()
    img = Image.frombuffer("RGB", (w, h), image.get_pixels(), "raw", image.get_pixel_format(), image.get_rowstride())
    buf = StringIOClass()
    img.save(buf, "PNG")
    data = buf.getvalue()
    buf.close()
    return w, h, "png", image.get_rowstride(), data


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
    def __init__(self, client, opts, blocking=False):
        log("ClientExtras.__init__(%s, %s, %s) swap_keys=%s", client, opts, blocking, opts.swap_keys)
        self.client = client
        self.blocking = blocking
        self.setup_event_loop()
        if opts and client:
            log("setting swap_keys=%s using %s", opts.swap_keys, client.keyboard_helper)
            if client.keyboard_helper and client.keyboard_helper.keyboard:
                log("%s.swap_keys=%s", client.keyboard_helper.keyboard, opts.swap_keys)
                client.keyboard_helper.keyboard.swap_keys = opts.swap_keys

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
    ClientExtras(None, None, True)


if __name__ == "__main__":
    main()
