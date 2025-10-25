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
from xpra.codecs.image import ImageWrapper
from xpra.common import MoveResize

from libc.stdlib cimport malloc, free, calloc
from libc.string cimport memset
from libc.stdint cimport uintptr_t, uint64_t, uint32_t, uint8_t
from libc.time cimport timespec

from xpra.buffers.membuf cimport getbuf, MemBuf
from xpra.wayland.pointer import WaylandPointer
from xpra.wayland.keyboard import WaylandKeyboard


cdef extern from "time.h":
    int clock_gettime(int clk_id, timespec *tp)
    cdef int CLOCK_MONOTONIC
    cdef int CLOCK_REALTIME


# Import definitions from .pxd file
from xpra.wayland.wlroots cimport (
    wl_display, wlr_xdg_shell,
    wl_display_create, wl_display_destroy_clients, wl_display_destroy, wl_display_run,
    wl_listener, wl_signal_add, wl_signal,
    wlr_xdg_surface_events,
    wlr_backend, wlr_backend_start, wlr_backend_destroy,
    wlr_seat, wlr_cursor, wlr_output_layout,
    wlr_seat_create, wlr_seat_set_capabilities, wlr_seat_destroy,
    WL_SEAT_CAPABILITY_POINTER, WL_SEAT_CAPABILITY_KEYBOARD, WL_SEAT_CAPABILITY_TOUCH,
    wlr_seat_keyboard_notify_enter,
    wlr_allocator, wlr_allocator_destroy, wlr_allocator_autocreate,
    wlr_compositor, wlr_compositor_create,
    wlr_subcompositor, wlr_subcompositor_create, wlr_subsurface, wlr_surface_for_each_surface,
    wlr_xdg_decoration_manager_v1, wlr_xdg_toplevel_decoration_v1, wlr_xdg_decoration_manager_v1_create,
    wlr_xdg_toplevel_decoration_v1_set_mode, WLR_XDG_TOPLEVEL_DECORATION_V1_MODE_SERVER_SIDE,
    wlr_cursor_create, wlr_cursor_destroy,
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
    wlr_xdg_toplevel_move_event, wlr_xdg_toplevel_resize_event,
    wlr_xdg_toplevel_set_size, wlr_xdg_toplevel_set_activated,
    wlr_xdg_surface_schedule_configure,
    wlr_output_layout_add_auto, wlr_output_layout_create, wlr_output_layout_destroy, wlr_cursor_attach_output_layout,
    wlr_output_commit_state, wlr_output_state_finish,
    wlr_output_state_init, wlr_output_schedule_frame, wlr_output_init_render, wlr_surface_send_frame_done,
    wlr_headless_add_output,
    wlr_data_device_manager_create,
    wl_list, wl_list_remove,
    WLR_ERROR, WLR_INFO, WLR_DEBUG,
    DRM_FORMAT_ABGR8888, WLR_OUTPUT_ADAPTIVE_SYNC_ENABLED,
    WLR_XDG_SURFACE_ROLE_NONE,
    WLR_XDG_SURFACE_ROLE_POPUP,
    WLR_XDG_SURFACE_ROLE_TOPLEVEL,
    WL_OUTPUT_TRANSFORM_NORMAL, WL_OUTPUT_TRANSFORM_90, WL_OUTPUT_TRANSFORM_180, WL_OUTPUT_TRANSFORM_270,
    WL_OUTPUT_TRANSFORM_FLIPPED, WL_OUTPUT_TRANSFORM_FLIPPED_90, WL_OUTPUT_TRANSFORM_FLIPPED_180, WL_OUTPUT_TRANSFORM_FLIPPED_270,
    WL_OUTPUT_SUBPIXEL_UNKNOWN, WL_OUTPUT_SUBPIXEL_NONE,
    WL_OUTPUT_SUBPIXEL_HORIZONTAL_RGB, WL_OUTPUT_SUBPIXEL_HORIZONTAL_BGR,
    WL_OUTPUT_SUBPIXEL_VERTICAL_RGB, WL_OUTPUT_SUBPIXEL_VERTICAL_BGR,
    DRM_FORMAT_BGRX5551, DRM_FORMAT_ARGB1555, DRM_FORMAT_ABGR1555, DRM_FORMAT_RGBA5551, DRM_FORMAT_BGRA5551,
    DRM_FORMAT_RGB565, DRM_FORMAT_BGR565, DRM_FORMAT_RGB888, DRM_FORMAT_BGR888,
    DRM_FORMAT_XRGB8888, DRM_FORMAT_XBGR8888, DRM_FORMAT_RGBX8888, DRM_FORMAT_BGRX8888,
    DRM_FORMAT_ARGB8888, DRM_FORMAT_ABGR8888, DRM_FORMAT_RGBA8888, DRM_FORMAT_BGRA8888,
    DRM_FORMAT_XRGB2101010, DRM_FORMAT_XBGR2101010, DRM_FORMAT_RGBX1010102,
    DRM_FORMAT_BGRX1010102, DRM_FORMAT_ARGB2101010, DRM_FORMAT_ABGR2101010,
    DRM_FORMAT_RGBA1010102, DRM_FORMAT_BGRA1010102, DRM_FORMAT_XRGB16161616,
    DRM_FORMAT_XBGR16161616, DRM_FORMAT_ARGB16161616, DRM_FORMAT_ABGR16161616,
    WLR_EDGE_TOP, WLR_EDGE_BOTTOM, WLR_EDGE_LEFT, WLR_EDGE_RIGHT
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
    wl_listener new_toplevel_decoration

    wlr_cursor *cursor
    wlr_output_layout *output_layout
    char *seat_name
    wl_listener new_output
    wl_listener new_xdg_surface

cdef struct output:
    wl_list link
    server *srv
    wlr_output *wlr_output
    wlr_scene_output *scene_output

    wl_listener frame
    wl_listener destroy

cdef struct xpra_surface:
    server *srv
    wlr_xdg_surface *wlr_xdg_surface
    wlr_scene_tree *scene_tree

    wl_listener map
    wl_listener unmap
    wl_listener destroy
    wl_listener commit
    wl_listener new_subsurface
    wl_listener request_move
    wl_listener request_resize
    wl_listener request_maximize
    wl_listener request_fullscreen
    wl_listener request_minimize
    wl_listener set_title
    wl_listener set_app_id

    int width
    int height
    unsigned long wid


cdef unsigned long wid = 0


# Helper macros as inline functions with compile-time offset calculation
cdef inline output* output_from_frame(wl_listener *listener) noexcept nogil:
    cdef size_t offset = <size_t>(<char*>&(<output*>0).frame - <char*>0)
    return <output*>(<char*>listener - offset)

cdef inline output* output_from_destroy(wl_listener *listener) noexcept nogil:
    cdef size_t offset = <size_t>(<char*>&(<output*>0).destroy - <char*>0)
    return <output*>(<char*>listener - offset)

cdef inline server* server_from_new_output(wl_listener *listener) noexcept nogil:
    cdef size_t offset = <size_t>(<char*>&(<server*>0).new_output - <char*>0)
    return <server*>(<char*>listener - offset)

cdef inline server* server_from_new_toplevel_decoration(wl_listener *listener) noexcept nogil:
    cdef size_t offset = <size_t>(<char*>&(<server*>0).new_toplevel_decoration - <char*>0)
    return <server*>(<char*>listener - offset)

cdef inline server* server_from_new_xdg_surface(wl_listener *listener) noexcept nogil:
    cdef size_t offset = <size_t>(<char*>&(<server*>0).new_xdg_surface - <char*>0)
    return <server*>(<char*>listener - offset)

cdef inline xpra_surface* xpra_surface_from_map(wl_listener *listener) noexcept nogil:
    cdef size_t offset = <size_t>(<char*>&(<xpra_surface*>0).map - <char*>0)
    return <xpra_surface*>(<char*>listener - offset)

cdef inline xpra_surface* xpra_surface_from_unmap(wl_listener *listener) noexcept nogil:
    cdef size_t offset = <size_t>(<char*>&(<xpra_surface*>0).unmap - <char*>0)
    return <xpra_surface*>(<char*>listener - offset)

cdef inline xpra_surface* xpra_surface_from_destroy(wl_listener *listener) noexcept nogil:
    cdef size_t offset = <size_t>(<char*>&(<xpra_surface*>0).destroy - <char*>0)
    return <xpra_surface*>(<char*>listener - offset)

cdef inline xpra_surface* xpra_surface_from_commit(wl_listener *listener) noexcept nogil:
    cdef size_t offset = <size_t>(<char*>&(<xpra_surface*>0).commit - <char*>0)
    return <xpra_surface*>(<char*>listener - offset)

cdef inline xpra_surface* xpra_surface_from_new_subsurface(wl_listener *listener) noexcept nogil:
    cdef size_t offset = <size_t>(<char*>&(<xpra_surface*>0).new_subsurface - <char*>0)
    return <xpra_surface*>(<char*>listener - offset)

cdef inline xpra_surface* xpra_surface_from_request_move(wl_listener *listener) noexcept nogil:
    cdef size_t offset = <size_t>(<char*>&(<xpra_surface*>0).request_move - <char*>0)
    return <xpra_surface*>(<char*>listener - offset)

cdef inline xpra_surface* xpra_surface_from_request_resize(wl_listener *listener) noexcept nogil:
    cdef size_t offset = <size_t>(<char*>&(<xpra_surface*>0).request_resize - <char*>0)
    return <xpra_surface*>(<char*>listener - offset)

cdef inline xpra_surface* xpra_surface_from_request_maximize(wl_listener *listener) noexcept nogil:
    cdef size_t offset = <size_t>(<char*>&(<xpra_surface*>0).request_maximize - <char*>0)
    return <xpra_surface*>(<char*>listener - offset)

cdef inline xpra_surface* xpra_surface_from_request_fullscreen(wl_listener *listener) noexcept nogil:
    cdef size_t offset = <size_t>(<char*>&(<xpra_surface*>0).request_fullscreen - <char*>0)
    return <xpra_surface*>(<char*>listener - offset)

cdef inline xpra_surface* xpra_surface_from_request_minimize(wl_listener *listener) noexcept nogil:
    cdef size_t offset = <size_t>(<char*>&(<xpra_surface*>0).request_minimize - <char*>0)
    return <xpra_surface*>(<char*>listener - offset)

cdef inline xpra_surface* xpra_surface_from_set_title(wl_listener *listener) noexcept nogil:
    cdef size_t offset = <size_t>(<char*>&(<xpra_surface*>0).set_title - <char*>0)
    return <xpra_surface*>(<char*>listener - offset)

cdef inline xpra_surface* xpra_surface_from_set_app_id(wl_listener *listener) noexcept nogil:
    cdef size_t offset = <size_t>(<char*>&(<xpra_surface*>0).set_app_id - <char*>0)
    return <xpra_surface*>(<char*>listener - offset)


log = Logger("wayland")
cdef bint debug = log.is_debug_enabled()


# Callback implementations
cdef void capture_surface_pixels(xpra_surface *surface) noexcept:
    cdef wlr_surface *wlr_surface = surface.wlr_xdg_surface.surface
    cdef wlr_client_buffer *client_buffer = wlr_surface.buffer
    if not client_buffer:
        return
    cdef wlr_texture *texture = client_buffer.texture
    if not texture:
        return

    cdef uint32_t width = texture.width
    cdef uint32_t height = texture.height
    cdef uint32_t stride = width * 4
    cdef uint32_t texture_size = stride * height
    cdef MemBuf texture_buffer = getbuf(texture_size, 0)
    log("Allocated pixel buffer: %dx%d (%d bytes)", width, height, texture_size)

    cdef wlr_texture_read_pixels_options opts
    opts.data = <void*> texture_buffer.get_mem()
    opts.format = DRM_FORMAT_ABGR8888
    opts.stride = stride
    opts.dst_x = 0
    opts.dst_y = 0
    # we can't modify src_box because it is declared as const,
    # but since we also cannot initialize the struct with the value we need,
    # let's patch it up by hand afterwards - yes this is safe
    cdef wlr_box src_box
    memset(<void *> &opts.src_box, 0, sizeof(wlr_box))
    cdef int *iptr
    iptr = <int*> &opts.src_box.x
    iptr[0] = surface.wlr_xdg_surface.geometry.x
    iptr = <int*> &opts.src_box.y
    iptr[0] = surface.wlr_xdg_surface.geometry.y
    iptr = <int*> &opts.src_box.width
    iptr[0] = width
    iptr = <int*> &opts.src_box.height
    iptr[0] = height

    cdef bint success
    with nogil:
        success = wlr_texture_read_pixels(texture, &opts)
    if not success:
        log.error("Error: failed to read texture pixels")
        return

    pixels = memoryview(texture_buffer)
    image = ImageWrapper(0, 0, width, height, pixels, "BGRA", 32, stride)
    emit("surface-image", surface.wid, image)


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
    # out.link is for a list we don't manage:
    # wl_list_remove(&out.link)
    free(out)


cdef void new_output(wl_listener *listener, void *data) noexcept nogil:
    cdef server *srv = server_from_new_output(listener)
    cdef wlr_output *wlr_out = <wlr_output*>data

    wlr_output_init_render(wlr_out, srv.allocator, srv.renderer)

    cdef output *out = <output*>calloc(1, sizeof(output))
    out.srv = srv
    out.wlr_output = wlr_out

    out.frame.notify = output_frame
    wl_signal_add(&wlr_out.events.frame, &out.frame)

    out.destroy.notify = output_destroy_handler
    wl_signal_add(&wlr_out.events.destroy, &out.destroy)

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

cdef object get_output_info(wlr_output *output):
    info = {
        "name": output.name.decode(),
    }
    add(info, "description", output.description)
    add(info, "make", output.make)
    add(info, "model", output.model)
    add(info, "serial", output.serial)
    info.update({
        "physical-width": output.phys_width,
        "physical-height": output.phys_height,
        "width": output.width,
        "height": output.height,
        "enabled": bool(output.enabled),
        # float:
        #"scale": output.scale,
    })
    if output.refresh:
        info["vertical-refresh"] = round(output.refresh / 1000)
        info["refresh"] = output.refresh        # MHz
    subpixel = {
        WL_OUTPUT_SUBPIXEL_UNKNOWN: "",
        WL_OUTPUT_SUBPIXEL_NONE: "none",
        WL_OUTPUT_SUBPIXEL_HORIZONTAL_RGB: "RGB",
        WL_OUTPUT_SUBPIXEL_HORIZONTAL_BGR: "BGR",
        WL_OUTPUT_SUBPIXEL_VERTICAL_RGB: "VRGB",
        WL_OUTPUT_SUBPIXEL_VERTICAL_BGR: "VBGR",
    }.get(output.subpixel)
    if subpixel:
        info["subpixel"] = subpixel
    transform = {
        WL_OUTPUT_TRANSFORM_NORMAL: "",
        WL_OUTPUT_TRANSFORM_90: "90",
        WL_OUTPUT_TRANSFORM_180: "180",
        WL_OUTPUT_TRANSFORM_270: "270",
        WL_OUTPUT_TRANSFORM_FLIPPED: "flipped",
        WL_OUTPUT_TRANSFORM_FLIPPED_90: "flipped-90",
        WL_OUTPUT_TRANSFORM_FLIPPED_180: "flipped-180",
        WL_OUTPUT_TRANSFORM_FLIPPED_270: "flipped-270",
    }.get(output.transform)
    if transform:
        info["transform"] = transform
    if output.adaptive_sync_supported:
        info["adaptive-sync"] = output.adaptive_sync_status == WLR_OUTPUT_ADAPTIVE_SYNC_ENABLED
    if output.needs_frame:
        info["needs-frame"] = True
    if output.frame_pending:
        info["frame-pending"] = True
    if output.non_desktop:
        info["non-desktop"] = True
    info["commit-sequence"] = output.commit_seq
    info["render-format"] = get_render_format(output.render_format)
    # wl_list modes
    # wlr_output_mode *current_mode
    return info

cdef str get_render_format(uint32_t fmt):
    return {
        DRM_FORMAT_BGRX5551: "BGRX5551",
        DRM_FORMAT_ARGB1555: "ARGB1555",
        DRM_FORMAT_ABGR1555: "ABGR1555",
        DRM_FORMAT_RGBA5551: "RGBA5551",
        DRM_FORMAT_BGRA5551: "BGRA5551",
        DRM_FORMAT_RGB565: "RGB565",
        DRM_FORMAT_BGR565: "BGR565",
        DRM_FORMAT_RGB888: "RGB888",
        DRM_FORMAT_BGR888: "BGR888",
        DRM_FORMAT_XRGB8888: "XRGB8888",
        DRM_FORMAT_XBGR8888: "XBGR8888",
        DRM_FORMAT_RGBX8888: "RGBX8888",
        DRM_FORMAT_BGRX8888: "BGRX8888",
        DRM_FORMAT_ARGB8888: "ARGB8888",
        DRM_FORMAT_ABGR8888: "ABGR8888",
        DRM_FORMAT_RGBA8888: "RGBA8888",
        DRM_FORMAT_BGRA8888: "BGRA8888",
        DRM_FORMAT_XRGB2101010: "XRGB2101010",
        DRM_FORMAT_XBGR2101010: "XBGR2101010",
        DRM_FORMAT_RGBX1010102: "RGBX1010102",
        DRM_FORMAT_BGRX1010102: "BGRX1010102",
        DRM_FORMAT_ARGB2101010: "ARGB2101010",
        DRM_FORMAT_ABGR2101010: "ABGR2101010",
        DRM_FORMAT_RGBA1010102: "RGBA1010102",
        DRM_FORMAT_BGRA1010102: "BGRA1010102",
        DRM_FORMAT_XRGB16161616: "XRGB16161616",
        DRM_FORMAT_XBGR16161616: "XBGR16161616",
        DRM_FORMAT_ARGB16161616: "ARGB16161616",
        DRM_FORMAT_ABGR16161616: "ABGR16161616",
    }.get(fmt, "")


cdef void new_toplevel_decoration(wl_listener *listener, void *data) noexcept nogil:
    cdef server *srv = server_from_new_toplevel_decoration(listener)
    cdef wlr_xdg_toplevel_decoration_v1 *decoration = <wlr_xdg_toplevel_decoration_v1*>data
    cdef wlr_xdg_toplevel *toplevel = decoration.toplevel
    cdef bint ssd = decoration.requested_mode == WLR_XDG_TOPLEVEL_DECORATION_V1_MODE_SERVER_SIDE
    wlr_xdg_toplevel_decoration_v1_set_mode(decoration, WLR_XDG_TOPLEVEL_DECORATION_V1_MODE_SERVER_SIDE)
    with gil:
        emit("ssd", <uintptr_t> toplevel, bool(ssd))

cdef void xdg_surface_map(wl_listener *listener, void *data) noexcept nogil:
    cdef xpra_surface *surface = xpra_surface_from_map(listener)
    cdef wlr_xdg_toplevel *toplevel = surface.wlr_xdg_surface.toplevel
    cdef wlr_box *geometry = &surface.wlr_xdg_surface.geometry
    register_toplevel_handlers(surface)
    with gil:
        title = toplevel.title.decode("utf8") if (toplevel and toplevel.title) else ""
        app_id = toplevel.app_id.decode("utf8") if (toplevel and toplevel.app_id) else ""
        size = (geometry.width, geometry.height)
        log("XDG surface MAPPED: %r, size=%s", title, size)
        emit("map", surface.wid, title, app_id, size)


cdef void xdg_surface_unmap(wl_listener *listener, void *data) noexcept nogil:
    # cdef wlr_xdg_surface wx_surface = <wlr_xdg_surface*> data
    cdef xpra_surface *surface = xpra_surface_from_unmap(listener)
    unregister_toplevel_handlers(surface)
    with gil:
        log("XDG surface UNMAPPED")
        emit("unmap", surface.wid)


cdef void xdg_surface_destroy_handler(wl_listener *listener, void *data) noexcept:
    cdef xpra_surface *surface = xpra_surface_from_destroy(listener)
    toplevel = surface.wlr_xdg_surface.toplevel != NULL
    log("XDG surface DESTROYED, toplevel=%s", bool(toplevel))

    wl_list_remove(&surface.map.link)
    wl_list_remove(&surface.unmap.link)
    wl_list_remove(&surface.destroy.link)
    wl_list_remove(&surface.commit.link)

    unregister_toplevel_handlers(surface)

    cdef unsigned long wid = surface.wid
    free(surface)
    if debug:
        log("xdg surface freed")
        emit("destroy", wid)


cdef void xdg_surface_commit(wl_listener *listener, void *data) noexcept nogil:
    if debug:
        with gil:
            log("xdg_surface_commit(%#x, %#x)", <uintptr_t> listener, <uintptr_t> data)
    cdef xpra_surface *surface = xpra_surface_from_commit(listener)
    cdef wlr_xdg_surface *xdg_surface = surface.wlr_xdg_surface

    if xdg_surface.role == WLR_XDG_SURFACE_ROLE_TOPLEVEL and xdg_surface.toplevel != NULL:
        register_toplevel_handlers(surface)
        # Fallback: If configure wasn't sent yet (toplevel wasn't ready), send it now
        if xdg_surface.initialized and not xdg_surface.configured:
            with gil:
                log("Surface initialized, sending first configure")
            wlr_xdg_toplevel_set_size(xdg_surface.toplevel, 0, 0)
            wlr_xdg_surface_schedule_configure(xdg_surface)

    cdef wlr_box *geometry = &xdg_surface.geometry
    cdef wlr_surface *wlr_surface = xdg_surface.surface
    with gil:
        size = (geometry.width, geometry.height)
        rects = []
        if wlr_surface.mapped:
            rects = get_damage_areas(&wlr_surface.buffer_damage)
            capture_surface_pixels(surface)

        subsurfaces = collect_surfaces(wlr_surface)
        emit("commit", surface.wid, bool(wlr_surface.mapped), size, rects, subsurfaces)


cdef object get_damage_areas(pixman_region32_t *damage):
    cdef int n_rects = 0
    cdef pixman_box32_t *rects = pixman_region32_rectangles(damage, &n_rects)

    rectangles = []
    cdef int i
    for i in range(n_rects):
        x = rects[i].x1
        y = rects[i].y1
        w = rects[i].x2 - rects[i].x1
        h = rects[i].y2 - rects[i].y1
        rectangles.append((x, y, w, h))
    return rectangles


cdef void collect_surface_callback(wlr_surface *surface, int sx, int sy, void *user_data) noexcept:
    """
    Callback that gets called for each surface in the tree.
    user_data is expected to be a Python list.
    """
    # Cast user_data back to a Python list
    surfaces = <object> user_data
    # Store the surface pointer as an integer (or you could wrap it)
    surfaces.append({
        "surface": <uintptr_t> surface,
        "x": sx,
        "y": sy
    })


cdef list collect_surfaces(wlr_surface *surface):
    """
    Collect all surfaces in the subsurface tree.

    Args:
        root_surface_ptr: Pointer to the root wlr_surface (as integer)

    Returns:
        List of dicts containing surface pointers and their positions
        [{"surface": ptr, "x": int, "y": int}, ...]
    """
    surfaces = []
    wlr_surface_for_each_surface(surface, collect_surface_callback, <void*>surfaces)
    return surfaces


cdef void handle_new_subsurface(wl_listener *listener, void *data) noexcept nogil:
    cdef xpra_surface *parent_surface = xpra_surface_from_new_subsurface(listener)
    cdef wlr_subsurface *subsurface = <wlr_subsurface*> data

    with gil:
        log("New SUBSURFACE created, parent wid=%#x", parent_surface.wid)
        log(" subsurface wlr_surface=%#x, parent wlr_surface=%#x",
            <uintptr_t>subsurface.surface, <uintptr_t>subsurface.parent)

        # Get dimensions if available
        width = subsurface.surface.current.width if subsurface.surface else 0
        height = subsurface.surface.current.height if subsurface.surface else 0

        global wid
        wid += 1
        log("allocated wid=%#x", wid)
        # TODO: allocate xpra_surface and populate it
        emit("new-subsurface", parent_surface.wid, wid, <uintptr_t> subsurface.surface, width, height)


cdef void xdg_toplevel_request_move(wl_listener *listener, void *data) noexcept nogil:
    cdef xpra_surface *surface = xpra_surface_from_request_move(listener)
    cdef wlr_xdg_toplevel_move_event *event = <wlr_xdg_toplevel_move_event*> data
    with gil:
        log("Surface REQUEST MOVE")
        emit("move", surface.wid, event.serial)


EDGES: Dict[int, str] = {
    WLR_EDGE_TOP: "TOP",
    WLR_EDGE_BOTTOM: "BOTTOM",
    WLR_EDGE_LEFT: "LEFT",
    WLR_EDGE_RIGHT: "RIGHT",
}

EDGES_MAP: dict[int, MoveResize] = {
    WLR_EDGE_TOP: MoveResize.SIZE_TOP,
    WLR_EDGE_TOP | WLR_EDGE_LEFT: MoveResize.SIZE_TOPLEFT,
    WLR_EDGE_TOP | WLR_EDGE_RIGHT: MoveResize.SIZE_TOPRIGHT,
    WLR_EDGE_BOTTOM: MoveResize.SIZE_BOTTOM,
    WLR_EDGE_BOTTOM | WLR_EDGE_LEFT: MoveResize.SIZE_BOTTOMLEFT,
    WLR_EDGE_BOTTOM | WLR_EDGE_RIGHT: MoveResize.SIZE_BOTTOMRIGHT,
    WLR_EDGE_LEFT: MoveResize.SIZE_LEFT,
    WLR_EDGE_RIGHT: MoveResize.SIZE_RIGHT,
}


cdef void xdg_toplevel_request_resize(wl_listener *listener, void *data) noexcept nogil:
    cdef xpra_surface *surface = xpra_surface_from_request_resize(listener)
    cdef wlr_xdg_toplevel_resize_event *event = <wlr_xdg_toplevel_resize_event*>data
    with gil:
        if debug:
            edges = tuple(edge_name for edge_val, edge_name in EDGES.items() if event.edges & edge_val)
            log("Surface REQUEST RESIZE edges: %d - %r", event.edges, edges)
        enumval = EDGES_MAP.get(event.edges, MoveResize.CANCEL)
        emit("resize", surface.wid, event.serial, enumval)


cdef void xdg_toplevel_request_maximize(wl_listener *listener, void *data) noexcept nogil:
    cdef xpra_surface *surface = xpra_surface_from_request_maximize(listener)
    if debug:
        with gil:
            log("Surface REQUEST MAXIMIZE")
    with gil:
        emit("maximize", surface.wid)


cdef void xdg_toplevel_request_fullscreen(wl_listener *listener, void *data) noexcept nogil:
    cdef xpra_surface *surface = xpra_surface_from_request_fullscreen(listener)
    if debug:
        with gil:
            log("Surface REQUEST FULLSCREEN")
    with gil:
        emit("fullscreen", surface.wid)


cdef void xdg_toplevel_request_minimize(wl_listener *listener, void *data) noexcept nogil:
    cdef xpra_surface *surface = xpra_surface_from_request_minimize(listener)
    if debug:
        with gil:
            log("Surface REQUEST MINIMIZE")
    with gil:
        emit("minimize", surface.wid)


cdef void xdg_toplevel_set_title_handler(wl_listener *listener, void *data) noexcept nogil:
    cdef xpra_surface *surface = xpra_surface_from_set_title(listener)
    if surface.wlr_xdg_surface.toplevel.title:
        with gil:
            title = surface.wlr_xdg_surface.toplevel.title.decode("utf8")
            log("Surface SET TITLE: %s", title)
            emit("title", title)


cdef void xdg_toplevel_set_app_id_handler(wl_listener *listener, void *data) noexcept nogil:
    cdef xpra_surface *surface = xpra_surface_from_set_app_id(listener)
    if surface.wlr_xdg_surface.toplevel.app_id:
        with gil:
            log.info("Surface SET APP_ID: %s", surface.wlr_xdg_surface.toplevel.app_id)


cdef void new_xdg_surface(wl_listener *listener, void *data) noexcept:
    cdef server *srv = server_from_new_xdg_surface(listener)
    cdef wlr_xdg_surface *xdg_surf = <wlr_xdg_surface*>data
    log("New XDG surface CREATED (role: %d, initialized: %d)", xdg_surf.role, xdg_surf.initialized)
    if xdg_surf.role != WLR_XDG_SURFACE_ROLE_NONE and xdg_surf.role != WLR_XDG_SURFACE_ROLE_TOPLEVEL:
        return

    log(" wlr_surface(%#x)=%#x", <uintptr_t> xdg_surf, <uintptr_t> xdg_surf.surface)
    cdef xpra_surface *surface = <xpra_surface*>calloc(1, sizeof(xpra_surface))
    surface.srv = srv
    surface.wlr_xdg_surface = xdg_surf
    surface.width = 0
    surface.height = 0
    global wid
    wid += 1
    surface.wid = wid
    log("allocated wid=%#x", wid)

    surface.scene_tree = wlr_scene_xdg_surface_create(&srv.scene.tree, xdg_surf)

    surface.map.notify = xdg_surface_map
    wl_signal_add(&xdg_surf.surface.events.map, &surface.map)

    surface.unmap.notify = xdg_surface_unmap
    wl_signal_add(&xdg_surf.surface.events.unmap, &surface.unmap)

    surface.destroy.notify = xdg_surface_destroy_handler
    wl_signal_add(&xdg_surf.surface.events.destroy, &surface.destroy)

    surface.commit.notify = xdg_surface_commit
    wl_signal_add(&xdg_surf.surface.events.commit, &surface.commit)

    # Listen for subsurfaces created on this surface
    surface.new_subsurface.notify = handle_new_subsurface
    wl_signal_add(&xdg_surf.surface.events.new_subsurface, &surface.new_subsurface)

    cdef wlr_xdg_toplevel *toplevel = xdg_surf.toplevel
    log("toplevel=%#x", <uintptr_t> toplevel)
    if toplevel:
        register_toplevel_handlers(surface)
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
    emit("new-surface", <uintptr_t> xdg_surf, wid, title, app_id, size)


cdef void register_toplevel_handlers(xpra_surface *surface) noexcept nogil:
    cdef wlr_xdg_surface *xdg_surf = surface.wlr_xdg_surface
    cdef wlr_xdg_toplevel *toplevel = xdg_surf.toplevel
    if toplevel == NULL:
        # no toplevel yet
        return
    if surface.request_move.link.next != NULL:
        # already done
        return

    with gil:
        log("Surface has toplevel, attaching toplevel handlers")

    surface.request_move.notify = xdg_toplevel_request_move
    wl_signal_add(&toplevel.events.request_move, &surface.request_move)

    surface.request_resize.notify = xdg_toplevel_request_resize
    wl_signal_add(&toplevel.events.request_resize, &surface.request_resize)

    surface.request_maximize.notify = xdg_toplevel_request_maximize
    wl_signal_add(&toplevel.events.request_maximize, &surface.request_maximize)

    surface.request_fullscreen.notify = xdg_toplevel_request_fullscreen
    wl_signal_add(&toplevel.events.request_fullscreen, &surface.request_fullscreen)

    surface.request_minimize.notify = xdg_toplevel_request_minimize
    wl_signal_add(&toplevel.events.request_minimize, &surface.request_minimize)

    surface.set_title.notify = xdg_toplevel_set_title_handler
    wl_signal_add(&toplevel.events.set_title, &surface.set_title)

    surface.set_app_id.notify = xdg_toplevel_set_app_id_handler
    wl_signal_add(&toplevel.events.set_app_id, &surface.set_app_id)


cdef void unregister_toplevel_handlers(xpra_surface *surface) noexcept nogil:
    cdef wlr_xdg_surface *xdg_surf = surface.wlr_xdg_surface
    cdef wlr_xdg_toplevel *toplevel = xdg_surf.toplevel

    if surface.new_subsurface.link.next != NULL:
        wl_list_remove(&surface.new_subsurface.link)
    if surface.request_move.link.next != NULL:
        wl_list_remove(&surface.request_move.link)
    if surface.request_resize.link.next != NULL:
        wl_list_remove(&surface.request_resize.link)
    if surface.request_maximize.link.next != NULL:
        wl_list_remove(&surface.request_maximize.link)
    if surface.request_fullscreen.link.next != NULL:
        wl_list_remove(&surface.request_fullscreen.link)
    if surface.request_minimize.link.next != NULL:
        wl_list_remove(&surface.request_minimize.link)
    if surface.set_title.link.next != NULL:
        wl_list_remove(&surface.set_title.link)
    if surface.set_app_id.link.next != NULL:
        wl_list_remove(&surface.set_app_id.link)


def frame_done(surf: int) -> None:
    cdef timespec now
    clock_gettime(CLOCK_MONOTONIC, &now)
    cdef wlr_xdg_surface *surface = <wlr_xdg_surface*> (<uintptr_t> surf)
    wlr_surface_send_frame_done(surface.surface, &now)


def flush_clients(disp: int) -> None:
    cdef wl_display *display = <wl_display*> (<uintptr_t> disp)
    wl_display_flush_clients(display)


# Python interface
cdef class WaylandCompositor:
    cdef server srv
    cdef str socket_name
    cdef wl_event_loop *event_loop

    def __cinit__(self):
        memset(&self.srv, 0, sizeof(server))
        self.socket_name = ""

    def initialize(self) -> None:
        log("starting headless wayland compositor")

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
        self.srv.subcompositor = wlr_subcompositor_create(self.srv.display)
        wlr_data_device_manager_create(self.srv.display)

        self.srv.xdg_shell = wlr_xdg_shell_create(self.srv.display, 3)
        self.srv.new_xdg_surface.notify = new_xdg_surface
        wl_signal_add(&self.srv.xdg_shell.events.new_surface, &self.srv.new_xdg_surface)

        self.srv.scene = wlr_scene_create()

        # Create output layout for multi-monitor support
        self.srv.output_layout = wlr_output_layout_create(self.srv.display)
        if not self.srv.output_layout:
            raise RuntimeError("Failed to create output layout")

        self.srv.decoration_manager = wlr_xdg_decoration_manager_v1_create(self.srv.display)
        if not self.srv.decoration_manager:
            log.warn("Warning: unable to create the decoration manager")
        else:
            self.srv.new_toplevel_decoration.notify = new_toplevel_decoration
            wl_signal_add(&self.srv.decoration_manager.events.new_toplevel_decoration, &self.srv.new_toplevel_decoration)

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

        self.srv.new_output.notify = new_output
        wl_signal_add(&self.srv.backend.events.new_output, &self.srv.new_output)

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

    def get_display_ptr(self) -> int:
        return <uintptr_t> self.srv.display

    def process_events(self) -> None:
        wl_event_loop_dispatch(self.event_loop, 0)
        self.flush()

    def flush(self) -> None:
        wl_display_flush_clients(self.srv.display)

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

        if self.srv.new_xdg_surface.link.next != NULL:
            wl_list_remove(&self.srv.new_xdg_surface.link)

        if self.srv.new_output.link.next != NULL:
            wl_list_remove(&self.srv.new_output.link)

        if self.srv.new_toplevel_decoration.link.next != NULL:
            wl_list_remove(&self.srv.new_toplevel_decoration.link)

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

    def resize(self, surf: int, width: int, height: int) -> None:
        cdef wlr_xdg_surface *surface = <wlr_xdg_surface*> (<uintptr_t> surf)
        cdef wlr_xdg_toplevel *toplevel = surface.toplevel
        log("wlr_xdg_toplevel_set_size(%#x, %i, %i)", <uintptr_t> toplevel, width, height)
        wlr_xdg_toplevel_set_size(toplevel, width, height)

    def focus(self, surf: int, focused: bool) -> None:
        cdef wlr_xdg_surface *surface = <wlr_xdg_surface*> (<uintptr_t> surf)
        cdef wlr_xdg_toplevel *toplevel = surface.toplevel
        log("wlr_xdg_toplevel_set_activated(%#x, %s)", <uintptr_t> toplevel, focused)
        wlr_xdg_toplevel_set_activated(toplevel, focused)

