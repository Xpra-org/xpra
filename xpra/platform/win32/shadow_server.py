# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import re
from time import monotonic
from typing import Any
from collections.abc import Sequence, Callable
from ctypes import create_unicode_buffer, sizeof, byref, c_ulong
from ctypes.wintypes import RECT, POINT, BYTE

from xpra.util.screen import prettify_plug_name
from xpra.util.str_fn import csv
from xpra.util.env import envbool
from xpra.util.system import is_VirtualBox
from xpra.common import XPRA_APP_ID, NotificationID
from xpra.scripts.config import InitException
from xpra.server.gtk_server import GTKServerBase
from xpra.server.shadow.shadow_server_base import try_setup_capture
from xpra.server.shadow.gtk_root_window_model import GTKImageCapture
from xpra.server.shadow.gtk_shadow_server_base import GTKShadowServerBase
from xpra.server.shadow.root_window_model import RootWindowModel
from xpra.platform.win32 import constants as win32con
from xpra.platform.win32.gui import get_desktop_name, get_fixed_cursor_size
from xpra.platform.win32.keyboard_config import KeyboardConfig, fake_key
from xpra.platform.win32.events import get_win32_event_listener, POWER_EVENTS
from xpra.platform.win32.shadow_cursor import get_cursor_data
from xpra.platform.win32.gdi_screen_capture import GDICapture
from xpra.log import Logger

# user32:
from xpra.platform.win32.common import (
    EnumWindows, EnumWindowsProc, FindWindowA, IsWindowVisible,
    GetWindowTextLengthW, GetWindowTextW,
    GetWindowRect,
    GetWindowThreadProcessId,
    GetSystemMetrics,
    SetPhysicalCursorPos, GetPhysicalCursorPos, GetCursorInfo, CURSORINFO,
    GetKeyboardState, SetKeyboardState,
    EnumDisplayMonitors, GetMonitorInfo,
    mouse_event,
)

log = Logger("shadow", "win32")
shapelog = Logger("shape")
cursorlog = Logger("cursor")
keylog = Logger("keyboard")
screenlog = Logger("screen")


SEAMLESS = envbool("XPRA_WIN32_SEAMLESS", False)
NVFBC = envbool("XPRA_SHADOW_NVFBC", True)
GDI = envbool("XPRA_SHADOW_GDI", True)
GSTREAMER = envbool("XPRA_SHADOW_GSTREAMER", True)


def check_gstreamer_d3d11() -> bool:
    return not is_VirtualBox()


def check_gstreamer_dx9() -> bool:
    return True


def check_gstreamer_gdi() -> bool:
    # we don't want to be using GStreamer for GDI capture
    return False


def get_gstreamer_capture_elements() -> Sequence[str]:
    if "XPRA_GSTREAMER_CAPTURE_ELEMENTS" in os.environ:
        elements = os.environ.get("XPRA_GSTREAMER_CAPTURE_ELEMENTS", "").split(",")
    else:
        elements = []
        for element, check in {
            "d3d11screencapturesrc" : check_gstreamer_d3d11,
            "dx9screencapsrc": check_gstreamer_dx9,
            "gdiscreencapsrc": check_gstreamer_gdi,
        }.items():
            if envbool("XPRA_GSTREAMER_CAPTURE_"+element.upper(), False) or check():
                elements.append(element)
    log(f"get_gstreamer_capture_elements()={elements}")
    return elements


GSTREAMER_CAPTURE_ELEMENTS: Sequence[str] = get_gstreamer_capture_elements()


def check_gstreamer() -> bool:
    if not GSTREAMER:
        return False
    from xpra.gstreamer.common import has_plugins, import_gst
    import_gst()
    return any(has_plugins(element) for element in GSTREAMER_CAPTURE_ELEMENTS)


def check_nvfbc() -> bool:
    if not NVFBC:
        return False
    from xpra.codecs.nvidia.nvfbc.capture import get_capture_instance
    assert get_capture_instance
    return NVFBC


def check_gdi() -> bool:
    return GDI


def check_gtk() -> bool:
    from xpra.gtk import signals
    assert signals
    return True


SHADOW_OPTIONS = {
    "auto": lambda: True,
    "nvfbc": check_nvfbc,
    "gstreamer": check_gstreamer,
    "gdi": check_gdi,
    "gtk": check_gtk,
}


NOEVENT = (0, 0)
BUTTON_EVENTS: dict[tuple[int, bool], tuple[int, int]] = {
    # (button,up-or-down)  : win-event-name
    (1, True): (win32con.MOUSEEVENTF_LEFTDOWN, 0),
    (1, False): (win32con.MOUSEEVENTF_LEFTUP, 0),
    (2, True): (win32con.MOUSEEVENTF_MIDDLEDOWN, 0),
    (2, False): (win32con.MOUSEEVENTF_MIDDLEUP, 0),
    (3, True): (win32con.MOUSEEVENTF_RIGHTDOWN, 0),
    (3, False): (win32con.MOUSEEVENTF_RIGHTUP, 0),
    (4, True): (win32con.MOUSEEVENTF_WHEEL, win32con.WHEEL_DELTA),
    (4, False): NOEVENT,
    (5, True): (win32con.MOUSEEVENTF_WHEEL, -win32con.WHEEL_DELTA),
    (5, False): NOEVENT,
    (6, True): (win32con.MOUSEEVENTF_HWHEEL, win32con.WHEEL_DELTA),
    (6, False): NOEVENT,
    (7, True): (win32con.MOUSEEVENTF_HWHEEL, -win32con.WHEEL_DELTA),
    (7, False): NOEVENT,
    (8, True): (win32con.MOUSEEVENTF_XDOWN, win32con.XBUTTON1),
    (8, False): (win32con.MOUSEEVENTF_XUP, win32con.XBUTTON1),
    (9, True): (win32con.MOUSEEVENTF_XDOWN, win32con.XBUTTON2),
    (9, False): (win32con.MOUSEEVENTF_XUP, win32con.XBUTTON2),
}


def get_root_window_size() -> tuple[int, int]:
    w = GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
    h = GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
    return w, h


def get_monitors() -> list[dict[str, Any]]:
    monitors = []
    for m in EnumDisplayMonitors():
        mi = GetMonitorInfo(m)
        monitors.append(mi)
    return monitors


def setup_nvfbc_capture(w: int, h: int, pixel_depth=32):
    if not NVFBC:
        return None
    from xpra.codecs.nvidia.nvfbc.capture import get_capture_instance
    capture = get_capture_instance()
    try:
        pixel_format = {
            24: "RGB",
            32: "BGRX",
            30: "r210",
        }[pixel_depth]
        capture.init_context(w, h, pixel_format)
        # this will test the capture and ensure we can call get_image()
        capture.refresh()
        return capture
    except Exception as e:
        log("NvFBC_Capture", exc_info=True)
        log.warn("Warning: NvFBC screen capture initialization failed:")
        for x in str(e).replace(". ", ":").split(":"):
            if x.strip() and x != "nvfbc":
                log.warn(" %s", x.strip())
        return None


def setup_gstreamer_capture(w: int, h: int, pixel_depth=32):
    from xpra.codecs.gstreamer.capture import Capture
    for el in GSTREAMER_CAPTURE_ELEMENTS:
        log(f"testing gstreamer capture using {el}")
        try:
            capture = Capture(el, pixel_format="BGRX", width=w, height=h)
            capture.start()
            image = capture.get_image(0, 0, w, h)
            if image:
                log(f"using gstreamer element {el}")
                return capture
        except Exception:
            log(f"gstreamer failed to capture the screen using {el}", exc_info=True)
    return None


def setup_gdi_capture(w: int, h: int, pixel_depth=32):
    return GDICapture()


def setup_gtk_capture(w: int, h: int, pixel_depth=32):
    return GTKImageCapture(None)


CAPTURE_BACKENDS: dict[str, Callable] = {
    "nvfbc": setup_nvfbc_capture,
    "gstreamer": setup_gstreamer_capture,
    "gdi": setup_gdi_capture,
    "gtk": setup_gtk_capture,
}


class SeamlessRootWindowModel(RootWindowModel):

    def __init__(self, root, capture, title, geometry):
        super().__init__(root, capture, title, geometry)
        log("SeamlessRootWindowModel(%s, %s) SEAMLESS=%s", root, capture, SEAMLESS)
        self.property_names.append("shape")
        self.dynamic_property_names.append("shape")
        self.rectangles = self.get_shape_rectangles(logit=True)

    def refresh_shape(self) -> None:
        rectangles = self.get_shape_rectangles()
        if rectangles == self.rectangles:
            return  # unchanged
        self.rectangles = rectangles
        shapelog("refresh_shape() sending notify for updated rectangles: %s", rectangles)
        self.notify("shape")

    def get_shape_rectangles(self, logit=False) -> list:
        # get the list of windows
        log_fn = log.debug
        if logit or envbool("XPRA_SHAPE_DEBUG", False):
            log_fn = shapelog.debug
        taskbar = FindWindowA("Shell_TrayWnd", None)
        log_fn("taskbar window=%#x", taskbar)
        ourpid = os.getpid()
        log_fn("our pid=%i", ourpid)
        rectangles = []

        def enum_windows_cb(hwnd: int, lparam: int) -> bool:
            if not IsWindowVisible(hwnd):
                log_fn("skipped invisible window %#x", hwnd)
                return True
            pid = c_ulong()
            thread_id = GetWindowThreadProcessId(hwnd, byref(pid))
            if pid == ourpid:
                log_fn("skipped our own window %#x", hwnd)
                return True
            # skipping IsWindowEnabled check
            length = GetWindowTextLengthW(hwnd)
            buf = create_unicode_buffer(length + 1)
            if GetWindowTextW(hwnd, buf, length + 1) > 0:
                window_title = buf.value
            else:
                window_title = ''
            log_fn("get_shape_rectangles() found window '%s' with pid=%i and thread id=%i", window_title, pid, thread_id)
            rect = RECT()
            if GetWindowRect(hwnd, byref(rect)) == 0:  # NOSONAR
                log_fn("GetWindowRect failure")
                return True
            left, top, right, bottom = int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
            if right < 0 or bottom < 0:
                log_fn("skipped offscreen window at %ix%i", right, bottom)
                return True
            if hwnd == taskbar:
                log_fn("skipped taskbar")
                return True
            # dirty way:
            if window_title == 'Program Manager':
                return True
            # this should be the proper way using GetTitleBarInfo (but does not seem to work)
            # import ctypes
            # from ctypes.windll.user32 import GetTitleBarInfo
            # from ctypes.wintypes import (DWORD, RECT)
            # class TITLEBARINFO(ctypes.Structure):
            #    pass
            # TITLEBARINFO._fields_ = [
            #    ('cbSize', DWORD),
            #    ('rcTitleBar', RECT),
            #    ('rgstate', DWORD * 6),
            # ]
            # ti = TITLEBARINFO()
            # ti.cbSize = sizeof(ti)
            # GetTitleBarInfo(hwnd, byref(ti))
            # if ti.rgstate[0] & win32con.STATE_SYSTEM_INVISIBLE:
            #    log("skipped system invisible window")
            #    return True
            w = right - left
            h = bottom - top
            log_fn("shape(%s - %#x)=%s", window_title, hwnd, (left, top, w, h))
            if w <= 0 and h <= 0:
                log_fn("skipped invalid window size: %ix%i", w, h)
                return True
            if left == -32000 and top == -32000:
                # there must be a better way of skipping those - I haven't found it
                log_fn("skipped special window")
                return True
            # now clip rectangle:
            if left < 0:
                left = 0
                w = right
            if top < 0:
                top = 0
                h = bottom
            rectangles.append((left, top, w, h))
            return True

        EnumWindows(EnumWindowsProc(enum_windows_cb), 0)
        log_fn("get_shape_rectangles()=%s", rectangles)
        return sorted(rectangles)

    def get_property(self, prop: str):
        if prop == "shape":
            shape = {"Bounding.rectangles": self.rectangles}
            # provide clip rectangle? (based on workspace area?)
            return shape
        return super().get_property(prop)


class Win32ShadowModel(RootWindowModel):
    __slots__ = ("hwnd", "iconic")

    def __init__(self, root_window, capture=None, title="", geometry=None):
        super().__init__(root_window, capture, title, geometry)
        self.hwnd = 0
        self.iconic = geometry[2] == -32000 and geometry[3] == -32000
        self.property_names.append("hwnd")
        self.dynamic_property_names.append("size-hints")

    def get_id(self) -> int:
        return self.hwnd

    def __repr__(self):
        return "Win32ShadowModel(%s : %24s : %s)" % (self.capture, self.geometry, self.hwnd)


class ShadowServer(GTKShadowServerBase):

    def __init__(self, display, attrs: dict[str, str]):
        super().__init__(attrs)
        self.pixel_depth = 32
        self.cursor_handle = None
        self.cursor_data = None
        self.cursor_errors = [0.0, 0]
        self.backend = attrs.get("backend", "auto")
        if GetSystemMetrics(win32con.SM_SAMEDISPLAYFORMAT) == 0:
            raise InitException("all the monitors must use the same display format")
        el = get_win32_event_listener()
        # TODO: deal with those messages?
        el.add_event_callback(win32con.WM_POWERBROADCAST, self.power_broadcast_event)
        # el.add_event_callback(WM_WTSSESSION_CHANGE,         self.session_change_event)
        # these are bound to callbacks in the client,
        # but on the server we just ignore them:
        el.ignore_events.update({
            win32con.WM_ACTIVATEAPP: "WM_ACTIVATEAPP",
            win32con.WM_MOVE: "WM_MOVE",
            win32con.WM_INPUTLANGCHANGE: "WM_INPUTLANGCHANGE",
            win32con.WM_WININICHANGE: "WM_WININICHANGE",
        })

    def init(self, opts) -> None:
        self.pixel_depth = int(opts.pixel_depth) or 32
        if self.pixel_depth not in (24, 30, 32):
            raise InitException("unsupported pixel depth: %s" % self.pixel_depth)
        super().init(opts)

    def power_broadcast_event(self, wParam: int, lParam: int) -> None:
        log("WM_POWERBROADCAST: %s/%s", POWER_EVENTS.get(wParam, wParam), lParam)
        if wParam == win32con.PBT_APMSUSPEND:
            log.info("WM_POWERBROADCAST: PBT_APMSUSPEND")
            for source in self._server_sources.values():
                source.may_notify(NotificationID.IDLE, "Server Suspending",
                                  "This Xpra server is going to suspend,\nthe connection is likely to be interrupted soon.",
                                  expire_timeout=10 * 1000, icon_name="shutdown")
        elif wParam == win32con.PBT_APMRESUMEAUTOMATIC:
            log.info("WM_POWERBROADCAST: PBT_APMRESUMEAUTOMATIC")

    def guess_session_name(self, _procs=None) -> None:
        desktop_name = get_desktop_name()
        log("get_desktop_name()=%s", desktop_name)
        if desktop_name:
            self.session_name = desktop_name

    def print_screen_info(self) -> None:
        size = self.get_root_window_size()
        if not size:
            # we probably don't have access to the screen
            return
        w, h = size
        try:
            display = prettify_plug_name(self.root.get_screen().get_display().get_name())
        except Exception:
            display = ""
        self.do_print_screen_info(display, w, h)

    def make_tray_widget(self):
        from xpra.platform.win32.tray import Win32Tray
        return Win32Tray(self, XPRA_APP_ID, self.tray_menu, "Xpra Shadow Server", "server-notconnected",
                         click_cb=self.tray_click_callback, exit_cb=self.tray_exit_callback)

    def setup_capture(self):
        w, h = get_root_window_size()
        capture = try_setup_capture(CAPTURE_BACKENDS, self.backend, w, h, self.pixel_depth)
        log(f"setup_capture() {self.backend} - {self.root}: {capture}")
        return capture

    def get_root_window_model_class(self) -> type:
        if SEAMLESS:
            return SeamlessRootWindowModel
        return RootWindowModel

    def makeDynamicWindowModels(self):
        assert self.window_matches
        ourpid = os.getpid()
        taskbar = FindWindowA("Shell_TrayWnd", None)
        windows: dict[int, tuple[str, tuple[int, int, int, int]]] = {}

        def enum_windows_cb(hwnd, lparam):
            if not IsWindowVisible(hwnd):
                log("window %#x is not visible", hwnd)
                return True
            pid = c_ulong()
            thread_id = GetWindowThreadProcessId(hwnd, byref(pid))
            if pid == ourpid:
                log("skipped our own window %#x, thread id=%#x", hwnd, thread_id)
                return True
            rect = RECT()
            if GetWindowRect(hwnd, byref(rect)) == 0:  # NOSONAR
                log("GetWindowRect failure")
                return True
            if hwnd == taskbar:
                log("skipped taskbar")
                return True
            # skipping IsWindowEnabled check
            length = GetWindowTextLengthW(hwnd)
            buf = create_unicode_buffer(length + 1)
            window_title = ''
            if GetWindowTextW(hwnd, buf, length + 1) > 0:
                window_title = buf.value
            left, top, right, bottom = int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
            w = right - left
            h = bottom - top
            if left <= -32000 or top <= -32000:
                log("%r is not visible: %s", window_title, (left, top, w, h))
            if w <= 0 and h <= 0:
                log("skipped invalid window size: %ix%i", w, h)
                return True
            windows[hwnd] = (window_title, (left, top, w, h))
            return True

        EnumWindows(EnumWindowsProc(enum_windows_cb), 0)
        log("makeDynamicWindowModels() windows=%s", windows)
        models = []

        def add_model(hwnd: int, title: str, geometry: tuple[int, int, int, int]):
            model = Win32ShadowModel(self.root, self.capture, title=title, geometry=geometry)
            model.hwnd = hwnd
            models.append(model)

        for m in self.window_matches:
            window = None
            try:
                if m.startswith("0x"):
                    hwnd = int(m, 16)
                else:
                    hwnd = int(m)
                if hwnd:
                    window = windows.pop(hwnd, None)
                    if window:
                        add_model(hwnd, *window)
            except ValueError:
                namere = re.compile(m, re.IGNORECASE)
                for hwnd, window in tuple(windows.items()):
                    title, geometry = window
                    if namere.match(title):
                        add_model(hwnd, title, geometry)
                        windows.pop(hwnd)
        log("makeDynamicWindowModels()=%s", models)
        return models

    def get_shadow_monitors(self) -> list:
        # convert to the format expected by GTKShadowServerBase:
        monitors = []
        for i, monitor in enumerate(get_monitors()):
            geom = monitor["Monitor"]
            x1, y1, x2, y2 = geom
            assert x1 < x2 and y1 < y2
            plug_name = monitor["Device"].lstrip("\\\\.\\")
            monitors.append((plug_name, x1, y1, x2 - x1, y2 - y1, 1))
            screenlog("monitor %i: %10s coordinates: %s", i, plug_name, geom)
        log("get_shadow_monitors()=%s", monitors)
        return monitors

    def refresh(self) -> bool:
        v = super().refresh()
        if v and SEAMLESS:
            for rwm in self._id_to_window.values():
                rwm.refresh_shape()
        log("refresh()=%s", v)
        return v

    def do_get_cursor_data(self) -> tuple | None:
        ci = CURSORINFO()
        ci.cbSize = sizeof(CURSORINFO)
        GetCursorInfo(byref(ci))
        # cursorlog("GetCursorInfo handle=%#x, last handle=%#x", ci.hCursor or 0, self.cursor_handle or 0)
        if not (ci.flags & win32con.CURSOR_SHOWING):
            # cursorlog("do_get_cursor_data() cursor not shown")
            return None
        handle = int(ci.hCursor)
        if handle == self.cursor_handle and self.last_cursor_data:
            # cursorlog("do_get_cursor_data() cursor handle unchanged")
            return self.last_cursor_data
        self.cursor_handle = handle
        cd = get_cursor_data(handle)
        if not cd:
            cursorlog("do_get_cursor_data() no cursor data")
            return self.last_cursor_data
        cd[0] = ci.ptScreenPos.x
        cd[1] = ci.ptScreenPos.y
        w, h = get_fixed_cursor_size()
        return (
            cd,
            ((w, h), [(w, h), ]),
        )

    def get_pointer_position(self) -> tuple[int, int]:
        pos = POINT()
        GetPhysicalCursorPos(byref(pos))  # NOSONAR
        return pos.x, pos.y

    def do_process_mouse_common(self, proto, device_id, wid: int, pointer, props) -> bool:
        ss = self._server_sources.get(proto)
        if not ss:
            return False
        # adjust pointer position for offset in client:
        try:
            x, y = pointer[:2]
            if SetPhysicalCursorPos(x, y):
                return True
            # rate limit the warnings:
            start, count = self.cursor_errors
            now = monotonic()
            elapsed = now - start
            if count == 0 or (count > 1 and elapsed > 10):
                log.warn("Warning: cannot move cursor")
                log.warn(" (%i events)", count + 1)
                self.cursor_errors = [now, 1]
            else:
                self.cursor_errors[1] = count + 1
        except Exception as e:
            log("SetPhysicalCursorPos%s failed", pointer, exc_info=True)
            log.error("Error: failed to move the cursor:")
            log.estr(e)
        return False

    def clear_keys_pressed(self) -> None:
        # noinspection PyCallingNonCallable,PyTypeChecker
        keystate = (BYTE * 256)()
        if GetKeyboardState(keystate):
            vknames = {}
            for vkconst in (x for x in dir(win32con) if x.startswith("VK_")):
                vknames[getattr(win32con, vkconst)] = vkconst[3:]
            pressed = []
            for i in range(256):
                if keystate[i]:
                    pressed.append(vknames.get(i, i))
            keylog("keys still pressed: %s", csv(pressed))
            for x in (
                    win32con.VK_LSHIFT, win32con.VK_RSHIFT, win32con.VK_SHIFT,
                    win32con.VK_LCONTROL, win32con.VK_RCONTROL, win32con.VK_CONTROL,
                    win32con.VK_LMENU, win32con.VK_RMENU, win32con.VK_MENU,
                    win32con.VK_LWIN, win32con.VK_RWIN,
            ):
                keystate[x] = 0
            SetKeyboardState(keystate)

    def get_keyboard_config(self, _props=None) -> KeyboardConfig:
        return KeyboardConfig()

    def fake_key(self, keycode: int, press: bool) -> None:
        fake_key(keycode, press)

    def do_process_button_action(self, proto, device_id, wid: int, button: int, pressed: bool, pointer, props) -> None:
        if "modifiers" in props:
            self._update_modifiers(proto, wid, props.get("modifiers"))
        # ignore device_id on win32:
        did = -1
        pointer = self.process_mouse_common(proto, did, wid, pointer)
        if pointer:
            self.get_server_source(proto).user_event()
            self.button_action(did, wid, pointer, button, pressed, props)

    def button_action(self, device_id, wid: int, pointer, button: int, pressed: bool, props) -> None:
        event = BUTTON_EVENTS.get((button, pressed))
        if event is None:
            log.warn("no matching event found for button=%s, pressed=%s", button, pressed)
            return
        elif event == NOEVENT:
            return
        dwFlags, dwData = event
        x, y = pointer[:2]
        mouse_event(dwFlags, x, y, dwData, 0)

    def make_hello(self, source) -> dict[str, Any]:
        capabilities = GTKServerBase.make_hello(self, source)
        capabilities["shadow"] = True
        capabilities["server_type"] = "Python/Win32-Shadow"
        return capabilities

    def get_info(self, proto, *_args) -> dict[str, Any]:
        info = GTKServerBase.get_info(self, proto)
        info.update(GTKShadowServerBase.get_info(self, proto))
        info.setdefault("features", {})["shadow"] = True
        info.setdefault("server", {
            "pixel-depth": self.pixel_depth,
            "type": "Python/Win32-Shadow",
            "tray": self.tray,
            "tray-icon": self.tray_icon or ""
        })
        return info


def main():
    from xpra.platform import program_context
    with program_context("Shadow-Test", "Shadow Server Screen Capture Test"):
        rwm = RootWindowModel(None)
        pngdata = rwm.take_screenshot()
        filename = "screenshot.png"
        with open(filename, "wb") as f:
            f.write(pngdata[4])
        print(f"saved screenshot as {filename}")


if __name__ == "__main__":
    main()
