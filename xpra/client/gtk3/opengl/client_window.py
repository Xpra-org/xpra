# This file is part of Xpra.
# Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.client.gtk3.window.window import ClientWindow
from xpra.gtk.window import set_visual
from xpra.os_util import gi_import, WIN32
from xpra.util.objects import typedict
from xpra.util.env import envbool
from xpra.log import Logger

Gdk = gi_import("Gdk")

log = Logger("opengl", "window")
cursorlog = Logger("opengl", "cursor")

MONITOR_REINIT = envbool("XPRA_OPENGL_MONITOR_REINIT", False)

if WIN32:
    import ctypes
    import ctypes.wintypes
    import re

    # GdkWin32Cursor.__repr__ returns e.g. "<GdkWin32Cursor at 0x1a2b3c4d5e6f)"
    # We extract the C struct address to read the HCURSOR field directly.
    _HCURSOR_PATTERN = re.compile(r"GdkWin32Cursor at (0x[0-9a-fA-F]+)\)")

    # Byte offset of the HCURSOR field within the GdkWin32Cursor C struct.
    # Layout: GObject(24) + display*(8) + cursor_type(4)+pad(4) + name*(8) + HCURSOR(8)
    # See: https://gitlab.gnome.org/GNOME/gtk/-/blob/gtk-3-24/gdk/win32/gdkprivate-win32.h
    # This is ABI-fragile: tied to GTK3's struct layout. GTK3 is in maintenance
    # mode (3.24.x final) so the layout is effectively frozen. If GTK4 is ever
    # used, this offset will be wrong — GTK4 uses a different cursor API entirely.
    # On failure, _get_hcursor_from_gdk_cursor returns 0 and the subclass is not installed.
    _GDKWIN32CURSOR_HCURSOR_OFFSET = 48

    # LRESULT CALLBACK SubclassProc(HWND, UINT, WPARAM, LPARAM, UINT_PTR, DWORD_PTR)
    # https://learn.microsoft.com/en-us/windows/win32/api/commctrl/nc-commctrl-subclassproc
    _SUBCLASSPROC = ctypes.WINFUNCTYPE(
        ctypes.c_longlong,    # LRESULT return
        ctypes.c_void_p,      # HWND
        ctypes.c_uint,        # UINT msg
        ctypes.c_ulonglong,   # WPARAM
        ctypes.c_longlong,    # LPARAM
        ctypes.c_ulonglong,   # UINT_PTR uIdSubclass
        ctypes.c_ulonglong,   # DWORD_PTR dwRefData
    )

    # Win32 API function signatures (set once at import time)
    ctypes.windll.user32.SetCursor.argtypes = [ctypes.c_void_p]
    ctypes.windll.user32.SetCursor.restype = ctypes.c_void_p
    ctypes.windll.user32.GetCursorPos.argtypes = [ctypes.POINTER(ctypes.wintypes.POINT)]
    ctypes.windll.user32.GetCursorPos.restype = ctypes.wintypes.BOOL
    ctypes.windll.user32.IsWindow.argtypes = [ctypes.c_void_p]
    ctypes.windll.user32.IsWindow.restype = ctypes.wintypes.BOOL
    ctypes.windll.user32.WindowFromPoint.argtypes = [ctypes.wintypes.POINT]
    ctypes.windll.user32.WindowFromPoint.restype = ctypes.c_void_p

    ctypes.windll.comctl32.DefSubclassProc.argtypes = [
        ctypes.c_void_p, ctypes.c_uint, ctypes.c_ulonglong, ctypes.c_longlong]
    ctypes.windll.comctl32.DefSubclassProc.restype = ctypes.c_longlong
    ctypes.windll.comctl32.SetWindowSubclass.argtypes = [
        ctypes.c_void_p, _SUBCLASSPROC, ctypes.c_ulonglong, ctypes.c_ulonglong]
    ctypes.windll.comctl32.SetWindowSubclass.restype = ctypes.c_bool
    ctypes.windll.comctl32.RemoveWindowSubclass.argtypes = [
        ctypes.c_void_p, _SUBCLASSPROC, ctypes.c_ulonglong]
    ctypes.windll.comctl32.RemoveWindowSubclass.restype = ctypes.c_bool


class GLClientWindowBase(ClientWindow):

    def __repr__(self):
        return f"GLClientWindow({self.wid:#x} : {self._backing})"

    def get_backing_class(self) -> type:
        raise NotImplementedError()

    def is_GL(self) -> bool:
        return True

    def queue_draw_area(self, x: int, y: int, w: int, h: int) -> None:
        b = self._backing
        if not b:
            return
        b.gl_expose_rect(x, y, w, h)

    def monitor_changed(self, monitor) -> None:
        super().monitor_changed(monitor)
        da = self.drawing_area
        if da and MONITOR_REINIT:
            # re-create the drawing area,
            # which will re-create the opengl context:
            try:
                self.remove(da)
            except Exception:
                log("monitor_changed: failed to remove %s", da)
            self.drawing_area = None
            w, h = self.get_size()
            self.new_backing(w, h)

    def remove_backing(self) -> None:
        b = self._backing
        log("remove_backing() backing=%s", b)
        if b:
            self._backing = None
            b.paint_screen = False
            b.close()
            glarea = b._backing
            log("remove_backing() glarea=%s", glarea)
            if glarea:
                try:
                    self.remove(glarea)
                except Exception:
                    log.warn("Warning: cannot remove %s", glarea, exc_info=True)

    def magic_key(self, *args) -> None:
        b = self._backing
        if self.border:
            self.border.toggle()
            if b:
                with b.gl_context() as ctx:
                    b.gl_init(ctx)
                    b.present_fbo(ctx, 0, 0, *b.size)
                self.repaint(0, 0, *self._size)
        log("gl magic_key%s border=%s, backing=%s", args, self.border, b)

    def set_alpha(self) -> None:
        super().set_alpha()
        rgb_formats = self._client_properties.setdefault("encodings.rgb_formats", [])
        # gl.backing supports BGR(A) too:
        if "RGBA" in rgb_formats:
            rgb_formats.append("BGRA")
        if "RGB" in rgb_formats:
            rgb_formats.append("BGR")

    def do_configure_event(self, event) -> None:
        log("GL do_configure_event(%s)", event)
        ClientWindow.do_configure_event(self, event)
        self._backing.paint_screen = True

    def destroy(self) -> None:
        self._remove_cursor_subclass()
        self.remove_backing()
        super().destroy()

    def init_drawing_area(self) -> None:
        self.drawing_area = None

    # ---- Win32 GL cursor fix ----
    #
    # On Win32, GL windows have a separate child HWND for the DrawingArea.
    # GDK stores the cursor on the GdkWindow but its WM_SETCURSOR handler
    # doesn't apply it correctly for this child HWND. We subclass the child
    # HWND via SetWindowSubclass (comctl32) to intercept WM_SETCURSOR and
    # call SetCursor with the correct HCURSOR ourselves.

    def _get_hcursor_from_gdk_cursor(self, cursor) -> int:
        # Extract the Win32 HCURSOR from GdkWin32Cursor's C struct.
        m = _HCURSOR_PATTERN.search(repr(cursor))
        if not m:
            cursorlog.warn("Warning: cannot parse GdkWin32Cursor repr: %s", repr(cursor)[:80])
            return 0
        c_ptr = int(m.group(1), 16)
        try:
            val = ctypes.c_void_p.from_address(c_ptr + _GDKWIN32CURSOR_HCURSOR_OFFSET).value or 0
            cursorlog("extracted HCURSOR=%s from GdkWin32Cursor struct", hex(val) if val else 0)
            return val
        except Exception as e:
            cursorlog.warn("Warning: failed reading HCURSOR at offset %d: %s",
                           _GDKWIN32CURSOR_HCURSOR_OFFSET, e)
            return 0

    def _get_hwnd_under_cursor(self) -> int:
        # Returns the Win32 HWND currently under the mouse cursor.
        try:
            pt = ctypes.wintypes.POINT()
            if not ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
                return 0
            hwnd = ctypes.windll.user32.WindowFromPoint(pt)
            if hwnd and ctypes.windll.user32.IsWindow(hwnd):
                return hwnd
        except Exception as e:
            cursorlog.warn("Warning: WindowFromPoint failed: %s", e)
        return 0

    def _remove_cursor_subclass(self) -> None:
        info = getattr(self, "_cursor_subclass_info", None)
        if not info:
            return
        hwnd, callback, subclass_id = info
        self._cursor_subclass_info = None
        self._cursor_hcursor_holder = None
        try:
            ctypes.windll.comctl32.RemoveWindowSubclass(hwnd, callback, subclass_id)
            cursorlog("removed cursor subclass from hwnd=%s wid=%#x", hex(hwnd), self.wid)
        except Exception as e:
            cursorlog.warn("Warning: RemoveWindowSubclass failed: %s", e)

    def _install_cursor_subclass(self, hwnd: int, hcursor: int) -> None:
        # Subclass the HWND to intercept WM_SETCURSOR and apply our cursor.
        # Uses SetWindowSubclass (comctl32) which is safe and chainable.
        existing = getattr(self, "_cursor_subclass_info", None)
        if existing and existing[0] == hwnd:
            # Already subclassed this HWND — update the cursor handle
            self._cursor_hcursor_holder[0] = hcursor
            cursorlog("updated HCURSOR=%s on existing subclass hwnd=%s wid=%#x",
                      hex(hcursor), hex(hwnd), self.wid)
            return

        # Remove any old subclass first
        self._remove_cursor_subclass()

        # https://learn.microsoft.com/en-us/windows/win32/menurc/wm-setcursor
        WM_SETCURSOR = 0x0020
        # https://learn.microsoft.com/en-us/windows/win32/winmsg/wm-ncdestroy
        WM_NCDESTROY = 0x0082
        # https://learn.microsoft.com/en-us/windows/win32/inputdev/wm-nchittest
        HTCLIENT = 1
        SUBCLASS_ID = 0xAC01  # arbitrary unique ID

        # Mutable holder so we can update HCURSOR without re-subclassing
        hcursor_holder = [hcursor]
        self._cursor_hcursor_holder = hcursor_holder

        comctl32 = ctypes.windll.comctl32
        # Capture wid for logging (closure also captures self for state cleanup)
        wid = self.wid

        @_SUBCLASSPROC
        def subclass_proc(h, msg, wparam, lparam, uid, ref_data):
            try:
                if msg == WM_SETCURSOR and (lparam & 0xFFFF) == HTCLIENT:
                    hc = hcursor_holder[0]
                    if hc:
                        ctypes.windll.user32.SetCursor(ctypes.c_void_p(hc))
                        return 1  # handled — prevents DefWindowProc from setting arrow
                if msg == WM_NCDESTROY:
                    comctl32.RemoveWindowSubclass(h, subclass_proc, SUBCLASS_ID)
                    # Clear state so set_windows_cursor doesn't update a dead subclass
                    self._cursor_subclass_info = None
                    self._cursor_hcursor_holder = None
                    cursorlog("cursor subclass removed on WM_NCDESTROY wid=%#x", wid)
            except Exception as e:
                cursorlog.warn("Warning: cursor subclass error in WndProc: %s", e)
            return comctl32.DefSubclassProc(h, msg, wparam, lparam)

        result = comctl32.SetWindowSubclass(hwnd, subclass_proc, SUBCLASS_ID, 0)
        if result:
            # Store strong references to prevent GC of the callback
            self._cursor_subclass_info = (hwnd, subclass_proc, SUBCLASS_ID)
            cursorlog("installed cursor subclass on hwnd=%s hcursor=%s wid=%#x",
                      hex(hwnd), hex(hcursor), self.wid)
        else:
            cursorlog.warn("Warning: SetWindowSubclass failed for hwnd=%s wid=%#x",
                           hex(hwnd), self.wid)

    def _update_cursor_subclass(self, cursor) -> bool:
        # Called from set_windows_cursor when a cursor update arrives.
        # Updates the HCURSOR holder so the subclass applies the new cursor on
        # the next WM_SETCURSOR without needing to re-subclass the HWND.
        # Returns True if handled; False to fall back to gdkwin.set_cursor().
        info = getattr(self, "_cursor_subclass_info", None)
        if not info:
            return False
        holder = getattr(self, "_cursor_hcursor_holder", None)
        if holder is None:
            return False  # inconsistent state, fall back to GDK
        if not cursor:
            # Cursor reset — zero holder so subclass falls through to DefWindowProc.
            # Return False so the caller also resets GDK's stored cursor; without
            # that, the parent HWND's WM_SETCURSOR handler would restore the old one.
            holder[0] = 0
            self._cursor_ref = None
            return False
        hcursor = self._get_hcursor_from_gdk_cursor(cursor)
        if hcursor:
            holder[0] = hcursor
            self._cursor_ref = cursor  # prevent GC of Win32 HCURSOR
        else:
            holder[0] = 0
            self._cursor_ref = None
        return True

    def _apply_cursor_on_enter(self, _widget, event=None) -> None:
        # Win32 only: apply the correct cursor when the pointer enters the
        # GL DrawingArea. If a subclass is already installed, its HCURSOR
        # holder is kept current by set_windows_cursor — just apply it.
        # On first enter, build a cursor and install the subclass.
        info = getattr(self, "_cursor_subclass_info", None)
        if info:
            holder = getattr(self, "_cursor_hcursor_holder", None)
            if holder and holder[0]:
                ctypes.windll.user32.SetCursor(ctypes.c_void_p(holder[0]))
            return

        client = self._client
        if not client:
            return
        cursor_data = getattr(self, "cursor_data", ()) or getattr(client, "_last_cursor_data", ())
        if not cursor_data:
            return

        cursor = None
        try:
            cursor = client.make_cursor(cursor_data)
        except Exception as e:
            cursorlog.warn("Warning: make_cursor failed on enter-notify: %s", e)
            return
        if cursor is None:
            return

        hcursor = self._get_hcursor_from_gdk_cursor(cursor)
        if not hcursor:
            cursorlog.warn("Warning: failed to extract HCURSOR for wid=%#x, skipping subclass", self.wid)
            return

        # Immediate SetCursor so cursor shows right now
        ctypes.windll.user32.SetCursor(ctypes.c_void_p(hcursor))

        # Install subclass on the HWND under the cursor so WM_SETCURSOR
        # keeps applying our cursor (instead of GDK resetting to arrow).
        hwnd = self._get_hwnd_under_cursor()
        if hwnd:
            self._install_cursor_subclass(hwnd, hcursor)
            # Keep a reference to the GdkCursor to prevent GC of the underlying Win32 cursor
            self._cursor_ref = cursor

    def new_backing(self, bw: int, bh: int) -> None:
        self._remove_cursor_subclass()
        widget = super().new_backing(bw, bh)
        if self.drawing_area:
            self.remove(self.drawing_area)
        set_visual(widget, self._has_alpha)
        widget.show()
        self.init_widget_events(widget)
        if self.drawing_area and self.size_constraints:
            # apply min size to the drawing_area:
            thints = typedict(self.size_constraints)
            minsize = thints.intpair("minimum-size", (0, 0))
            self.drawing_area.set_size_request(*minsize)
        self.add(widget)
        self.drawing_area = widget
        # Win32 GL cursor fix: GDK doesn't handle WM_SETCURSOR for the GL
        # DrawingArea's child HWND. We intercept enter-notify to subclass
        # the HWND and apply the cursor directly via Win32 SetCursor.
        if WIN32:
            widget.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK)
            widget.connect_after("enter-notify-event", self._apply_cursor_on_enter)
        # maybe redundant?:
        self.apply_geometry_hints(self.geometry_hints)

    def draw_widget(self, widget, context) -> bool:
        mapped = self.get_mapped()
        backing = self._backing
        log(f"draw_widget({widget}, {context}) {mapped=}, {backing=}", )
        if not mapped:
            return False
        if not backing:
            return False
        return backing.draw_fbo(context)
