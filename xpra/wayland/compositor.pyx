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
from libc.string cimport memset
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


# Internal structures
cdef struct server:
    wl_display *display
    wlr_backend *backend
    wlr_renderer *renderer
    wlr_allocator *allocator

    wlr_compositor *compositor
    wlr_subcompositor *subcompositor
    wlr_xdg_shell *xdg_shell
    wlr_scene *scene
    wlr_seat *seat
    wlr_xdg_decoration_manager_v1 *decoration_manager
    xpra_listener new_toplevel_decoration

    wlr_cursor *cursor
    wlr_output_layout *output_layout
    char *seat_name
    xpra_listener new_output
    xpra_listener new_xdg_surface

cdef struct output:
    wl_list link
    server *srv
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


cdef void new_output(wl_listener *listener, void *data) noexcept nogil:
    cdef server *srv = <server*>owner_of(listener)
    cdef wlr_output *wlr_out = <wlr_output*>data

    wlr_output_init_render(wlr_out, srv.allocator, srv.renderer)

    cdef output *out = <output*>calloc(1, sizeof(output))
    out.srv = srv
    out.wlr_output = wlr_out

    out.frame.owner = out
    out.frame.listener.notify = output_frame
    wl_signal_add(&wlr_out.events.frame, &out.frame.listener)

    out.destroy.owner = out
    out.destroy.listener.notify = output_destroy_handler
    wl_signal_add(&wlr_out.events.destroy, &out.destroy.listener)

    out.scene_output = wlr_scene_output_create(srv.scene, wlr_out)

    wlr_output_layout_add_auto(srv.output_layout, wlr_out)

    cdef wlr_output_state state
    wlr_output_state_init(&state)
    wlr_output_commit_state(wlr_out, &state)
    wlr_output_state_finish(&state)

    with gil:
        name = wlr_out.name.decode()
        log("new output: %r", name)
        log(" virtual output %r initialized", name)
        emit("new-output", name, get_output_info(wlr_out))


cdef void add(info: dict, key: str, char* value):
    if value != NULL:
        info[key] = value.decode()




cdef void new_toplevel_decoration(wl_listener *listener, void *data) noexcept nogil:
    cdef server *srv = <server*>owner_of(listener)
    cdef wlr_xdg_toplevel_decoration_v1 *decoration = <wlr_xdg_toplevel_decoration_v1*>data
    cdef wlr_xdg_toplevel *toplevel = decoration.toplevel
    cdef bint ssd = decoration.requested_mode == WLR_XDG_TOPLEVEL_DECORATION_V1_MODE_SERVER_SIDE
    wlr_xdg_toplevel_decoration_v1_set_mode(decoration, WLR_XDG_TOPLEVEL_DECORATION_V1_MODE_SERVER_SIDE)
    with gil:
        emit("ssd", <uintptr_t> toplevel, bool(ssd))


cdef void new_xdg_surface(wl_listener *listener, void *data) noexcept:
    cdef server *srv = <server*>owner_of(listener)
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

    surface.scene_tree = wlr_scene_xdg_surface_create(&srv.scene.tree, xdg_surf)
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
    cdef server srv
    cdef str socket_name
    cdef wl_event_loop *event_loop
    cdef Display display

    def __cinit__(self):
        memset(&self.srv, 0, sizeof(server))
        self.socket_name = ""

    def initialize(self) -> None:
        log("starting headless wayland compositor")

        self.srv.display = wl_display_create()
        if not self.srv.display:
            raise RuntimeError("Failed to create display")

        self.display = Display()
        self.display.display = self.srv.display

        self.event_loop = wl_display_get_event_loop(self.srv.display)
        self.srv.backend = wlr_headless_backend_create(self.event_loop)
        if not self.srv.backend:
            raise RuntimeError("Failed to create headless backend")

        wlr_headless_add_output(self.srv.backend, 1920, 1080)

        self.srv.renderer = wlr_renderer_autocreate(self.srv.backend)
        if not self.srv.renderer:
            raise RuntimeError("Failed to create renderer")

        wlr_renderer_init_wl_display(self.srv.renderer, self.srv.display)

        self.srv.allocator = wlr_allocator_autocreate(self.srv.backend, self.srv.renderer)
        if not self.srv.allocator:
            raise RuntimeError("Failed to create allocator")

        self.srv.compositor = wlr_compositor_create(self.srv.display, 5, self.srv.renderer)
        self.srv.subcompositor = wlr_subcompositor_create(self.srv.display)
        wlr_data_device_manager_create(self.srv.display)

        self.srv.xdg_shell = wlr_xdg_shell_create(self.srv.display, 3)
        self.srv.new_xdg_surface.owner = &self.srv
        self.srv.new_xdg_surface.listener.notify = new_xdg_surface
        wl_signal_add(&self.srv.xdg_shell.events.new_surface, &self.srv.new_xdg_surface.listener)

        self.srv.scene = wlr_scene_create()

        # Create output layout for multi-monitor support
        self.srv.output_layout = wlr_output_layout_create(self.srv.display)
        if not self.srv.output_layout:
            raise RuntimeError("Failed to create output layout")

        self.srv.decoration_manager = wlr_xdg_decoration_manager_v1_create(self.srv.display)
        if not self.srv.decoration_manager:
            log.warn("Warning: unable to create the decoration manager")
        else:
            self.srv.new_toplevel_decoration.owner = &self.srv
            self.srv.new_toplevel_decoration.listener.notify = new_toplevel_decoration
            wl_signal_add(&self.srv.decoration_manager.events.new_toplevel_decoration, &self.srv.new_toplevel_decoration.listener)

        # Create cursor
        self.srv.cursor = wlr_cursor_create()
        if not self.srv.cursor:
            raise RuntimeError("Failed to create cursor")
        wlr_cursor_attach_output_layout(self.srv.cursor, self.srv.output_layout)

        # Create seat for input handling
        self.srv.seat_name = b"seat0"
        self.srv.seat = wlr_seat_create(self.srv.display, self.srv.seat_name)
        cdef int caps = WL_SEAT_CAPABILITY_POINTER | WL_SEAT_CAPABILITY_KEYBOARD | WL_SEAT_CAPABILITY_TOUCH
        wlr_seat_set_capabilities(self.srv.seat, caps)

        self.srv.new_output.owner = &self.srv
        self.srv.new_output.listener.notify = new_output
        wl_signal_add(&self.srv.backend.events.new_output, &self.srv.new_output.listener)

        bname = wl_display_add_socket_auto(self.srv.display)
        if not bname:
            raise RuntimeError("Failed to add socket")
        self.socket_name = bname.decode("utf8")

        if not wlr_backend_start(self.srv.backend):
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
        wl_display_run(self.srv.display)

    def __dealloc__(self):
        self.cleanup()

    def cleanup(self) -> None:
        """Clean up compositor resources"""
        if not self.srv.display:
            return
        wl_display_destroy_clients(self.srv.display)

        if self.srv.new_xdg_surface.listener.link.next != NULL:
            wl_list_remove(&self.srv.new_xdg_surface.listener.link)

        if self.srv.new_output.listener.link.next != NULL:
            wl_list_remove(&self.srv.new_output.listener.link)

        if self.srv.new_toplevel_decoration.listener.link.next != NULL:
            wl_list_remove(&self.srv.new_toplevel_decoration.listener.link)

        if self.srv.scene:
            wlr_scene_node_destroy(&self.srv.scene.tree.node)
            self.srv.scene = NULL
        if self.srv.cursor:
            wlr_cursor_destroy(self.srv.cursor)
            self.srv.cursor = NULL
        if self.srv.output_layout:
            wlr_output_layout_destroy(self.srv.output_layout)
            self.srv.output_layout = NULL
        if self.srv.seat:
            wlr_seat_destroy(self.srv.seat)
            self.srv.seat = NULL
        if self.srv.allocator:
            wlr_allocator_destroy(self.srv.allocator)
            self.srv.allocator = NULL
        if self.srv.renderer:
            wlr_renderer_destroy(self.srv.renderer)
            self.srv.renderer = NULL
        if self.srv.backend:
            wlr_backend_destroy(self.srv.backend)
            self.srv.backend = NULL
        wl_display_destroy(self.srv.display)
        self.srv.display = NULL

    def get_pointer_device(self):
        return WaylandPointer(<uintptr_t> self.srv.seat, <uintptr_t> self.srv.cursor)

    def get_keyboard_device(self):
        return WaylandKeyboard(<uintptr_t> self.srv.seat)
