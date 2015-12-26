# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2012-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time
import win32api         #@UnresolvedImport
import win32con         #@UnresolvedImport
import win32ui          #@UnresolvedImport
import win32gui         #@UnresolvedImport
import win32process     #@UnresolvedImport

from xpra.log import Logger
from xpra.util import AdHocStruct
log = Logger("shadow", "win32")
traylog = Logger("tray")
shapelog = Logger("shape")

from xpra.os_util import StringIOClass
from xpra.server.gtk_server_base import GTKServerBase
from xpra.server.shadow.shadow_server_base import ShadowServerBase
from xpra.server.shadow.root_window_model import RootWindowModel
from xpra.platform.win32.keyboard_config import KeyboardConfig, fake_key
from xpra.platform.win32.gui import get_virtualscreenmetrics
from xpra.codecs.image_wrapper import ImageWrapper

NOEVENT = object()
BUTTON_EVENTS = {
                 #(button,up-or-down)  : win-event-name
                 (1, True)  : (win32con.MOUSEEVENTF_LEFTDOWN,   0),
                 (1, False) : (win32con.MOUSEEVENTF_LEFTUP,     0),
                 (2, True)  : (win32con.MOUSEEVENTF_MIDDLEDOWN, 0),
                 (2, False) : (win32con.MOUSEEVENTF_MIDDLEUP,   0),
                 (3, True)  : (win32con.MOUSEEVENTF_RIGHTDOWN,  0),
                 (3, False) : (win32con.MOUSEEVENTF_RIGHTUP,    0),
                 (4, True)  : (win32con.MOUSEEVENTF_WHEEL,      win32con.WHEEL_DELTA),
                 (4, False) : NOEVENT,
                 (5, True)  : (win32con.MOUSEEVENTF_WHEEL,      -win32con.WHEEL_DELTA),
                 (5, False) : NOEVENT,
                 }

SEAMLESS = os.environ.get("XPRA_WIN32_SEAMLESS", "0")=="1"


class Win32RootWindowModel(RootWindowModel):

    def __init__(self, root):
        RootWindowModel.__init__(self, root)
        self.metrics = None
        self.ddc, self.cdc, self.memdc, self.bitmap = None, None, None, None
        if SEAMLESS:
            self.property_names.append("shape")
            self.dynamic_property_names.append("shape")
            self.rectangles = self.get_shape_rectangles(logit=True)
            self.shape_notify = []

    def refresh_shape(self):
        rectangles = self.get_shape_rectangles()
        if rectangles==self.rectangles:
            return  #unchanged
        self.rectangles = rectangles
        shapelog("refresh_shape() sending notify for updated rectangles: %s", rectangles)
        #notify listeners:
        pspec = AdHocStruct()
        pspec.name = "shape"
        for cb, args in self.shape_notify:
            shapelog("refresh_shape() notifying: %s", cb)
            try:
                cb(self, pspec, *args)
            except:
                shapelog.error("error in shape notify callback %s", cb, exc_info=True)

    def connect(self, signal, cb, *args):
        if signal=="notify::shape":
            self.shape_notify.append((cb, args))
        else:
            RootWindowModel.connect(self, signal, cb, *args)

    def get_shape_rectangles(self, logit=False):
        #get the list of windows
        l = log
        if logit or os.environ.get("XPRA_SHAPE_DEBUG", "0")=="1":
            l = shapelog
        taskbar = win32gui.FindWindow("Shell_TrayWnd", None)
        l("taskbar window=%#x", taskbar)
        ourpid = os.getpid()
        l("our pid=%i", ourpid)
        def enum_windows_cb(hwnd, rects):
            if not win32gui.IsWindowVisible(hwnd):
                l("skipped invisible window %#x", hwnd)
                return True
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid==ourpid:
                l("skipped our own window %#x", hwnd)
                return True
            #skipping IsWindowEnabled check
            window_title = win32gui.GetWindowText(hwnd)
            l("get_shape_rectangles() found window '%s' with pid=%s", window_title, pid)
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            if right<0 or bottom<0:
                l("skipped offscreen window at %ix%i", right, bottom)
                return True
            if hwnd==taskbar:
                l("skipped taskbar")
                return True
            #dirty way:
            if window_title=='Program Manager':
                return True
            #this should be the proper way using GetTitleBarInfo (but does not seem to work)
            #import ctypes
            #from ctypes.windll.user32 import GetTitleBarInfo        #@UnresolvedImport
            #from ctypes.wintypes import (DWORD, RECT)
            #class TITLEBARINFO(ctypes.Structure):
            #    pass
            #TITLEBARINFO._fields_ = [
            #    ('cbSize', DWORD),
            #    ('rcTitleBar', RECT),
            #    ('rgstate', DWORD * 6),
            #]
            #ti = TITLEBARINFO()
            #ti.cbSize = ctypes.sizeof(ti)
            #GetTitleBarInfo(hwnd, ctypes.byref(ti))
            #if ti.rgstate[0] & win32con.STATE_SYSTEM_INVISIBLE:
            #    log("skipped system invisible window")
            #    return True
            w = right-left
            h = bottom-top
            l("shape(%s - %#x)=%s", window_title, hwnd, (left, top, w, h))
            if w<=0 and h<=0:
                l("skipped invalid window size: %ix%i", w, h)
                return True
            if left==-32000 and top==-32000:
                #there must be a better way of skipping those - I haven't found it
                l("skipped special window")
                return True
            #now clip rectangle:
            if left<0:
                left = 0
                w = right
            if top<0:
                top = 0
                h = bottom
            rects.append((left, top, w, h))
            return True
        rectangles = []
        win32gui.EnumWindows(enum_windows_cb, rectangles)
        l("get_shape_rectangles()=%s", rectangles)
        return sorted(rectangles)

    def get_property(self, prop):
        if prop=="shape":
            assert SEAMLESS
            shape = {"Bounding.rectangles" : self.rectangles}
            #provide clip rectangle? (based on workspace area?)
            return shape
        return RootWindowModel.get_property(self, prop)


    def get_root_window_size(self):
        w = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
        h = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
        return w, h

    def get_image(self, x, y, width, height, logger=None):
        start = time.time()
        desktop_wnd = win32gui.GetDesktopWindow()
        metrics = get_virtualscreenmetrics()
        if self.metrics is None or self.metrics!=metrics:
            #new metrics, start from scratch:
            self.metrics = metrics
            self.ddc, self.cdc, self.memdc, self.bitmap = None, None, None, None
        dx, dy, dw, dh = metrics
        #clamp rectangle requested to the virtual desktop size:
        if x<dx:
            width -= x-dx
            x = dx
        if y<dy:
            height -= y-dy
            y = dy
        if width>dw:
            width = dw
        if height>dh:
            height = dh
        try:
            if not self.ddc:
                self.ddc = win32gui.GetWindowDC(desktop_wnd)
                assert self.ddc, "cannot get a drawing context from the desktop window %s" % desktop_wnd
                self.cdc = win32ui.CreateDCFromHandle(self.ddc)
                assert self.cdc, "cannot get a compatible drawing context from the desktop drawing context %s" % self.ddc
                self.memdc = self.cdc.CreateCompatibleDC()
                self.bitmap = win32ui.CreateBitmap()
                self.bitmap.CreateCompatibleBitmap(self.cdc, width, height)
            self.memdc.SelectObject(self.bitmap)
            select_time = time.time()
            log("get_image up to SelectObject took %ims", (select_time-start)*1000)
            self.memdc.BitBlt((0, 0), (width, height), self.cdc, (x, y), win32con.SRCCOPY)
            bitblt_time = time.time()
            log("get_image BitBlt took %ims", (bitblt_time-select_time)*1000)
            pixels = self.bitmap.GetBitmapBits(True)
            log("get_image GetBitmapBits took %ims", (time.time()-bitblt_time)*1000)
        finally:
            pass
        assert pixels, "no pixels returned from GetBitmapBits"
        v = ImageWrapper(0, 0, width, height, pixels, "BGRX", 24, width*4, planes=ImageWrapper.PACKED, thread_safe=True)
        if logger==None:
            logger = log
        log("get_image%s=%s took %ims", (x, y, width, height), v, (time.time()-start)*1000)
        return v

    def take_screenshot(self):
        from PIL import Image               #@UnresolvedImport
        x, y, w, h = get_virtualscreenmetrics()
        image = self.get_image(x, y, w, h)
        assert image.get_width()==w and image.get_height()==h
        assert image.get_pixel_format()=="BGRX"
        img = Image.frombuffer("RGB", (w, h), image.get_pixels(), "raw", "BGRX", 0, 1)
        out = StringIOClass()
        img.save(out, format="PNG")
        screenshot = (img.width, img.height, "png", img.width*3, out.getvalue())
        out.close()
        return screenshot


class ShadowServer(ShadowServerBase, GTKServerBase):

    def __init__(self):
        #TODO: root should be a wrapper for the win32 system metrics bits?
        #(or even not bother passing root to ShadowServerBase?
        import gtk.gdk
        ShadowServerBase.__init__(self, gtk.gdk.get_default_root_window())
        GTKServerBase.__init__(self)
        self.keycodes = {}
        self.menu = None
        self.menu_shown = False
        self.tray_widget = None
        self.tray = False
        self.delay_tray = False
        self.tray_icon = None

    def init(self, opts):
        GTKServerBase.init(self, opts)
        self.tray = opts.tray
        self.delay_tray = opts.delay_tray
        self.tray_icon = opts.tray_icon or "xpra.ico"
        if self.tray:
            self.setup_tray()

    ############################################################################
    # system tray methods, mostly copied from the gtk client...
    # (most of these should probably be moved to a common location instead)

    def setup_tray(self):
        try:
            from xpra.gtk_common.gobject_compat import import_gtk
            gtk = import_gtk()
            from xpra.gtk_common.gtk_util import popup_menu_workaround
            #menu:
            self.menu = gtk.Menu()
            self.menu.set_title("Xpra Server")
            from xpra.gtk_common.about import about
            self.menu.append(self.menuitem("About Xpra", "information.png", None, about))
            self.menu.append(self.menuitem("Exit", "quit.png", None, self.quit))
            self.menu.append(self.menuitem("Close Menu", "close.png", None, self.close_menu))
            #maybe add: session info, clipboard, sharing, etc
            #control: disconnect clients
            self.menu.connect("deactivate", self.menu_deactivated)
            popup_menu_workaround(self.menu, self.close_menu)
            #tray:
            from xpra.platform.paths import get_icon_dir
            icon_filename = os.path.join(get_icon_dir(), self.tray_icon)
            from xpra.platform.win32.win32_NotifyIcon import win32NotifyIcon
            self.tray_widget = win32NotifyIcon("Xpra Server", None, self.click_callback, self.exit_callback)
            self.tray_widget.set_icon(icon_filename)
        except ImportError as e:
            traylog.warn("Warning: failed to load systemtray:")
            traylog.warn(" %s", e)
        except Exception as e:
            traylog.error("Error setting up system tray", exc_info=True)

    def menuitem(self, title, icon_name=None, tooltip=None, cb=None):
        """ Utility method for easily creating an ImageMenuItem """
        from xpra.gtk_common.gtk_util import menuitem
        image = None
        if icon_name:
            from xpra.platform.gui import get_icon_size
            icon_size = get_icon_size()
            image = self.get_image(icon_name, icon_size)
        return menuitem(title, image, tooltip, cb)

    def get_pixbuf(self, icon_name):
        from xpra.platform.paths import get_icon_filename
        from xpra.gtk_common.gtk_util import pixbuf_new_from_file
        try:
            if not icon_name:
                traylog("get_pixbuf(%s)=None", icon_name)
                return None
            icon_filename = get_icon_filename(icon_name)
            traylog("get_pixbuf(%s) icon_filename=%s", icon_name, icon_filename)
            if icon_filename:
                return pixbuf_new_from_file(icon_filename)
        except:
            traylog.error("get_pixbuf(%s)", icon_name, exc_info=True)
        return  None

    def get_image(self, icon_name, size=None):
        from xpra.gtk_common.gtk_util import scaled_image
        try:
            pixbuf = self.get_pixbuf(icon_name)
            traylog("get_image(%s, %s) pixbuf=%s", icon_name, size, pixbuf)
            if not pixbuf:
                return  None
            return scaled_image(pixbuf, size)
        except:
            traylog.error("get_image(%s, %s)", icon_name, size, exc_info=True)
            return  None


    def menu_deactivated(self, *args):
        self.menu_shown = False

    def click_callback(self, button, pressed):
        traylog("click_callback(%s, %s)", button, pressed)
        if pressed:
            self.close_menu()
        self.menu.popup(None, None, None, button, 0)
        self.menu_shown = True

    def exit_callback(self, *args):
        self.quit(False)

    def close_menu(self, *args):
        if self.menu_shown:
            self.menu.popdown()
            self.menu_shown = False

    def cleanup(self):
        GTKServerBase.cleanup(self)
        if self.tray_widget:
            self.tray_widget.close()
            self.tray_widget = None

    ############################################################################


    def makeRootWindowModel(self):
        return Win32RootWindowModel(self.root)

    def refresh(self):
        v = ShadowServerBase.refresh(self)
        if v and SEAMLESS:
            self.root_window_model.refresh_shape()
        log("refresh()=%s", v)
        return v

    def _process_mouse_common(self, proto, wid, pointer, modifiers):
        #adjust pointer position for offset in client:
        x, y = pointer
        wx, wy = self.mapped_at[:2]
        rx, ry = x-wx, y-wy
        win32api.SetCursorPos((rx, ry))

    def get_keyboard_config(self, props):
        return KeyboardConfig()

    def fake_key(self, keycode, press):
        fake_key(keycode, press)

    def _process_button_action(self, proto, packet):
        wid, button, pressed, pointer, modifiers = packet[1:6]
        self._process_mouse_common(proto, wid, pointer, modifiers)
        self._server_sources.get(proto).user_event()
        event = BUTTON_EVENTS.get((button, pressed))
        if event is None:
            log.warn("no matching event found for button=%s, pressed=%s", button, pressed)
            return
        elif event is NOEVENT:
            return
        x, y = pointer
        dwFlags, dwData = event
        win32api.mouse_event(dwFlags, x, y, dwData, 0)

    def make_hello(self, source):
        capabilities = GTKServerBase.make_hello(self, source)
        capabilities["shadow"] = True
        capabilities["server_type"] = "Python/gtk2/win32-shadow"
        return capabilities

    def get_info(self, proto):
        info = GTKServerBase.get_info(self, proto)
        info["features.shadow"] = True
        info["server.type"] = "Python/gtk2/win32-shadow"
        info["server.tray"] = self.tray
        info["server.tray-icon"] = self.tray_icon or ""
        return info


def main():
    from xpra.platform import program_context
    with program_context("Shadow-Test", "Shadow Server Screen Capture Test"):
        rwm = Win32RootWindowModel(None)
        pngdata = rwm.take_screenshot()
        FILENAME = "screenshot.png"
        with open(FILENAME , "wb") as f:
            f.write(pngdata[4])
        print("saved screenshot as %s" % FILENAME)


if __name__ == "__main__":
    main()
