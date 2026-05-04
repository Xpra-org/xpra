# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from libc.stdint cimport uint8_t, uint32_t, uint64_t
from xpra.wayland.wlroots cimport wl_display, wl_global, wl_list, wl_resource, wl_signal, wlr_seat, wlr_surface
from xpra.wayland.pixman cimport pixman_region32_t


cdef extern from "wlr/types/wlr_relative_pointer_v1.h":
    cdef struct wlr_relative_pointer_manager_v1_events:
        wl_signal destroy
        wl_signal new_relative_pointer

    cdef struct wlr_relative_pointer_manager_v1:
        wl_global *_global
        wl_list relative_pointers
        wlr_relative_pointer_manager_v1_events events
        void *data

    cdef struct wlr_relative_pointer_v1_events:
        wl_signal destroy

    cdef struct wlr_relative_pointer_v1:
        wl_resource *resource
        wl_resource *pointer_resource
        wlr_seat *seat
        wl_list link
        wlr_relative_pointer_v1_events events
        void *data

    wlr_relative_pointer_manager_v1 *wlr_relative_pointer_manager_v1_create(wl_display *display)
    void wlr_relative_pointer_manager_v1_send_relative_motion(
        wlr_relative_pointer_manager_v1 *manager, wlr_seat *seat,
        uint64_t time_usec, double dx, double dy, double dx_unaccel, double dy_unaccel)


cdef extern from *:
    """
    enum wlr_pointer_constraint_v1_type {
        WLR_POINTER_CONSTRAINT_V1_LOCKED,
        WLR_POINTER_CONSTRAINT_V1_CONFINED,
    };

    struct wlr_pointer_constraint_v1_cursor_hint {
        bool enabled;
        double x, y;
    };

    struct wlr_pointer_constraint_v1_state {
        uint32_t committed;
        pixman_region32_t region;
        struct wlr_pointer_constraint_v1_cursor_hint cursor_hint;
    };

    struct wlr_pointer_constraint_v1_events {
        struct wl_signal set_region;
        struct wl_signal destroy;
    };

    struct wlr_pointer_constraints_v1_events {
        struct wl_signal destroy;
        struct wl_signal new_constraint;
    };

    struct wlr_pointer_constraints_v1 {
        struct wl_global *global;
        struct wl_list constraints;
        struct wlr_pointer_constraints_v1_events events;
        void *data;
    };

    struct wlr_pointer_constraint_v1 {
        struct wlr_pointer_constraints_v1 *pointer_constraints;
        struct wl_resource *resource;
        struct wlr_surface *surface;
        struct wlr_seat *seat;
        int lifetime;
        enum wlr_pointer_constraint_v1_type type;
        pixman_region32_t region;
        struct wlr_pointer_constraint_v1_state current, pending;
        struct wl_list link;
        struct wlr_pointer_constraint_v1_events events;
        void *data;
    };

    struct wlr_pointer_constraints_v1 *wlr_pointer_constraints_v1_create(struct wl_display *display);
    struct wlr_pointer_constraint_v1 *wlr_pointer_constraints_v1_constraint_for_surface(
        struct wlr_pointer_constraints_v1 *pointer_constraints,
        struct wlr_surface *surface, struct wlr_seat *seat);
    void wlr_pointer_constraint_v1_send_activated(struct wlr_pointer_constraint_v1 *constraint);
    void wlr_pointer_constraint_v1_send_deactivated(struct wlr_pointer_constraint_v1 *constraint);
    """
    cdef enum wlr_pointer_constraint_v1_type:
        WLR_POINTER_CONSTRAINT_V1_LOCKED
        WLR_POINTER_CONSTRAINT_V1_CONFINED

    cdef struct wlr_pointer_constraint_v1_cursor_hint:
        uint8_t enabled
        double x
        double y

    cdef struct wlr_pointer_constraint_v1_state:
        uint32_t committed
        pixman_region32_t region
        wlr_pointer_constraint_v1_cursor_hint cursor_hint

    cdef struct wlr_pointer_constraint_v1_events:
        wl_signal set_region
        wl_signal destroy

    cdef struct wlr_pointer_constraint_v1:
        wlr_pointer_constraints_v1 *pointer_constraints
        wl_resource *resource
        wlr_surface *surface
        wlr_seat *seat
        int lifetime
        wlr_pointer_constraint_v1_type type
        pixman_region32_t region
        wlr_pointer_constraint_v1_state current
        wlr_pointer_constraint_v1_state pending
        wl_list link
        wlr_pointer_constraint_v1_events events
        void *data

    cdef struct wlr_pointer_constraints_v1_events:
        wl_signal destroy
        wl_signal new_constraint

    cdef struct wlr_pointer_constraints_v1:
        wl_global *_global
        wl_list constraints
        wlr_pointer_constraints_v1_events events
        void *data

    wlr_pointer_constraints_v1 *wlr_pointer_constraints_v1_create(wl_display *display)
    wlr_pointer_constraint_v1 *wlr_pointer_constraints_v1_constraint_for_surface(
        wlr_pointer_constraints_v1 *pointer_constraints, wlr_surface *surface, wlr_seat *seat)
    void wlr_pointer_constraint_v1_send_activated(wlr_pointer_constraint_v1 *constraint)
    void wlr_pointer_constraint_v1_send_deactivated(wlr_pointer_constraint_v1 *constraint)
