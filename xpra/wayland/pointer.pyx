#!/usr/bin/env python3
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic
from collections.abc import Sequence
from typing import Tuple

from xpra.log import Logger

from libc.stdint cimport uintptr_t, uint64_t, uint32_t, int32_t
from xpra.wayland.wlroots cimport (
    wlr_cursor, wlr_seat, wlr_surface, wlr_xdg_surface,
    wlr_axis_orientation, wlr_button_state,
    wlr_cursor_warp, wlr_cursor_move,
    wlr_seat_pointer_notify_motion, wlr_seat_pointer_notify_button, wlr_seat_pointer_notify_axis,
    wlr_seat_pointer_notify_enter, wlr_seat_pointer_notify_frame,
    wlr_seat_pointer_notify_clear_focus,
    wlr_button_state, wlr_axis_orientation,
    WLR_BUTTON_PRESSED, WLR_BUTTON_RELEASED,
    WL_POINTER_AXIS_VERTICAL_SCROLL,
    WL_POINTER_AXIS_SOURCE_WHEEL, WL_POINTER_AXIS_RELATIVE_DIRECTION_IDENTICAL,
    BTN_MOUSE,
)


log = Logger("wayland", "pointer")

base_time = monotonic()


cdef inline uint32_t get_time_msec() noexcept:
    return round((monotonic() - base_time) * 1000)


cdef class WaylandPointer:
    cdef wlr_cursor *cursor
    cdef wlr_seat *seat
    cdef uint32_t offset_x
    cdef uint32_t offset_y

    def __init__(self, uintptr_t seat_ptr, uintptr_t cursor_ptr):
        log("WaylandPointer(%#x, %#x)", seat_ptr, cursor_ptr)
        self.seat = <wlr_seat*> seat_ptr
        self.cursor = <wlr_cursor*> cursor_ptr
        self.offset_x = 0
        self.offset_y = 0
        if not seat_ptr:
            raise ValueError("seat pointer is NULL")
        if not cursor_ptr:
            raise ValueError("cursor pointer is NULL")

    def has_precise_wheel(self) -> bool:
        return True

    def get_position(self) -> Tuple[int, int]:
        return round(self.cursor.x), round(self.cursor.y)

    def move_pointer(self, x: int, y: int, props: dict) -> None:
        log("move_pointer(%i, %i, %s)", x, y, props)
        self.cursor.x = x
        self.cursor.y = y
        # wlr_cursor_warp(self.cursor, NULL, x, y)
        cdef uint32_t time = get_time_msec()
        cdef uint32_t relx = x + self.offset_x
        cdef uint32_t rely = y + self.offset_y
        wlr_seat_pointer_notify_motion(self.seat, time, relx, rely)
        wlr_seat_pointer_notify_frame(self.seat)
        # requires a device?
        # wlr_cursor_move(self.cursor, NULL, delta_x, delta_y)

    def enter_surface(self, uintptr_t xdg_surface_ptr, x: int, y: int) -> bool:
        cdef wlr_xdg_surface *xdg_surface = <wlr_xdg_surface*> xdg_surface_ptr
        cdef wlr_surface *surface = xdg_surface.surface
        if not surface:
            log("surface is NULL")
            return False
        if not surface.mapped:
            log("surface is not mapped")
            return False
        log("enter_surface(%#x, %i, %i) seat=%#x, surface=%#x",
            xdg_surface_ptr, x, y, <uintptr_t> self.seat, <uintptr_t> surface)
        self.offset_x = xdg_surface.geometry.x
        self.offset_y = xdg_surface.geometry.y
        cdef uint32_t relx = x + self.offset_x
        cdef uint32_t rely = y + self.offset_y
        wlr_seat_pointer_notify_enter(self.seat, surface, relx, rely)
        return True

    def leave_surface(self):
        log("leave_surface()")
        wlr_seat_pointer_notify_clear_focus(self.seat)
        self.offset_x = 0
        self.offset_y = 0

    def click(self, position: Sequence[int], button: int, pressed: bool, props: dict) -> None:
        cdef uint32_t time = get_time_msec()
        cdef uint32_t code = BTN_MOUSE + (button - 1)
        cdef wlr_button_state state = WLR_BUTTON_PRESSED if pressed else WLR_BUTTON_RELEASED
        wlr_seat_pointer_notify_button(self.seat, time, code, state)
        wlr_seat_pointer_notify_frame(self.seat)

    def wheel_motion(self, button: int, distance: float) -> None:
        cdef uint32_t time = get_time_msec()
        wlr_seat_pointer_notify_axis(self.seat, time, WL_POINTER_AXIS_VERTICAL_SCROLL,
                                     distance, round(distance),
                                     WL_POINTER_AXIS_SOURCE_WHEEL, WL_POINTER_AXIS_RELATIVE_DIRECTION_IDENTICAL)
        wlr_seat_pointer_notify_frame(self.seat)
