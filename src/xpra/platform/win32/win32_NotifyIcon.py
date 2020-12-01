#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Low level support for the "system tray" on MS Windows
# Based on code from winswitch, itself based on "win32gui_taskbar demo"

import os
import ctypes
from ctypes import POINTER, Structure, byref, WinDLL, c_void_p, sizeof, create_string_buffer
from ctypes.wintypes import HWND, UINT, POINT, HICON, BOOL, WCHAR, DWORD

from xpra.util import typedict, csv, nonl, envbool, XPRA_GUID1, XPRA_GUID2, XPRA_GUID3, XPRA_GUID4
from xpra.os_util import memoryview_to_bytes, bytestostr
from xpra.platform.win32 import constants as win32con
from xpra.platform.win32.common import (
    GUID, WNDCLASSEX, WNDPROC,
    GetSystemMetrics,
    GetCursorPos,
    PostMessageA,
    CreateWindowExA, CreatePopupMenu, AppendMenu,
    LoadIconA,
    DefWindowProcA, RegisterWindowMessageA, RegisterClassExA,
    ICONINFO, BITMAPV5HEADER,
    LoadImageW, CreateIconIndirect, DestroyIcon,
    GetDC, ReleaseDC,
    CreateBitmap, CreateDIBSection,
    UpdateWindow, DestroyWindow,
    PostQuitMessage,
    GetModuleHandleA,
    GetStockObject, DeleteObject,
    )
from xpra.log import Logger

log = Logger("tray", "win32")

log("loading ctypes NotifyIcon functions")
sprintf = ctypes.cdll.msvcrt.sprintf


TRAY_ALPHA = envbool("XPRA_TRAY_ALPHA", True)


def GetProductInfo(dwOSMajorVersion=5, dwOSMinorVersion=0, dwSpMajorVersion=0, dwSpMinorVersion=0):
    product_type = DWORD(0)
    from xpra.platform.win32.common import GetProductInfo as k32GetProductInfo
    v = k32GetProductInfo(dwOSMajorVersion, dwOSMinorVersion, dwSpMajorVersion, dwSpMinorVersion, byref(product_type))
    log("GetProductInfo(%i, %i, %i, %i)=%i product_type=%s", dwOSMajorVersion, dwOSMinorVersion, dwSpMajorVersion, dwSpMinorVersion, v, hex(product_type.value))
    return bool(v)
#win7 is actually 6.1:
try:
    ISWIN7ORHIGHER = GetProductInfo(6, 1)
except AttributeError as e:
    #likely running on win XP:
    log("cannot query GetProductInfo", exc_info=True)
    raise ImportError("cannot query GetProductInfo: %s" % e)

if ISWIN7ORHIGHER:
    MAX_TIP_SIZE = 128
else:
    MAX_TIP_SIZE = 64

class NOTIFYICONDATA(Structure):
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

shell32 = WinDLL("shell32", use_last_error=True)
Shell_NotifyIconW = shell32.Shell_NotifyIconW
Shell_NotifyIconW.restype = BOOL
Shell_NotifyIconW.argtypes = [DWORD, POINTER(NOTIFYICONDATA)]

BI_RGB = 0
BI_BITFIELDS = 0x00000003

XPRA_GUID = GUID()
XPRA_GUID.Data1 = XPRA_GUID1
XPRA_GUID.Data2 = XPRA_GUID2
XPRA_GUID.Data3 = XPRA_GUID3
XPRA_GUID.Data4 = XPRA_GUID4

FALLBACK_ICON = LoadIconA(0, win32con.IDI_APPLICATION)

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


def image_to_ICONINFO(img):
    w, h = img.size
    if TRAY_ALPHA and img.mode.find("A")>=0:   #ie: RGBA
        rgb_format = "BGRA"
    else:
        rgb_format = "BGR"
    rgb_data = img.tobytes("raw", rgb_format)
    return make_ICONINFO(w, h, rgb_data, rgb_format=rgb_format)

def make_ICONINFO(w, h, rgb_data, rgb_format="BGRA"):
    log("make_ICONINFO(%i, %i, %i bytes, %s)", w, h, len(rgb_data), rgb_format)
    bitmap = 0
    mask = 0
    try:
        bytes_per_pixel = len(rgb_format)
        bitmap = rgb_to_bitmap(rgb_data, bytes_per_pixel, w, h)
        mask = CreateBitmap(w, h, 1, 1, None)

        iconinfo = ICONINFO()
        iconinfo.fIcon = True
        iconinfo.hbmMask = mask
        iconinfo.hbmColor = bitmap
        hicon = CreateIconIndirect(byref(iconinfo))
        log("CreateIconIndirect()=%#x", hicon)
        if not hicon:
            raise ctypes.WinError(ctypes.get_last_error())
        return hicon
    except Exception:
        log.error("Error: failed to set tray icon", exc_info=True)
        return FALLBACK_ICON
    finally:
        if mask:
            DeleteObject(mask)
        if bitmap:
            DeleteObject(bitmap)

def rgb_to_bitmap(rgb_data, bytes_per_pixel, w, h):
    assert bytes_per_pixel in (3, 4)        #only BGRA or BGR are supported
    header = BITMAPV5HEADER()
    header.bV5Size = sizeof(BITMAPV5HEADER)
    header.bV5Width = w
    header.bV5Height = -h
    header.bV5Planes = 1
    header.bV5BitCount = bytes_per_pixel*8
    header.bV5Compression = BI_RGB      #BI_BITFIELDS
    #header.bV5RedMask = 0x000000ff
    #header.bV5GreenMask = 0x0000ff00
    #header.bV5BlueMask = 0x00ff0000
    #header.bV5AlphaMask = 0xff000000
    bitmap = 0
    try:
        hdc = GetDC(None)
        dataptr = c_void_p()
        log("GetDC()=%#x", hdc)
        bitmap = CreateDIBSection(hdc, byref(header), win32con.DIB_RGB_COLORS, byref(dataptr), None, 0)
    finally:
        ReleaseDC(None, hdc)
    assert dataptr and bitmap, "failed to create DIB section"
    log("CreateDIBSection(..) got bitmap=%#x, dataptr=%s", int(bitmap), dataptr)
    img_data = create_string_buffer(rgb_data)
    ctypes.memmove(dataptr, byref(img_data), w*h*bytes_per_pixel)
    return bitmap


class win32NotifyIcon(object):

    #we register the windows event handler on the class,
    #this allows us to know which hwnd refers to which instance:
    instances = {}

    def __init__(self, app_id=0, title="", move_callbacks=None, click_callback=None, exit_callback=None, command_callback=None, iconPathName=None):
        log("win32NotifyIcon: app_id=%i, title='%s'", app_id, nonl(title))
        self.app_id = app_id
        self.title = title
        self.current_icon = None
        self.destroy_icon = None
        self.move_callback = move_callbacks
        self.click_callback = click_callback
        self.exit_callback = exit_callback
        self.command_callback = command_callback
        self.reset_function = None
        self.image_cache = {}
        # Create the Window.
        if iconPathName:
            try:
                iconPathName = iconPathName.decode()
            except:
                pass
            self.current_icon = self.LoadImage(iconPathName) or FALLBACK_ICON
        self.create_tray_window()

    def __repr__(self):
        return "win32NotifyIcon(%#x)" % self.app_id

    def create_tray_window(self):
        log("create_tray_window()")
        self.create_window()
        self.register_tray()

    def create_window(self):
        style = win32con.WS_OVERLAPPED | win32con.WS_SYSMENU
        window_name = u"%s StatusIcon Window" % bytestostr(self.title)
        self.hwnd = CreateWindowExA(0, NIclassAtom, window_name, style,
            win32con.CW_USEDEFAULT, win32con.CW_USEDEFAULT, 0, 0, \
            0, 0, NIwc.hInstance, None)
        log("create_window() hwnd=%#x", self.hwnd or 0)
        if not self.hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        UpdateWindow(self.hwnd)
        #register callbacks:
        win32NotifyIcon.instances[self.hwnd] = self

    def register_tray(self):
        r = Shell_NotifyIconW(NIM_ADD, self.make_nid(NIF_ICON | NIF_MESSAGE | NIF_TIP))
        log("Shell_NotifyIconW ADD=%i", r)
        if not r:
            raise Exception("Shell_NotifyIconW failed to ADD")

    def make_nid(self, flags):
        assert self.hwnd
        nid = NOTIFYICONDATA()
        nid.cbSize = sizeof(NOTIFYICONDATA)
        nid.hWnd = self.hwnd
        nid.uCallbackMessage = win32con.WM_MENUCOMMAND
        nid.hIcon = self.current_icon
        #don't ask why we have to use sprintf to get what we want:
        title = bytestostr(self.title[:MAX_TIP_SIZE-1])
        nid.szTip = title
        nid.dwState = 0
        nid.dwStateMask = 0
        nid.guidItem = XPRA_GUID
        nid.uID = self.app_id
        flags |= NIF_GUID
        #balloon notification bits:
        #szInfo
        #uTimeout
        #szInfoTitle
        #dwInfoFlags
        #hBalloonIcon
        #flags |= NIF_SHOWTIP
        nid.uVersion = 4
        nid.uFlags = flags
        log("make_nid(..)=%s tooltip='%s', app_id=%i, actual flags=%s", nid, nonl(title), self.app_id, csv([v for k,v in NIF_FLAGS.items() if k&flags]))
        return nid

    def delete_tray_window(self):
        if not self.hwnd:
            return
        try:
            nid = self.make_nid(0)
            log("delete_tray_window(..) calling Shell_NotifyIconW(NIM_DELETE, %s)", nid)
            if not Shell_NotifyIconW(NIM_DELETE, nid):
                log.warn("Warning: failed to remove system tray")
            else:
                self.hwnd = 0
            ci = self.current_icon
            di = self.destroy_icon
            if ci and di:
                self.current_icon = None
                self.destroy_icon = None
                di(ci)
        except Exception as e:
            log("delete_tray_window()", exc_info=True)
            log.error("Error: failed to delete tray window")
            log.error(" %s", e)


    def set_blinking(self, on):
        #FIXME: implement blinking on win32 using a timer
        pass

    def set_tooltip(self, tooltip):
        log("set_tooltip(%s)", nonl(tooltip))
        self.title = tooltip
        Shell_NotifyIconW(NIM_MODIFY, self.make_nid(NIF_ICON | NIF_MESSAGE | NIF_TIP))


    def set_icon(self, iconPathName):
        log("set_icon(%s)", iconPathName)
        hicon = self.LoadImage(iconPathName) or FALLBACK_ICON
        self.do_set_icon(hicon)
        Shell_NotifyIconW(NIM_MODIFY, self.make_nid(NIF_ICON))
        self.reset_function = (self.set_icon, iconPathName)

    def do_set_icon(self, hicon, destroy_icon=None):
        log("do_set_icon(%#x)", hicon)
        ci = self.current_icon
        di = self.destroy_icon
        if ci and ci!=hicon and di:
            di(ci)
        self.current_icon = hicon
        self.destroy_icon = destroy_icon
        Shell_NotifyIconW(NIM_MODIFY, self.make_nid(NIF_ICON))

    def set_icon_from_data(self, pixels, has_alpha, w, h, rowstride, options=None):
        #this is convoluted but it works..
        log("set_icon_from_data%s", ("%s pixels" % len(pixels), has_alpha, w, h, rowstride, options))
        from PIL import Image   #@UnresolvedImport
        if has_alpha:
            img_format = "RGBA"
        else:
            img_format = "RGBX"
        rgb_format = typedict(options or {}).strget("rgb_format", "RGBA")
        img = Image.frombuffer(img_format, (w, h), pixels, "raw", rgb_format, rowstride, 1)
        assert img, "failed to load image from buffer (%i bytes for %ix%i %s)" % (len(pixels), w, h, rgb_format)
        #apparently, we have to use SM_CXSMICON (small icon) and not SM_CXICON (regular size):
        icon_w = GetSystemMetrics(win32con.SM_CXSMICON)
        icon_h = GetSystemMetrics(win32con.SM_CYSMICON)
        if w!=icon_w or h!=icon_h:
            log("resizing tray icon to %ix%i", icon_w, icon_h)
            img = img.resize((icon_w, icon_h), Image.ANTIALIAS)
            rowstride = w*4

        hicon = image_to_ICONINFO(img)
        self.do_set_icon(hicon, DestroyIcon)
        UpdateWindow(self.hwnd)
        self.reset_function = (self.set_icon_from_data, pixels, has_alpha, w, h, rowstride)

    def LoadImage(self, iconPathName):
        if not iconPathName:
            return None
        image = self.image_cache.get(iconPathName)
        if not image:
            image = self.doLoadImage(iconPathName)
            self.image_cache[iconPathName] = image
        return image

    def doLoadImage(self, iconPathName):
        mingw_prefix = os.environ.get("MINGW_PREFIX")
        if mingw_prefix and iconPathName.find(mingw_prefix)>=0:
            #python can deal with mixed win32 and unix paths,
            #but the native win32 LoadImage function cannot,
            #this happens when running from a mingw environment
            iconPathName = iconPathName.replace("/", "\\")
        icon_flags = win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE
        try:
            assert os.path.exists(iconPathName)
            img_type = win32con.IMAGE_ICON
            if iconPathName.lower().split(".")[-1] in ("png", "bmp"):
                img_type = win32con.IMAGE_BITMAP
                icon_flags |= win32con.LR_CREATEDIBSECTION | win32con.LR_LOADTRANSPARENT
            log("LoadImage(%s) using image type=%s", iconPathName,
                                        {
                                            win32con.IMAGE_ICON    : "ICON",
                                            win32con.IMAGE_BITMAP  : "BITMAP",
                                         }.get(img_type))
            v = LoadImageW(NIwc.hInstance, iconPathName, img_type, 0, 0, icon_flags)
            assert v is not None
        except:
            log.error("Error: failed to load icon '%s'", iconPathName, exc_info=True)
            return None
        else:
            log("LoadImage(%s)=%#x", iconPathName, v)
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
        cb = self.command_callback
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
            bm = [(hwnd, int(msg), int(wparam), int(lparam))]
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
            except KeyError:
                pass


WM_TRAY_EVENT = win32con.WM_MENUCOMMAND     #a message id we choose
TASKBAR_CREATED = RegisterWindowMessageA("TaskbarCreated")
message_map = {
    TASKBAR_CREATED                     : win32NotifyIcon.OnTrayRestart,
    win32con.WM_DESTROY                 : win32NotifyIcon.OnDestroy,
    win32con.WM_COMMAND                 : win32NotifyIcon.OnCommand,
    WM_TRAY_EVENT                       : win32NotifyIcon.OnTaskbarNotify,
}
def NotifyIconWndProc(hwnd, msg, wParam, lParam):
    instance = win32NotifyIcon.instances.get(hwnd)
    fn = message_map.get(msg)
    def i(v):
        try:
            return int(v)
        except:
            return v
    log("NotifyIconWndProc%s instance=%s, message(%i)=%s", (i(hwnd), i(msg), i(wParam), i(lParam)), instance, msg, fn)
    #log("potential matching win32 constants for message: %s", [x for x in dir(win32con) if getattr(win32con, x)==msg])
    if instance and fn:
        return fn(instance, hwnd, msg, wParam, lParam) or 0
    return DefWindowProcA(hwnd, msg, wParam, lParam)

NIwc = WNDCLASSEX()
NIwc.cbSize = sizeof(WNDCLASSEX)
NIwc.style = win32con.CS_HREDRAW | win32con.CS_VREDRAW
NIwc.lpfnWndProc = WNDPROC(NotifyIconWndProc)
NIwc.hInstance = GetModuleHandleA(0)
NIwc.hBrush = GetStockObject(win32con.WHITE_BRUSH)
NIwc.lpszClassName = u"win32NotifyIcon"

NIclassAtom = RegisterClassExA(byref(NIwc))
log("RegisterClassExA(%s)=%i", NIwc.lpszClassName, NIclassAtom)
if NIclassAtom==0:
    raise ctypes.WinError(ctypes.get_last_error())


def main():
    from xpra.platform.win32.common import user32

    def click_callback(button, pressed):
        menu = CreatePopupMenu()
        AppendMenu(menu, win32con.MF_STRING, 1024, u"Generate balloon")
        AppendMenu(menu, win32con.MF_STRING, 1025, u"Exit")
        pos = POINT()
        GetCursorPos(byref(pos))
        hwnd = tray.hwnd
        user32.SetForegroundWindow(hwnd)
        user32.TrackPopupMenu(menu, win32con.TPM_LEFTALIGN, pos.x, pos.y, 0, hwnd, None)
        PostMessageA(hwnd, win32con.WM_NULL, 0, 0)

    def command_callback(hwnd, cid):
        if cid == 1024:
            from xpra.platform.win32.win32_balloon import notify
            try:
                from PIL import Image   #@UnresolvedImport
                from io import BytesIO
                img = Image.open("icons\\printer.png")
                buf = BytesIO()
                img.save(buf, "PNG")
                data = buf.getvalue()
                buf.close()
                icon = (b"png", img.size[0], img.size[1], data)
            except Exception as e:
                print("could not find icon: %s" % (e,))
                icon = None
            else:
                pass
            notify(hwnd, 0, "hello", "world", timeout=1000, icon=icon)
        elif cid == 1025:
            print("Goodbye")
            DestroyWindow(hwnd)
        else:
            print("OnCommand for ID=%s" % cid)

    def win32_quit():
        PostQuitMessage(0) # Terminate the app.

    from xpra.platform.paths import get_app_dir
    idir = os.path.abspath(get_app_dir())
    wdir = os.path.join(idir, "icons")
    if os.path.exists(wdir):
        idir = wdir
    iconPathName = os.path.join(idir, "xpra.ico")
    tray = win32NotifyIcon(0, "test", move_callbacks=None, click_callback=click_callback, exit_callback=win32_quit, command_callback=command_callback, iconPathName=iconPathName)
    #pump messages:
    msg = ctypes.wintypes.MSG()
    pMsg = ctypes.pointer(msg)
    while user32.GetMessageA(pMsg, win32con.NULL, 0, 0) != 0:
        user32.TranslateMessage(pMsg)
        user32.DispatchMessageA(pMsg)


if __name__=='__main__':
    main()
