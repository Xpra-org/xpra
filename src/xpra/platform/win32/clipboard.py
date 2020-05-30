# This file is part of Xpra.
# Copyright (C) 2019-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from ctypes import (
    sizeof, byref, cast,
    get_last_error, create_string_buffer,
    WinError, FormatError,
    )
from gi.repository import GLib

from xpra.platform.win32.common import (
    WNDCLASSEX, GetLastError,
    WNDPROC, LPCWSTR, LPWSTR, LPCSTR, DWORD,
    DefWindowProcW,
    GetModuleHandleA, RegisterClassExW, UnregisterClassA,
    CreateWindowExW, DestroyWindow,
    OpenClipboard, EmptyClipboard, CloseClipboard, GetClipboardData,
    GlobalLock, GlobalUnlock, GlobalAlloc, GlobalFree,
    WideCharToMultiByte, MultiByteToWideChar,
    AddClipboardFormatListener, RemoveClipboardFormatListener,
    SetClipboardData, EnumClipboardFormats, GetClipboardFormatNameA, GetClipboardOwner,
    GetWindowThreadProcessId, QueryFullProcessImageNameA, OpenProcess, CloseHandle,
    )
from xpra.platform.win32 import win32con
from xpra.clipboard.clipboard_timeout_helper import ClipboardTimeoutHelper
from xpra.clipboard.clipboard_core import (
    ClipboardProxyCore, log, _filter_targets,
    TEXT_TARGETS, MAX_CLIPBOARD_PACKET_SIZE,
    )
from xpra.util import csv, ellipsizer, envint, envbool
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

class Win32Clipboard(ClipboardTimeoutHelper):
    """
        Use Native win32 API to access the clipboard
    """
    def __init__(self, send_packet_cb, progress_cb=None, **kwargs):
        self.init_window()
        super().__init__(send_packet_cb, progress_cb, **kwargs)

    def init_window(self):
        log("Win32Clipboard.init_window() creating clipboard window class and instance")
        class_name = "XpraWin32Clipboard"
        self.wndclass = WNDCLASSEX()
        self.wndclass.cbSize = sizeof(WNDCLASSEX)
        self.wndclass.lpfnWndProc = WNDPROC(self.wnd_proc)
        self.wndclass.style =  win32con.CS_GLOBALCLASS
        self.wndclass.hInstance = GetModuleHandleA(0)
        self.wndclass.lpszClassName = class_name
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
            UnregisterClassA(wch, GetModuleHandleA(0))

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
        log("with_clipboard_lock%s", (success_callback, failure_callback, retries, delay))
        r = OpenClipboard(self.window)
        if r:
            log("OpenClipboard(%#x)=%s", self.window, r)
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
        log("OpenClipboard(%#x)=%s, current owner: %s", self.window, e, get_owner_info(owner, self.window))
        if retries<=0:
            failure_callback("OpenClipboard: too many failed attempts, giving up")
            return
        #try again later:
        GLib.timeout_add(delay, self.with_clipboard_lock,
                         success_callback, failure_callback, retries-1, delay+5)

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
        #TODO: if contents are not text,
        #send just the token
        if self._greedy_client:
            target = "UTF8_STRING"
            def got_contents(dtype, dformat, data):
                packet_data = ([target], (target, dtype, dformat, data))
                self.send_clipboard_token_handler(self, packet_data)
            self.get_contents(target, got_contents)
        else:
            self.send_clipboard_token_handler(self)

    def get_contents(self, target, got_contents):
        log("get_contents%s", (target, got_contents))
        if target=="TARGETS":
            #we only support text at the moment:
            got_contents("ATOM", 32, ["TEXT", "STRING", "text/plain", "text/plain;charset=utf-8", "UTF8_STRING"])
            return
        if target not in ("TEXT", "STRING", "text/plain", "text/plain;charset=utf-8", "UTF8_STRING"):
            #we don't know how to handle this target,
            #return an empty response:
            got_contents(target, 8, b"")
            return
        def got_text(text):
            log("got_text(%s)", ellipsizer(text))
            got_contents(target, 8, text)
        def errback(error_text=""):
            log("errback(%s)", error_text)
            if error_text:
                log.warn("Warning: failed to get clipboard data")
                log.warn(" %s", error_text)
            got_contents(target, 8, b"")
        utf8 = target.lower().find("utf")>=0
        self.get_clipboard_text(utf8, got_text, errback)


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
        if dformat==8 and dtype in TEXT_TARGETS:
            log("we got a byte string: %s", data)
            self.set_clipboard_text(data)


    def get_clipboard_text(self, utf8, callback, errback):
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
        def get_text():
            formats = []
            fmt = 0
            while True:
                fmt = EnumClipboardFormats(fmt)
                if fmt:
                    formats.append(fmt)
                else:
                    break
            log("clipboard formats: %s", csv(format_name(x) for x in formats))
            matching = []
            for u in (utf8, not utf8):
                if u:
                    fmts = [win32con.CF_UNICODETEXT]
                else:
                    fmts = [win32con.CF_TEXT, win32con.CF_OEMTEXT]
                matching += [fmt for fmt in formats if fmt in fmts]
            log("supported formats: %s (prefer utf8: %s)", csv(format_name(x) for x in matching), utf8)
            if not matching:
                log("no supported formats, only: %s", csv(format_name(x) for x in formats))
                errback()
                return True
            data_handle = None
            for fmt in matching:
                data_handle = GetClipboardData(fmt)
                log("GetClipboardData(%s)=%#x", format_name(fmt), data_handle or 0)
                if data_handle:
                    break
            if not data_handle:
                log("no valid data handle using %s (may try again)", csv(format_name(x) for x in matching))
                return False
            data = GlobalLock(data_handle)
            if not data:
                log("failed to lock data handle %#x (may try again)", data_handle)
                return False
            log("got data handle lock %#x for format '%s'", data, format_name(fmt))
            try:
                if fmt==win32con.CF_UNICODETEXT:
                    wstr = cast(data, LPCWSTR)
                    ulen = WideCharToMultiByte(CP_UTF8, 0, wstr, -1, None, 0, None, None)
                    if ulen>MAX_CLIPBOARD_PACKET_SIZE:
                        errback("unicode data is too large: %i bytes" % ulen)
                        return True
                    buf = create_string_buffer(ulen)
                    l = WideCharToMultiByte(CP_UTF8, 0, wstr, -1, byref(buf), ulen, None, None)
                    if l==0:
                        errback("failed to convert to UTF8: %s" % FormatError(get_last_error()))
                        return True
                    if buf.raw[l-1:l]==b"\0":
                        s = buf.raw[:l-1]
                    else:
                        s = buf.raw[:l]
                    log("got %i bytes of UNICODE data: %s", len(s), ellipsizer(s))
                    if CONVERT_LINE_ENDINGS:
                        v = s.decode("utf8").replace("\r\n", "\n").encode("utf8")
                    else:
                        v = strtobytes(s)
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
