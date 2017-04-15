# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2012-2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time
import win32api         #@UnresolvedImport
import win32con         #@UnresolvedImport
import win32ui          #@UnresolvedImport
import win32gui         #@UnresolvedImport
import win32process     #@UnresolvedImport
import pywintypes       #@UnresolvedImport

from xpra.log import Logger
from xpra.util import AdHocStruct, envbool, prettify_plug_name
log = Logger("shadow", "win32")
traylog = Logger("tray")
shapelog = Logger("shape")
netlog = Logger("network")

from xpra.os_util import StringIOClass
from xpra.server.gtk_server_base import GTKServerBase
from xpra.server.shadow.gtk_shadow_server_base import GTKShadowServerBase
from xpra.server.shadow.root_window_model import RootWindowModel
from xpra.platform.win32.keyboard_config import KeyboardConfig, fake_key
from xpra.platform.win32.gui import get_virtualscreenmetrics
from xpra.platform.win32.namedpipes.connection import NamedPipeConnection
from xpra.platform.win32.win32_events import get_win32_event_listener
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

SEAMLESS = envbool("XPRA_WIN32_SEAMLESS", False)
DISABLE_DWM_COMPOSITION = True
#no composition on XP, don't bother trying:
try:
    from sys import getwindowsversion       #@UnresolvedImport
    if getwindowsversion().major<6:
        DISABLE_DWM_COMPOSITION = False
except:
    pass
DISABLE_DWM_COMPOSITION = envbool("XPRA_DISABLE_DWM_COMPOSITION", DISABLE_DWM_COMPOSITION)

DWM_EC_DISABLECOMPOSITION = 0
DWM_EC_ENABLECOMPOSITION = 1
def set_dwm_composition(value=DWM_EC_DISABLECOMPOSITION):
    try:
        from ctypes import windll
        windll.dwmapi.DwmEnableComposition(value)
        log("DwmEnableComposition(%s) succeeded", value)
        return True
    except Exception as e:
        log.error("Error: cannot change dwm composition:")
        log.error(" %s", e)
        return False


class Win32RootWindowModel(RootWindowModel):

    def __init__(self, root):
        RootWindowModel.__init__(self, root)
        self.metrics = None
        self.ddc, self.cdc, self.memdc, self.bitmap = None, None, None, None
        self.disabled_dwm_composition = DISABLE_DWM_COMPOSITION and set_dwm_composition(DWM_EC_DISABLECOMPOSITION)
        if SEAMLESS:
            self.property_names.append("shape")
            self.dynamic_property_names.append("shape")
            self.rectangles = self.get_shape_rectangles(logit=True)
            self.shape_notify = []

    def cleanup(self):
        if self.disabled_dwm_composition:
            set_dwm_composition(DWM_EC_ENABLECOMPOSITION)

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
        if logit or envbool("XPRA_SHAPE_DEBUG", False):
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
            try:
                self.memdc.BitBlt((0, 0), (width, height), self.cdc, (x, y), win32con.SRCCOPY)
            except win32ui.error as e:
                log.error("Error: cannot capture screen")
                log("win32ui.error: %s", e)
                return None
            bitblt_time = time.time()
            log("get_image BitBlt took %ims", (bitblt_time-select_time)*1000)
            pixels = self.bitmap.GetBitmapBits(True)
            log("get_image GetBitmapBits took %ims", (time.time()-bitblt_time)*1000)
        finally:
            pass
        assert pixels, "no pixels returned from GetBitmapBits"
        v = ImageWrapper(x, y, width, height, pixels, "BGRX", 24, width*4, planes=ImageWrapper.PACKED, thread_safe=True)
        if logger==None:
            logger = log
        log("get_image%s=%s took %ims", (x, y, width, height), v, (time.time()-start)*1000)
        return v

    def take_screenshot(self):
        from PIL import Image               #@UnresolvedImport
        x, y, w, h = get_virtualscreenmetrics()
        image = self.get_image(x, y, w, h)
        if not image:
            return None
        assert image.get_width()==w and image.get_height()==h
        assert image.get_pixel_format()=="BGRX"
        img = Image.frombuffer("RGB", (w, h), image.get_pixels(), "raw", "BGRX", 0, 1)
        out = StringIOClass()
        img.save(out, format="PNG")
        screenshot = (img.width, img.height, "png", img.width*3, out.getvalue())
        out.close()
        return screenshot


class ShadowServer(GTKShadowServerBase):

    def __init__(self):
        GTKShadowServerBase.__init__(self)
        self.keycodes = {}
        el = get_win32_event_listener()
        from xpra.net.bytestreams import set_continue_wait
        #on win32, we want to wait just a little while,
        #to prevent servers spinning wildly on non-blocking sockets:
        set_continue_wait(5)
        #TODO: deal with those messages?
        #el.add_event_callback(win32con.WM_POWERBROADCAST,   self.power_broadcast_event)
        #el.add_event_callback(WM_WTSSESSION_CHANGE,         self.session_change_event)
        #these are bound to callbacks in the client,
        #but on the server we just ignore them:
        el.ignore_events.update({
                                 win32con.WM_ACTIVATEAPP        : "WM_ACTIVATEAPP",
                                 win32con.WM_MOVE               : "WM_MOVE",
                                 win32con.WM_INPUTLANGCHANGE    : "WM_INPUTLANGCHANGE",
                                 win32con.WM_WININICHANGE       : "WM_WININICHANGE",
                                 })


    def print_screen_info(self):
        w, h = self.root.get_size()
        try:
            display = prettify_plug_name(self.root.get_screen().get_display().get_name())
        except:
            display = ""
        self.do_print_screen_info(display, w, h)


    def add_listen_socket(self, socktype, sock):
        log("add_listen_socket(%s, %s)", socktype, sock)
        if socktype=="named-pipe":
            #named pipe listener uses a thread:
            sock.new_connection_cb = self._new_connection
            self.socket_types[sock] = socktype
            sock.start()
        else:
            GTKServerBase.add_listen_socket(self, socktype, sock)

    def _new_connection(self, listener, *args):
        socktype = self.socket_types.get(listener)
        log("_new_connection(%s) socktype=%s", listener, socktype)
        if socktype!="named-pipe":
            return GTKServerBase._new_connection(self, listener)
        pipe_handle = args[0]
        conn = NamedPipeConnection(listener.pipe_name, pipe_handle)
        netlog.info("New %s connection received on %s", socktype, conn.target)
        return self.make_protocol(socktype, conn, frominfo=conn.target)


    def make_tray_widget(self):
        from xpra.platform.win32.win32_tray import Win32Tray
        return Win32Tray(self, self.tray_menu, "Xpra Shadow Server", "server-notconnected", None, self.tray_click_callback, None, self.tray_exit_callback)


    def makeRootWindowModel(self):
        return Win32RootWindowModel(self.root)


    def refresh(self):
        v = GTKShadowServerBase.refresh(self)
        if v and SEAMLESS:
            self.root_window_model.refresh_shape()
        log("refresh()=%s", v)
        return v

    def do_process_mouse_common(self, proto, wid, pointer):
        #adjust pointer position for offset in client:
        try:
            win32api.SetCursorPos(pointer)
        except pywintypes.error as e:
            log.error("Error: failed to move the cursor:")
            log("pywintypes.error: %s", e[2])

    def get_keyboard_config(self, props):
        return KeyboardConfig()

    def fake_key(self, keycode, press):
        fake_key(keycode, press)

    def do_process_button_action(self, proto, wid, button, pressed, pointer, modifiers, *args):
        self._update_modifiers(proto, wid, modifiers)
        x, y = self._process_mouse_common(proto, wid, pointer)
        self._server_sources.get(proto).user_event()
        event = BUTTON_EVENTS.get((button, pressed))
        if event is None:
            log.warn("no matching event found for button=%s, pressed=%s", button, pressed)
            return
        elif event is NOEVENT:
            return
        dwFlags, dwData = event
        win32api.mouse_event(dwFlags, x, y, dwData, 0)

    def make_hello(self, source):
        capabilities = GTKServerBase.make_hello(self, source)
        capabilities["shadow"] = True
        capabilities["server_type"] = "Python/gtk2/win32-shadow"
        return capabilities

    def get_info(self, proto):
        info = GTKServerBase.get_info(self, proto)
        info.setdefault("features", {})["shadow"] = True
        info.setdefault("server", {
                                   "type"       : "Python/gtk2/win32-shadow",
                                   "tray"       : self.tray,
                                   "tray-icon"  : self.tray_icon or ""
                                   })
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
