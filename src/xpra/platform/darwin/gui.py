#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import math
import ctypes
import struct
import weakref
import gtkosx_application           #@UnresolvedImport

import objc                         #@UnresolvedImport
import Quartz                       #@UnresolvedImport
import Quartz.CoreGraphics as CG    #@UnresolvedImport
from Quartz import CGWindowListCopyWindowInfo, kCGWindowListOptionOnScreenOnly, kCGNullWindowID, kCGWindowListOptionAll #@UnresolvedImport
from AppKit import NSAppleEventManager, NSScreen, NSObject, NSBeep   #@UnresolvedImport
from AppKit import NSApp, NSApplication, NSWorkspace, NSWorkspaceActiveSpaceDidChangeNotification, NSWorkspaceWillSleepNotification, NSWorkspaceDidWakeNotification     #@UnresolvedImport
from Foundation import NSUserNotification, NSUserNotificationCenter, NSUserNotificationDefaultSoundName #@UnresolvedImport

from xpra.util import envbool, envint, roundup
from xpra.client.notifications.notifier_base import NotifierBase

from xpra.log import Logger
log = Logger("osx", "events")
workspacelog = Logger("osx", "events", "workspace")
mouselog = Logger("osx", "events", "mouse")
notifylog = Logger("osx", "notify")


OSX_FOCUS_WORKAROUND = envint("XPRA_OSX_FOCUS_WORKAROUND", 2000)
SLEEP_HANDLER = envbool("XPRA_OSX_SLEEP_HANDLER", True)
OSX_WHEEL_MULTIPLIER = envint("XPRA_OSX_WHEEL_MULTIPLIER", 100)
OSX_WHEEL_PRECISE_MULTIPLIER = envint("XPRA_OSX_WHEEL_PRECISE_MULTIPLIER", 1)
WHEEL = envbool("XPRA_WHEEL", True)
NATIVE_NOTIFIER = envbool("XPRA_OSX_NATIVE_NOTIFIER", False)
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
try:
    Carbon_ctypes = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
    GetDblTime = Carbon_ctypes.GetDblTime
except:
    GetDblTime = None


exit_cb = None
def quit_handler(*_args):
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
        macapp = gtkosx_application.Application()
        macapp.connect("NSApplicationWillTerminate", quit_handler)
    return macapp


def do_init():
    osxapp = get_OSXApplication()
    log("do_init() osxapp=%s", osxapp)
    if not osxapp:
        return  #not much else we can do here
    from xpra.platform.paths import get_icon
    icon = get_icon("xpra.png")
    log("do_init() icon=%s", icon)
    if icon:
        osxapp.set_dock_icon_pixbuf(icon)
    from xpra.platform.darwin.osx_menu import getOSXMenuHelper
    mh = getOSXMenuHelper(None)
    log("do_init() menu helper=%s", mh)
    osxapp.set_dock_menu(mh.build_dock_menu())
    osxapp.set_menu_bar(mh.rebuild())


def do_ready():
    osxapp = get_OSXApplication()
    if osxapp:
        osxapp.ready()


class OSX_Notifier(NotifierBase):

    def __init__(self):
        self.notifications = {}
        self.notification_center = NSUserNotificationCenter.defaultUserNotificationCenter()
        assert self.notification_center

    def show_notify(self, dbus_id, tray, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout):
        notification = NSUserNotification.alloc().init()
        notification.setTitle_(summary)
        notification.setInformativeText_(body)
        notification.setIdentifier_("%s" % nid)
        #enable sound:
        notification.setSoundName_(NSUserNotificationDefaultSoundName)
        notifylog("show_notify(..) nid=%s, %s(%s)", nid, self.notification_center.deliverNotification_, notification)
        self.notifications[nid] = notification
        self.notification_center.deliverNotification_(notification)

    def close_notify(self, nid):
        notification = self.notifications.get(nid)
        notifylog("close_notify(..) notification[%i]=%s", nid, notification)
        if notification:
            self.notification_center.removeDeliveredNotification_(notification)

    def cleanup(self):
        NotifierBase.cleanup(self)
        self.notification_center.removeAllDeliveredNotifications_()


class OSX_Subprocess_Notifier(NotifierBase):
    def show_notify(self, dbus_id, tray, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout):
        from xpra.platform.darwin import osx_notifier
        osx_notifier_file = osx_notifier.__file__
        if osx_notifier_file.endswith("pyc"):
            osx_notifier_file = osx_notifier_file[:-1]
        import time
        #osx_notifier_file = "/Users/osx/osx_notifier.py"
        from xpra.platform.paths import get_app_dir
        base = get_app_dir()
        #python_bin = "/usr/bin/python"
        python_bin = os.path.join(base, "Resources", "bin", "python")
        cmd = [python_bin, osx_notifier_file, "%s-%s" % (int(time.time()), nid), summary, body]
        from xpra.child_reaper import getChildReaper
        import subprocess
        env = os.environ.copy()
        for x in ("DYLD_LIBRARY_PATH", "XDG_CONFIG_DIRS", "XDG_DATA_DIRS",
                  "GTK_DATA_PREFIX", "GTK_EXE_PREFIX", "GTK_PATH",
                  "GTK2_RC_FILES", "GTK_IM_MODULE_FILE", "GDK_PIXBUF_MODULE_FILE",
                  "PANGO_RC_FILE", "PANGO_LIBDIR", "PANGO_SYSCONFDIR",
                  "CHARSETALIASDIR",
                  "GST_BUNDLE_CONTENTS", "PYTHON", "PYTHONHOME",
                  "PYTHONPATH"):
            if x in env:
                del env[x]
        notifylog("running %s with env=%s", cmd, env)
        proc = subprocess.Popen(cmd, env=env)
        proc.wait()
        notifylog("returned %i", proc.poll())
        getChildReaper().add_process(proc, "notifier-%s" % nid, cmd, True, True)

    def close_notify(self, nid):
        pass
    

def get_native_notifier_classes():
    v = []
    if NATIVE_NOTIFIER and NSUserNotificationCenter.defaultUserNotificationCenter():
        v.append(OSX_Notifier)
    if SUBPROCESS_NOTIFIER:
        v.append(OSX_Subprocess_Notifier)
    notifylog("get_native_notifier_classes()=%s", v)
    return v

def get_native_tray_menu_helper_classes():
    if get_OSXApplication():
        from xpra.platform.darwin.osx_menu import getOSXMenuHelper
        return [getOSXMenuHelper]
    return []

def get_native_tray_classes():
    if get_OSXApplication():
        from xpra.platform.darwin.osx_tray import OSXTray
        return [OSXTray]
    return []

def system_bell(*_args):
    NSBeep()
    return True


def _sizetotuple(s):
    return int(s.width), int(s.height)
def _recttotuple(r):
    return tuple(int(v) for v in (r.origin.x, r.origin.y, r.size.width, r.size.height))

def get_double_click_time():
    try:
        #what are ticks? just an Apple retarded way of measuring elapsed time.
        #They must have considered gigaparsecs divided by teapot too, which is just as useful.
        #(but still call it "Time" you see)
        MS_PER_TICK = 1000/60
        return int(GetDblTime() * MS_PER_TICK)
    except:
        return -1


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
    except:
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
        try:
            #10.7 onwards:
            log(" backingScaleFactor=%s", screen.backingScaleFactor())
        except:
            pass
        x = int(visibleFrame.origin.x - frame.origin.x)
        y = int((frame.size.height - visibleFrame.size.height) - (visibleFrame.origin.y - frame.origin.y))
        w = int(visibleFrame.size.width)
        h = int(visibleFrame.size.height)
        workareas.append((x, y, w, h))
    log("get_workareas()=%s", workareas)
    return workareas

def get_vrefresh():
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


def get_display_icc_info():
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


def get_colorspace_info(cs):
    MODELS = {
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
    def tomodelstr(v):
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

def get_display_mode_info(mode):
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

def get_display_modes_info(modes):
    return dict((i,get_display_mode_info(mode)) for i,mode in enumerate(modes))


def _call_CG_conv(defs, argument):
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

def get_display_info(did):
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

def get_displays_info():
    did = CG.CGMainDisplayID()
    info = {
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

def get_info():
    from xpra.platform.gui import get_info_base
    i = get_info_base()
    try:
        i["displays"] = get_displays_info()
    except:
        log.error("Error: OSX get_display_info failed", exc_info=True)
    return i


#global menu handling:
window_menus = {}

def window_focused(window, event):
    global window_menus
    wid = window._id
    menu_data = window_menus.get(wid)
    log("window_focused(%s, %s) menu(%s)=%s", window, event, wid, menu_data)
    application_actions, window_menu = None, None
    if menu_data:
        menus, application_action_callback, window_action_callback = menu_data
        application_actions = menus.get("application-actions")
        window_actions = menus.get("window-actions")
        window_menu = menus.get("window-menu")
    from xpra.platform.darwin.osx_menu import getOSXMenuHelper
    mh = getOSXMenuHelper()
    mh.rebuild()
    mh.add_full_menu()
    if not menu_data or (not application_actions and not window_actions) or not window_menu:
        return
    #add the application menus after that:
    #ie: menu = {
    #         'enabled': True,
    #         'application-id':         'org.xpra.ExampleMenu',
    #         'application-actions':    {'quit': (True, '', ()), 'about': (True, '', ()), 'help': (True, '', ()), 'custom': (True, '', ()), 'activate-tab': (True, 's', ()), 'preferences': (True, '', ())},
    #         'window-actions':         {'edit-profile': (True, 's', ()), 'reset': (True, 'b', ()), 'about': (True, '', ()), 'help': (True, '', ()), 'fullscreen': (True, '', (0,)), 'detach-tab': (True, '', ()), 'save-contents': (True, '', ()), 'zoom': (True, 'i', ()), 'move-tab': (True, 'i', ()), 'new-terminal': (True, '(ss)', ()), 'switch-tab': (True, 'i', ()), 'new-profile': (True, '', ()), 'close': (True, 's', ()), 'show-menubar': (True, '', (1,)), 'select-all': (True, '', ()), 'copy': (True, '', ()), 'paste': (True, 's', ()), 'find': (True, 's', ()), 'preferences': (True, '', ())},
    #         'window-menu':            {0:
    #               {0: ({':section': (0, 1)}, {':section': (0, 2)}, {':section': (0, 3)}),
    #                1: ({'action': 'win.new-terminal', 'target': ('default', 'default'), 'label': '_New Terminal'},),
    #                2: ({'action': 'app.preferences', 'label': '_Preferences'},),
    #                3: ({'action': 'app.help', 'label': '_Help'}, {'action': 'app.about', 'label': '_About'}, {'action': 'app.quit', 'label': '_Quit'}),
    #                }
    #             }
    #           }
    #go through all the groups (not sure how we would get more than one with gtk menus.. but still):
    def cb(menu_item):
        #find the action for this item:
        action = getattr(menu_item, "_action", "undefined")
        log("application menu cb %s, action=%s", menu_item, action)
        if action.startswith("app."):
            callback = application_action_callback
            actions = application_actions
            action = action[4:]
        elif action.startswith("win."):
            callback = window_action_callback
            actions = window_actions
            action = action[4:]
        else:
            log.warn("Warning: unknown action type '%s'", action)
            return
        action_def = actions.get(action)
        if action_def is None:
            log.warn("Warning: cannot find action '%s'", action)
            return
        enabled, state, pdata = action_def[:3]
        if not enabled:
            log("action %s: %s is not enabled", action, action_def)
            return
        if len(action_def)>=4:
            callback = action_def[3]        #use action supplied callback
        log("OSX application menu item %s, action=%s, action_def=%s, callback=%s", menu_item, action, action_def, callback)
        if callback:
            callback(menu_item, action, state, pdata)
    for group_id in sorted(window_menu.keys()):
        group = window_menu[group_id]
        try:
            title = str(window._metadata.get("title"))
            assert title
        except:
            title = window.get_title() or "Application"
        app_menu = mh.make_menu()
        for menuid in sorted(group.keys()):
            menu_entries = group[menuid]
            for d in menu_entries:
                action = d.get("action")
                if not action:
                    continue
                label = d.get("label") or action
                item = mh.menuitem(label, cb=cb)
                item._action = action
                item._target = d.get("target")
                app_menu.add(item)
                log("added %s to %s menu for %s", label, title, window)
        mh.add_to_menu_bar(title, app_menu)


#keep track of the window object for each view
VIEW_TO_WINDOW = weakref.WeakValueDictionary()

def add_window_hooks(window):
    window.connect("focus-in-event", window_focused)
    global VIEW_TO_WINDOW
    try:
        gdkwin = window.get_window()
        VIEW_TO_WINDOW[gdkwin.nsview] = window
    except:
        log("add_window_hooks(%s)", window, exc_info=True)
        log.error("Error: failed to associate window %s with its nsview", window, exc_info=True)

def remove_window_hooks(window):
    try:
        del window_menus[window]
    except:
        pass
    global VIEW_TO_WINDOW
    #this should be redundant as we use weak references:
    try:
        gdkwin = window.get_window()
        del VIEW_TO_WINDOW[gdkwin.nsview]
    except:
        pass


def _set_osx_window_menu(add, wid, window, menus, application_action_callback=None, window_action_callback=None):
    global window_menus
    log("_set_osx_window_menu%s", (add, wid, window, menus, application_action_callback, window_action_callback))
    if (not menus) or (menus.get("enabled") is not True) or (add is False):
        try:
            del window_menus[wid]
        except:
            pass
    else:
        window_menus[wid] = (menus, application_action_callback, window_action_callback)


def get_menu_support_function():
    return _set_osx_window_menu


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
    return ImageWrapper(x, y, width, height, argb, "BGRX", 24, rowstride)

def take_screenshot():
    log("grabbing screenshot")
    from PIL import Image                       #@UnresolvedImport
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


def register_URL_handler(handler):
    log("register_URL_handler(%s)", handler)
    class GURLHandler(NSObject):
        def handleEvent_withReplyEvent_(self, event, reply_event):
            log("GURLHandler.handleEvent(%s, %s)", event, reply_event)
            url = event.descriptorForKeyword_(fourCharToInt('----')).stringValue()
            log("URL=%s", url)
            handler(url.encode())

    # A helper to make struct since cocoa headers seem to make
    # it impossible to use kAE*
    fourCharToInt = lambda code: struct.unpack('>l', code)[0]

    urlh = GURLHandler.alloc()
    urlh.init()
    urlh.retain()
    manager = NSAppleEventManager.sharedAppleEventManager()
    manager.setEventHandler_andSelector_forEventClass_andEventID_(
        urlh, 'handleEvent:withReplyEvent:',
        fourCharToInt('GURL'), fourCharToInt('GURL')
        )


class Delegate(NSObject):
    def applicationDidFinishLaunching_(self, notification):
        log("applicationDidFinishLaunching_(%s)", notification)
        if SLEEP_HANDLER:
            self.register_sleep_handlers()
        if WHEEL:
            from xpra.platform.darwin.gdk_bindings import init_quartz_filter, set_wheel_event_handler   #@UnresolvedImport
            set_wheel_event_handler(self.wheel_event_handler)
            init_quartz_filter()

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
            v = abs(distance)/10.0*m
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
            wid = window._id
            client.wheel_event(wid, dx, dy)
        return True

    @objc.python_method
    def register_sleep_handlers(self):
        log("register_sleep_handlers()")
        workspace          = NSWorkspace.sharedWorkspace()
        notificationCenter = workspace.notificationCenter()
        def add_observer(fn, val):
            notificationCenter.addObserver_selector_name_object_(self, fn, val, None)
        #NSWorkspaceWillPowerOffNotification
        add_observer(self.receiveSleepNotification_, NSWorkspaceWillSleepNotification)
        add_observer(self.receiveWakeNotification_, NSWorkspaceDidWakeNotification)
        add_observer(self.receiveWorkspaceChangeNotification_, NSWorkspaceActiveSpaceDidChangeNotification)

    @objc.signature('B@:#B')
    def applicationShouldHandleReopen_hasVisibleWindows_(self, ns_app, flag):
        log("applicationShouldHandleReopen_hasVisibleWindows%s", (ns_app, flag))
        self.delegate_cb("deiconify_callback")
        return True

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
                self.delegate_cb("wake_callback")
            else:
                self.delegate_cb("sleep_callback")
        except:
            workspacelog.error("Error querying workspace info", exc_info=True)

    def receiveSleepNotification_(self, aNotification):
        log("receiveSleepNotification_(%s) sleep_callback=%s", aNotification, self.sleep_callback)
        self.delegate_cb("sleep_callback")

    def receiveWakeNotification_(self, aNotification):
        log("receiveWakeNotification_(%s)", aNotification)
        self.delegate_cb("wake_callback")

    @objc.python_method
    def delegate_cb(self, name):
        #find the named callback and call it
        callback = getattr(self, name, None)
        log("delegate_cb(%s)=%s", name, callback)
        if callback:
            try:
                callback()
            except:
                log.error("Error in %s callback %s", name, callback, exc_info=True)


def disable_focus_workaround():
    NSApp.activateIgnoringOtherApps_(False)
def enable_focus_workaround():
    NSApp.activateIgnoringOtherApps_(True)

class ClientExtras(object):
    def __init__(self, client, opts):
        if OSX_FOCUS_WORKAROUND:
            def first_ui_received(*_args):
                enable_focus_workaround()
                client.timeout_add(OSX_FOCUS_WORKAROUND, disable_focus_workaround)
            client.connect("first-ui-received", first_ui_received)
        swap_keys = opts and opts.swap_keys
        log("ClientExtras.__init__(%s, %s) swap_keys=%s", client, opts, swap_keys)
        self.client = client
        self.event_loop_started = False
        if opts and client:
            log("setting swap_keys=%s using %s", swap_keys, client.keyboard_helper)
            if client.keyboard_helper and client.keyboard_helper.keyboard:
                log("%s.swap_keys=%s", client.keyboard_helper.keyboard, swap_keys)
                client.keyboard_helper.keyboard.swap_keys = swap_keys

    def cleanup(self):
        self.client = None

    def ready(self):
        try:
            self.setup_event_listener()
        except:
            log.error("Error setting up OSX event listener", exc_info=True)

    def setup_event_listener(self):
        log("setup_event_listener()")
        if NSObject is object:
            log.warn("NSObject is missing, not setting up OSX event listener")
            return
        self.shared_app = None
        self.delegate = None
        self.shared_app = NSApplication.sharedApplication()

        self.delegate = Delegate.alloc().init()
        self.delegate.retain()
        if self.client:
            self.delegate.sleep_callback = self.client.suspend
            self.delegate.wake_callback = self.client.resume
            self.delegate.deiconify_callback = self.client.deiconify_windows
        self.shared_app.setDelegate_(self.delegate)
        log("setup_event_listener() the application delegate has been registered")


    def run(self):
        #this is for running standalone
        log("starting console event loop")
        self.event_loop_started = True
        import PyObjCTools.AppHelper as AppHelper   #@UnresolvedImport
        AppHelper.runConsoleEventLoop(installInterrupt=True)
        #when running from the GTK main loop, we rely on another part of the code
        #to run the event loop for us

    def stop(self):
        if self.event_loop_started:
            self.event_loop_started = False
            import PyObjCTools.AppHelper as AppHelper   #@UnresolvedImport
            AppHelper.stopEventLoop()


def main():
    from xpra.platform import program_context
    with program_context("OSX Extras"):
        log.enable_debug()
        ce = ClientExtras(None, None)
        ce.run()


if __name__ == "__main__":
    main()
