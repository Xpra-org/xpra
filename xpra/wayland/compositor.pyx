# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# cython: language_level=3

import os
from typing import Dict, List
from collections.abc import Callable

from xpra.log import Logger
from xpra.util.str_fn import Ellipsizer

from libc.stdlib cimport free, calloc
from libc.stdint cimport uintptr_t

from xpra.wayland.pointer import WaylandPointer
from xpra.wayland.keyboard import WaylandKeyboard
from xpra.wayland.surface cimport Surface
from xpra.wayland.display cimport Display
from xpra.wayland.output cimport get_output_info
from xpra.wayland.events cimport xpra_listener, owner_of



# Import definitions from .pxd file
from xpra.wayland.wlroots cimport (
    wl_display, wlr_xdg_shell,
    wl_display_create, wl_display_destroy_clients, wl_display_destroy, wl_display_run,
    wl_listener, wl_signal_add, wl_signal, wl_notify_func_t,
    wlr_xdg_surface, wlr_xdg_surface_events,
    WLR_XDG_SURFACE_ROLE_NONE, WLR_XDG_SURFACE_ROLE_TOPLEVEL,
    wlr_backend, wlr_backend_start, wlr_backend_destroy,
    wlr_seat, wlr_cursor, wlr_output_layout,
    wlr_seat_create, wlr_seat_set_capabilities, wlr_seat_destroy,
    WL_SEAT_CAPABILITY_POINTER, WL_SEAT_CAPABILITY_KEYBOARD, WL_SEAT_CAPABILITY_TOUCH,
    wlr_allocator, wlr_allocator_destroy, wlr_allocator_autocreate,
    wlr_compositor, wlr_compositor_create,
    wlr_subcompositor, wlr_subcompositor_create,
    wlr_xdg_toplevel, wlr_xdg_toplevel_set_size, wlr_xdg_surface_schedule_configure,
    wlr_xdg_decoration_manager_v1, wlr_xdg_toplevel_decoration_v1, wlr_xdg_decoration_manager_v1_create,
    wlr_xdg_toplevel_decoration_v1_set_mode, WLR_XDG_TOPLEVEL_DECORATION_V1_MODE_SERVER_SIDE,
    wlr_cursor_create, wlr_cursor_destroy,
    wlr_xdg_shell_create,
    wlr_scene, wlr_scene_create, wlr_scene_node_destroy, wlr_scene_output_create,
    wlr_scene_xdg_surface_create, wlr_scene_tree, wlr_scene_output, wlr_scene_output_commit,
    wl_display_add_socket_auto,
    wl_event_loop, wl_display_get_event_loop, wl_event_loop_get_fd, wl_event_loop_dispatch,
    wlr_renderer, wlr_renderer_autocreate, wlr_renderer_destroy, wlr_renderer_init_wl_display,
    wlr_headless_backend_create,
    wlr_texture, wlr_client_buffer, wlr_box, wlr_output, wlr_output_state,
    wlr_output_layout_add_auto, wlr_output_layout_create, wlr_output_layout_destroy, wlr_cursor_attach_output_layout,
    wlr_output_commit_state, wlr_output_state_finish,
    wlr_output_state_init, wlr_output_schedule_frame, wlr_output_init_render,
    wlr_headless_add_output,
    wlr_data_device_manager_create,
    wl_list, wl_list_remove,
    WLR_ERROR, WLR_INFO, WLR_DEBUG,
    DRM_FORMAT_ABGR8888, WLR_OUTPUT_ADAPTIVE_SYNC_ENABLED,
)
from xpra.wayland.pixman cimport pixman_region32_t, pixman_box32_t, pixman_region32_rectangles



# generic event listeners:
event_listeners: Dict[str, List[Callable]] = {}


def add_event_listener(event_name: str, callback: Callable) -> None:
    global event_listeners
    event_listeners.setdefault(event_name, []).append(callback)


def remove_event_listener(event_name: str, callback: Callable) -> None:
    global event_listeners
    callbacks = event_listeners.get(event_name)
    if not callbacks:
        return
    if callback not in callbacks:
        return
    callbacks.remove(callback)
    if not callbacks:
        event_listeners.pop(event_name)


def emit(event_name: str, *args) -> None:
    global event_listeners
    callbacks = event_listeners.get(event_name, ())
    log("emit%s callbacks=%s", Ellipsizer(tuple([event_name] + list(args))), callbacks)
    for callback in callbacks:
        callback(*args)


# Per-output bookkeeping; calloc'd in new_output(), freed in
# output_destroy_handler(). Held only by wlroots via the embedded listeners.
cdef struct output:
    wl_list link
    wlr_output *wlr_output
    wlr_scene_output *scene_output
    xpra_listener frame
    xpra_listener destroy


cdef unsigned long wid = 0


log = Logger("wayland")
cdef bint debug = log.is_debug_enabled()


cdef void output_frame(wl_listener *listener, void *data) noexcept nogil:
    if debug:
        with gil:
            log("output_frame(%#x, %#x)", <uintptr_t> listener, <uintptr_t> data)
    cdef output *out = <output*>owner_of(listener)
    wlr_scene_output_commit(out.scene_output, NULL)
    wlr_output_schedule_frame(out.wlr_output)


cdef void output_destroy_handler(wl_listener *listener, void *data) noexcept nogil:
    if debug:
        with gil:
            log("output_destroy_handler(%#x, %#x)", <uintptr_t> listener, <uintptr_t> data)
    cdef output *out = <output*>owner_of(listener)
    wl_list_remove(&out.frame.listener.link)
    wl_list_remove(&out.destroy.listener.link)
    # out.link is for a list we don't manage:
    # wl_list_remove(&out.link)
    free(out)


cdef void new_output(wl_listener *listener, void *data) noexcept:
    # Called by wlroots from within wl_event_loop_dispatch, which is invoked
    # from Python-side WaylandCompositor.process_events() — so the GIL is held.
    cdef WaylandCompositor compositor = <WaylandCompositor>owner_of(listener)
    cdef wlr_output *wlr_out = <wlr_output*>data

    wlr_output_init_render(wlr_out, compositor.allocator, compositor.renderer)

    cdef output *out = <output*>calloc(1, sizeof(output))
    out.wlr_output = wlr_out

    out.frame.owner = out
    out.frame.listener.notify = output_frame
    wl_signal_add(&wlr_out.events.frame, &out.frame.listener)

    out.destroy.owner = out
    out.destroy.listener.notify = output_destroy_handler
    wl_signal_add(&wlr_out.events.destroy, &out.destroy.listener)

    out.scene_output = wlr_scene_output_create(compositor.scene, wlr_out)
    wlr_output_layout_add_auto(compositor.output_layout, wlr_out)

    cdef wlr_output_state state
    wlr_output_state_init(&state)
    wlr_output_commit_state(wlr_out, &state)
    wlr_output_state_finish(&state)

    name = wlr_out.name.decode()
    log("new output: %r", name)
    log(" virtual output %r initialized", name)
    emit("new-output", name, get_output_info(wlr_out))


cdef void new_toplevel_decoration(wl_listener *listener, void *data) noexcept nogil:
    cdef wlr_xdg_toplevel_decoration_v1 *decoration = <wlr_xdg_toplevel_decoration_v1*>data
    cdef wlr_xdg_toplevel *toplevel = decoration.toplevel
    cdef bint ssd = decoration.requested_mode == WLR_XDG_TOPLEVEL_DECORATION_V1_MODE_SERVER_SIDE
    wlr_xdg_toplevel_decoration_v1_set_mode(decoration, WLR_XDG_TOPLEVEL_DECORATION_V1_MODE_SERVER_SIDE)
    with gil:
        emit("ssd", <uintptr_t> toplevel, bool(ssd))


cdef void new_xdg_surface(wl_listener *listener, void *data) noexcept:
    cdef WaylandCompositor compositor = <WaylandCompositor>owner_of(listener)
    cdef wlr_xdg_surface *xdg_surf = <wlr_xdg_surface*>data
    log("New XDG surface CREATED (role: %d, initialized: %d)", xdg_surf.role, xdg_surf.initialized)
    if xdg_surf.role != WLR_XDG_SURFACE_ROLE_NONE and xdg_surf.role != WLR_XDG_SURFACE_ROLE_TOPLEVEL:
        return

    log(" wlr_surface(%#x)=%#x", <uintptr_t> xdg_surf, <uintptr_t> xdg_surf.surface)
    cdef Surface surface = Surface()
    surface.wlr_xdg_surface = xdg_surf
    surface.width = 0
    surface.height = 0
    global wid
    wid += 1
    surface.wid = wid
    log("allocated wid=%#x", wid)

    surface.scene_tree = wlr_scene_xdg_surface_create(&compositor.scene.tree, xdg_surf)
    surface.add_main_listeners()

    cdef wlr_xdg_toplevel *toplevel = xdg_surf.toplevel
    if toplevel:
        surface.register_toplevel_handlers()
        # Send initial configure for the toplevel
        log("Sending initial configure for toplevel")
        wlr_xdg_toplevel_set_size(toplevel, 0, 0)  # 0, 0 = let client choose initial size
        wlr_xdg_surface_schedule_configure(xdg_surf)

    log("All listeners attached")
    title = toplevel.title.decode("utf8") if (toplevel and toplevel.title) else ""
    app_id = toplevel.app_id.decode("utf8") if (toplevel and toplevel.app_id) else ""
    size = (xdg_surf.geometry.width, xdg_surf.geometry.height)
    log("new surface: wlr_xdg_surface=%#x, size=%s", <uintptr_t> xdg_surf, size)
    log(" configured=%s, initialized=%s, initial_commit=%i", bool(xdg_surf.configured), bool(xdg_surf.initialized), bool(xdg_surf.initial_commit))
    # Pass the Surface instance so consumers can connect per-surface signals.
    emit("new-surface", surface, wid, title, app_id, size)


# Python interface
cdef class WaylandCompositor:
    # ---- C-level pointers (formerly the `server` struct, now folded in) ----
    # Accessed in C callbacks via `<WaylandCompositor>owner_of(listener)`.
    cdef wl_display *display_ptr
    cdef wlr_backend *backend
    cdef wlr_renderer *renderer
    cdef wlr_allocator *allocator
    cdef wlr_compositor *wlr_compositor
    cdef wlr_subcompositor *subcompositor
    cdef wlr_xdg_shell *xdg_shell
    cdef wlr_scene *scene
    cdef wlr_seat *seat
    cdef wlr_xdg_decoration_manager_v1 *decoration_manager
    cdef wlr_cursor *cursor
    cdef wlr_output_layout *output_layout
    cdef char *seat_name
    # listeners owned by the compositor (back-pointer is `self`)
    cdef xpra_listener new_toplevel_decoration_listener
    cdef xpra_listener new_output_listener
    cdef xpra_listener new_xdg_surface_listener
    # ---- Python-level wrappers / state ----
    cdef Display display
    cdef str socket_name
    cdef wl_event_loop *event_loop

    def __cinit__(self):
        # All cdef pointer/struct fields are zero-initialised by Cython's tp_alloc.
        self.socket_name = ""

    def initialize(self) -> None:
        log("starting headless wayland compositor")

        self.display_ptr = wl_display_create()
        if not self.display_ptr:
            raise RuntimeError("Failed to create display")

        self.display = Display()
        self.display.display = self.display_ptr

        self.event_loop = wl_display_get_event_loop(self.display_ptr)
        self.backend = wlr_headless_backend_create(self.event_loop)
        if not self.backend:
            raise RuntimeError("Failed to create headless backend")

        wlr_headless_add_output(self.backend, 1920, 1080)

        self.renderer = wlr_renderer_autocreate(self.backend)
        if not self.renderer:
            raise RuntimeError("Failed to create renderer")

        wlr_renderer_init_wl_display(self.renderer, self.display_ptr)

        self.allocator = wlr_allocator_autocreate(self.backend, self.renderer)
        if not self.allocator:
            raise RuntimeError("Failed to create allocator")

        self.wlr_compositor = wlr_compositor_create(self.display_ptr, 5, self.renderer)
        self.subcompositor = wlr_subcompositor_create(self.display_ptr)
        wlr_data_device_manager_create(self.display_ptr)

        self.xdg_shell = wlr_xdg_shell_create(self.display_ptr, 3)
        self.new_xdg_surface_listener.owner = <void*>self
        self.new_xdg_surface_listener.listener.notify = new_xdg_surface
        wl_signal_add(&self.xdg_shell.events.new_surface, &self.new_xdg_surface_listener.listener)

        self.scene = wlr_scene_create()

        # Create output layout for multi-monitor support
        self.output_layout = wlr_output_layout_create(self.display_ptr)
        if not self.output_layout:
            raise RuntimeError("Failed to create output layout")

        self.decoration_manager = wlr_xdg_decoration_manager_v1_create(self.display_ptr)
        if not self.decoration_manager:
            log.warn("Warning: unable to create the decoration manager")
        else:
            self.new_toplevel_decoration_listener.owner = <void*>self
            self.new_toplevel_decoration_listener.listener.notify = new_toplevel_decoration
            wl_signal_add(&self.decoration_manager.events.new_toplevel_decoration,
                          &self.new_toplevel_decoration_listener.listener)

        # Create cursor
        self.cursor = wlr_cursor_create()
        if not self.cursor:
            raise RuntimeError("Failed to create cursor")
        wlr_cursor_attach_output_layout(self.cursor, self.output_layout)

        # Create seat for input handling
        self.seat_name = b"seat0"
        self.seat = wlr_seat_create(self.display_ptr, self.seat_name)
        cdef int caps = WL_SEAT_CAPABILITY_POINTER | WL_SEAT_CAPABILITY_KEYBOARD | WL_SEAT_CAPABILITY_TOUCH
        wlr_seat_set_capabilities(self.seat, caps)

        self.new_output_listener.owner = <void*>self
        self.new_output_listener.listener.notify = new_output
        wl_signal_add(&self.backend.events.new_output, &self.new_output_listener.listener)

        bname = wl_display_add_socket_auto(self.display_ptr)
        if not bname:
            raise RuntimeError("Failed to add socket")
        self.socket_name = bname.decode("utf8")

        if not wlr_backend_start(self.backend):
            raise RuntimeError("Failed to start backend")

        log.info("compositor running on WAYLAND_DISPLAY=%s", self.socket_name)
        os.environ["WAYLAND_DISPLAY"] = self.socket_name

        return self.socket_name

    def get_event_loop_fd(self) -> int:
        return wl_event_loop_get_fd(self.event_loop)

    def get_display(self) -> Display:
        return self.display

    def process_events(self) -> None:
        wl_event_loop_dispatch(self.event_loop, 0)
        self.flush()

    def flush(self) -> None:
        if display := self.display:
            display.flush_clients()

    def run(self) -> None:
        """Run the compositor event loop"""
        log.info("Entering main event loop...")
        wl_display_run(self.display_ptr)

    def __dealloc__(self):
        self.cleanup()

    def cleanup(self) -> None:
        """Clean up compositor resources"""
        if not self.display_ptr:
            return
        wl_display_destroy_clients(self.display_ptr)

        if self.new_xdg_surface_listener.listener.link.next != NULL:
            wl_list_remove(&self.new_xdg_surface_listener.listener.link)
        if self.new_output_listener.listener.link.next != NULL:
            wl_list_remove(&self.new_output_listener.listener.link)
        if self.new_toplevel_decoration_listener.listener.link.next != NULL:
            wl_list_remove(&self.new_toplevel_decoration_listener.listener.link)

        if self.scene:
            wlr_scene_node_destroy(&self.scene.tree.node)
            self.scene = NULL
        if self.cursor:
            wlr_cursor_destroy(self.cursor)
            self.cursor = NULL
        if self.output_layout:
            wlr_output_layout_destroy(self.output_layout)
            self.output_layout = NULL
        if self.seat:
            wlr_seat_destroy(self.seat)
            self.seat = NULL
        if self.allocator:
            wlr_allocator_destroy(self.allocator)
            self.allocator = NULL
        if self.renderer:
            wlr_renderer_destroy(self.renderer)
            self.renderer = NULL
        if self.backend:
            wlr_backend_destroy(self.backend)
            self.backend = NULL
        wl_display_destroy(self.display_ptr)
        self.display_ptr = NULL

    def get_pointer_device(self):
        return WaylandPointer(<uintptr_t> self.seat, <uintptr_t> self.cursor)

    def get_keyboard_device(self):
        return WaylandKeyboard(<uintptr_t> self.seat)
