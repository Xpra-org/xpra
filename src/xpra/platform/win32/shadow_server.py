# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2012-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import ctypes

from ctypes.wintypes import RECT, POINT

from xpra.log import Logger
from xpra.util import envbool, prettify_plug_name
from xpra.platform.win32.constants import DI_NORMAL, CURSOR_SHOWING
log = Logger("shadow", "win32")
traylog = Logger("tray")
shapelog = Logger("shape")
cursorlog = Logger("cursor")
netlog = Logger("network")

from collections import namedtuple
from xpra.util import XPRA_APP_ID, XPRA_IDLE_NOTIFICATION_ID
from xpra.scripts.config import InitException
from xpra.server.gtk_server_base import GTKServerBase
from xpra.server.shadow.gtk_shadow_server_base import GTKShadowServerBase
from xpra.server.shadow.root_window_model import RootWindowModel
from xpra.platform.win32 import constants as win32con
from xpra.platform.win32.gui import get_desktop_name, get_fixed_cursor_size
from xpra.platform.win32.keyboard_config import KeyboardConfig, fake_key
from xpra.platform.win32.win32_events import get_win32_event_listener, POWER_EVENTS
from xpra.platform.win32.gdi_screen_capture import GDICapture

#user32:
from xpra.platform.win32.common import (EnumWindows, EnumWindowsProc, FindWindowA, IsWindowVisible,
                                        GetWindowTextLengthW, GetWindowTextW,
                                        GetWindowRect,
                                        GetWindowThreadProcessId,
                                        GetSystemMetrics,
                                        SetPhysicalCursorPos,
                                        GetPhysicalCursorPos,
                                        GetCursorInfo, CURSORINFO,
                                        GetDC, CreateCompatibleDC, CreateCompatibleBitmap, SelectObject, DeleteObject, ReleaseDC, DeleteDC, DrawIconEx, GetBitmapBits,
                                        GetIconInfo, ICONINFO,
                                        mouse_event)

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
SHADOW_NVFBC = envbool("XPRA_SHADOW_NVFBC", True)
SHADOW_GDI = envbool("XPRA_SHADOW_GDI", True)
NVFBC_CUDA = envbool("XPRA_NVFBC_CUDA", True)


def get_cursor_data(hCursor):
    w, h = get_fixed_cursor_size()
    x, y = 0, 0
    dc = None
    memdc = None
    bitmap = None
    old_handle = None
    pixels = None
    try:
        dc = GetDC(None)
        assert dc, "failed to get a drawing context"
        memdc = CreateCompatibleDC(dc)
        assert memdc, "failed to get a compatible drawing context from %s" % dc
        bitmap = CreateCompatibleBitmap(dc, w, h)
        assert bitmap, "failed to get a compatible bitmap from %s" % dc
        old_handle = SelectObject(memdc, bitmap)
        ii = ICONINFO()
        if not GetIconInfo(hCursor, ctypes.byref(ii)):
            raise WindowsError()
        x = ii.xHotspot
        y = ii.yHotspot
        cursorlog("get_cursor_data(%#x) hotspot at %ix%i", hCursor, x, y)
        #if not DrawIcon(memdc, 0, 0, hCursor):
        if not DrawIconEx(memdc, 0, 0, hCursor, w, h, 0, 0, DI_NORMAL):
            raise WindowsError()
        Bpp = 4
        rowstride = w*Bpp
        buf_size = rowstride*h
        buf = ctypes.create_string_buffer(b"", buf_size)
        r = GetBitmapBits(bitmap, buf_size, ctypes.byref(buf))
        cursorlog("get_cursor_data(%#x) GetBitmapBits(%#x, %#x, %#x)=%i", hCursor, bitmap, buf_size, ctypes.addressof(buf), r)
        if r==0:
            cursorlog.error("Error: failed to copy screen bitmap data")
        elif r!=buf_size:
            cursorlog.warn("Warning: invalid cursor buffer size, got %i bytes but expected %i", r, buf_size)
        else:
            pixels = buf.raw
    except Exception as e:
        cursorlog("get_cursor_data(%#x)", hCursor, exc_info=True)
        cursorlog.error("Error: failed to grab cursor:")
        cursorlog.error(" %s", e)
    finally:
        if old_handle:
            SelectObject(memdc, old_handle)
        if bitmap:
            DeleteObject(bitmap)
        if memdc:
            DeleteDC(memdc)
        if dc:
            ReleaseDC(None, dc)
    return [w, h, x, y, hCursor, pixels, ""]


def init_capture(pixel_depth=32):
    capture = None
    if SHADOW_NVFBC:
        try:
            from xpra.codecs.nvfbc.fbc_capture_win import init_nvfbc_library
        except ImportError:
            log("NvFBC capture is not available", exc_info=True)
        else:
            try:
                if init_nvfbc_library():
                    log("NVFBC_CUDA=%s", NVFBC_CUDA)
                    pixel_format = {
                        24  : "RGB",
                        32  : "BGRX",
                        30  : "r210",
                        }[pixel_depth]
                    if NVFBC_CUDA:
                        from xpra.codecs.nvfbc.fbc_capture_win import NvFBC_CUDACapture
                        capture = NvFBC_CUDACapture()
                    else:
                        from xpra.codecs.nvfbc.fbc_capture_win import NvFBC_SysCapture
                        capture = NvFBC_SysCapture()
                    capture.init_context(-1, -1, pixel_format)
            except Exception as e:
                log("NvFBC_Capture", exc_info=True)
                log.warn("Warning: NvFBC screen capture initialization failed:")
                log.warn(" %s", e)
                log.warn(" using the slower GDI capture code")
                del e
    if not capture:
        if SHADOW_GDI:
            capture = GDICapture()
        if not capture:
            raise Exception("no screen capture methods enabled (GDI capture is disabled)")
    log("init_capture()=%s", capture)
    return capture


class Win32RootWindowModel(RootWindowModel):

    def __init__(self, root, capture):
        RootWindowModel.__init__(self, root, capture)
        log("Win32RootWindowModel(%s, %s) SEAMLESS=%s", root, capture, SEAMLESS)
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
        PSpec = namedtuple("PSpec", "name")
        pspec = PSpec(name="shape")
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
        taskbar = FindWindowA("Shell_TrayWnd", None)
        l("taskbar window=%#x", taskbar)
        ourpid = os.getpid()
        l("our pid=%i", ourpid)
        rectangles = []
        def enum_windows_cb(hwnd, lparam):
            if not IsWindowVisible(hwnd):
                l("skipped invisible window %#x", hwnd)
                return True
            pid = ctypes.c_int()
            thread_id = GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid==ourpid:
                l("skipped our own window %#x", hwnd)
                return True
            #skipping IsWindowEnabled check
            length = GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length+1)
            if GetWindowTextW(hwnd, buf, length+1)>0:
                window_title = buf.value
            else:
                window_title = ''
            l("get_shape_rectangles() found window '%s' with pid=%i and thread id=%i", window_title, pid, thread_id)
            rect = RECT()
            if GetWindowRect(hwnd, ctypes.byref(rect))==0:
                l("GetWindowRect failure")
                return True
            left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
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
            rectangles.append((left, top, w, h))
            return True
        EnumWindows(EnumWindowsProc(enum_windows_cb))
        l("get_shape_rectangles()=%s", rectangles)
        return sorted(rectangles)

    def get_property(self, prop):
        if prop=="shape":
            assert SEAMLESS
            shape = {"Bounding.rectangles" : self.rectangles}
            #provide clip rectangle? (based on workspace area?)
            return shape
        return RootWindowModel.get_property(self, prop)

    def get_dimensions(self):
        return self.get_root_window_size()

    def get_root_window_size(self):
        w = GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
        h = GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
        return w, h


class ShadowServer(GTKShadowServerBase):

    def __init__(self):
        GTKShadowServerBase.__init__(self)
        self.keycodes = {}
        self.cursor_handle = None
        self.cursor_data = None
        if GetSystemMetrics(win32con.SM_SAMEDISPLAYFORMAT)==0:
            raise InitException("all the monitors must use the same display format")
        el = get_win32_event_listener()
        from xpra.net.bytestreams import set_continue_wait
        #on win32, we want to wait just a little while,
        #to prevent servers spinning wildly on non-blocking sockets:
        set_continue_wait(5)
        #TODO: deal with those messages?
        el.add_event_callback(win32con.WM_POWERBROADCAST,   self.power_broadcast_event)
        #el.add_event_callback(WM_WTSSESSION_CHANGE,         self.session_change_event)
        #these are bound to callbacks in the client,
        #but on the server we just ignore them:
        el.ignore_events.update({
                                 win32con.WM_ACTIVATEAPP        : "WM_ACTIVATEAPP",
                                 win32con.WM_MOVE               : "WM_MOVE",
                                 win32con.WM_INPUTLANGCHANGE    : "WM_INPUTLANGCHANGE",
                                 win32con.WM_WININICHANGE       : "WM_WININICHANGE",
                                 })
        #non-blocking server sockets (TCP and named pipes):
        from xpra.net.bytestreams import CONTINUE_ERRNO
        import errno
        CONTINUE_ERRNO[errno.WSAEWOULDBLOCK] = "WSAEWOULDBLOCK"     #@UndefinedVariable

    def init(self, opts):
        self.pixel_depth = int(opts.pixel_depth) or 32
        if self.pixel_depth not in (24, 30, 32):
            raise InitException("unsupported pixel depth: %s" % self.pixel_depth)
        GTKShadowServerBase.init(self, opts)


    def power_broadcast_event(self, wParam, lParam):
        log("WM_POWERBROADCAST: %s/%s", POWER_EVENTS.get(wParam, wParam), lParam)
        if wParam==win32con.PBT_APMSUSPEND:
            log.info("WM_POWERBROADCAST: PBT_APMSUSPEND")
            for source in self._server_sources.values():
                source.may_notify(XPRA_IDLE_NOTIFICATION_ID, "Server Suspending",
                                  "This Xpra server is going to suspend,\nthe connection is likely to be interrupted soon.", expire_timeout=10*1000, icon_name="shutdown")
        elif wParam==win32con.PBT_APMRESUMEAUTOMATIC:
            log.info("WM_POWERBROADCAST: PBT_APMRESUMEAUTOMATIC")


    def guess_session_name(self, _procs):
        desktop_name = get_desktop_name()
        if desktop_name:
            self.session_name = desktop_name


    def print_screen_info(self):
        w, h = self.get_root_window_size()
        try:
            display = prettify_plug_name(self.root.get_screen().get_display().get_name())
        except:
            display = ""
        self.do_print_screen_info(display, w, h)


    def make_tray_widget(self):
        from xpra.platform.win32.win32_tray import Win32Tray
        return Win32Tray(self, XPRA_APP_ID, self.tray_menu, "Xpra Shadow Server", "server-notconnected", None, self.tray_click_callback, None, self.tray_exit_callback)


    def makeRootWindowModels(self):
        self.capture = init_capture(self.pixel_depth)
        return (Win32RootWindowModel(self.root, self.capture),)


    def refresh(self):
        v = GTKShadowServerBase.refresh(self)
        if v and SEAMLESS:
            for rwm in self._id_to_window.values():
                rwm.refresh_shape()
        log("refresh()=%s", v)
        return v

    def do_get_cursor_data(self):
        ci = CURSORINFO()
        ci.cbSize = ctypes.sizeof(CURSORINFO)
        GetCursorInfo(ctypes.byref(ci))
        #cursorlog("GetCursorInfo handle=%#x, last handle=%#x", ci.hCursor or 0, self.cursor_handle or 0)
        if not (ci.flags & CURSOR_SHOWING):
            #cursorlog("do_get_cursor_data() cursor not shown")
            return None
        handle = int(ci.hCursor)
        if handle==self.cursor_handle and self.last_cursor_data:
            #cursorlog("do_get_cursor_data() cursor handle unchanged")
            return self.last_cursor_data
        self.cursor_handle = handle
        cd = get_cursor_data(handle)
        if not cd:
            cursorlog("do_get_cursor_data() no cursor data")
            return self.last_cursor_data
        w, h = get_fixed_cursor_size()
        return (
            [ci.ptScreenPos.x, ci.ptScreenPos.y]+cd,
            ((w,h), [(w,h), ]),
            )

    def get_pointer_position(self):
        pos = POINT()
        GetPhysicalCursorPos(ctypes.byref(pos))
        return pos.x, pos.y

    def do_process_mouse_common(self, proto, wid, pointer, *_args):
        #adjust pointer position for offset in client:
        try:
            x, y = pointer
            SetPhysicalCursorPos(x, y)
        except Exception as e:
            log("SetPhysicalCursorPos%s failed", pointer, exc_info=True)
            log.error("Error: failed to move the cursor:")
            log.error(" %s", e)

    def get_keyboard_config(self, props):
        return KeyboardConfig()

    def fake_key(self, keycode, press):
        fake_key(keycode, press)

    def do_process_button_action(self, proto, wid, button, pressed, pointer, modifiers, *args):
        self._update_modifiers(proto, wid, modifiers)
        pointer = self._process_mouse_common(proto, wid, pointer)
        self._server_sources.get(proto).user_event()
        self.button_action(pointer, button, pressed, -1, *args)

    def button_action(self, pointer, button, pressed, deviceid=-1, *args):
        event = BUTTON_EVENTS.get((button, pressed))
        if event is None:
            log.warn("no matching event found for button=%s, pressed=%s", button, pressed)
            return
        elif event is NOEVENT:
            return
        dwFlags, dwData = event
        x, y = pointer
        mouse_event(dwFlags, x, y, dwData, 0)

    def make_hello(self, source):
        capabilities = GTKServerBase.make_hello(self, source)
        capabilities["shadow"] = True
        capabilities["server_type"] = "Python/gtk2/win32-shadow"
        return capabilities

    def get_info(self, proto, *_args):
        info = GTKServerBase.get_info(self, proto)
        info.update(GTKShadowServerBase.get_info(self, proto))
        info.setdefault("features", {})["shadow"] = True
        info.setdefault("server", {
                                   "pixel-depth": self.pixel_depth,
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
