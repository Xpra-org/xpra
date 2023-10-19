#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import math
import ctypes
import struct
from weakref import WeakValueDictionary
from typing import Any, Callable, Dict, List, Type, Optional, Tuple

from gi.repository import GLib      #@UnresolvedImport
import objc                         #@UnresolvedImport
import Quartz                       #@UnresolvedImport
import Quartz.CoreGraphics as CG    #@UnresolvedImport
from Quartz import (
    CGWindowListCopyWindowInfo, kCGDisplaySetModeFlag, kCGWindowListOptionOnScreenOnly, #@UnresolvedImport
    kCGNullWindowID, kCGWindowListOptionAll,    #@UnresolvedImport
    )
from Quartz.CoreGraphics import (
    CGDisplayRegisterReconfigurationCallback,   #@UnresolvedImport
    CGDisplayRemoveReconfigurationCallback,     #@UnresolvedImport
    )
from AppKit import (
    NSObject, NSAppleEventManager, NSScreen, NSBeep,   #@UnresolvedImport
    NSApp, NSApplication, NSWorkspace,              #@UnresolvedImport
    NSWorkspaceActiveSpaceDidChangeNotification,    #@UnresolvedImport
    NSWorkspaceWillSleepNotification,               #@UnresolvedImport
    NSWorkspaceDidWakeNotification,                 #@UnresolvedImport
    )
from Foundation import (
    NSUserNotification, NSUserNotificationCenter,   #@UnresolvedImport
    NSUserNotificationDefaultSoundName,             #@UnresolvedImport
    )

from xpra.util import envbool, envint, roundup
from xpra.notifications.notifier_base import NotifierBase
from xpra.platform.darwin import get_OSXApplication
from xpra.log import Logger

log = Logger("osx", "events")
workspacelog = Logger("osx", "events", "workspace")
mouselog = Logger("osx", "events", "mouse")
notifylog = Logger("osx", "notify")

OSX_FOCUS_WORKAROUND = envint("XPRA_OSX_FOCUS_WORKAROUND", 2000)
SLEEP_HANDLER = envbool("XPRA_OSX_SLEEP_HANDLER", True)
EVENT_LISTENER = envbool("XPRA_OSX_EVENT_LISTENER", True)
OSX_WHEEL_MULTIPLIER = envint("XPRA_OSX_WHEEL_MULTIPLIER", 100)
OSX_WHEEL_PRECISE_MULTIPLIER = envint("XPRA_OSX_WHEEL_PRECISE_MULTIPLIER", 1)
OSX_WHEEL_DIVISOR = envint("XPRA_OSX_WHEEL_DIVISOR", 10)
WHEEL = envbool("XPRA_WHEEL", True)
NATIVE_NOTIFIER = envbool("XPRA_OSX_NATIVE_NOTIFIER", True)
SUBPROCESS_NOTIFIER = envbool("XPRA_OSX_SUBPROCESS_NOTIFIER", False)

ALPHA = {
         CG.kCGImageAlphaNone                  : "AlphaNone",
         CG.kCGImageAlphaPremultipliedLast     : "PremultipliedLast",
         CG.kCGImageAlphaPremultipliedFirst    : "PremultipliedFirst",
         CG.kCGImageAlphaLast                  : "Last",
         CG.kCGImageAlphaFirst                 : "First",
         CG.kCGImageAlphaNoneSkipLast          : "SkipLast",
         CG.kCGImageAlphaNoneSkipFirst         : "SkipFirst",
   }
#if there is an easier way of doing this, I couldn't find it:
def nodbltime() -> float:
    return -1
GetDblTime : Callable = nodbltime
try:
    Carbon_ctypes = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
    GetDblTime = Carbon_ctypes.GetDblTime
except Exception:
    log("GetDblTime not found", exc_info=True)


def do_init() -> None:
    osxapp = get_OSXApplication()
    log("do_init() osxapp=%s", osxapp)
    if not osxapp:
        return  #not much else we can do here
    from xpra.platform.paths import get_icon
    from xpra.platform.gui import get_default_icon
    filename = get_default_icon()
    icon = get_icon(filename)
    log("do_init() icon=%s", icon)
    if icon:
        osxapp.set_dock_icon_pixbuf(icon)
    from xpra.platform.darwin.osx_menu import getOSXMenuHelper
    mh = getOSXMenuHelper(None)
    log("do_init() menu helper=%s", mh)
    osxapp.set_dock_menu(mh.build_dock_menu())
    import warnings
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*invalid cast from 'GtkMenuBar'")
        osxapp.set_menu_bar(mh.rebuild())


def do_ready() -> None:
    osxapp = get_OSXApplication()
    if osxapp:
        log("%s()", osxapp.ready)
        osxapp.ready()


class OSX_Notifier(NotifierBase):

    def __init__(self, closed_cb=None, action_cb=None):
        super().__init__(closed_cb, action_cb)
        self.gtk_notifier = None
        self.gtk_notifications = set()
        self.notifications = {}
        self.notification_center = NSUserNotificationCenter.defaultUserNotificationCenter()
        assert self.notification_center

    def show_notify(self, dbus_id, tray, nid, app_name, replaces_nid, app_icon,
                    summary, body, actions, hints, expire_timeout, icon):
        GTK_NOTIFIER = envbool("XPRA_OSX_GTK_NOTIFIER", True)
        if actions and GTK_NOTIFIER:
            #try to use GTK notifier if we have actions buttons to handle:
            try:
                from xpra.gtk_common.gtk_notifier import GTK_Notifier
            except ImportError as e:
                log("cannot use GTK notifier for handling actions: %s", e)
            else:
                self.gtk_notifier = GTK_Notifier(self.closed_cb, self.action_cb)
                self.gtk_notifier.show_notify(dbus_id, tray, nid, app_name, replaces_nid, app_icon,
                                              summary, body, actions, hints, expire_timeout, icon)
                self.gtk_notifications.add(nid)
                return
        GLib.idle_add(self.do_show_notify, dbus_id, tray, nid, app_name, replaces_nid, app_icon, summary, body, actions, hints, expire_timeout, icon)

    def do_show_notify(self, dbus_id, tray, nid:int, app_name, replaces_nid:int, app_icon,
                       summary:str, body:str, actions, hints, expire_timeout:int, icon):
        notification = NSUserNotification.alloc()
        notification.init()
        notification.setTitle_(summary)
        notification.setInformativeText_(body)
        notification.setIdentifier_("%s" % nid)
        #enable sound:
        notification.setSoundName_(NSUserNotificationDefaultSoundName)
        notifylog("do_show_notify(..) nid=%s, %s(%s)", nid, self.notification_center.deliverNotification_, notification)
        self.notifications[nid] = notification
        self.notification_center.deliverNotification_(notification)

    def close_notify(self, nid):
        try:
            self.gtk_notifications.remove(nid)
        except KeyError:
            notification = self.notifications.get(nid)
            notifylog("close_notify(..) notification[%i]=%s", nid, notification)
            if notification:
                GLib.idle_add(self.notification_center.removeDeliveredNotification_, notification)
        else:
            self.gtk_notifier.close_notify(nid)

    def cleanup(self):
        super().cleanup()
        GLib.idle_add(self.notification_center.removeAllDeliveredNotifications)


def get_clipboard_native_class() -> str:
    return "xpra.platform.darwin.osx_clipboard.OSXClipboardProtocolHelper"


def get_native_notifier_classes() -> List[Type]:
    v = []
    if NATIVE_NOTIFIER and NSUserNotificationCenter.defaultUserNotificationCenter():
        v.append(OSX_Notifier)
    notifylog("get_native_notifier_classes()=%s", v)
    return v

def get_native_tray_menu_helper_class() -> Optional[Callable]:
    if get_OSXApplication():
        from xpra.platform.darwin.osx_menu import getOSXMenuHelper
        return getOSXMenuHelper
    return None

def get_native_tray_classes() -> List[Type]:
    if get_OSXApplication():
        from xpra.platform.darwin.osx_tray import OSXTray
        return [OSXTray]
    return []

def system_bell(*_args) -> bool:
    NSBeep()
    return True


def _sizetotuple(s) -> Tuple[int,int]:
    return int(s.width), int(s.height)
def _recttotuple(r) -> Tuple[int,int,int,int]:
    return int(r.origin.x), int(r.origin.y), int(r.size.width), int(r.size.height)

def get_double_click_time() -> int:
    try:
        #what are ticks? just an Apple retarded way of measuring elapsed time.
        #They must have considered gigaparsecs divided by teapot too, which is just as useful.
        #(but still call it "Time" you see)
        MS_PER_TICK = 1000.0/60
        v = GetDblTime()
        if v>0:
            return int(v * MS_PER_TICK)
    except Exception:
        pass
    return -1


def get_window_min_size() -> Tuple[int,int]:
    #roughly enough to see the window buttons:
    return 120, 1

#def get_window_max_size():
#    return 2**15-1, 2**15-1

def get_window_frame_sizes():
    #use a hard-coded window position and size:
    return get_window_frame_size(20, 20, 100, 100)

def get_window_frame_size(x, y, w, h):
    try:
        cr = Quartz.NSMakeRect(x, y, w, h)
        mask = Quartz.NSTitledWindowMask | Quartz.NSClosableWindowMask | Quartz.NSMiniaturizableWindowMask | Quartz.NSResizableWindowMask
        wr = Quartz.NSWindow.pyobjc_classMethods.frameRectForContentRect_styleMask_(cr, mask)
        dx = int(wr[0][0] - cr[0][0])
        dy = int(wr[0][1] - cr[0][1])
        dw = int(wr[1][0] - cr[1][0])
        dh = int(wr[1][1] - cr[1][1])
        #note: we assume that the title bar is at the top
        #dx, dy and dw are usually 0
        #dh is usually 22 on my 10.5.x system
        return {
                "offset"    : (dx+dw//2, dy+dh),
                "frame"     : (dx+dw//2, dx+dw//2, dy+dh, dy),
                }
    except Exception:
        log("failed to query frame size using Quartz, using hardcoded value", exc_info=True)
        return {            #left, right, top, bottom:
                "offset"    : (0, 22),
                "frame"     : (0, 0, 22, 0),
               }

def get_workarea():
    w = get_workareas()
    if w and len(w)==1:
        return w[0]
    return None

#per monitor workareas (assuming a single screen)
def get_workareas():
    workareas = []
    screens = NSScreen.screens()
    for screen in screens:
        log("get_workareas() testing screen %s", screen)
        frame = screen.frame()
        visibleFrame = screen.visibleFrame()
        log(" frame=%s, visibleFrame=%s", frame, visibleFrame)
        log(" backingScaleFactor=%s", screen.backingScaleFactor())
        x = int(visibleFrame.origin.x - frame.origin.x)
        y = int((frame.size.height - visibleFrame.size.height) - (visibleFrame.origin.y - frame.origin.y))
        w = int(visibleFrame.size.width)
        h = int(visibleFrame.size.height)
        workareas.append((x, y, w, h))
    log("get_workareas()=%s", workareas)
    return workareas

def get_vrefresh() -> int:
    vrefresh = []
    try:
        err, active_displays, no = CG.CGGetActiveDisplayList(99, None, None)
        log("get_vrefresh() %i active displays: %s (err=%i)", no, active_displays, err)
        if err==0 and no>0:
            for adid in active_displays:
                mode = CG.CGDisplayCopyDisplayMode(adid)
                v = int(CG.CGDisplayModeGetRefreshRate(mode))
                log("get_vrefresh() refresh-rate(%#x)=%i", adid, v)
                if v>0:
                    vrefresh.append(v)
    except Exception:
        log("failed to query vrefresh for active displays: %s", exc_info=True)
    log("get_vrefresh() found %s", vrefresh)
    if len(vrefresh)>0:
        return min(vrefresh)
    return -1


def get_display_icc_info() -> Dict[Any,Dict]:
    info = {}
    try:
        err, active_displays, no = CG.CGGetActiveDisplayList(99, None, None)
        if err==0 and no>0:
            for i,adid in enumerate(active_displays):
                info[i] = get_colorspace_info(CG.CGDisplayCopyColorSpace(adid))
    except Exception as e:
        log("failed to query colorspace for active displays: %s", e)
    return info

def get_icc_info():
    #maybe we shouldn't return anything if there's more than one display?
    info = {}
    try:
        did = CG.CGMainDisplayID()
        info = get_colorspace_info(CG.CGDisplayCopyColorSpace(did))
    except Exception as e:
        log("failed to query colorspace for main display: %s", e)
    return info


def get_colorspace_info(cs) -> Dict[str,Any]:
    MODELS : Dict[Any, str] = {
              CG.kCGColorSpaceModelUnknown     : "unknown",
              CG.kCGColorSpaceModelMonochrome  : "monochrome",
              CG.kCGColorSpaceModelRGB         : "RGB",
              CG.kCGColorSpaceModelCMYK        : "CMYK",
              CG.kCGColorSpaceModelLab         : "lab",
              CG.kCGColorSpaceModelDeviceN     : "DeviceN",
              CG.kCGColorSpaceModelIndexed     : "indexed",
              CG.kCGColorSpaceModelPattern     : "pattern",
              }
    #base = CGColorSpaceGetBaseColorSpace(cs)
    #color_table = CGColorSpaceGetColorTable(cs)
    def tomodelstr(v) -> str:
        return MODELS.get(v, "unknown")
    defs = (
            ("name",                "CGColorSpaceCopyName",                 str),
            ("icc-profile",         "CGColorSpaceCopyICCProfile",           str),
            ("icc-data",            "CGColorSpaceCopyICCData",              str),
            ("components",          "CGColorSpaceGetNumberOfComponents",    int),
            ("supports-output",     "CGColorSpaceSupportsOutput",           bool),
            ("model",               "CGColorSpaceGetModel",                 tomodelstr),
            ("wide-gamut",          "CGColorSpaceIsWideGamutRGB",           bool),
            ("color-table-count",   "CGColorSpaceGetColorTableCount",       int),
            )
    return _call_CG_conv(defs, cs)

def get_display_mode_info(mode) -> Dict[str,Any]:
    defs = (
            ("width",               "CGDisplayModeGetWidth",                int),
            ("height",              "CGDisplayModeGetHeight",               int),
            ("pixel-encoding",      "CGDisplayModeCopyPixelEncoding",       str),
            ("vrefresh",            "CGDisplayModeGetRefreshRate",          int),
            ("io-flags",            "CGDisplayModeGetIOFlags",              int),
            ("id",                  "CGDisplayModeGetIODisplayModeID",      int),
            ("usable-for-desktop",  "CGDisplayModeIsUsableForDesktopGUI",   bool),
            )
    return _call_CG_conv(defs, mode)

def get_display_modes_info(modes) -> Dict[int,Any]:
    return dict((i,get_display_mode_info(mode)) for i,mode in enumerate(modes))


def _call_CG_conv(defs:Tuple[Tuple[str,str,Callable],...], argument) -> Dict[str,Any]:
    #utility for calling functions on CG with an argument,
    #then convert the return value using another function
    #missing functions are ignored, and None values are skipped
    info = {}
    for prop_name, fn_name, conv in defs:
        fn = getattr(CG, fn_name, None)
        if fn:
            try:
                v = fn(argument)
            except Exception as e:
                log("function %s failed: %s", fn_name, e)
                del e
                continue
            if v is not None:
                info[prop_name] = conv(v)
            else:
                log("%s is not set", prop_name)
        else:
            log("function %s does not exist", fn_name)
    return info

def get_display_info(did) -> Dict[str,Any]:
    defs = (
            ("height",                  "CGDisplayPixelsHigh",              int),
            ("width",                   "CGDisplayPixelsWide",              int),
            ("bounds",                  "CGDisplayBounds",                  _recttotuple),
            ("active",                  "CGDisplayIsActive",                bool),
            ("asleep",                  "CGDisplayIsAsleep",                bool),
            ("online",                  "CGDisplayIsOnline",                bool),
            ("main",                    "CGDisplayIsMain",                  bool),
            ("builtin",                 "CGDisplayIsBuiltin",               bool),
            ("in-mirror-set",           "CGDisplayIsInMirrorSet",           bool),
            ("always-in-mirror-set",    "CGDisplayIsAlwaysInMirrorSet",     bool),
            ("in-hw-mirror-set",        "CGDisplayIsInHWMirrorSet",         bool),
            ("mirrors-display",         "CGDisplayMirrorsDisplay",          int),
            ("stereo",                  "CGDisplayIsStereo",                bool),
            ("primary",                 "CGDisplayPrimaryDisplay",          bool),
            ("unit-number",             "CGDisplayUnitNumber",              int),
            ("vendor",                  "CGDisplayVendorNumber",            int),
            ("model",                   "CGDisplayModelNumber",             int),
            ("serial",                  "CGDisplaySerialNumber",            int),
            ("service-port",            "CGDisplayIOServicePort",           int),
            ("size",                    "CGDisplayScreenSize",              _sizetotuple),
            ("rotation",                "CGDisplayRotation",                int),
            ("colorspace",              "CGDisplayCopyColorSpace",          get_colorspace_info),
            ("opengl-acceleration",     "CGDisplayUsesOpenGLAcceleration",  bool),
            ("mode",                    "CGDisplayCopyDisplayMode",         get_display_mode_info),
            )
    info = _call_CG_conv(defs, did)
    try:
        modes = CG.CGDisplayCopyAllDisplayModes(did, None)
        info["modes"] = get_display_modes_info(modes)
    except Exception as e:
        log("failed to query display modes: %s", e)
    return info

def get_displays_info() -> Dict[str,Any]:
    did = CG.CGMainDisplayID()
    info : Dict[str,Any] = {
            "main" : get_display_info(did),
            }
    err, active_displays, no = CG.CGGetActiveDisplayList(99, None, None)
    if err==0 and no>0:
        for i,adid in enumerate(active_displays):
            info.setdefault("active", {})[i] = get_display_info(adid)
    err, online_displays, no = CG.CGGetOnlineDisplayList(99, None, None)
    if err==0 and no>0:
        for i,odid in enumerate(online_displays):
            info.setdefault("online", {})[i] = get_display_info(odid)
    return info

def get_info() -> Dict[str,Any]:
    from xpra.platform.gui import get_info_base
    i = get_info_base()
    try:
        i["displays"] = get_displays_info()
    except Exception:
        log.error("Error: OSX get_display_info failed", exc_info=True)
    return i


#keep track of the window object for each view
VIEW_TO_WINDOW : WeakValueDictionary[int,Any] = WeakValueDictionary()

def get_nsview(window) -> int:
    try:
        from xpra.platform.darwin.gdk3_bindings import get_nsview_ptr
    except ImportError:
        return 0
    try:
        return get_nsview_ptr(window.get_window())
    except Exception:
        return 0

def add_window_hooks(window) -> None:
    if WHEEL:
        nsview = get_nsview(window)
        if nsview:
            VIEW_TO_WINDOW[nsview] = window

def remove_window_hooks(window) -> None:
    if WHEEL:
        nsview = get_nsview(window)
        if nsview:
            VIEW_TO_WINDOW.pop(nsview, None)


def get_CG_imagewrapper(rect=None):
    from xpra.codecs.image_wrapper import ImageWrapper
    assert CG, "cannot capture without Quartz.CoreGraphics"
    if rect is None:
        x = 0
        y = 0
        region = CG.CGRectInfinite
    else:
        x, y, w, h = rect
        region = CG.CGRectMake(x, y, roundup(w, 2), roundup(h, 2))
    image = CG.CGWindowListCreateImage(region,
                CG.kCGWindowListOptionOnScreenOnly,
                CG.kCGNullWindowID,
                CG.kCGWindowImageNominalResolution) #CG.kCGWindowImageDefault)
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
    return ImageWrapper(x, y, width, height, argb, "BGRX", 24, rowstride)

def take_screenshot() -> Tuple[int,int,str,int,bytes]:
    log("grabbing screenshot")
    from PIL import Image                       #@UnresolvedImport
    from io import BytesIO
    image = get_CG_imagewrapper()
    w = image.get_width()
    h = image.get_height()
    img = Image.frombuffer("RGB", (w, h), image.get_pixels(), "raw", image.get_pixel_format(), image.get_rowstride())
    buf = BytesIO()
    img.save(buf, "PNG")
    data = buf.getvalue()
    buf.close()
    return w, h, "png", image.get_rowstride(), data

def force_focus(duration=2000) -> None:
    enable_focus_workaround()
    GLib.timeout_add(duration, disable_focus_workaround)


__osx_open_signal = False
#We have to wait for the main loop to be running
#to get the NSApplicationOpenFile signal,
#or the GURLHandler.
OPEN_SIGNAL_WAIT = envint("XPRA_OSX_OPEN_SIGNAL_WAIT", 500)
def add_open_handlers(open_file_cb:Callable, open_url_cb:Callable) -> None:

    def idle_add(fn, *args):
        GLib.idle_add(fn, *args)

    def open_URL(url) -> bool:
        global __osx_open_signal
        __osx_open_signal = True
        log("open_URL(%s)", url)
        idle_add(open_url_cb, url)
        return True

    def open_file(_, filename:str, *args) -> bool:
        global __osx_open_signal
        __osx_open_signal = True
        log("open_file(%s, %s)", filename, args)
        idle_add(open_file_cb, filename)
        return True
    register_file_handler(open_file)
    register_URL_handler(open_URL)

def wait_for_open_handlers(show_cb:Callable,
                           open_file_cb:Callable,
                           open_url_cb:Callable,
                           delay:int=OPEN_SIGNAL_WAIT) -> None:
    add_open_handlers(open_file_cb, open_url_cb)
    def may_show():
        global __osx_open_signal
        log("may_show() osx open signal=%s", __osx_open_signal)
        if not __osx_open_signal:
            force_focus()
            show_cb()
    GLib.timeout_add(delay, may_show)

def register_file_handler(handler:Callable) -> None:
    log("register_file_handler(%s)", handler)
    try:
        get_OSXApplication().connect("NSApplicationOpenFile", handler)
    except Exception as e:
        log.error("Error: cannot handle file associations:")
        log.estr(e)

def register_URL_handler(handler:Callable) -> None:
    log("register_URL_handler(%s)", handler)
    class GURLHandler(NSObject):
        def handleEvent_withReplyEvent_(self, event, reply_event):
            log("GURLHandler.handleEvent(%s, %s)", event, reply_event)
            url = event.descriptorForKeyword_(fourCharToInt(b'----')).stringValue()
            log("URL=%s", url)
            handler(url.encode())

    # A helper to make struct since cocoa headers seem to make
    # it impossible to use kAE*
    fourCharToInt = lambda code: struct.unpack(b'>l', code)[0]

    urlh = GURLHandler.alloc()
    urlh.init()
    urlh.retain()
    manager = NSAppleEventManager.sharedAppleEventManager()
    manager.setEventHandler_andSelector_forEventClass_andEventID_(
        urlh, 'handleEvent:withReplyEvent:',
        fourCharToInt(b'GURL'), fourCharToInt(b'GURL')
        )


class AppDelegate(NSObject):

    def init(self) -> None:
        self = objc.super(AppDelegate, self).init()
        if self is None:
            return None
        self.callbacks : Dict[str,Callable] = {}
        self.workspace = None
        self.notificationCenter = None
        return self

    @objc.python_method
    def wheel_event_handler(self, nsview, deltax, deltay, precise):
        global VIEW_TO_WINDOW
        window = VIEW_TO_WINDOW.get(nsview)
        mouselog("wheel_event_handler(%#x, %.4f, %.4f, %s) window=%s", nsview, deltax, deltay, precise, window)
        if not window:
            return False    #not handled
        def normalize_precision(distance):
            if distance==0:
                return 0
            if precise:
                m = OSX_WHEEL_PRECISE_MULTIPLIER
            else:
                m = OSX_WHEEL_MULTIPLIER
            v = m*abs(distance)/OSX_WHEEL_DIVISOR
            if v>1:
                #cancel out some of the crazy fast scroll acceleration from macos:
                v = math.sqrt(v)
            if distance<0:
                #restore sign:
                v = -v
            mouselog("normalize_precision(%.3f)=%.3f (multiplier=%i)", distance, v, m)
            return v
        dx = normalize_precision(deltax)
        dy = normalize_precision(deltay)
        if dx!=0 or dy!=0:
            client = window._client
            wid = window.wid
            pointer = window.get_mouse_position()
            device_id = -1
            client.wheel_event(device_id, wid, dx, dy, pointer)
        return True

    @objc.python_method
    def register_sleep_handlers(self):
        log("register_sleep_handlers()")
        self.workspace : NSWorkspace = NSWorkspace.sharedWorkspace()
        self.notificationCenter = self.workspace.notificationCenter()
        def add_observer(fn, val):
            self.notificationCenter.addObserver_selector_name_object_(self, fn, val, None)
        #NSWorkspaceWillPowerOffNotification
        add_observer(self.receiveSleepNotification_, NSWorkspaceWillSleepNotification)
        add_observer(self.receiveWakeNotification_, NSWorkspaceDidWakeNotification)
        add_observer(self.receiveWorkspaceChangeNotification_, NSWorkspaceActiveSpaceDidChangeNotification)


    @objc.typedSelector(b'B@:#B')
    def applicationShouldHandleReopen_hasVisibleWindows_(self, ns_app, flag):
        log("applicationShouldHandleReopen_hasVisibleWindows%s", (ns_app, flag))
        self.delegate_cb("deiconify")
        return True

    @objc.typedSelector(b'v@:I')
    def receiveWorkspaceChangeNotification_(self, aNotification):
        workspacelog("receiveWorkspaceChangeNotification_(%s)", aNotification)
        if not CGWindowListCopyWindowInfo:
            return
        try:
            ourpid = os.getpid()
            windowList = CGWindowListCopyWindowInfo(kCGWindowListOptionAll | kCGWindowListOptionOnScreenOnly, kCGNullWindowID)
            our_windows = {}
            for window in windowList:
                pid = window['kCGWindowOwnerPID']
                if pid==ourpid:
                    num = window['kCGWindowNumber']
                    name = window['kCGWindowName']
                    our_windows[num] = name
            workspacelog("workspace change - our windows on screen: %s", our_windows)
            if our_windows:
                self.delegate_cb("wake")
            else:
                self.delegate_cb("sleep")
        except Exception:
            workspacelog.error("Error querying workspace info", exc_info=True)

    #def application_openFile_(self, application, fileName):
    #    log.warn("application_openFile_(%s, %s)", application, fileName)
    @objc.typedSelector(b'v@:I')
    def receiveSleepNotification_(self, aNotification):
        log("receiveSleepNotification_(%s) sleep_callback=%s", aNotification, self.sleep_callback)
        self.delegate_cb("sleep")

    @objc.typedSelector(b'v@:I')
    def receiveWakeNotification_(self, aNotification):
        log("receiveWakeNotification_(%s)", aNotification)
        self.delegate_cb("wake")

    @objc.python_method
    def delegate_cb(self, name):
        #find the named callback and call it
        callback = self.callbacks.get(name)
        log("delegate_cb(%s)=%s", name, callback)
        if callback:
            try:
                callback()
            except Exception:
                log.error("Error in %s callback %s", name, callback, exc_info=True)


def disable_focus_workaround() -> None:
    NSApp.activateIgnoringOtherApps_(False)
def enable_focus_workaround() -> None:
    NSApp.activateIgnoringOtherApps_(True)


def can_access_display() -> bool:
    #see: https://stackoverflow.com/a/11511419/428751
    d = Quartz.CGSessionCopyCurrentDictionary()
    if not d:
        return False
    kCGSSessionOnConsoleKey = d.get("kCGSSessionOnConsoleKey", 0)
    log("kCGSSessionOnConsoleKey=%s", kCGSSessionOnConsoleKey)
    if kCGSSessionOnConsoleKey==0:
        #GUI session doesn't own the console, or the console's screens are asleep
        return False
    CGSSessionScreenIsLocked = d.get("CGSSessionScreenIsLocked", 0)
    log("CGSSessionScreenIsLocked=%s", CGSSessionScreenIsLocked)
    if CGSSessionScreenIsLocked:
        #screen is locked
        return False
    return True


class ClientExtras:
    def __init__(self, client=None, opts=None):
        if OSX_FOCUS_WORKAROUND and client:
            def first_ui_received(*_args):
                enable_focus_workaround()
                client.timeout_add(OSX_FOCUS_WORKAROUND, disable_focus_workaround)
            client.connect("first-ui-received", first_ui_received)
        log("ClientExtras.__init__(%s, %s)", client, opts)
        self.client = client
        self.event_loop_started = False
        self.check_display_timer = 0
        self.display_is_asleep = False
        self.shared_app = None
        self.delegate = None
        if opts and client:
            swap_keys = opts.swap_keys
            log("setting swap_keys=%s using %s", swap_keys, client.keyboard_helper)
            if client.keyboard_helper and client.keyboard_helper.keyboard:
                log("%s.swap_keys=%s", client.keyboard_helper.keyboard, swap_keys)
                client.keyboard_helper.keyboard.swap_keys = swap_keys
        if client:
            self.check_display_timer = client.timeout_add(60*1000, self.check_display)

    def cleanup(self) -> None:
        cdt = self.check_display_timer
        client = self.client
        if cdt and client:
            client.source_remove(cdt)
            self.check_display_timer = 0
        try:
            r = CGDisplayRemoveReconfigurationCallback(self.display_change, self)
        except ValueError as e:
            log("CGDisplayRemoveReconfigurationCallback: %s", e)
            #if we exit from a signal, this may fail
            r = 1
        if r!=0:
            #don't bother logging this as a warning since we are terminating anyway:
            log("failed to unregister display reconfiguration callback")
        self.client = None

    def ready(self) -> None:
        if EVENT_LISTENER:
            try:
                self.setup_event_listener()
            except Exception:
                log.error("Error setting up OSX event listener", exc_info=True)

    def setup_event_listener(self) -> None:
        self.shared_app = NSApplication.sharedApplication()
        log(f"setup_event_listener() delegate={self.delegate}, shared app={self.shared_app}")
        self.delegate = AppDelegate.alloc()
        self.delegate.init()
        self.delegate.retain()
        if self.client:
            self.delegate.callbacks.update({
                "sleep" : self.client.suspend,
                "wake" : self.client.resume,
                "deiconify" : self.client.deiconify_windows,
                })
        self.shared_app.setDelegate_(self.delegate)
        log("setup_event_listener() the application delegate has been registered")
        r = CGDisplayRegisterReconfigurationCallback(self.display_change, self)
        if r!=0:
            log.warn("Warning: failed to register display reconfiguration callback")

    def display_change(self, display, flags, userinfo) -> None:
        log("display_change%s", (display, flags, userinfo))
        c = self.client
        #The display mode has changed
        #opengl windows may need to be re-created since the GPU may have changed:
        if (flags & kCGDisplaySetModeFlag) and c and c.opengl_enabled:
            c.reinit_windows()

    def check_display(self) -> bool:
        log("check_display()")
        try:
            c = self.client
            asleep = None
            if not can_access_display():
                asleep = True
            else:
                did = CG.CGMainDisplayID()
                log("check_display() CGMainDisplayID()=%#x", did)
                if did and c:
                    asleep = bool(CG.CGDisplayIsAsleep(did))
                    log("check_display() CGDisplayIsAsleep(%#x)=%s", did, asleep)
            if c and asleep is not None and self.display_is_asleep!=asleep:
                self.display_is_asleep = asleep
                if asleep:
                    c.suspend()
                else:
                    c.resume()
            return True
        except Exception:
            log.error("Error checking display sleep status", exc_info=True)
            self.check_display_timer = 0
            return False

    def run(self) -> None:
        #this is for running standalone
        log("starting console event loop")
        self.event_loop_started = True
        import PyObjCTools.AppHelper as AppHelper   #@UnresolvedImport
        AppHelper.runConsoleEventLoop(installInterrupt=True)
        #when running from the GTK main loop, we rely on another part of the code
        #to run the event loop for us

    def stop(self) -> None:
        if self.event_loop_started:
            self.event_loop_started = False
            import PyObjCTools.AppHelper as AppHelper   #@UnresolvedImport
            AppHelper.stopEventLoop()


def main():
    from xpra.platform import program_context
    with program_context("OSX Extras"):
        log.enable_debug()
        ce = ClientExtras(None, None)
        ce.check_display()
        ce.ready()
        ce.run()


if __name__ == "__main__":
    main()
