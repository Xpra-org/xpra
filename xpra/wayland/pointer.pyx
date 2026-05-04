#!/usr/bin/env python3
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic
from collections.abc import Sequence
from typing import Dict, Tuple

from xpra.log import Logger

from libc.stdint cimport uintptr_t, uint64_t, uint32_t, int32_t
from xpra.wayland.events cimport ListenerObject
from xpra.wayland.wlroots cimport (
    wl_listener,
    wlr_cursor, wlr_seat, wlr_surface, wlr_xdg_surface,
    wl_pointer_axis, wlr_button_state,
    wlr_cursor_warp, wlr_cursor_move,
    wlr_seat_pointer_notify_motion, wlr_seat_pointer_notify_button, wlr_seat_pointer_notify_axis,
    wlr_seat_pointer_notify_enter, wlr_seat_pointer_notify_frame,
    wlr_seat_pointer_notify_clear_focus,
    wlr_button_state,
    WLR_BUTTON_PRESSED, WLR_BUTTON_RELEASED,
    WL_POINTER_AXIS_VERTICAL_SCROLL, WL_POINTER_AXIS_HORIZONTAL_SCROLL,
    WL_POINTER_AXIS_SOURCE_WHEEL, WL_POINTER_AXIS_RELATIVE_DIRECTION_IDENTICAL,
    BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_SIDE, BTN_EXTRA, BTN_FORWARD, BTN_BACK,
)
from xpra.wayland.pointer_protocols cimport (
    wlr_relative_pointer_manager_v1, wlr_relative_pointer_manager_v1_send_relative_motion,
    wlr_pointer_constraints_v1, wlr_pointer_constraint_v1,
    wlr_pointer_constraints_v1_constraint_for_surface,
    wlr_pointer_constraint_v1_send_activated, wlr_pointer_constraint_v1_send_deactivated,
    WLR_POINTER_CONSTRAINT_V1_LOCKED, WLR_POINTER_CONSTRAINT_V1_CONFINED,
)


log = Logger("wayland", "pointer")

base_time = monotonic()
WHEEL_AXIS_STEP = 15.0
WHEEL_DISCRETE_STEP = 120


BUTTON_MAP: Dict[int, int] = {
    1: BTN_LEFT,
    2: BTN_MIDDLE,
    3: BTN_RIGHT,
    8: BTN_SIDE,
    9: BTN_EXTRA,
    10: BTN_FORWARD,
    11: BTN_BACK,
}
WHEEL_BUTTONS: Dict[int, Tuple[wl_pointer_axis, float]] = {
    4: (WL_POINTER_AXIS_VERTICAL_SCROLL, -WHEEL_AXIS_STEP),
    5: (WL_POINTER_AXIS_VERTICAL_SCROLL, WHEEL_AXIS_STEP),
    6: (WL_POINTER_AXIS_HORIZONTAL_SCROLL, -WHEEL_AXIS_STEP),
    7: (WL_POINTER_AXIS_HORIZONTAL_SCROLL, WHEEL_AXIS_STEP),
}


cdef inline uint32_t get_time_msec() noexcept:
    return round((monotonic() - base_time) * 1000)


cdef inline uint64_t get_time_usec() noexcept:
    return round((monotonic() - base_time) * 1000000)


cdef inline int clamp_int(int value, int low, int high) noexcept:
    if value < low:
        return low
    if value > high:
        return high
    return value


cdef enum PointerListener:
    L_NEW_CONSTRAINT
    N_POINTER_LISTENERS


cdef enum ConstraintListener:
    L_CONSTRAINT_SET_REGION
    L_CONSTRAINT_DESTROY
    N_CONSTRAINT_LISTENERS


cdef class WaylandPointer(ListenerObject):
    cdef wlr_cursor *cursor
    cdef wlr_seat *seat
    cdef wlr_relative_pointer_manager_v1 *relative_pointer_manager
    cdef wlr_pointer_constraints_v1 *pointer_constraints
    cdef wlr_surface *focused_surface
    cdef wlr_xdg_surface *focused_xdg_surface
    cdef wlr_pointer_constraint_v1 *active_constraint
    cdef uint32_t offset_x
    cdef uint32_t offset_y
    cdef int last_x
    cdef int last_y
    cdef bint have_last
    cdef dict constraints

    def __init__(self, uintptr_t seat_ptr, uintptr_t cursor_ptr,
                 uintptr_t relative_pointer_manager_ptr=0, uintptr_t pointer_constraints_ptr=0):
        super().__init__(N_POINTER_LISTENERS)
        log("WaylandPointer(%#x, %#x, %#x, %#x)",
            seat_ptr, cursor_ptr, relative_pointer_manager_ptr, pointer_constraints_ptr)
        self.seat = <wlr_seat*> seat_ptr
        self.cursor = <wlr_cursor*> cursor_ptr
        self.relative_pointer_manager = <wlr_relative_pointer_manager_v1*> relative_pointer_manager_ptr
        self.pointer_constraints = <wlr_pointer_constraints_v1*> pointer_constraints_ptr
        self.focused_surface = NULL
        self.focused_xdg_surface = NULL
        self.active_constraint = NULL
        self.offset_x = 0
        self.offset_y = 0
        self.last_x = 0
        self.last_y = 0
        self.have_last = False
        self.constraints = {}
        if not seat_ptr:
            raise ValueError("seat pointer is NULL")
        if not cursor_ptr:
            raise ValueError("cursor pointer is NULL")
        if self.pointer_constraints != NULL:
            self.add_listener(L_NEW_CONSTRAINT, &self.pointer_constraints.events.new_constraint)

    cdef void dispatch(self, wl_listener *listener, void *data) noexcept:
        cdef int slot = self.slot_of(listener)
        if slot == L_NEW_CONSTRAINT:
            self.new_constraint(<wlr_pointer_constraint_v1*> data)
        else:
            log.error("Error: unexpected pointer event slot %i", slot)

    def has_precise_wheel(self) -> bool:
        return True

    def get_position(self) -> Tuple[int, int]:
        return round(self.cursor.x), round(self.cursor.y)

    def move_pointer(self, x: int, y: int, props: dict) -> None:
        log("move_pointer(%i, %i, %s)", x, y, props)
        cdef uint32_t time = get_time_msec()
        cdef double dx = 0
        cdef double dy = 0
        cdef int sx = x
        cdef int sy = y
        if self.have_last:
            dx = x - self.last_x
            dy = y - self.last_y
        else:
            self.have_last = True
        self.last_x = x
        self.last_y = y
        if self.relative_pointer_manager != NULL and (dx != 0 or dy != 0):
            wlr_relative_pointer_manager_v1_send_relative_motion(
                self.relative_pointer_manager, self.seat, get_time_usec(), dx, dy, dx, dy)
        if self.active_constraint != NULL and self.active_constraint.type == WLR_POINTER_CONSTRAINT_V1_LOCKED:
            log("locked pointer constraint active: suppressing absolute motion")
            return
        if self.active_constraint != NULL and self.active_constraint.type == WLR_POINTER_CONSTRAINT_V1_CONFINED:
            self.confine_position(&sx, &sy)
        self.cursor.x = sx
        self.cursor.y = sy
        # wlr_cursor_warp(self.cursor, NULL, sx, sy)
        cdef uint32_t relx = sx + self.offset_x
        cdef uint32_t rely = sy + self.offset_y
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
        if self.focused_surface != surface:
            self.deactivate_constraint()
        self.focused_xdg_surface = xdg_surface
        self.focused_surface = surface
        self.offset_x = xdg_surface.geometry.x
        self.offset_y = xdg_surface.geometry.y
        self.last_x = x
        self.last_y = y
        self.have_last = True
        cdef uint32_t relx = x + self.offset_x
        cdef uint32_t rely = y + self.offset_y
        wlr_seat_pointer_notify_enter(self.seat, surface, relx, rely)
        wlr_seat_pointer_notify_frame(self.seat)
        self.activate_constraint()
        return True

    def leave_surface(self):
        log("leave_surface()")
        self.deactivate_constraint()
        wlr_seat_pointer_notify_clear_focus(self.seat)
        self.focused_surface = NULL
        self.focused_xdg_surface = NULL
        self.offset_x = 0
        self.offset_y = 0
        self.have_last = False

    def click(self, button: int, pressed: bool, props: dict) -> None:
        log("click%s", (button, pressed, props))
        cdef uint32_t time = get_time_msec()
        cdef uint32_t code
        cdef wlr_button_state state = WLR_BUTTON_PRESSED if pressed else WLR_BUTTON_RELEASED
        wheel = WHEEL_BUTTONS.get(button)
        if wheel:
            if pressed:
                self.do_wheel_motion(time, wheel[0], wheel[1],
                                     round(wheel[1] / WHEEL_AXIS_STEP * WHEEL_DISCRETE_STEP))
            return
        mapped = BUTTON_MAP.get(button, -1)
        if mapped < 0:
            log.warn("Warning: unsupported pointer button %i", button)
            return
        code = <uint32_t> mapped
        wlr_seat_pointer_notify_button(self.seat, time, code, state)
        wlr_seat_pointer_notify_frame(self.seat)

    def wheel_motion(self, button: int, distance: float) -> None:
        cdef uint32_t time = get_time_msec()
        cdef wl_pointer_axis orientation = WL_POINTER_AXIS_VERTICAL_SCROLL
        if button in (6, 7):
            orientation = WL_POINTER_AXIS_HORIZONTAL_SCROLL
        self.do_wheel_motion(time, orientation, distance, round(distance * WHEEL_DISCRETE_STEP))

    cdef void do_wheel_motion(self, uint32_t time, wl_pointer_axis orientation, double distance,
                              int32_t discrete) noexcept:
        log("do_wheel_motion%s", (time, orientation, distance, discrete))
        wlr_seat_pointer_notify_axis(self.seat, time, orientation,
                                     distance, discrete,
                                     WL_POINTER_AXIS_SOURCE_WHEEL, WL_POINTER_AXIS_RELATIVE_DIRECTION_IDENTICAL)
        wlr_seat_pointer_notify_frame(self.seat)

    cdef void new_constraint(self, wlr_pointer_constraint_v1 *constraint) noexcept:
        if constraint == NULL:
            return
        log("new pointer constraint %#x surface=%#x seat=%#x type=%i",
            <uintptr_t> constraint, <uintptr_t> constraint.surface,
            <uintptr_t> constraint.seat, constraint.type)
        if constraint.seat != self.seat:
            log("ignoring pointer constraint for another seat")
            return
        self.constraints[<uintptr_t> constraint] = PointerConstraint(self, <uintptr_t> constraint)
        if self.focused_surface != NULL and constraint.surface == self.focused_surface:
            self.activate_constraint()

    cdef void remove_constraint(self, wlr_pointer_constraint_v1 *constraint) noexcept:
        cdef uintptr_t constraint_ptr = <uintptr_t> constraint
        log("remove pointer constraint %#x", constraint_ptr)
        self.constraints.pop(constraint_ptr, None)
        if self.active_constraint == constraint:
            self.active_constraint = NULL

    cdef void activate_constraint(self) noexcept:
        cdef wlr_pointer_constraint_v1 *constraint = NULL
        if self.pointer_constraints == NULL or self.focused_surface == NULL:
            return
        constraint = wlr_pointer_constraints_v1_constraint_for_surface(
            self.pointer_constraints, self.focused_surface, self.seat)
        if constraint == self.active_constraint:
            return
        self.deactivate_constraint()
        if constraint == NULL:
            return
        self.active_constraint = constraint
        log("activating pointer constraint %#x type=%i", <uintptr_t> constraint, constraint.type)
        wlr_pointer_constraint_v1_send_activated(constraint)

    cdef void deactivate_constraint(self) noexcept:
        cdef wlr_pointer_constraint_v1 *constraint = self.active_constraint
        if constraint == NULL:
            return
        self.active_constraint = NULL
        log("deactivating pointer constraint %#x", <uintptr_t> constraint)
        wlr_pointer_constraint_v1_send_deactivated(constraint)

    cdef void constraint_region_changed(self, wlr_pointer_constraint_v1 *constraint) noexcept:
        cdef int x = 0
        cdef int y = 0
        log("pointer constraint %#x region changed", <uintptr_t> constraint)
        if constraint == self.active_constraint and constraint.type == WLR_POINTER_CONSTRAINT_V1_CONFINED:
            x = <int> self.cursor.x
            y = <int> self.cursor.y
            self.confine_position(&x, &y)
            self.cursor.x = x
            self.cursor.y = y

    cdef void confine_position(self, int *x, int *y) noexcept:
        cdef int min_x = 0
        cdef int min_y = 0
        cdef int max_x = 0
        cdef int max_y = 0
        cdef wlr_pointer_constraint_v1 *constraint = self.active_constraint
        if self.focused_surface == NULL:
            return
        max_x = self.focused_surface.current.width - 1
        max_y = self.focused_surface.current.height - 1
        if constraint != NULL and constraint.region.extents.x2 > constraint.region.extents.x1 \
                and constraint.region.extents.y2 > constraint.region.extents.y1:
            min_x = constraint.region.extents.x1
            min_y = constraint.region.extents.y1
            max_x = constraint.region.extents.x2 - 1
            max_y = constraint.region.extents.y2 - 1
        if max_x < min_x:
            max_x = min_x
        if max_y < min_y:
            max_y = min_y
        x[0] = clamp_int(x[0], min_x, max_x)
        y[0] = clamp_int(y[0], min_y, max_y)


cdef class PointerConstraint(ListenerObject):
    cdef WaylandPointer pointer
    cdef wlr_pointer_constraint_v1 *constraint

    def __init__(self, WaylandPointer pointer, uintptr_t constraint_ptr):
        super().__init__(N_CONSTRAINT_LISTENERS)
        self.pointer = pointer
        self.constraint = <wlr_pointer_constraint_v1*> constraint_ptr
        if self.constraint == NULL:
            raise ValueError("pointer constraint is NULL")
        self.add_listener(L_CONSTRAINT_SET_REGION, &self.constraint.events.set_region)
        self.add_listener(L_CONSTRAINT_DESTROY, &self.constraint.events.destroy)

    cdef void dispatch(self, wl_listener *listener, void *data) noexcept:
        cdef int slot = self.slot_of(listener)
        if slot == L_CONSTRAINT_SET_REGION:
            self.pointer.constraint_region_changed(self.constraint)
        elif slot == L_CONSTRAINT_DESTROY:
            self._detach_all()
            self.pointer.remove_constraint(self.constraint)
            self.constraint = NULL
        else:
            log.error("Error: unexpected pointer constraint event slot %i", slot)
