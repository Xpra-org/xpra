# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# cython: language_level=3

from libc.stdint cimport uintptr_t

from xpra.log import Logger
from xpra.wayland.events cimport ListenerObject
from xpra.wayland.wlroots cimport (
    wl_listener,
    wlr_seat, wlr_surface,
    wlr_seat_pointer_request_set_cursor_event,
    xpra_wlr_seat_request_set_cursor_signal,
    xpra_wlr_seat_cursor_event_is_focused,
)
from xpra.wayland.wayland_surface cimport WaylandSurface, next_wid


log = Logger("wayland", "cursor")


cdef enum CursorSurfaceListener:
    L_COMMIT
    L_DESTROY
    N_LISTENERS


cdef enum SeatCursorListener:
    L_REQUEST_SET_CURSOR
    N_SEAT_LISTENERS


cdef class CursorSurface(WaylandSurface):

    def __init__(self):
        super().__init__(N_LISTENERS)
        self.wid = next_wid()
        self.hotspot_x = 0
        self.hotspot_y = 0

    cdef void attach(self, wlr_surface *surface, int hotspot_x, int hotspot_y):
        if surface == NULL:
            return
        self.wlr_surface = surface
        self.hotspot_x = hotspot_x
        self.hotspot_y = hotspot_y
        self.register()
        self.add_listener(L_COMMIT, &surface.events.commit)
        self.add_listener(L_DESTROY, &surface.events.destroy)

    cdef void update_hotspot(self, int hotspot_x, int hotspot_y):
        self.hotspot_x = hotspot_x
        self.hotspot_y = hotspot_y
        self.refresh()

    cdef void refresh(self):
        self.commit()

    cdef void dispatch(self, wl_listener *listener, void *data) noexcept:
        cdef int slot = self.slot_of(listener)
        if slot == L_COMMIT:
            self.commit()
        elif slot == L_DESTROY:
            self.destroy()
        else:
            log.error("Error: unknown cursor surface listener slot %i", slot)

    cdef void commit(self) noexcept:
        if self.wlr_surface == NULL:
            return
        if not self.wlr_surface.mapped:
            self._emit("cursor-image", self.wid, None, self.hotspot_x, self.hotspot_y)
            return
        image = self.capture_pixels()
        log("cursor surface %#x commit: %s", <uintptr_t> self.wlr_surface, image)
        self._emit("cursor-image", self.wid, image, self.hotspot_x, self.hotspot_y)

    cdef void destroy(self) noexcept:
        if self.wlr_surface == NULL:
            return
        log("cursor surface %#x destroyed", <uintptr_t> self.wlr_surface)
        self._detach_all()
        self._emit("destroy", self.wid)
        self.unregister()
        self.wlr_surface = NULL


cdef class SeatCursorTracker(ListenerObject):

    def __init__(self, uintptr_t seat_ptr, callback):
        super().__init__(N_SEAT_LISTENERS)
        if not seat_ptr:
            raise ValueError("seat pointer is NULL")
        if callback is None:
            raise ValueError("cursor callback is required")
        self.seat = <wlr_seat*> seat_ptr
        self.callback = callback
        self.cursor_surface = None
        self.add_listener(L_REQUEST_SET_CURSOR, xpra_wlr_seat_request_set_cursor_signal(self.seat))

    def cleanup(self) -> None:
        if self.cursor_surface is not None:
            cursor_surface = self.cursor_surface
            self.cursor_surface = None
            cursor_surface.destroy()
        self._detach_all()
        self.seat = NULL
        self.callback = None

    cdef void dispatch(self, wl_listener *listener, void *data) noexcept:
        cdef int slot = self.slot_of(listener)
        if slot == L_REQUEST_SET_CURSOR:
            self.request_set_cursor(data)
        else:
            log.error("Error: unknown seat cursor listener slot %i", slot)

    cdef void request_set_cursor(self, void *data) noexcept:
        if data == NULL or self.seat == NULL:
            return
        cdef wlr_seat_pointer_request_set_cursor_event *event = <wlr_seat_pointer_request_set_cursor_event*> data
        cdef uintptr_t surface_ptr = <uintptr_t> event.surface
        log("request_set_cursor(surface=%#x, hotspot=%i,%i, serial=%i)",
            surface_ptr, event.hotspot_x, event.hotspot_y, event.serial)
        if not xpra_wlr_seat_cursor_event_is_focused(self.seat, event):
            log("ignoring cursor request from unfocused seat client")
            return
        if event.surface == NULL:
            if self.cursor_surface is not None:
                cursor_surface = self.cursor_surface
                self.cursor_surface = None
                cursor_surface.destroy()
            self.emit_cursor(None, event.hotspot_x, event.hotspot_y)
            return
        if self.cursor_surface is not None:
            if self.cursor_surface.wl_surface_ptr == surface_ptr:
                self.cursor_surface.update_hotspot(event.hotspot_x, event.hotspot_y)
                return
            cursor_surface = self.cursor_surface
            self.cursor_surface = None
            cursor_surface.destroy()
        self.cursor_surface = CursorSurface()
        self.cursor_surface.attach(event.surface, event.hotspot_x, event.hotspot_y)
        self.cursor_surface.connect("cursor-image", self.cursor_image)
        self.cursor_surface.connect("destroy", self.cursor_destroy)
        self.cursor_surface.refresh()

    cdef void emit_cursor(self, object image, int hotspot_x, int hotspot_y):
        if self.callback is not None:
            self.callback(image, hotspot_x, hotspot_y)

    def cursor_image(self, wid: int, image, hotspot_x: int, hotspot_y: int) -> None:
        if self.cursor_surface is None or self.cursor_surface.wid != wid:
            return
        self.emit_cursor(image, hotspot_x, hotspot_y)

    def cursor_destroy(self, wid: int) -> None:
        if self.cursor_surface is not None and self.cursor_surface.wid == wid:
            self.cursor_surface = None
            self.emit_cursor(None, 0, 0)
