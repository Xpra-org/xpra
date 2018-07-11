#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2017-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from ctypes import WinDLL, POINTER, WINFUNCTYPE, GetLastError, Structure, c_ulong, c_ushort, c_ubyte, c_int, c_long, c_void_p, c_size_t, c_char, byref, sizeof
from ctypes.wintypes import HWND, DWORD, WPARAM, LPARAM, HDC, HMONITOR, HMODULE, SHORT, ATOM, RECT, POINT, MAX_PATH, WCHAR, BYTE
from ctypes.wintypes import HANDLE, LPCWSTR, UINT, INT, BOOL, WORD, HGDIOBJ, LONG, LPVOID, HBITMAP, LPCSTR, LPWSTR, HWINSTA, HINSTANCE, HMENU
#imported from this module but not used here:
assert GetLastError

LPCTSTR = LPCSTR
LRESULT = c_long
DEVMODE = c_void_p
PDWORD = POINTER(DWORD)
LPDWORD = POINTER(DWORD)
PBYTE = POINTER(BYTE)
HCURSOR = HANDLE
HICON = HANDLE
HBRUSH = HANDLE

class CURSORINFO(Structure):
    _fields_ = [
        ("cbSize",          DWORD),
        ("flags",           DWORD),
        ("hCursor",         HCURSOR),
        ("ptScreenPos",     POINT),
    ]

class ICONINFO(Structure):
    _fields_ = [
        ("fIcon",           BOOL),
        ("xHotspot",        DWORD),
        ("yHotspot",        DWORD),
        ("hbmMask",         HBITMAP),
        ("hbmColor",        HBITMAP),
    ]
PICONINFO = POINTER(ICONINFO)

class ICONINFOEXA(Structure):
    _fields_ = [
        ("cbSize",          DWORD),
        ("fIcon",           BOOL),
        ("xHotspot",        DWORD),
        ("yHotspot",        DWORD),
        ("hbmMask",         HBITMAP),
        ("hbmColor",        HBITMAP),
        ("wResID",          WORD),
        ("sxModName",       c_char*MAX_PATH),
        ("szResName",       c_char*MAX_PATH),
    ]
PICONINFOEXA = POINTER(ICONINFOEXA)
class ICONINFOEXW(Structure):
    _fields_ = [
        ("cbSize",          DWORD),
        ("fIcon",           BOOL),
        ("xHotspot",        DWORD),
        ("yHotspot",        DWORD),
        ("hbmMask",         HBITMAP),
        ("hbmColor",        HBITMAP),
        ("wResID",          WORD),
        ("sxModName",       WCHAR*MAX_PATH),
        ("szResName",       WCHAR*MAX_PATH),
    ]
PICONINFOEXW = POINTER(ICONINFOEXW)

class Bitmap(Structure):
    _fields_ = [
        ("bmType",          LONG),
        ("bmWidth",         LONG),
        ("bmHeight",        LONG),
        ("bmWidthBytes",    LONG),
        ("bmPlanes",        WORD),
        ("bmBitsPixel",     WORD),
        ("bmBits",          LPVOID)
        ]

class CIEXYZ(Structure):
    _fields_ = [
        ('ciexyzX', DWORD),
        ('ciexyzY', DWORD),
        ('ciexyzZ', DWORD),
    ]

class CIEXYZTRIPLE(Structure):
    _fields_ = [
        ('ciexyzRed',   CIEXYZ),
        ('ciexyzBlue',  CIEXYZ),
        ('ciexyzGreen', CIEXYZ),
    ]

class BITMAPV5HEADER(Structure):
    _fields_ = [
        ('bV5Size',             DWORD),
        ('bV5Width',            LONG),
        ('bV5Height',           LONG),
        ('bV5Planes',           WORD),
        ('bV5BitCount',         WORD),
        ('bV5Compression',      DWORD),
        ('bV5SizeImage',        DWORD),
        ('bV5XPelsPerMeter',    LONG),
        ('bV5YPelsPerMeter',    LONG),
        ('bV5ClrUsed',          DWORD),
        ('bV5ClrImportant',     DWORD),
        ('bV5RedMask',          DWORD),
        ('bV5GreenMask',        DWORD),
        ('bV5BlueMask',         DWORD),
        ('bV5AlphaMask',        DWORD),
        ('bV5CSType',           DWORD),
        ('bV5Endpoints',        CIEXYZTRIPLE),
        ('bV5GammaRed',         DWORD),
        ('bV5GammaGreen',       DWORD),
        ('bV5GammaBlue',        DWORD),
        ('bV5Intent',           DWORD),
        ('bV5ProfileData',      DWORD),
        ('bV5ProfileSize',      DWORD),
        ('bV5Reserved',         DWORD),
    ]

CCHDEVICENAME = 32
class MONITORINFOEX(Structure):
    _fields_ = [
        ('cbSize', DWORD),
        ('rcMonitor', RECT),
        ('rcWork', RECT),
        ('dwFlags', DWORD),
        ('szDevice', WCHAR * CCHDEVICENAME),
        ]

def GetMonitorInfo(hmonitor):
    info = MONITORINFOEX()
    info.szDevice = ""
    info.cbSize = sizeof(MONITORINFOEX)
    if not GetMonitorInfoW(hmonitor, byref(info)):
        raise WindowsError()
    monitor = info.rcMonitor.left, info.rcMonitor.top, info.rcMonitor.right, info.rcMonitor.bottom
    work = info.rcWork.left, info.rcWork.top, info.rcWork.right, info.rcWork.bottom
    return  {
        "Work"      : work,
        "Monitor"   : monitor,
        "Flags"     : info.dwFlags,
        "Device"    : info.szDevice or "",
        }

kernel32 = WinDLL("kernel32", use_last_error=True)
SetConsoleTitleA = kernel32.SetConsoleTitleA
SetConsoleTitleA.restype = INT
SetConsoleTitleA.argtypes = [LPCTSTR] 
GetConsoleScreenBufferInfo = kernel32.GetConsoleScreenBufferInfo
GetModuleHandleA = kernel32.GetModuleHandleA
GetModuleHandleA.restype = HMODULE
GetModuleHandleW = kernel32.GetModuleHandleW
GetModuleHandleW.restype = HMODULE
SetConsoleCtrlHandler = kernel32.SetConsoleCtrlHandler
GetComputerNameW = kernel32.GetComputerNameW
GetComputerNameW.restype = BOOL
GetComputerNameW.argtypes = [LPWSTR, LPDWORD]
GetCurrentProcess = kernel32.GetCurrentProcess
GetCurrentProcess.argtypes = []
GetCurrentProcess.restype = HANDLE
HeapAlloc = kernel32.HeapAlloc
HeapAlloc.restype = LPVOID
HeapAlloc.argtypes = [HANDLE, DWORD, c_size_t]
GetProcessHeap = kernel32.GetProcessHeap
GetProcessHeap.restype = HANDLE
GetProcessHeap.argtypes = []
CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [HANDLE]
CloseHandle.restype = BOOL
GetProductInfo = kernel32.GetProductInfo
GetProductInfo.argtypes = [DWORD, DWORD, DWORD, DWORD, PDWORD]
GetProductInfo.restype  = BOOL

user32 = WinDLL("user32", use_last_error=True)
RegisterClassExA = user32.RegisterClassExA
RegisterClassExA.restype = ATOM
RegisterClassExW = user32.RegisterClassExW
RegisterClassExW.restype = ATOM
UnregisterClassA = user32.UnregisterClassA
UnregisterClassA.restype = BOOL
#painful to convert to LPCSTR, so don't bother:
#UnregisterClassA.argtypes = [LPCSTR, HINSTANCE]
UnregisterClassW = user32.UnregisterClassW
UnregisterClassW.restype = BOOL
UnregisterClassW.argtypes = [LPCWSTR, HINSTANCE]
CreateWindowExA = user32.CreateWindowExA
CreateWindowExA.restype = HWND
DestroyWindow = user32.DestroyWindow
DestroyWindow.restype = BOOL
DestroyWindow.argtypes = [HWND] 
DefWindowProcA = user32.DefWindowProcA
DefWindowProcW = user32.DefWindowProcW
MessageBoxA = user32.MessageBoxA
MessageBoxA.restype = INT
MessageBoxA.argtypes = [HWND, LPCTSTR, LPCTSTR, UINT]
GetSystemMetrics = user32.GetSystemMetrics
GetSystemMetrics.restype = INT
GetSystemMetrics.argtypes = [INT]
SetWindowLongW = user32.SetWindowLongW
GetWindowLongW = user32.GetWindowLongW
ClipCursor = user32.ClipCursor
ClipCursor.restype = BOOL
GetCursorPos = user32.GetCursorPos
SetCursorPos = user32.SetCursorPos
GetPhysicalCursorPos = user32.GetPhysicalCursorPos
GetPhysicalCursorPos.argtypes = [POINTER(POINT)]
GetPhysicalCursorPos.restype = BOOL
SetPhysicalCursorPos = user32.SetPhysicalCursorPos
SetPhysicalCursorPos.argtypes = [INT, INT]
SetPhysicalCursorPos.restype = BOOL
GetCursorInfo = user32.GetCursorInfo
GetCursorInfo.argtypes = [POINTER(CURSORINFO)]
GetCursorInfo.restype = BOOL
LogicalToPhysicalPoint = user32.LogicalToPhysicalPoint
LogicalToPhysicalPoint.argtypes = [HWND, POINTER(POINT)]
LogicalToPhysicalPoint.restype = BOOL
SendMessageA = user32.SendMessageA
PostMessageA = user32.PostMessageA
FindWindowA = user32.FindWindowA
GetWindowRect = user32.GetWindowRect
GetDoubleClickTime = user32.GetDoubleClickTime
EnumDisplayMonitors = user32.EnumDisplayMonitors
MonitorFromWindow = user32.MonitorFromWindow
MonitorFromWindow.restype = HMONITOR
GetMonitorInfoW = user32.GetMonitorInfoW
GetMonitorInfoW.argtypes = [HMONITOR, POINTER(MONITORINFOEX)]
GetMonitorInfoW.restype = BOOL
UnhookWindowsHookEx = user32.UnhookWindowsHookEx
CallNextHookEx = user32.CallNextHookEx
SetWindowsHookExA = user32.SetWindowsHookExA
GetMessageA = user32.GetMessageA
TranslateMessage = user32.TranslateMessage
DispatchMessageA = user32.DispatchMessageA
MapVirtualKeyW = user32.MapVirtualKeyW
GetKeyboardState = user32.GetKeyboardState
GetKeyboardState.argtypes = [PBYTE]
GetKeyboardState.restype = BOOL
SetKeyboardState = user32.SetKeyboardState
SetKeyboardState.argtypes = [PBYTE]
SetKeyboardState.restype = BOOL
GetAsyncKeyState = user32.GetAsyncKeyState
GetAsyncKeyState.argtypes = [INT]
GetAsyncKeyState.restype = SHORT
VkKeyScanW = user32.VkKeyScanW
VkKeyScanW.argtypes = [WCHAR]
keybd_event = user32.keybd_event
GetKeyState = user32.GetKeyState
GetKeyState.restype = SHORT
GetKeyboardLayout = user32.GetKeyboardLayout
GetKeyboardLayoutList = user32.GetKeyboardLayoutList
GetKeyboardLayoutList.argtypes = [c_int, POINTER(HANDLE*32)]
SystemParametersInfoA = user32.SystemParametersInfoA
EnumWindows = user32.EnumWindows
EnumWindowsProc = WINFUNCTYPE(BOOL, HWND, LPARAM)
IsWindowVisible = user32.IsWindowVisible
GetWindowTextLengthW = user32.GetWindowTextLengthW
GetWindowTextW = user32.GetWindowTextW
GetWindowThreadProcessId = user32.GetWindowThreadProcessId
GetWindowThreadProcessId.restype = DWORD
GetDesktopWindow = user32.GetDesktopWindow
GetDesktopWindow.restype = HWND
GetWindowDC = user32.GetWindowDC
GetWindowDC.argtypes = [HWND]
GetWindowDC.restype = HDC
ReleaseDC = user32.ReleaseDC
ReleaseDC.restype = c_int
ReleaseDC.argtypes = [HWND, HDC]
mouse_event = user32.mouse_event
LoadIconA = user32.LoadIconA
LoadIconA.restype = HICON
#can also pass int as second arg, so don't declare argtypes:
#LoadIconA.argtypes = [HINSTANCE, LPCSTR]
RegisterWindowMessageA = user32.RegisterWindowMessageA
UpdateWindow = user32.UpdateWindow
DestroyIcon = user32.DestroyIcon
DestroyIcon.restype = BOOL
DestroyIcon.argtypes = [HICON]
LoadImageW = user32.LoadImageW
LoadImageW.argtypes = [HINSTANCE, LPCWSTR, UINT, INT, INT, UINT]
LoadImageW.restype = HANDLE
CreateIconIndirect = user32.CreateIconIndirect
CreateIconIndirect.restype = HICON
CreateIconIndirect.argtypes = [POINTER(ICONINFO)]
GetDC = user32.GetDC
GetDC.argtypes = [HWND]
GetDC.restype = HDC
ReleaseDC = user32.ReleaseDC
ReleaseDC.argtypes = [HWND, HDC]
ReleaseDC.restype = c_int
DrawIcon = user32.DrawIcon
DrawIcon.argtypes = [HDC, INT, INT, HICON]
DrawIcon.restype = BOOL
DrawIconEx = user32.DrawIconEx
DrawIconEx.argtypes = [HDC, INT, INT, HICON, INT, INT, UINT, HBRUSH, UINT]
DrawIconEx.restype = BOOL
GetIconInfo = user32.GetIconInfo
GetIconInfo.argtypes = [HICON, PICONINFO]
GetIconInfo.restype = BOOL
GetIconInfoExA = user32.GetIconInfoExA
GetIconInfoExA.argtypes = [HICON, PICONINFOEXA]
GetIconInfoExA.restype = BOOL
GetIconInfoExW = user32.GetIconInfoExW
GetIconInfoExW.argtypes = [HICON, PICONINFOEXW]
GetIconInfoExW.restype = BOOL
CopyIcon = user32.CopyIcon
CopyIcon.argtypes = [HICON]
CopyIcon.restype = HICON
PostQuitMessage = user32.PostQuitMessage
PostQuitMessage.argtypes = [INT]
OpenWindowStationW = user32.OpenWindowStationW
OpenWindowStationW.restype = HWINSTA
ACCESS_MASK = DWORD
OpenWindowStationW.argtypes = [LPWSTR, BOOL, ACCESS_MASK]
GetProcessWindowStation = user32.GetProcessWindowStation
GetProcessWindowStation.restype = HWINSTA
GetProcessWindowStation.argtypes = []
SetProcessWindowStation = user32.SetProcessWindowStation
SetProcessWindowStation.restype = BOOL
SetProcessWindowStation.argtypes = [HWINSTA]
CloseWindowStation = user32.CloseWindowStation
CloseWindowStation.restype = BOOL
CloseWindowStation.argtypes = [HWINSTA]
HDESK = HANDLE
OpenDesktopW = user32.OpenDesktopW
OpenDesktopW.restype = HDESK
OpenDesktopW.argtypes = [LPWSTR, DWORD, BOOL, ACCESS_MASK]
CloseDesktop = user32.CloseDesktop
CloseDesktop.restype = BOOL
CloseDesktop.argtypes = [HDESK]
OpenInputDesktop = user32.OpenInputDesktop
OpenInputDesktop.restype = HDESK
OpenInputDesktop.argtypes = [DWORD, BOOL, ACCESS_MASK] 
GetUserObjectInformationA = user32.GetUserObjectInformationA
GetUserObjectInformationA.restype = BOOL
GetUserObjectInformationA.argtypes = [HANDLE, INT, LPVOID, DWORD, LPDWORD]
CreatePopupMenu = user32.CreatePopupMenu
CreatePopupMenu.restype = HMENU
CreatePopupMenu.argtypes = []
AppendMenu = user32.AppendMenuW
AppendMenu.restype = BOOL
AppendMenu.argtypes = [HMENU, UINT, UINT, LPCWSTR]

gdi32 = WinDLL("gdi32", use_last_error=True)
CreateCompatibleDC = gdi32.CreateCompatibleDC
CreateCompatibleDC.argtypes = [HDC]
CreateCompatibleDC.restype = HDC
CreateCompatibleBitmap = gdi32.CreateCompatibleBitmap
CreateCompatibleBitmap.argtypes = [HDC, c_int, c_int]
CreateCompatibleBitmap.restype = HBITMAP
CreateBitmap = gdi32.CreateBitmap
CreateBitmap.argtypes = [INT, INT, UINT, UINT, POINTER(c_void_p)]
CreateBitmap.restype = HBITMAP
GetBitmapBits = gdi32.GetBitmapBits
GetBitmapBits.argtypes = [HGDIOBJ, LONG, LPVOID]
GetBitmapBits.restype  = LONG
SelectObject = gdi32.SelectObject
SelectObject.argtypes = [HDC, HGDIOBJ]
SelectObject.restype = HGDIOBJ
BitBlt = gdi32.BitBlt
BitBlt.argtypes = [HDC, c_int, c_int, c_int, c_int, HDC, c_int, c_int, DWORD]
BitBlt.restype = BOOL
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
CreateDIBSection.restype = HBITMAP
CreateDIBSection.argtypes = [HANDLE, POINTER(BITMAPV5HEADER), UINT, POINTER(c_void_p), HANDLE, DWORD]
DeleteObject = gdi32.DeleteObject
DeleteObject.argtypes = [HGDIOBJ]
DeleteObject.restype = BOOL
DeleteDC = gdi32.DeleteDC
DeleteDC.restype = BOOL
DeleteDC.argtypes = [HDC]
CreateDCA = gdi32.CreateDCA
CreateDCA.restype = HDC
CreateDCA.argtypes = [LPCSTR, LPCSTR, LPCSTR, DEVMODE]
ChoosePixelFormat = gdi32.ChoosePixelFormat
ChoosePixelFormat.argtypes = [HDC, c_void_p]
ChoosePixelFormat.restype = c_int
GetPixelFormat = gdi32.GetPixelFormat
GetPixelFormat.argtypes = [HDC]
GetPixelFormat.restype = c_int
SetPixelFormat = gdi32.SetPixelFormat
SetPixelFormat.argtypes = [HDC, c_int, c_void_p]
SetPixelFormat.restype = BOOL
DescribePixelFormat = gdi32.DescribePixelFormat
DescribePixelFormat.argtypes = [HDC, c_int, UINT, c_void_p]
DescribePixelFormat.restype = c_int
SwapBuffers = gdi32.SwapBuffers
SwapBuffers.argtypes = [HDC]
SwapBuffers.restype = BOOL
BeginPaint = user32.BeginPaint
BeginPaint.argtypes = [HWND, c_void_p]
BeginPaint.restype = HDC
EndPaint = user32.EndPaint
EndPaint.argtypes = [HWND, c_void_p]
EndPaint.restype = HDC
GetObjectA = gdi32.GetObjectA
GetObjectA.argtypes = [HGDIOBJ, INT, LPVOID]
GetObjectA.restype = INT

#wrap EnumDisplayMonitors to hide the callback function:
MonitorEnumProc = WINFUNCTYPE(BOOL, HMONITOR, HDC, POINTER(RECT), LPARAM)
EnumDisplayMonitors.argtypes = [HDC, POINTER(RECT), MonitorEnumProc, LPARAM]
EnumDisplayMonitors.restype = BOOL
_EnumDisplayMonitors = EnumDisplayMonitors
def EnumDisplayMonitors():
    results = []
    def _callback(monitor, dc, rect, data):
        results.append(monitor)
        return 1
    callback = MonitorEnumProc(_callback)
    _EnumDisplayMonitors(0, 0, callback, 0)
    return results

def GetIntSystemParametersInfo(key):
    rv = INT()
    r = SystemParametersInfoA(key, 0, byref(rv), 0)
    if r==0:
        return None
    return rv.value


WNDPROC = WINFUNCTYPE(LRESULT, HWND, UINT, WPARAM, LPARAM)

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

#GUID = c_ubyte * 16
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
