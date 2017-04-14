#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import ctypes

from ctypes import WinDLL, Structure, c_ulong, c_ushort, c_ubyte, c_int, c_uint, c_double
from ctypes.wintypes import HWND, DWORD, WPARAM, LPARAM, HDC, HMONITOR, HMODULE, SHORT, ATOM, POINTER, RECT
from ctypes.wintypes import HANDLE, LPCWSTR, UINT, INT, WINFUNCTYPE, BOOL, HGDIOBJ, LONG, LPVOID, HBITMAP

kernel32 = WinDLL("kernel32", use_last_error=True)
SetConsoleTitleA = kernel32.SetConsoleTitleA
GetConsoleScreenBufferInfo = kernel32.GetConsoleScreenBufferInfo
GetModuleHandleA = kernel32.GetModuleHandleA
GetModuleHandleA.restype = HMODULE
SetConsoleCtrlHandler = kernel32.SetConsoleCtrlHandler

user32 = WinDLL("user32", use_last_error=True)
RegisterClassExW = user32.RegisterClassExW
RegisterClassExW.restype = ATOM
CreateWindowExA = user32.CreateWindowExA
CreateWindowExA.restype = HWND
UnregisterClassW = user32.UnregisterClassW
DestroyWindow = user32.DestroyWindow
DefWindowProcW = user32.DefWindowProcW
MessageBoxA = user32.MessageBoxA
GetLastError = ctypes.GetLastError
GetSystemMetrics = user32.GetSystemMetrics
SetWindowLongW = user32.SetWindowLongW
GetWindowLongW = user32.GetWindowLongW
ClipCursor = user32.ClipCursor
GetCursorPos = user32.GetCursorPos
SetCursorPos = user32.SetCursorPos
SendMessageA = user32.SendMessageA
PostMessageA = user32.PostMessageA
FindWindowA = user32.FindWindowA
GetWindowRect = user32.GetWindowRect
GetDoubleClickTime = user32.GetDoubleClickTime
EnumDisplayMonitors = user32.EnumDisplayMonitors
MonitorFromWindow = user32.MonitorFromWindow
MonitorFromWindow.restype = HMONITOR
GetMonitorInfoW = user32.GetMonitorInfoW
UnhookWindowsHookEx = user32.UnhookWindowsHookEx
CallNextHookEx = user32.CallNextHookEx
SetWindowsHookExA = user32.SetWindowsHookExA
GetMessageA = user32.GetMessageA
TranslateMessage = user32.TranslateMessage
DispatchMessageA = user32.DispatchMessageA
MapVirtualKeyW = user32.MapVirtualKeyW
GetAsyncKeyState = user32.GetAsyncKeyState
VkKeyScanW = user32.VkKeyScanW
VkKeyScanW.argtypes = [ctypes.c_wchar]
keybd_event = user32.keybd_event
GetKeyState = user32.GetKeyState
GetKeyState.restype = SHORT
GetKeyboardLayout = user32.GetKeyboardLayout
GetKeyboardLayoutList = user32.GetKeyboardLayoutList
GetKeyboardLayoutList.argtypes = [c_int, POINTER(HANDLE*32)]
SystemParametersInfoA = user32.SystemParametersInfoA
EnumWindows = user32.EnumWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(BOOL, HWND, LPARAM)
IsWindowVisible = user32.IsWindowVisible
GetWindowTextLengthW = user32.GetWindowTextLengthW
GetWindowTextW = user32.GetWindowTextW
GetWindowThreadProcessId = user32.GetWindowThreadProcessId
GetWindowThreadProcessId.restype = DWORD
GetDesktopWindow = user32.GetDesktopWindow
GetDesktopWindow.restype = HWND
GetWindowDC = user32.GetWindowDC
GetWindowDC.restype = HWND
mouse_event = user32.mouse_event
LoadIconA = user32.LoadIconA
RegisterWindowMessageA = user32.RegisterWindowMessageA
UpdateWindow = user32.UpdateWindow
DestroyIcon = user32.DestroyIcon
LoadImageW = user32.LoadImageW
CreateIconIndirect = user32.CreateIconIndirect
GetDC = user32.GetDC
GetDC.argtypes = [HWND]
GetDC.restype = HDC
ReleaseDC = user32.ReleaseDC
PostQuitMessage = user32.PostQuitMessage

gdi32 = WinDLL("gdi32", use_last_error=True)
CreateCompatibleDC = gdi32.CreateCompatibleDC
CreateCompatibleDC.restype = HDC
CreateCompatibleBitmap = gdi32.CreateCompatibleBitmap
CreateCompatibleBitmap.restype = HBITMAP
CreateBitmap = gdi32.CreateBitmap
CreateBitmap.restype = HBITMAP
GetBitmapBits = gdi32.GetBitmapBits
GetBitmapBits.argtypes = [HGDIOBJ, LONG, LPVOID]
GetBitmapBits.restype  = LONG
SelectObject = gdi32.SelectObject
SelectObject.argtypes = [HDC, HGDIOBJ]
SelectObject.restype = HGDIOBJ
BitBlt = gdi32.BitBlt
GetDeviceCaps = gdi32.GetDeviceCaps
GetDeviceCaps.argtypes = [HDC, c_int]
GetDeviceCaps.restype = c_int
GetSystemPaletteEntries = gdi32.GetSystemPaletteEntries
GetSystemPaletteEntries.restype = UINT
GetStockObject = gdi32.GetStockObject
GetStockObject.restype = HGDIOBJ
SetPixelV = gdi32.SetPixelV
DeleteDC = gdi32.DeleteDC
CreateDIBSection = gdi32.CreateDIBSection
DeleteObject = gdi32.DeleteObject


#wrap EnumDisplayMonitors to hide the callback function:
MonitorEnumProc = ctypes.WINFUNCTYPE(c_int, c_ulong, c_ulong, POINTER(RECT), c_double)
_EnumDisplayMonitors = EnumDisplayMonitors
def EnumDisplayMonitors():
    results = []
    def _callback(monitor, dc, rect, data):
        results.append(monitor)
        return 1
    callback = MonitorEnumProc(_callback)
    _EnumDisplayMonitors(0, 0, callback, 0)
    return results


WNDPROC = WINFUNCTYPE(c_int, HANDLE, c_uint, WPARAM, LPARAM)

class WNDCLASSEX(Structure):
    _fields_ = [
        ("cbSize",          UINT),
        ("style",           UINT),
        ("lpfnWndProc",     WNDPROC),
        ("cbClsExtra",      INT),
        ("cbWndExtra",      INT),
        ("hInstance",       HANDLE),
        ("hIcon",           HANDLE),
        ("hCursor",         HANDLE),
        ("hbrBackground",   HANDLE),
        ("lpszMenuName",    LPCWSTR),
        ("lpszClassName",   LPCWSTR),
        ("hIconSm",         HANDLE),
    ]

#GUID = ctypes.c_ubyte * 16
class GUID(Structure):
    _fields_ = [
        ('Data1', c_ulong),
        ('Data2', c_ushort),
        ('Data3', c_ushort),
        ('Data4', c_ubyte*8),
    ]
    def __str__(self):
        return "{%08x-%04x-%04x-%s-%s}" % (
            self.Data1,
            self.Data2,
            self.Data3,
            ''.join(["%02x" % d for d in self.Data4[:2]]),
            ''.join(["%02x" % d for d in self.Data4[2:]]),
        )

IID = GUID
REFIID = POINTER(IID)
