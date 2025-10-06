# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# cython: language_level=3

import os
from collections.abc import Callable

from xpra.log import Logger
from libc.stdlib cimport malloc, free, calloc
from libc.string cimport memset
from libc.stdint cimport uintptr_t, uint64_t, uint8_t

# Import definitions from .pxd file
from xpra.wayland.wlroots cimport (
    wl_display, wlr_xdg_shell,
    wl_display_create, wl_display_destroy_clients, wl_display_destroy, wl_display_run,
    wl_listener, wl_signal_add, wl_signal,
    wlr_xdg_surface_events,
    wlr_backend, wlr_backend_start, wlr_backend_destroy,
    wlr_allocator, wlr_allocator_destroy, wlr_allocator_autocreate,
    wlr_compositor, wlr_compositor_create,
    wlr_xdg_shell_create,
    wlr_scene, wlr_scene_create, wlr_scene_node_destroy, wlr_scene_output_create,
    wlr_scene_xdg_surface_create, wlr_scene_tree, wlr_scene_output, wlr_scene_output_commit,
    wl_display_add_socket_auto,
    wl_event_loop, wl_display_get_event_loop, wl_event_loop_get_fd, wl_event_loop_dispatch,
    wl_display_flush_clients,
    wlr_renderer, wlr_renderer_autocreate, wlr_renderer_destroy, wlr_renderer_init_wl_display,
    wlr_headless_backend_create,
    wlr_surface, wlr_texture, wlr_client_buffer, wlr_box, wlr_output, wlr_output_state,
    wlr_xdg_toplevel, wlr_xdg_surface,
    wlr_texture_read_pixels_options, wlr_texture_read_pixels,
    wlr_xdg_toplevel_resize_event, wlr_xdg_toplevel_set_size,
    wlr_xdg_surface_schedule_configure,
    wlr_output_commit_state, wlr_output_state_finish,
    wlr_output_state_init, wlr_output_schedule_frame, wlr_output_init_render,
    wlr_headless_add_output,
    wlr_data_device_manager_create,
    wl_list, wl_list_remove,
    WLR_ERROR, WLR_INFO, WLR_DEBUG,
    DRM_FORMAT_ABGR8888,
    WLR_XDG_SURFACE_ROLE_NONE,
    WLR_XDG_SURFACE_ROLE_TOPLEVEL,
)

# Global Python callback storage
cdef object g_pixel_callback = None


# Internal structures
cdef struct server:
    wl_display *display
    wlr_backend *backend
    wlr_renderer *renderer
    wlr_allocator *allocator

    wlr_compositor *compositor
    wlr_xdg_shell *xdg_shell
    wlr_scene *scene

    wl_listener new_output
    wl_listener new_xdg_surface

cdef struct output:
    wl_list link
    server *srv
    wlr_output *wlr_output
    wlr_scene_output *scene_output

    wl_listener frame
    wl_listener destroy

cdef struct xdg_surface:
    server *srv
    wlr_xdg_surface *wlr_xdg_surface
    wlr_scene_tree *scene_tree

    wl_listener map
    wl_listener unmap
    wl_listener destroy
    wl_listener commit
    wl_listener request_move
    wl_listener request_resize
    wl_listener request_maximize
    wl_listener request_fullscreen
    wl_listener request_minimize
    wl_listener set_title
    wl_listener set_app_id

    uint8_t *pixels
    int width
    int height


# Helper macros as inline functions with compile-time offset calculation
cdef inline output* output_from_frame(wl_listener *listener) nogil:
    cdef size_t offset = <size_t>(<char*>&(<output*>0).frame - <char*>0)
    return <output*>(<char*>listener - offset)

cdef inline output* output_from_destroy(wl_listener *listener) nogil:
    cdef size_t offset = <size_t>(<char*>&(<output*>0).destroy - <char*>0)
    return <output*>(<char*>listener - offset)

cdef inline server* server_from_new_output(wl_listener *listener) nogil:
    cdef size_t offset = <size_t>(<char*>&(<server*>0).new_output - <char*>0)
    return <server*>(<char*>listener - offset)

cdef inline server* server_from_new_xdg_surface(wl_listener *listener) nogil:
    cdef size_t offset = <size_t>(<char*>&(<server*>0).new_xdg_surface - <char*>0)
    return <server*>(<char*>listener - offset)

cdef inline xdg_surface* xdg_surface_from_map(wl_listener *listener) nogil:
    cdef size_t offset = <size_t>(<char*>&(<xdg_surface*>0).map - <char*>0)
    return <xdg_surface*>(<char*>listener - offset)

cdef inline xdg_surface* xdg_surface_from_unmap(wl_listener *listener) nogil:
    cdef size_t offset = <size_t>(<char*>&(<xdg_surface*>0).unmap - <char*>0)
    return <xdg_surface*>(<char*>listener - offset)

cdef inline xdg_surface* xdg_surface_from_destroy(wl_listener *listener) nogil:
    cdef size_t offset = <size_t>(<char*>&(<xdg_surface*>0).destroy - <char*>0)
    return <xdg_surface*>(<char*>listener - offset)

cdef inline xdg_surface* xdg_surface_from_commit(wl_listener *listener) nogil:
    cdef size_t offset = <size_t>(<char*>&(<xdg_surface*>0).commit - <char*>0)
    return <xdg_surface*>(<char*>listener - offset)

cdef inline xdg_surface* xdg_surface_from_set_title(wl_listener *listener) nogil:
    cdef size_t offset = <size_t>(<char*>&(<xdg_surface*>0).set_title - <char*>0)
    return <xdg_surface*>(<char*>listener - offset)

cdef inline xdg_surface* xdg_surface_from_set_app_id(wl_listener *listener) nogil:
    cdef size_t offset = <size_t>(<char*>&(<xdg_surface*>0).set_app_id - <char*>0)
    return <xdg_surface*>(<char*>listener - offset)


log = Logger("wayland")
cdef bint debug = log.is_debug_enabled()


# Callback implementations
cdef void capture_surface_pixels(xdg_surface *surface) noexcept nogil:
    cdef wlr_surface *wlr_surface = surface.wlr_xdg_surface.surface
    cdef wlr_client_buffer *client_buffer
    cdef wlr_texture *texture
    cdef int width, height
    cdef wlr_box src_box
    cdef wlr_texture_read_pixels_options opts

    if not wlr_surface.buffer:
        return

    client_buffer = wlr_surface.buffer
    texture = client_buffer.texture

    if not texture:
        return

    width = texture.width
    height = texture.height

    if surface.width != width or surface.height != height:
        if surface.pixels:
            free(surface.pixels)
        surface.width = width
        surface.height = height
        surface.pixels = <uint8_t*> malloc(width * height * 4)

        with gil:
            if not surface.pixels:
                log.error("Error: failed to allocate pixel buffer")
                return
            log("Allocated pixel buffer: %dx%d (%d bytes)", width, height, width * height * 4)

    opts.data = surface.pixels
    opts.format = DRM_FORMAT_ABGR8888
    opts.stride = width * 4
    opts.dst_x = 0
    opts.dst_y = 0
    # we can't modify src_box because it is declared as const,
    # but since we also cannot initialize the struct with the value we need,
    # let's patch it up by hand afterwards - yes this is safe
    memset(<void *> &opts.src_box, 0, sizeof(wlr_box))
    cdef int *iptr
    iptr = <int*> &opts.src_box.width
    iptr[0] = width
    iptr = <int*> &opts.src_box.height
    iptr[0] = height

    cdef bint success = wlr_texture_read_pixels(texture, &opts)
    if not success:
        with gil:
            log.error("Error: failed to read texture pixels")
        return
    cdef uint64_t sum_r = 0
    cdef uint64_t sum_g = 0
    cdef uint64_t sum_b = 0
    cdef int total_pixels = width * height

    cdef int i
    for i in range(total_pixels):
        sum_r += surface.pixels[i * 4 + 0]
        sum_g += surface.pixels[i * 4 + 1]
        sum_b += surface.pixels[i * 4 + 2]

    with gil:
        log("Captured %ix%i pixels | Avg RGB: (%i, %i, %i)",
            width, height,
            sum_r / total_pixels,
            sum_g / total_pixels,
            sum_b / total_pixels)

    # Call Python callback if set
    if g_pixel_callback is not None:
        with gil:
            try:
                # Create memoryview of pixel data
                # cdef uint8_t[:,:,::1] pixel_array = <uint8_t[:height,:width,:4]>surface.pixels
                pixel_array = b""
                g_pixel_callback(pixel_array, width, height)
            except:
                pass

cdef void output_frame(wl_listener *listener, void *data) noexcept nogil:
    if debug:
        with gil:
            log("output_frame(%#x, %#x)", <uintptr_t> listener, <uintptr_t> data)
    cdef output *out = output_from_frame(listener)
    wlr_scene_output_commit(out.scene_output, NULL)
    wlr_output_schedule_frame(out.wlr_output)

cdef void output_destroy_handler(wl_listener *listener, void *data) noexcept nogil:
    if debug:
        with gil:
            log("output_destroy_handler(%#x, %#x)", <uintptr_t> listener, <uintptr_t> data)
    cdef output *out = output_from_destroy(listener)
    wl_list_remove(&out.frame.link)
    wl_list_remove(&out.destroy.link)
    wl_list_remove(&out.link)
    free(out)

cdef void new_output(wl_listener *listener, void *data) noexcept nogil:
    cdef server *srv = server_from_new_output(listener)
    cdef wlr_output *wlr_out = <wlr_output*>data
    cdef output *out
    cdef wlr_output_state state

    with gil:
        name = wlr_out.name.decode()
        log.info("New output: %r", name)

    wlr_output_init_render(wlr_out, srv.allocator, srv.renderer)

    out = <output*>calloc(1, sizeof(output))
    out.srv = srv
    out.wlr_output = wlr_out

    out.frame.notify = output_frame
    wl_signal_add(&wlr_out.events.frame, &out.frame)

    out.destroy.notify = output_destroy_handler
    wl_signal_add(&wlr_out.events.destroy, &out.destroy)

    out.scene_output = wlr_scene_output_create(srv.scene, wlr_out)

    wlr_output_state_init(&state)
    wlr_output_commit_state(wlr_out, &state)
    wlr_output_state_finish(&state)

    with gil:
        log.info("Output %r initialized", name)

cdef void xdg_surface_map(wl_listener *listener, void *data) noexcept nogil:
    cdef xdg_surface *surface = xdg_surface_from_map(listener)
    cdef wlr_xdg_toplevel *toplevel = surface.wlr_xdg_surface.toplevel

    with gil:
        log.info("XDG surface MAPPED:")
        if toplevel.title:
            title = toplevel.title.decode("utf8")
            log.info("  Title: %r", title)
        if toplevel.app_id:
            app_id = toplevel.app_id.decode("utf8")
            log.info("  App ID: %r", app_id)

cdef void xdg_surface_unmap(wl_listener *listener, void *data) noexcept nogil:
    cdef xdg_surface *surface = xdg_surface_from_unmap(listener)
    with gil:
        log.info("XDG surface UNMAPPED")

cdef void xdg_surface_destroy_handler(wl_listener *listener, void *data) noexcept:
    cdef xdg_surface *surface = xdg_surface_from_destroy(listener)
    toplevel = surface.wlr_xdg_surface.toplevel != NULL

    log.info("XDG surface DESTROYED, toplevel=%s", bool(toplevel))

    wl_list_remove(&surface.map.link)
    wl_list_remove(&surface.unmap.link)
    wl_list_remove(&surface.destroy.link)
    wl_list_remove(&surface.commit.link)
    if toplevel:
        wl_list_remove(&surface.request_move.link)
        wl_list_remove(&surface.request_resize.link)
        wl_list_remove(&surface.request_maximize.link)
        wl_list_remove(&surface.request_fullscreen.link)
        wl_list_remove(&surface.request_minimize.link)
        wl_list_remove(&surface.set_title.link)
        wl_list_remove(&surface.set_app_id.link)

    if surface.pixels:
        free(surface.pixels)
    free(surface)
    if debug:
        log("xdg surface freed")

cdef void xdg_surface_commit(wl_listener *listener, void *data) noexcept nogil:
    if debug:
        with gil:
            log("xdg_surface_commit(%#x, %#x)", <uintptr_t> listener, <uintptr_t> data)
    cdef xdg_surface *surface = xdg_surface_from_commit(listener)
    cdef wlr_xdg_surface *xdg_surface = surface.wlr_xdg_surface

    if xdg_surface.toplevel != NULL and xdg_surface.initialized and not xdg_surface.configured:
        with gil:
            log("Surface initialized, sending first configure")
        wlr_xdg_toplevel_set_size(xdg_surface.toplevel, 800, 600)
        wlr_xdg_surface_schedule_configure(xdg_surface)

    if xdg_surface.surface.mapped:
        capture_surface_pixels(surface)

cdef void xdg_toplevel_request_move(wl_listener *listener, void *data) noexcept nogil:
    if debug:
        with gil:
            log("Surface REQUEST MOVE")

cdef void xdg_toplevel_request_resize(wl_listener *listener, void *data) noexcept nogil:
    cdef wlr_xdg_toplevel_resize_event *event = <wlr_xdg_toplevel_resize_event*>data
    if debug:
        with gil:
            log("Surface REQUEST RESIZE (edges: %d)", event.edges)

cdef void xdg_toplevel_request_maximize(wl_listener *listener, void *data) noexcept nogil:
    if debug:
        with gil:
            log("Surface REQUEST MAXIMIZE")

cdef void xdg_toplevel_request_fullscreen(wl_listener *listener, void *data) noexcept nogil:
    if debug:
        with gil:
            log("Surface REQUEST FULLSCREEN")

cdef void xdg_toplevel_request_minimize(wl_listener *listener, void *data) noexcept nogil:
    if debug:
        with gil:
            log("Surface REQUEST MINIMIZE")

cdef void xdg_toplevel_set_title_handler(wl_listener *listener, void *data) noexcept nogil:
    cdef xdg_surface *surface = xdg_surface_from_set_title(listener)
    if surface.wlr_xdg_surface.toplevel.title:
        with gil:
            log.info("Surface SET TITLE: %s", surface.wlr_xdg_surface.toplevel.title)

cdef void xdg_toplevel_set_app_id_handler(wl_listener *listener, void *data) noexcept nogil:
    cdef xdg_surface *surface = xdg_surface_from_set_app_id(listener)
    if surface.wlr_xdg_surface.toplevel.app_id:
        with gil:
            log.info("Surface SET APP_ID: %s", surface.wlr_xdg_surface.toplevel.app_id)

cdef void new_xdg_surface(wl_listener *listener, void *data) noexcept:
    cdef server *srv = server_from_new_xdg_surface(listener)
    cdef wlr_xdg_surface *xdg_surf = <wlr_xdg_surface*>data
    cdef xdg_surface *surface

    log("New XDG surface CREATED (role: %d, initialized: %d)", xdg_surf.role, xdg_surf.initialized)

    if xdg_surf.role != WLR_XDG_SURFACE_ROLE_NONE and xdg_surf.role != WLR_XDG_SURFACE_ROLE_TOPLEVEL:
        return

    surface = <xdg_surface*>calloc(1, sizeof(xdg_surface))
    surface.srv = srv
    surface.wlr_xdg_surface = xdg_surf
    surface.pixels = NULL
    surface.width = 0
    surface.height = 0

    surface.scene_tree = wlr_scene_xdg_surface_create(&srv.scene.tree, xdg_surf)

    surface.map.notify = xdg_surface_map
    wl_signal_add(&xdg_surf.surface.events.map, &surface.map)

    surface.unmap.notify = xdg_surface_unmap
    wl_signal_add(&xdg_surf.surface.events.unmap, &surface.unmap)

    surface.destroy.notify = xdg_surface_destroy_handler
    wl_signal_add(&xdg_surf.surface.events.destroy, &surface.destroy)

    surface.commit.notify = xdg_surface_commit
    wl_signal_add(&xdg_surf.surface.events.commit, &surface.commit)

    if xdg_surf.toplevel:
        log.info("Surface has toplevel, attaching toplevel handlers")

        surface.request_move.notify = xdg_toplevel_request_move
        wl_signal_add(&xdg_surf.toplevel.events.request_move, &surface.request_move)

        surface.request_resize.notify = xdg_toplevel_request_resize
        wl_signal_add(&xdg_surf.toplevel.events.request_resize, &surface.request_resize)

        surface.request_maximize.notify = xdg_toplevel_request_maximize
        wl_signal_add(&xdg_surf.toplevel.events.request_maximize, &surface.request_maximize)

        surface.request_fullscreen.notify = xdg_toplevel_request_fullscreen
        wl_signal_add(&xdg_surf.toplevel.events.request_fullscreen, &surface.request_fullscreen)

        surface.request_minimize.notify = xdg_toplevel_request_minimize
        wl_signal_add(&xdg_surf.toplevel.events.request_minimize, &surface.request_minimize)

        surface.set_title.notify = xdg_toplevel_set_title_handler
        wl_signal_add(&xdg_surf.toplevel.events.set_title, &surface.set_title)

        surface.set_app_id.notify = xdg_toplevel_set_app_id_handler
        wl_signal_add(&xdg_surf.toplevel.events.set_app_id, &surface.set_app_id)

    log("All listeners attached")


# Python interface
cdef class WaylandCompositor:
    cdef server srv
    cdef str socket_name
    cdef wl_event_loop *event_loop

    def __cinit__(self):
        memset(&self.srv, 0, sizeof(server))
        self.socket_name = ""

    def initialize(self) -> None:
        """Initialize the compositor"""
        log.info("Starting headless compositor...")

        self.srv.display = wl_display_create()
        if not self.srv.display:
            raise RuntimeError("Failed to create display")

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
        wlr_data_device_manager_create(self.srv.display)

        self.srv.xdg_shell = wlr_xdg_shell_create(self.srv.display, 3)
        self.srv.new_xdg_surface.notify = new_xdg_surface
        wl_signal_add(&self.srv.xdg_shell.events.new_surface, &self.srv.new_xdg_surface)

        self.srv.scene = wlr_scene_create()

        self.srv.new_output.notify = new_output
        wl_signal_add(&self.srv.backend.events.new_output, &self.srv.new_output)

        bname = wl_display_add_socket_auto(self.srv.display)
        if not bname:
            raise RuntimeError("Failed to add socket")
        self.socket_name = bname.decode("utf8")

        if not wlr_backend_start(self.srv.backend):
            raise RuntimeError("Failed to start backend")

        log.info("Compositor running on WAYLAND_DISPLAY=%s", self.socket_name)
        os.environ["WAYLAND_DISPLAY"] = self.socket_name

        return self.socket_name

    def get_event_loop_fd(self) -> int:
        return wl_event_loop_get_fd(self.event_loop)

    def process_events(self) -> None:
        wl_event_loop_dispatch(self.event_loop, 0)
        wl_display_flush_clients(self.srv.display)

    def run(self) -> None:
        """Run the compositor event loop"""
        log.info("Entering main event loop...")
        wl_display_run(self.srv.display)

    def set_pixel_callback(self, callback: Callable):
        """Set a callback to be called when pixels are captured

        The callback should accept (pixel_array, width, height) where
        pixel_array is a numpy-compatible memoryview of shape (height, width, 4)
        """
        global g_pixel_callback
        g_pixel_callback = callback

    def cleanup(self) -> None:
        """Clean up compositor resources"""
        if self.srv.display:
            wl_display_destroy_clients(self.srv.display)
            if self.srv.scene:
                wlr_scene_node_destroy(&self.srv.scene.tree.node)
            if self.srv.allocator:
                wlr_allocator_destroy(self.srv.allocator)
            if self.srv.renderer:
                wlr_renderer_destroy(self.srv.renderer)
            if self.srv.backend:
                wlr_backend_destroy(self.srv.backend)
            wl_display_destroy(self.srv.display)
            self.srv.display = NULL

    def __dealloc__(self):
        self.cleanup()
