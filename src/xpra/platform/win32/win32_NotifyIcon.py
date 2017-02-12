#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Low level support for the "system tray" on MS Windows
# Based on code from winswitch, itself based on "win32gui_taskbar demo"

import ctypes
from ctypes.wintypes import HWND, UINT, POINT, HICON, BOOL, DWORD, HBITMAP, WCHAR

from xpra.util import csv
from xpra.platform.win32 import constants as win32con
from xpra.platform.win32.common import GUID, WNDCLASSEX, WNDPROC
from xpra.log import Logger
log = Logger("tray", "win32")

log("loading ctypes NotifyIcon functions")

user32 = ctypes.windll.user32
GetSystemMetrics = user32.GetSystemMetrics
GetCursorPos = user32.GetCursorPos
PostMessage = user32.PostMessageA
LoadIcon = user32.LoadIconA
CreateWindowEx = user32.CreateWindowExA
DefWindowProcW = user32.DefWindowProcW
RegisterWindowMessage = user32.RegisterWindowMessageA
RegisterClassEx = user32.RegisterClassExW
UpdateWindow = user32.UpdateWindow
DestroyIcon = user32.DestroyIcon
LoadImage = user32.LoadImageW
CreateIconIndirect = user32.CreateIconIndirect
GetDC = user32.GetDC
ReleaseDC = user32.ReleaseDC
DestroyWindow = user32.DestroyWindow
PostQuitMessage = user32.PostQuitMessage

kernel32 = ctypes.windll.kernel32
GetModuleHandle = kernel32.GetModuleHandleA

gdi32 = ctypes.windll.gdi32
GetStockObject = gdi32.GetStockObject
CreateCompatibleDC = gdi32.CreateCompatibleDC
CreateCompatibleBitmap = gdi32.CreateCompatibleBitmap
SelectObject = gdi32.SelectObject
SetPixelV = gdi32.SetPixelV

class ICONINFO(ctypes.Structure):
    __fields__ = [
        ('fIcon',       BOOL),
        ('xHotspot',    DWORD),
        ('yHotspot',    DWORD),
        ('hbmMask',     HBITMAP),
        ('hbmColor',    HBITMAP),
    ]
CreateIconIndirect.restype = HICON
CreateIconIndirect.argtypes = [ctypes.POINTER(ICONINFO)]

class NOTIFYICONDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize",              DWORD),
        ("hWnd",                HWND),
        ("uID",                 UINT),
        ("uFlags",              UINT),
        ("uCallbackMessage",    UINT),
        ("hIcon",               HICON),
        ("szTip",               WCHAR * 64),
        ("dwState",             DWORD),
        ("dwStateMask",         DWORD),
        ("szInfo",              WCHAR * 256),
        ("uVersion",            UINT),
        ("szInfoTitle",         WCHAR * 64),
        ("dwInfoFlags",         DWORD),
        ("guidItem",            GUID),
        ("hBalloonIcon",        HICON),
    ]

shell32 = ctypes.windll.shell32
Shell_NotifyIcon = shell32.Shell_NotifyIcon
Shell_NotifyIcon.restype = ctypes.wintypes.BOOL
Shell_NotifyIcon.argtypes = [ctypes.wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATA)]


FALLBACK_ICON = LoadIcon(0, win32con.IDI_APPLICATION)

#constants found in win32gui:
NIM_ADD         = 0
NIM_MODIFY      = 1
NIM_DELETE      = 2
NIM_SETFOCUS    = 3
NIM_SETVERSION  = 4

NIF_MESSAGE     = 1
NIF_ICON        = 2
NIF_TIP         = 4
NIF_STATE       = 8
NIF_INFO        = 16
NIF_GUID        = 32
NIF_REALTIME    = 64
NIF_SHOWTIP     = 128

NIF_FLAGS = {
    NIF_MESSAGE     : "MESSAGE",
    NIF_ICON        : "ICON",
    NIF_TIP         : "TIP",
    NIF_STATE       : "STATE",
    NIF_INFO        : "INFO",
    NIF_GUID        : "GUID",
    NIF_REALTIME    : "REALTIME",
    NIF_SHOWTIP     : "SHOWTIP",
    }

NOTIFYICON_VERSION = 3
NOTIFYICON_VERSION_4 = 4

#found here:
#http://msdn.microsoft.com/en-us/library/windows/desktop/ff468877(v=vs.85).aspx
WM_XBUTTONDOWN  = 0x020B
WM_XBUTTONUP    = 0x020C
WM_XBUTTONDBLCLK= 0x020D

BUTTON_MAP = {
            win32con.WM_LBUTTONDOWN     : [(1, 1)],
            win32con.WM_LBUTTONUP       : [(1, 0)],
            win32con.WM_MBUTTONDOWN     : [(2, 1)],
            win32con.WM_MBUTTONUP       : [(2, 0)],
            win32con.WM_RBUTTONDOWN     : [(3, 1)],
            win32con.WM_RBUTTONUP       : [(3, 0)],
            win32con.WM_LBUTTONDBLCLK   : [(1, 1), (1, 0)],
            win32con.WM_MBUTTONDBLCLK   : [(2, 1), (2, 0)],
            win32con.WM_RBUTTONDBLCLK   : [(3, 1), (3, 0)],
            WM_XBUTTONDOWN              : [(4, 1)],
            WM_XBUTTONUP                : [(4, 0)],
            WM_XBUTTONDBLCLK            : [(4, 1), (4, 0)],
            }


class win32NotifyIcon(object):

    #we register the windows event handler on the class,
    #this allows us to know which hwnd refers to which instance:
    instances = {}

    def __init__(self, app_id, title, move_callbacks, click_callback, exit_callback, command_callback=None, iconPathName=None):
        log("win32NotifyIcon: app_id=%i, title='%s'", app_id, title)
        self.app_id = app_id
        self.title = title
        self.current_icon = None
        # Create the Window.
        if iconPathName:
            try:
                iconPathName = iconPathName.decode()
            except:
                pass
            self.current_icon = self.LoadImage(iconPathName)
        self.create_tray_window()
        #register callbacks:
        win32NotifyIcon.instances[self.hwnd] = self
        self.move_callback = move_callbacks
        self.click_callback = click_callback
        self.exit_callback = exit_callback
        self.command_callback = command_callback
        self.reset_function = None

    def create_tray_window(self):
        style = win32con.WS_OVERLAPPED | win32con.WS_SYSMENU
        window_name = (self.title+" StatusIcon Window").decode()
        self.hwnd = CreateWindowEx(0, NIclassAtom, window_name, style,
            0, 0, win32con.CW_USEDEFAULT, win32con.CW_USEDEFAULT, \
            0, 0, NIwc.hInstance, None)
        if self.hwnd==0:
            raise ctypes.WinError()
        log("hwnd=%#x", self.hwnd)
        UpdateWindow(self.hwnd)
        r = Shell_NotifyIcon(NIM_ADD, self.make_nid(NIF_ICON | NIF_MESSAGE | NIF_TIP))
        log("Shell_NotifyIcon ADD=%i", r)
        if not r:
            raise Exception("Shell_NotifyIcon failed to ADD")

    def make_nid(self, flags, version_timeout=5000):
        nid = NOTIFYICONDATA()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        nid.hWnd = self.hwnd
        nid.uID = 20+self.app_id
        nid.uCallbackMessage = win32con.WM_MENUCOMMAND
        nid.hIcon = self.current_icon
        nid.szTip = self.title
        nid.dwState = 0
        nid.dwStateMask = 0
        nid.uVersion = version_timeout
        #balloon notification bits:
        #szInfo
        #uTimeout
        #szInfoTitle
        #dwInfoFlags
        #guidItem
        #hBalloonIcon
        log("make_nid(..)=%s tooltip='%s', app_id=%i, actual flags=%s", nid, title, self.app_id, csv([v for k,v in NIF_FLAGS.items() if k&flags]))
        return nid

    def delete_tray_window(self):
        if not self.hwnd:
            return
        try:
            nid = self.make_nid(0, 0)
            log("delete_tray_window(..) calling Shell_NotifyIcon(NIM_DELETE, %s)", nid)
            Shell_NotifyIcon(NIM_DELETE, nid)
        except Exception as e:
            log.error("Error: failed to delete tray window")
            log.error(" %s", e)
        self.hwnd = 0


    def set_blinking(self, on):
        #FIXME: implement blinking on win32 using a timer
        pass

    def set_tooltip(self, tooltip):
        self.title = tooltip
        Shell_NotifyIcon(NIM_MODIFY, self.make_nid(NIF_ICON | NIF_MESSAGE | NIF_TIP))


    def set_icon(self, iconPathName):
        hicon = self.LoadImage(iconPathName)
        self.do_set_icon(hicon)
        Shell_NotifyIcon(NIM_MODIFY, self.make_nid(NIF_ICON))
        self.reset_function = (self.set_icon, iconPathName)

    def do_set_icon(self, hicon):
        log("do_set_icon(%s)", hicon)
        self.current_icon = hicon
        Shell_NotifyIcon(NIM_MODIFY, self.make_nid(NIF_ICON))


    def set_icon_from_data(self, pixels, has_alpha, w, h, rowstride, options={}):
        #this is convoluted but it works..
        log("set_icon_from_data%s", ("%s pixels" % len(pixels), has_alpha, w, h, rowstride))
        from PIL import Image, ImageOps           #@UnresolvedImport
        if has_alpha:
            rgb_format = "RGBA"
        else:
            rgb_format = "RGB"
        img = Image.frombuffer(rgb_format, (w, h), pixels, "raw", rgb_format, 0, 1)
        #apparently, we have to use SM_CXSMICON (small icon) and not SM_CXICON (regular size):
        size = GetSystemMetrics(win32con.SM_CXSMICON)
        if w!=h or w!=size:
            img = img.resize((size, size), Image.ANTIALIAS)
        if has_alpha:
            #extract alpha channel as mask into an inverted "L" channel image:
            alpha = img.tobytes("raw", "A")
            mask = Image.frombytes("L", img.size, alpha)
            mask = ImageOps.invert(mask)
            #strip alpha from pixels:
            img = img.convert("RGB")
        else:
            #no alpha: just use image as mask:
            mask = img

        def img_to_bitmap(image, pixel_value):
            hdc = CreateCompatibleDC(0)
            dc = GetDC(0)
            hbm = CreateCompatibleBitmap(dc, size, size)
            hbm_save = SelectObject(hdc, hbm)
            for x in range(size):
                for y in range(size):
                    pixel = image.getpixel((x, y))
                    v = pixel_value(pixel)
                    SetPixelV(hdc, x, y, v)
            SelectObject(hdc, hbm_save)
            ReleaseDC(self.hwnd, hdc)
            ReleaseDC(self.hwnd, dc)
            return hbm

        hicon = FALLBACK_ICON
        try:
            def rgb_pixel(pixel):
                r, g, b = pixel[:3]
                return r+g*256+b*256*256
            bitmap = img_to_bitmap(img, rgb_pixel)
            if mask is img:
                mask_bitmap = bitmap
            else:
                #mask is in "L" mode, so we get the pixel value directly from getpixel(x, y)
                def mask_pixel(l):
                    return l+l*256+l*256*256
                mask_bitmap = img_to_bitmap(mask, mask_pixel)
            if mask_bitmap:
                pyiconinfo = (True, 0, 0, mask_bitmap, bitmap)
                hicon = CreateIconIndirect(pyiconinfo)
                log("CreateIconIndirect(%s)=%s", pyiconinfo, hicon)
                if hicon==0:
                    hicon = FALLBACK_ICON
            self.do_set_icon(hicon)
            UpdateWindow(self.hwnd)
            self.reset_function = (self.set_icon_from_data, pixels, has_alpha, w, h, rowstride, options)
        except:
            log.error("error setting icon", exc_info=True)
        finally:
            #DeleteDC(dc)
            if hicon!=FALLBACK_ICON:
                DestroyIcon(hicon)

    def LoadImage(self, iconPathName, fallback=FALLBACK_ICON):
        v = fallback
        if iconPathName:
            icon_flags = win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE
            try:
                img_type = win32con.IMAGE_ICON
                if iconPathName.lower().split(".")[-1] in ("png", "bmp"):
                    img_type = win32con.IMAGE_BITMAP
                    icon_flags |= win32con.LR_CREATEDIBSECTION | win32con.LR_LOADTRANSPARENT
                log("LoadImage(%s) using image type=%s", iconPathName,
                                            {
                                                win32con.IMAGE_ICON    : "ICON",
                                                win32con.IMAGE_BITMAP  : "BITMAP",
                                             }.get(img_type))
                v = LoadImage(NIwc.hInstance, iconPathName, img_type, 0, 0, icon_flags)
            except:
                log.error("Failed to load icon at %s", iconPathName, exc_info=True)
        log("LoadImage(%s)=%s", iconPathName, v)
        return v


    def OnTrayRestart(self, hwnd=0, msg=0, wparam=0, lparam=0):
        try:
            #re-create the tray window:
            self.delete_tray_window()
            self.create_tray_window()
            #now try to repaint the tray:
            rfn = self.reset_function
            log("OnTrayRestart%s reset function: %s", (hwnd, msg, wparam, lparam), rfn)
            if rfn:
                rfn[0](*rfn[1:])
        except Exception as e:
            log.error("Error: cannot reset tray icon")
            log.error(" %s", e)

    def OnCommand(self, hwnd, msg, wparam, lparam):
        cb = getattr(self, "command_callback", None)
        log("OnCommand%s callback=%s", (hwnd, msg, wparam, lparam), cb)
        if cb:
            cid = wparam & 0xFFFF
            cb(hwnd, cid)

    def OnDestroy(self, hwnd, msg, wparam, lparam):
        log("OnDestroy%s", (hwnd, msg, wparam, lparam))
        self.destroy()

    def OnTaskbarNotify(self, hwnd, msg, wparam, lparam):
        if lparam==win32con.WM_MOUSEMOVE:
            cb = self.move_callback
            bm = [(hwnd, msg, wparam, lparam)]
        else:
            cb = self.click_callback
            bm = BUTTON_MAP.get(lparam)
        log("OnTaskbarNotify%s button(s) lookup: %s, callback=%s", (hwnd, msg, wparam, lparam), bm, cb)
        if bm is not None and cb:
            for button_event in bm:
                cb(*button_event)
        return 1

    def close(self):
        log("win32NotifyIcon.close()")
        self.destroy()

    def destroy(self):
        cb = self.exit_callback
        hwnd = self.hwnd
        log("destroy() hwnd=%#x, exit callback=%s", hwnd, cb)
        self.delete_tray_window()
        try:
            if cb:
                self.exit_callback = None
                cb()
        except:
            log.error("destroy()", exc_info=True)
        if hwnd:
            try:
                del win32NotifyIcon.instances[hwnd]
            except:
                pass


WM_TRAY_EVENT = win32con.WM_MENUCOMMAND     #a message id we choose
TASKBAR_CREATED = RegisterWindowMessage("TaskbarCreated")
message_map = {
    TASKBAR_CREATED                     : win32NotifyIcon.OnTrayRestart,
    win32con.WM_DESTROY                 : win32NotifyIcon.OnDestroy,
    win32con.WM_COMMAND                 : win32NotifyIcon.OnCommand,
    WM_TRAY_EVENT                       : win32NotifyIcon.OnTaskbarNotify,
}
def NotifyIconWndProc(hwnd, msg, wParam, lParam):
    instance = win32NotifyIcon.instances.get(hwnd)
    fn = message_map.get(msg)
    log("NotifyIconWndProc%s instance=%s, message(%i)=%s", (hwnd, msg, wParam, lParam), instance, msg, fn)
    #log("potential matching win32 constants for message: %s", [x for x in dir(win32con) if getattr(win32con, x)==msg])
    if instance and fn:
        return fn(instance, hwnd, msg, wParam, lParam) or 0
    return user32.DefWindowProcW(hwnd, msg, wParam, lParam)

NIwc = WNDCLASSEX()
NIwc.cbSize = ctypes.sizeof(WNDCLASSEX)
NIwc.style = win32con.CS_HREDRAW | win32con.CS_VREDRAW
NIwc.lpfnWndProc = WNDPROC(NotifyIconWndProc)
NIwc.cbClsExtra = 0
NIwc.cbWndExtra = 0
NIwc.hInstance = GetModuleHandle(0)
NIwc.hIcon = 0
NIwc.hCursor = 0
NIwc.hBrush = GetStockObject(win32con.WHITE_BRUSH)
NIwc.lpszMenuName = 0
NIwc.lpszClassName = u"win32NotifyIcon"
NIwc.hIconSm = 0

NIclassAtom = RegisterClassEx(ctypes.byref(NIwc))
if NIclassAtom==0:
    raise ctypes.WinError()
log("RegisterClassEx(%s)=%i", NIwc.lpszClassName, NIclassAtom)

def main():
    import os
    import sys

    def click_callback(button, pressed):
        CreatePopupMenu = user32.CreatePopupMenu
        CreatePopupMenu.restype = ctypes.wintypes.HMENU
        CreatePopupMenu.argtypes = []
        AppendMenu = user32.AppendMenuW
        AppendMenu.restype = ctypes.wintypes.BOOL
        AppendMenu.argtypes = [ctypes.wintypes.HMENU, ctypes.wintypes.UINT, ctypes.wintypes.UINT, ctypes.wintypes.LPCWSTR]
        menu = CreatePopupMenu()
        AppendMenu(menu, win32con.MF_STRING, 1024, u"Generate balloon")
        AppendMenu(menu, win32con.MF_STRING, 1025, u"Exit")
        pos = POINT()
        GetCursorPos(ctypes.byref(pos))
        hwnd = tray.hwnd
        user32.SetForegroundWindow(hwnd)
        user32.TrackPopupMenu(menu, win32con.TPM_LEFTALIGN, pos.x, pos.y, 0, hwnd, None)
        PostMessage(hwnd, win32con.WM_NULL, 0, 0)

    def command_callback(hwnd, cid):
        if cid == 1024:
            from xpra.platform.win32.win32_balloon import notify
            notify(hwnd, "hello", "world")
        elif cid == 1025:
            print("Goodbye")
            DestroyWindow(hwnd)
        else:
            print("OnCommand for ID=%s" % cid)

    def win32_quit():
        PostQuitMessage(0) # Terminate the app.

    iconPathName = os.path.abspath(os.path.join( sys.prefix, "pyc.ico"))
    tray = win32NotifyIcon("test", move_callbacks=None, click_callback=click_callback, exit_callback=win32_quit, command_callback=command_callback, iconPathName=iconPathName)
    #pump messages:
    msg = ctypes.wintypes.MSG()
    pMsg = ctypes.pointer(msg)
    while user32.GetMessageA(pMsg, win32con.NULL, 0, 0) != 0:
        user32.TranslateMessage(pMsg)
        user32.DispatchMessageA(pMsg)


if __name__=='__main__':
    main()
