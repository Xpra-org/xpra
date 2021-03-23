# This file is part of Xpra.
# Copyright (C) 2019-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from io import BytesIO
from ctypes import (
    sizeof, byref, cast, memset, memmove,
    get_last_error, create_string_buffer,
    WinError, FormatError,
    c_char, c_void_p,
    )
from gi.repository import GLib

from xpra.platform.win32.common import (
    GetDC, ReleaseDC,
    WNDCLASSEX, GetLastError,
    WNDPROC, LPCWSTR, LPWSTR, LPCSTR, DWORD,
    BITMAPINFOHEADER, PBITMAPV5HEADER, BITMAPINFO,
    DefWindowProcW,
    GetModuleHandleA, RegisterClassExW, UnregisterClassW,
    CreateWindowExW, DestroyWindow,
    OpenClipboard, EmptyClipboard, CloseClipboard, GetClipboardData,
    GlobalLock, GlobalUnlock, GlobalAlloc, GlobalFree, GlobalSize,
    WideCharToMultiByte, MultiByteToWideChar,
    AddClipboardFormatListener, RemoveClipboardFormatListener,
    SetClipboardData, EnumClipboardFormats, GetClipboardFormatNameA, GetClipboardOwner,
    RegisterClipboardFormatA,
    GetWindowThreadProcessId, QueryFullProcessImageNameA, OpenProcess, CloseHandle,
    CreateDIBitmap,
    )
from xpra.platform.win32 import win32con
from xpra.clipboard.clipboard_timeout_helper import ClipboardTimeoutHelper
from xpra.clipboard.clipboard_core import (
    ClipboardProxyCore, log, _filter_targets,
    TEXT_TARGETS, MAX_CLIPBOARD_PACKET_SIZE,
    )
from xpra.util import csv, ellipsizer, envint, envbool, roundup
from xpra.os_util import bytestostr, strtobytes
from xpra.platform.win32.constants import PROCESS_QUERY_INFORMATION

CP_UTF8 = 65001
MB_ERR_INVALID_CHARS = 0x00000008
GMEM_MOVEABLE = 0x0002

WM_CLIPBOARDUPDATE = 0x031D

CLIPBOARD_EVENTS = {
    win32con.WM_CLEAR               : "CLEAR",
    win32con.WM_CUT                 : "CUT",
    win32con.WM_COPY                : "COPY",
    win32con.WM_PASTE               : "PASTE",
    win32con.WM_ASKCBFORMATNAME     : "ASKCBFORMATNAME",
    win32con.WM_CHANGECBCHAIN       : "CHANGECBCHAIN",
    WM_CLIPBOARDUPDATE              : "CLIPBOARDUPDATE",
    win32con.WM_DESTROYCLIPBOARD    : "DESTROYCLIPBOARD",
    win32con.WM_DRAWCLIPBOARD       : "DRAWCLIPBOARD",
    win32con.WM_HSCROLLCLIPBOARD    : "HSCROLLCLIPBOARD",
    win32con.WM_PAINTCLIPBOARD      : "PAINTCLIPBOARD",
    win32con.WM_RENDERALLFORMATS    : "RENDERALLFORMATS",
    win32con.WM_RENDERFORMAT        : "RENDERFORMAT",
    win32con.WM_SIZECLIPBOARD       : "SIZECLIPBOARD",
    win32con.WM_VSCROLLCLIPBOARD    : "WM_VSCROLLCLIPBOARD",
    }

CLIPBOARD_FORMATS = {
    win32con.CF_BITMAP      : "CF_BITMAP",
    win32con.CF_DIB         : "CF_DIB",
    win32con.CF_DIBV5       : "CF_DIBV5",
    win32con.CF_ENHMETAFILE : "CF_ENHMETAFILE",
    win32con.CF_METAFILEPICT: "CF_METAFILEPICT",
    win32con.CF_OEMTEXT     : "CF_OEMTEXT",
    win32con.CF_TEXT        : "CF_TEXT",
    win32con.CF_UNICODETEXT : "CF_UNICODETEXT",
    }

BI_RGB = 0x0000
BI_RLE8 = 0x0001
BI_RLE4 = 0x0002
BI_BITFIELDS = 0x0003
BI_JPEG = 0x0004
BI_PNG = 0x0005
BI_CMYK = 0x000B
BI_CMYKRLE8 = 0x000C
BI_CMYKRLE4 = 0x000D
BI_FORMATS = {
    BI_RGB : "RGB",
    BI_RLE8 : "RLE8",
    BI_RLE4 : "RLE4",
    BI_BITFIELDS : "BITFIELDS",
    BI_JPEG : "JPEG",
    BI_PNG : "PNG",
    BI_CMYK : "CMYK",
    BI_CMYKRLE8 : "CMYKRLE8",
    BI_CMYKRLE4 : "CMYKRLE4",
    }

LCS_CALIBRATED_RGB = 0x00000000
LCS_sRGB = 0x73524742
LCS_WINDOWS_COLOR_SPACE = 0x57696E20
PROFILE_LINKED = 3
PROFILE_EMBEDDED = 4
COLOR_PROFILES = {
    LCS_CALIBRATED_RGB  : "CALIBRATED_RGB",
    LCS_sRGB            : "sRGB",
    LCS_WINDOWS_COLOR_SPACE : "WINDOWS",
    PROFILE_LINKED      : "PROFILE_LINKED",
    PROFILE_EMBEDDED    : "PROFILE_EMBEDDED",
    }

RETRY = envint("XPRA_CLIPBOARD_RETRY", 5)
DELAY = envint("XPRA_CLIPBOARD_INITIAL_DELAY", 10)
CONVERT_LINE_ENDINGS = envbool("XPRA_CONVERT_LINE_ENDINGS", True)
log("win32 clipboard: RETRY=%i, DELAY=%i, CONVERT_LINE_ENDINGS=%s",
    RETRY, DELAY, CONVERT_LINE_ENDINGS)
#can be used to blacklist problematic clipboard peers:
#ie: VBoxTray.exe
BLACKLISTED_CLIPBOARD_CLIENTS = [x for x in
                                 os.environ.get("XPRA_BLACKLISTED_CLIPBOARD_CLIENTS", "").split(",")
                                 if x]
log("BLACKLISTED_CLIPBOARD_CLIENTS=%s", BLACKLISTED_CLIPBOARD_CLIENTS)
COMPRESSED_IMAGES = envbool("XPRA_CLIPBOARD_COMPRESSED_IMAGES", True)

CLIPBOARD_WINDOW_CLASS_NAME = "XpraWin32Clipboard"


def is_blacklisted(owner_info):
    return any(owner_info.find(x)>=0 for x in BLACKLISTED_CLIPBOARD_CLIENTS)

#initialize the window we will use
#for communicating with the OS clipboard API:

def get_owner_info(owner, our_window):
    if not owner:
        return "unknown"
    if owner==our_window:
        return "our window (hwnd=%#x)" % our_window
    pid = DWORD(0)
    GetWindowThreadProcessId(owner, byref(pid))
    if not pid:
        return "unknown (hwnd=%#x)" % owner
    #log("get_owner_info(%#x) pid=%s", owner, pid.value)
    proc_handle = OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
    if not proc_handle:
        return "pid %i (hwnd=%#x)" % (pid.value, owner)
    try:
        size = DWORD(256)
        process_name = create_string_buffer(size.value+1)
        if not QueryFullProcessImageNameA(proc_handle, 0, process_name, byref(size)):
            return "pid %i" % pid.value
        return "'%s' with pid %s (hwnd=%#x)" % (bytestostr(process_name.value), pid.value, owner)
    finally:
        CloseHandle(proc_handle)

def with_clipboard_lock(window, success_callback, failure_callback, retries=RETRY, delay=DELAY):
    log("with_clipboard_lock%s", (window, success_callback, failure_callback, retries, delay))
    r = OpenClipboard(window)
    if r:
        log("OpenClipboard(%#x)=%s", window, r)
        try:
            r = success_callback()
            log("%s()=%s", success_callback, r)
            if r:
                return
        finally:
            r = CloseClipboard()
            log("CloseClipboard()=%s", r)
    e = WinError(GetLastError())
    owner = GetClipboardOwner()
    log("OpenClipboard(%#x)=%s, current owner: %s", window, e, get_owner_info(owner, window))
    if retries<=0:
        failure_callback("OpenClipboard: too many failed attempts, giving up")
        return
    #try again later:
    GLib.timeout_add(delay, with_clipboard_lock,
                     window, success_callback, failure_callback, retries-1, delay+5)

def format_name(fmt):
    name = CLIPBOARD_FORMATS.get(fmt)
    if name:
        return name
    ulen = 128
    buf = LPCSTR(b" "*ulen)
    r = GetClipboardFormatNameA(fmt, buf, ulen-1)
    if r==0:
        return str(fmt)
    return (buf.value[:r]).decode("latin1")

def format_names(fmts):
    return tuple(format_name(x) for x in fmts)

def get_clipboard_formats():
    formats = []
    fmt = 0
    while True:
        fmt = EnumClipboardFormats(fmt)
        if fmt:
            formats.append(fmt)
        else:
            break
    log("get_clipboard formats()=%s", csv(format_name(x) for x in formats))
    return formats

def w_to_utf8(data):
    wstr = cast(data, LPCWSTR)
    ulen = WideCharToMultiByte(CP_UTF8, 0, wstr, -1, None, 0, None, None)
    if ulen>MAX_CLIPBOARD_PACKET_SIZE:
        raise Exception("unicode data is too large: %i bytes" % ulen)
    buf = create_string_buffer(ulen)
    l = WideCharToMultiByte(CP_UTF8, 0, wstr, -1, byref(buf), ulen, None, None)
    if l==0:
        raise Exception("failed to convert to UTF8: %s" % FormatError(get_last_error()))
    if buf.raw[l-1:l]==b"\0":
        s = buf.raw[:l-1]
    else:
        s = buf.raw[:l]
    log("got %i bytes of UNICODE data: %s", len(s), ellipsizer(s))
    if CONVERT_LINE_ENDINGS:
        return s.decode("utf8").replace("\r\n", "\n").encode("utf8")
    return strtobytes(s)


class Win32Clipboard(ClipboardTimeoutHelper):
    """
        Use Native win32 API to access the clipboard
    """
    def __init__(self, send_packet_cb, progress_cb=None, **kwargs):
        self.init_window()
        super().__init__(send_packet_cb, progress_cb, **kwargs)

    def init_window(self):
        log("Win32Clipboard.init_window() creating clipboard window class and instance")
        self.wndclass = WNDCLASSEX()
        self.wndclass.cbSize = sizeof(WNDCLASSEX)
        self.wndclass.lpfnWndProc = WNDPROC(self.wnd_proc)
        self.wndclass.style =  win32con.CS_GLOBALCLASS
        self.wndclass.hInstance = GetModuleHandleA(0)
        self.wndclass.lpszClassName = CLIPBOARD_WINDOW_CLASS_NAME
        self.wndclass_handle = RegisterClassExW(byref(self.wndclass))
        log("RegisterClassExA(%s)=%#x", self.wndclass.lpszClassName, self.wndclass_handle)
        if self.wndclass_handle==0:
            raise WinError()
        style = win32con.WS_CAPTION   #win32con.WS_OVERLAPPED
        self.window = CreateWindowExW(0, self.wndclass_handle, "Clipboard", style,
                                      0, 0, win32con.CW_USEDEFAULT, win32con.CW_USEDEFAULT,
                                      win32con.HWND_MESSAGE, 0, self.wndclass.hInstance, None)
        log("clipboard window=%#x", self.window)
        if not self.window:
            raise WinError()
        if not AddClipboardFormatListener(self.window):
            log.warn("Warning: failed to setup clipboard format listener")
            log.warn(" %s", get_last_error())

    def wnd_proc(self, hwnd, msg, wparam, lparam):
        r = DefWindowProcW(hwnd, msg, wparam, lparam)
        if msg in CLIPBOARD_EVENTS:
            owner = GetClipboardOwner()
            log("clipboard event: %s, current owner: %s",
                CLIPBOARD_EVENTS.get(msg), get_owner_info(owner, self.window))
        if msg==WM_CLIPBOARDUPDATE and owner!=self.window:
            owner = GetClipboardOwner()
            owner_info = get_owner_info(owner, self.window)
            if is_blacklisted(owner_info):
                #ie: don't try to sync from VirtualBox
                log("CLIPBOARDUPDATE coming from '%s' ignored", owner_info)
                return r
            for proxy in self._clipboard_proxies.values():
                if not proxy._block_owner_change:
                    proxy.schedule_emit_token()
        return r


    def cleanup(self):
        ClipboardTimeoutHelper.cleanup(self)
        self.cleanup_window()

    def cleanup_window(self):
        w = self.window
        if w:
            self.window = None
            RemoveClipboardFormatListener(w)
            DestroyWindow(w)
        wch = self.wndclass_handle
        if wch:
            self.wndclass = None
            self.wndclass_handle = None
            UnregisterClassW(CLIPBOARD_WINDOW_CLASS_NAME, GetModuleHandleA(0))

    def make_proxy(self, selection):
        proxy = Win32ClipboardProxy(self.window, selection,
                                    self._send_clipboard_request_handler, self._send_clipboard_token_handler)
        proxy.set_want_targets(self._want_targets)
        proxy.set_direction(self.can_send, self.can_receive)
        return proxy

    ############################################################################
    # just pass ATOM targets through
    # (we use them internally as strings)
    ############################################################################
    def _munge_wire_selection_to_raw(self, encoding, dtype, dformat, data):
        if encoding=="atoms":
            return _filter_targets(data)
        return super()._munge_wire_selection_to_raw(encoding, dtype, dformat, data)

    def _munge_raw_selection_to_wire(self, target, dtype, dformat, data):
        if dtype=="ATOM":
            assert isinstance(data, (tuple, list))
            return "atoms", _filter_targets(data)
        return super()._munge_raw_selection_to_wire(target, dtype, dformat, data)


class Win32ClipboardProxy(ClipboardProxyCore):
    def __init__(self, window, selection, send_clipboard_request_handler, send_clipboard_token_handler):
        self.window = window
        self.send_clipboard_request_handler = send_clipboard_request_handler
        self.send_clipboard_token_handler = send_clipboard_token_handler
        super().__init__(selection)

    def with_clipboard_lock(self, success_callback, failure_callback, retries=RETRY, delay=DELAY):
        with_clipboard_lock(self.window, success_callback, failure_callback, retries=retries, delay=delay)

    def clear(self):
        self.with_clipboard_lock(self.empty_clipboard, self.clear_error)

    def empty_clipboard(self):
        r = EmptyClipboard()
        log("EmptyClipboard()=%s", r)
        return True

    def clear_error(self, error_text=""):
        log.warn("Warning: failed to clear the clipboard")
        if error_text:
            log.warn(" %s", error_text)


    def do_emit_token(self):
        if not self._greedy_client:
            #send just the token
            self.send_clipboard_token_handler(self)
            return
        #greedy clients want data with the token,
        #so we have to get the clipboard lock
        def send_token(formats):
            #default target:
            target = "UTF8_STRING"
            if formats:
                tnames = format_names(formats)
                if win32con.CF_UNICODETEXT in formats:
                    target = "UTF8_STRING"
                elif win32con.CF_TEXT in formats or win32con.CF_OEMTEXT in formats:
                    target = "STRING"
                elif "PNG" in tnames:
                    target = "image/png"
            def got_contents(dtype, dformat, data):
                packet_data = ([target], (target, dtype, dformat, data))
                self.send_clipboard_token_handler(self, packet_data)
            self.get_contents(target, got_contents)
        def got_clipboard_lock():
            fmts = get_clipboard_formats()
            log("do_emit_token() formats=%s", format_names(fmts))
            send_token(fmts)
            return True
        def errback(_errmsg=None):
            send_token()
        self.with_clipboard_lock(got_clipboard_lock, errback)

    def get_contents(self, target, got_contents):
        log("get_contents%s", (target, got_contents))
        if target=="TARGETS":
            def got_clipboard_lock():
                formats = get_clipboard_formats()
                fnames = format_names(formats)
                targets = []
                if win32con.CF_UNICODETEXT in formats:
                    targets += ["text/plain;charset=utf-8", "UTF8_STRING", "CF_UNICODETEXT"]
                if win32con.CF_TEXT in formats or win32con.CF_OEMTEXT in formats:
                    targets += ["TEXT", "STRING", "text/plain"]
                #if any(x in fnames for x in ("CF_DIB", "CF_BITMAP", "CF_DIBV5")):
                if "CF_DIBV5" in fnames:
                    targets += ["image/png", "image/jpeg"]
                log("targets(%s)=%s", csv(fnames), csv(targets))
                got_contents("ATOM", 32, targets)
                return True
            def lockerror(_message):
                #assume text:
                got_contents("ATOM", 32, ["TEXT", "STRING", "text/plain", "text/plain;charset=utf-8", "UTF8_STRING"])
            self.with_clipboard_lock(got_clipboard_lock, lockerror)
            return
        def nodata(*args):
            log("nodata%s", args)
            got_contents(target, 8, b"")
        if target in ("image/png", "image/jpeg"):
            def got_image(img_data, trusted=False):
                log("got_image(%i bytes)", len(img_data))
                img_data = self.filter_data(dtype=target, dformat=8, data=img_data, trusted=trusted)
                got_contents(target, 8, img_data)
            img_format = target.split("/")[-1].upper()  #ie: "PNG" or "JPEG"
            self.get_clipboard_image(img_format, got_image, nodata)
            return
        if target not in ("TEXT", "STRING", "text/plain", "text/plain;charset=utf-8", "UTF8_STRING"):
            #we don't know how to handle this target,
            #return an empty response:
            nodata()
            return
        def got_text(text):
            log("got_text(%s)", ellipsizer(text))
            got_contents(target, 8, text)
        def errback(error_text=""):
            log("errback(%s)", error_text)
            if error_text:
                log.warn("Warning: failed to get clipboard data as text")
                log.warn(" %s", error_text)
            got_contents(target, 8, b"")
        utf8 = target.lower().find("utf")>=0
        self.get_clipboard_text(utf8, got_text, errback)

    def get_clipboard_image(self, img_format, got_image, errback):
        def got_clipboard_lock():
            if COMPRESSED_IMAGES:
                fmt_name = LPCSTR(img_format.upper().encode("latin1")+b"\0")   #ie: "PNG"
                fmt = RegisterClipboardFormatA(fmt_name)
                if fmt:
                    data_handle = GetClipboardData(fmt)
                    if data_handle:
                        size = GlobalSize(data_handle)
                        data = GlobalLock(data_handle)
                        log("GetClipboardData(%s)=%#x size=%s, data=%#x",
                            img_format.upper(), data_handle, size, data)
                        if data and size:
                            try:
                                cdata = (c_char*size).from_address(data)
                            finally:
                                GlobalUnlock(data)
                            got_image(bytes(cdata), False)
                            return True

            data_handle = GetClipboardData(win32con.CF_DIBV5)
            log("CF_BITMAP=%s", data_handle)
            data = GlobalLock(data_handle)
            if not data:
                log("failed to lock data handle %#x (may try again)", data_handle)
                return False
            try:
                header = cast(data, PBITMAPV5HEADER).contents
                offset = header.bV5Size + header.bV5ClrUsed * 4
                w, h = header.bV5Width, abs(header.bV5Height)
                bits = header.bV5BitCount
                log("offset=%s, width=%i, height=%i, compression=%s",
                    offset, w, h, BI_FORMATS.get(header.bV5Compression, header.bV5Compression))
                log("planes=%i, bitcount=%i", header.bV5Planes, bits)
                log("colorspace=%s", COLOR_PROFILES.get(header.bV5CSType, header.bV5CSType))
                #if header.bV5Compression in (BI_JPEG, BI_PNG):
                #    pass
                if header.bV5Compression!=BI_RGB:
                    errback("cannot handle %s compression yet" % BI_FORMATS.get(header.bV5Compression, header.bV5Compression))
                    return True
                if bits==24:
                    save_format = "RGB"
                    rgb_format = "BGR"
                    stride = roundup(w*3, 4)
                elif bits==32:
                    save_format = "RGBA"
                    rgb_format = "BGRA"
                    stride = w*4
                else:
                    errback("cannot handle image data with %i bits per pixel yet" % bits)
                    return True
                img_size = stride*h
                rgb_data = (c_char*img_size).from_address(data+offset)
                from PIL import Image, ImageOps
                img = Image.frombytes(save_format, (w, h), rgb_data, "raw", rgb_format, stride, 1)
                if header.bV5Height>0:
                    img = ImageOps.flip(img)
                buf = BytesIO()
                img.save(buf, format=save_format)
                data = buf.getvalue()
                buf.close()
                got_image(data, True)
                return True
            finally:
                GlobalUnlock(data)
        self.with_clipboard_lock(got_clipboard_lock, errback)


    def got_token(self, targets, target_data=None, claim=True, _synchronous_client=False):
        # the remote end now owns the clipboard
        self.cancel_emit_token()
        if not self._enabled:
            return
        self._got_token_events += 1
        log("got token, selection=%s, targets=%s, target data=%s, claim=%s, can-receive=%s",
            self._selection, targets, target_data, claim, self._can_receive)
        if self._can_receive:
            self.targets = _filter_targets(targets or ())
            self.target_data = target_data or {}
            if targets:
                self.got_contents("TARGETS", "ATOM", 32, targets)
            if target_data:
                for target, td_def in target_data.items():
                    dtype, dformat, data = td_def
                    dtype = bytestostr(dtype)
                    self.got_contents(target, dtype, dformat, data)
            #since we claim to be greedy
            #the peer should have sent us the target and target_data,
            #if not then request it:
            if not targets:
                self.send_clipboard_request_handler(self, self._selection, "TARGETS")
        if not claim:
            log("token packet without claim, not setting the token flag")
            return
        self._have_token = True
        if self._can_receive:
            self.claim()

    def got_contents(self, target, dtype=None, dformat=None, data=None):
        #if this is the special target 'TARGETS', cache the result:
        if target=="TARGETS" and dtype=="ATOM" and dformat==32:
            self.targets = _filter_targets(data)
            #TODO: tell system what targets we have
            log("got_contents: tell OS we have %s", csv(self.targets))
            image_formats = tuple(x for x in ("image/png", "image/jpeg") if x in self.targets)
            if image_formats:
                #request it:
                self.send_clipboard_request_handler(self, self._selection, image_formats[0])
        elif dformat==8 and dtype in TEXT_TARGETS:
            log("we got a byte string: %s", data)
            self.set_clipboard_text(data)
        elif dformat==8 and dtype.startswith("image/"):
            img_format = dtype.split("/")[-1]   #ie: 'png'
            self.set_clipboard_image(img_format, data)
        else:
            log("no handling: target=%s, dtype=%s, dformat=%s, data=%s",
                target, dtype, dformat, ellipsizer(data))

    def set_clipboard_image(self, img_format, img_data):
        image_formats = {}
        if COMPRESSED_IMAGES:
            #first save it as binary compressed data:
            fmt_name = LPCSTR(img_format.upper().encode("latin1")+b"\0")   #ie: "PNG"
            fmt = RegisterClipboardFormatA(fmt_name)
            if fmt:
                buf = create_string_buffer(img_data)
                pbuf = cast(byref(buf), c_void_p)
                l = len(img_data)
                data_handle = GlobalAlloc(GMEM_MOVEABLE, l)
                if not data_handle:
                    log.error("Error: failed to allocate %i bytes of global memory", l)
                    return True
                data = GlobalLock(data_handle)
                if not data:
                    log("failed to lock data handle %#x (may try again)", data_handle)
                    return False
                log("got data handle lock %#x for %i bytes of '%s' data", data, l, img_format)
                try:
                    memmove(data, pbuf, l)
                finally:
                    GlobalUnlock(data)
                image_formats[fmt] = data_handle

        #also convert it to a bitmap:
        from PIL import Image
        buf = BytesIO(img_data)
        img = Image.open(buf)
        if img.mode!="RGBA":
            img = img.convert("RGBA")
        rgb_data = img.tobytes("raw", "BGRA")
        w, h = img.size
        log("set_clipboard_image(%s, %s) image size=%s, BGR buffer=%i bytes",
            img_format, ellipsizer(data), img.size, len(rgb_data))
        header = BITMAPINFOHEADER()
        memset(byref(header), 0, sizeof(BITMAPINFOHEADER ))
        header.biSize       = sizeof(BITMAPINFOHEADER)
        header.biWidth      = w
        header.biHeight     = -h
        header.biPlanes     = 1
        header.biBitCount   = 32
        header.biCompression    = BI_RGB
        header.biSizeImage      = 0
        header.biXPelsPerMeter  = 10
        header.biYPelsPerMeter  = 10
        bitmapinfo = BITMAPINFO()
        bitmapinfo.bmiColors = 0
        memmove(byref(bitmapinfo.bmiHeader), byref(header), sizeof(BITMAPINFOHEADER))
        rgb_buf = create_string_buffer(rgb_data)
        pbuf = cast(byref(rgb_buf), c_void_p)
        hdc = GetDC(None)
        CBM_INIT = 4
        bitmap = CreateDIBitmap(hdc, byref(header), CBM_INIT, pbuf, byref(bitmapinfo), win32con.DIB_RGB_COLORS)
        ReleaseDC(None, hdc)
        image_formats[win32con.CF_BITMAP] = bitmap

        self.do_set_clipboard_image(image_formats)

    def do_set_clipboard_image(self, image_formats):
        def got_clipboard_lock():
            EmptyClipboard()
            c = 0
            for fmt, handle in image_formats.items():
                log("do_set_clipboard_image: %s", format_name(fmt))
                r = SetClipboardData(fmt, handle)
                if not r:
                    e = WinError(GetLastError())
                    log("SetClipboardData(%s, %#x)=%s (%s)", format_name(fmt), handle, r, e)
                else:
                    c += 1
            return bool(c)
        def nolock(*_args):
            log.warn("Warning: failed to copy image data to the clipboard")
        self.with_clipboard_lock(got_clipboard_lock, nolock)


    def get_clipboard_text(self, utf8, callback, errback):
        def get_text():
            formats = get_clipboard_formats()
            matching = []
            for u in (utf8, not utf8):
                if u:
                    fmts = [win32con.CF_UNICODETEXT]
                else:
                    fmts = [win32con.CF_TEXT, win32con.CF_OEMTEXT]
                matching += [fmt for fmt in formats if fmt in fmts]
            log("supported formats: %s (prefer utf8: %s)", csv(format_names(matching)), utf8)
            if not matching:
                log("no supported formats, only: %s", csv(format_names(formats)))
                errback()
                return True
            data_handle = None
            for fmt in matching:
                data_handle = GetClipboardData(fmt)
                log("GetClipboardData(%s)=%#x", format_name(fmt), data_handle or 0)
                if data_handle:
                    break
            if not data_handle:
                log("no valid data handle using %s (may try again)", csv(format_names(matching)))
                return False
            data = GlobalLock(data_handle)
            if not data:
                log("failed to lock data handle %#x (may try again)", data_handle)
                return False
            log("got data handle lock %#x for format '%s'", data, format_name(fmt))
            try:
                if fmt==win32con.CF_UNICODETEXT:
                    try:
                        v = w_to_utf8(data)
                    except Exception as e:
                        log("w_to_utf8(..)", exc_info=True)
                        errback(str(e))
                        return True
                    callback(v)
                    return True
                #CF_TEXT or CF_OEMTEXT:
                astr = cast(data, LPCSTR)
                s = astr.value.decode("latin1")
                if CONVERT_LINE_ENDINGS:
                    s = s.replace("\r\n", "\n")
                b = s.encode("latin1")
                ulen = len(b)
                if ulen>MAX_CLIPBOARD_PACKET_SIZE:
                    errback("text data is too large: %i characters" % ulen)
                    return True
                log("got %i bytes of TEXT data: %s", len(b), ellipsizer(b))
                callback(b)
                return True
            finally:
                GlobalUnlock(data)
        self.with_clipboard_lock(get_text, errback)

    def set_err(self, msg):
        log.warn("Warning: cannot set clipboard value")
        log.warn(" %s", msg)

    def set_clipboard_text(self, text):
        #convert to wide char
        #get the length in wide chars:
        if CONVERT_LINE_ENDINGS:
            text = text.decode("utf8").replace("\n", "\r\n").encode("utf8")
        wlen = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, len(text), None, 0)
        if not wlen:
            self.set_err("failed to prepare to convert to wide char")
            return True
        log("MultiByteToWideChar wlen=%i", wlen)
        #allocate some memory for it:
        l = (wlen+1)*2
        buf = GlobalAlloc(GMEM_MOVEABLE, l)
        if not buf:
            self.set_err("failed to allocate %i bytes of global memory" % l)
            return True
        log("GlobalAlloc buf=%#x", buf)
        locked = GlobalLock(buf)
        if not locked:
            self.set_err("failed to lock buffer %#x" % buf)
            GlobalFree(buf)
            return True
        try:
            locked_buf = cast(locked, LPWSTR)
            r = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, len(text), locked_buf, wlen)
            if not r:
                self.set_err("failed to convert to wide char")
                GlobalFree(buf)
                return True
        finally:
            GlobalUnlock(locked)
        #we're going to alter the clipboard ourselves,
        #ignore messages until we're done:
        self._block_owner_change = True
        def cleanup():
            GLib.idle_add(self.remove_block)
        def set_clipboard_data():
            r = EmptyClipboard()
            log("EmptyClipboard()=%s", r)
            if not r:
                self.set_err("failed to empty the clipboard")
                return False
            r = SetClipboardData(win32con.CF_UNICODETEXT, buf)
            if not r:
                e = WinError(GetLastError())
                log("SetClipboardData(CF_UNICODETEXT, %i chars)=%s (%s)", wlen, r, e)
                return False
            log("SetClipboardData(CF_UNICODETEXT, %i chars)=%s", wlen, r)
            cleanup()
            return True
        def set_clipboard_error(error_text=""):
            log("set_clipboard_error(%s)", error_text)
            if error_text:
                log.warn("Warning: failed to set clipboard data")
                log.warn(" %s", error_text)
            cleanup()
        self.with_clipboard_lock(set_clipboard_data, set_clipboard_error)


    def __repr__(self):
        return "Win32ClipboardProxy"
