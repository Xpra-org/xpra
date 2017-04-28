# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2012-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import ctypes

from ctypes.wintypes import RECT

from xpra.log import Logger
from xpra.util import AdHocStruct, envbool, prettify_plug_name
log = Logger("shadow", "win32")
traylog = Logger("tray")
shapelog = Logger("shape")
netlog = Logger("network")

from xpra.util import XPRA_APP_ID
from xpra.scripts.config import InitException
from xpra.codecs.codec_constants import CodecStateException, TransientCodecException
from xpra.server.gtk_server_base import GTKServerBase
from xpra.server.shadow.gtk_shadow_server_base import GTKShadowServerBase
from xpra.server.shadow.root_window_model import RootWindowModel
from xpra.platform.win32 import constants as win32con
from xpra.platform.win32.keyboard_config import KeyboardConfig, fake_key
from xpra.platform.win32.namedpipes.connection import NamedPipeConnection
from xpra.platform.win32.win32_events import get_win32_event_listener
from xpra.platform.win32.gdi_screen_capture import GDICapture

#user32:
from xpra.platform.win32.common import (EnumWindows, EnumWindowsProc, FindWindowA, IsWindowVisible,
                                        GetWindowTextLengthW, GetWindowTextW,
                                        GetWindowRect,
                                        GetWindowThreadProcessId,
                                        GetSystemMetrics,
                                        SetCursorPos,
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


class Win32RootWindowModel(RootWindowModel):

    def __init__(self, root, pixel_depth=32):
        RootWindowModel.__init__(self, root)
        self.pixel_depth = pixel_depth
        self.capture = self.init_capture()
        log("Win32RootWindowModel(%s, %i) capture=%s", root, pixel_depth, self.capture)
        if SEAMLESS:
            self.property_names.append("shape")
            self.dynamic_property_names.append("shape")
            self.rectangles = self.get_shape_rectangles(logit=True)
            self.shape_notify = []

    def init_capture(self):
        if SHADOW_NVFBC:
            try:
                from xpra.codecs.nvfbc.fbc_capture import init_nvfbc_library
            except ImportError as e:
                log("NvFBC capture is not available", exc_info=True)
            else:
                try:
                    if init_nvfbc_library():
                        log.info("NVFBC_CUDA=%s", NVFBC_CUDA)
                        if NVFBC_CUDA:
                            from xpra.codecs.nvfbc.fbc_capture import NvFBC_CUDACapture
                            capture = NvFBC_CUDACapture()
                            capture.init_context()
                        else:
                            from xpra.codecs.nvfbc.fbc_capture import NvFBC_SysCapture
                            pixel_format = {
                                24  : "RGB",
                                32  : "BGRA",
                                30  : "r210",
                                }[self.pixel_depth]
                            capture = NvFBC_SysCapture()
                            capture.init_context(-1, -1, pixel_format)
                        return capture
                except Exception as e:
                    log("NvFBC_Capture", exc_info=True)
                    log.warn("Warning: NvFBC screen capture initialization failed:")
                    log.warn(" %s", e)
                    log.warn(" using the slower GDI capture code")
        if SHADOW_GDI:
            return GDICapture()
        raise Exception("no screen capture methods enabled (GDI capture is disabled)")

    def cleanup(self):
        RootWindowModel.cleanup(self)
        self.cleanup_capture()

    def cleanup_capture(self):
        c = self.capture
        if c:
            self.capture = None
            c.clean()

    def get_info(self):
        c = self.capture
        info = {}
        if c:
            info["capture"] = c.get_info()
        info["pixel-depth"] = self.pixel_depth
        return info


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


    def get_root_window_size(self):
        w = GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
        h = GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
        return w, h

    def get_image(self, x, y, width, height, logger=None):
        try:
            return self.capture.get_image(x, y, width, height)
        except CodecStateException as e:
            #maybe we should exit here?
            log.warn("Warning: %s", e)
            self.cleanup_capture()
            self.init_capture()
            return None
        except TransientCodecException as e:
            log.warn("Warning: %s", e)
            self.cleanup_capture()
            self.init_capture()
            return None

    def take_screenshot(self):
        return self.capture.take_screenshot()


class ShadowServer(GTKShadowServerBase):

    def __init__(self):
        GTKShadowServerBase.__init__(self)
        self.keycodes = {}
        if GetSystemMetrics(win32con.SM_SAMEDISPLAYFORMAT)==0:
            raise InitException("all the monitors must use the same display format")
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

    def init(self, opts):
        self.pixel_depth = int(opts.pixel_depth)
        assert self.pixel_depth in (24, 30, 32), "unsupported pixel depth: %s" % self.pixel_depth
        GTKShadowServerBase.init(self, opts)


    def print_screen_info(self):
        w, h = self.root.get_size()
        try:
            display = prettify_plug_name(self.root.get_screen().get_display().get_name())
        except:
            display = ""
        self.do_print_screen_info(display, w, h)


    def add_listen_socket(self, socktype, sock):
        netlog("add_listen_socket(%s, %s)", socktype, sock)
        if socktype=="named-pipe":
            #named pipe listener uses a thread:
            sock.new_connection_cb = self._new_connection
            self.socket_types[sock] = socktype
            sock.start()
        else:
            GTKServerBase.add_listen_socket(self, socktype, sock)

    def _new_connection(self, listener, *args):
        socktype = self.socket_types.get(listener)
        netlog("_new_connection(%s) socktype=%s", listener, socktype)
        if socktype!="named-pipe":
            return GTKServerBase._new_connection(self, listener)
        pipe_handle = args[0]
        conn = NamedPipeConnection(listener.pipe_name, pipe_handle)
        netlog.info("New %s connection received on %s", socktype, conn.target)
        return self.make_protocol(socktype, conn, frominfo=conn.target)


    def make_tray_widget(self):
        from xpra.platform.win32.win32_tray import Win32Tray
        return Win32Tray(self, XPRA_APP_ID, self.tray_menu, "Xpra Shadow Server", "server-notconnected", None, self.tray_click_callback, None, self.tray_exit_callback)


    def makeRootWindowModel(self):
        return Win32RootWindowModel(self.root, self.pixel_depth)


    def refresh(self):
        v = GTKShadowServerBase.refresh(self)
        if v and SEAMLESS:
            self.root_window_model.refresh_shape()
        log("refresh()=%s", v)
        return v

    def do_process_mouse_common(self, proto, wid, pointer):
        #adjust pointer position for offset in client:
        try:
            SetCursorPos(*pointer)
        except Exception as e:
            log("SetCursorPos%s failed", pointer, exc_info=True)
            log.error("Error: failed to move the cursor:")
            log.error(" %s", e)

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
        mouse_event(dwFlags, x, y, dwData, 0)

    def make_hello(self, source):
        capabilities = GTKServerBase.make_hello(self, source)
        capabilities["shadow"] = True
        capabilities["server_type"] = "Python/gtk2/win32-shadow"
        return capabilities

    def get_info(self, proto):
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
