# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# cython: language_level=3

from typing import Dict
from collections.abc import Callable

from xpra.log import Logger
from xpra.util.str_fn import Ellipsizer
from xpra.codecs.image import ImageWrapper
from xpra.constants import MoveResize

from libc.string cimport memset
from libc.stdint cimport uintptr_t, uint32_t, int32_t
from libc.time cimport timespec

from xpra.buffers.membuf cimport getbuf, MemBuf
from xpra.wayland.events cimport ListenerObject, owner_listener, owner_of

cdef extern from "time.h":
    int clock_gettime(int clk_id, timespec *tp)
    cdef int CLOCK_MONOTONIC


# Import definitions from .pxd file
from xpra.wayland.wlroots cimport (
    wl_listener, wl_signal_add, wl_signal, wl_notify_func_t,
    wlr_xdg_surface_events,
    wlr_cursor,
    wlr_subsurface, wlr_surface_for_each_surface,
    wlr_cursor_create, wlr_cursor_destroy,
    wlr_xdg_shell_create,
    wlr_scene_tree,
    wlr_surface, wlr_surface_events, wlr_texture, wlr_client_buffer, wlr_box,
    wlr_xdg_toplevel, wlr_xdg_toplevel_events, wlr_xdg_surface,
    wlr_texture_read_pixels_options, wlr_texture_read_pixels,
    wlr_xdg_toplevel_move_event, wlr_xdg_toplevel_resize_event, wlr_xdg_toplevel_show_window_menu_event,
    wlr_xdg_toplevel_set_size, wlr_xdg_toplevel_set_activated,
    wlr_xdg_surface_schedule_configure,
    wlr_surface_send_frame_done,
    wl_list, wl_list_remove,
    DRM_FORMAT_ABGR8888,
    WLR_XDG_SURFACE_ROLE_NONE,
    WLR_XDG_SURFACE_ROLE_POPUP,
    WLR_XDG_SURFACE_ROLE_TOPLEVEL,
    WLR_EDGE_TOP, WLR_EDGE_BOTTOM, WLR_EDGE_LEFT, WLR_EDGE_RIGHT
)
from xpra.wayland.pixman cimport pixman_region32_t, pixman_box32_t, pixman_region32_rectangles


EDGES: Dict[int, str] = {
    WLR_EDGE_TOP: "TOP",
    WLR_EDGE_BOTTOM: "BOTTOM",
    WLR_EDGE_LEFT: "LEFT",
    WLR_EDGE_RIGHT: "RIGHT",
}

EDGES_MAP: Dict[int, MoveResize] = {
    WLR_EDGE_TOP: MoveResize.SIZE_TOP,
    WLR_EDGE_TOP | WLR_EDGE_LEFT: MoveResize.SIZE_TOPLEFT,
    WLR_EDGE_TOP | WLR_EDGE_RIGHT: MoveResize.SIZE_TOPRIGHT,
    WLR_EDGE_BOTTOM: MoveResize.SIZE_BOTTOM,
    WLR_EDGE_BOTTOM | WLR_EDGE_LEFT: MoveResize.SIZE_BOTTOMLEFT,
    WLR_EDGE_BOTTOM | WLR_EDGE_RIGHT: MoveResize.SIZE_BOTTOMRIGHT,
    WLR_EDGE_LEFT: MoveResize.SIZE_LEFT,
    WLR_EDGE_RIGHT: MoveResize.SIZE_RIGHT,
}


# Listener slot indices for Surface; N_LISTENERS sizes the listeners array.
# Toplevel slots are kept contiguous so unregister_toplevel_handlers can use
# a simple range loop — when adding a new toplevel-only slot, place it in the
# block bounded by L_REQUEST_MOVE..L_SET_PARENT (inclusive).
cdef enum SurfaceListener:
    L_MAP
    L_UNMAP
    L_DESTROY
    L_COMMIT
    L_NEW_SUBSURFACE
    L_REQUEST_MOVE
    L_REQUEST_RESIZE
    L_REQUEST_MAXIMIZE
    L_REQUEST_FULLSCREEN
    L_REQUEST_MINIMIZE
    L_SET_TITLE
    L_SET_APP_ID
    L_SET_PARENT
    L_REQUEST_SHOW_WINDOW_MENU
    N_LISTENERS


log = Logger("wayland")
cdef bint debug = log.is_debug_enabled()


# Registry that keeps Surface objects alive while wlroots holds listener refs.
# Removed in xdg_surface_destroy_handler so __dealloc__ runs deterministically.
surfaces: Dict[int, Surface] = {}

cdef unsigned long wid = 0

cdef inline unsigned long next_wid():
    global wid
    wid += 1
    return wid


cdef class Surface(ListenerObject):

    def __cinit__(self):
        self._callbacks = {}
        self.title = ""
        self.app_id = ""

    def __init__(self):
        super().__init__(N_LISTENERS)
        self.wid = next_wid()

    def __repr__(self):
        return "Surface(%i : %s)" % (self.wid, self.title)

    @property
    def xdg_surface_ptr(self) -> int:
        """Raw wlr_xdg_surface pointer; for callers (e.g. WaylandPointer/Keyboard)
        that still take a plain integer. Returns 0 once the surface has been
        destroyed by wlroots — callers must treat 0 as 'gone'."""
        return <uintptr_t> self.wlr_xdg_surface

    def frame_done(self) -> None:
        """Tell the client we finished rendering this frame.
        No-op once the underlying wlr_xdg_surface has been destroyed."""
        if self.wlr_xdg_surface == NULL:
            return
        cdef timespec now
        clock_gettime(CLOCK_MONOTONIC, &now)
        wlr_surface_send_frame_done(self.wlr_xdg_surface.surface, &now)

    def connect(self, event: str, callback) -> None:
        self._callbacks.setdefault(event, []).append(callback)

    def disconnect(self, event: str, callback) -> None:
        cbs = self._callbacks.get(event)
        if not cbs or callback not in cbs:
            return
        cbs.remove(callback)
        if not cbs:
            self._callbacks.pop(event, None)

    def _emit(self, str event, *args):
        cdef list cbs = self._callbacks.get(event)
        if not cbs:
            return
        if debug:
            log("%s._emit(%s, %s) callbacks=%s", self, event, Ellipsizer(args), cbs)
        for cb in cbs:
            cb(*args)

    cdef void add_main_listeners(self):
        cdef wlr_surface *s = self.wlr_xdg_surface.surface
        self.add_listener(L_COMMIT, &s.events.commit)
        self.add_listener(L_MAP, &s.events.map)
        self.add_listener(L_UNMAP, &s.events.unmap)
        self.add_listener(L_NEW_SUBSURFACE, &s.events.new_subsurface)
        self.add_listener(L_DESTROY, &s.events.destroy)
        # Keep the Surface alive while wlroots holds listener pointers into it.
        surfaces[<uintptr_t> self.wlr_xdg_surface] = self

    # Single C shim for every Surface-level listener. The slot is recovered by
    # pointer arithmetic on the listeners[] array, then dispatched to the matching
    # Surface method. This replaces 12 individual one-line callback wrappers.
    cdef void dispatch(self, wl_listener *listener, void *data) noexcept:
        cdef int slot = self.slot_of(listener)
        cdef wlr_xdg_toplevel_move_event *move_event
        cdef wlr_xdg_toplevel_resize_event *resize_event
        cdef wlr_xdg_toplevel_show_window_menu_event *show_menu_event
        if slot == L_MAP:
            self.map()
        elif slot == L_UNMAP:
            self.unmap()
        elif slot == L_DESTROY:
            self.destroy()
        elif slot == L_COMMIT:
            self.commit()
        elif slot == L_NEW_SUBSURFACE:
            self.new_subsurface(<wlr_subsurface*>data)
        elif slot == L_REQUEST_MOVE:
            move_event = <wlr_xdg_toplevel_move_event*>data
            self.request_move(move_event.serial)
        elif slot == L_REQUEST_RESIZE:
            resize_event = <wlr_xdg_toplevel_resize_event*>data
            self.request_resize(resize_event.edges, resize_event.serial)
        elif slot == L_REQUEST_MAXIMIZE:
            self.request_maximize()
        elif slot == L_REQUEST_FULLSCREEN:
            self.request_fullscreen()
        elif slot == L_REQUEST_MINIMIZE:
            self.request_minimize()
        elif slot == L_SET_TITLE:
            self.set_title()
        elif slot == L_SET_APP_ID:
            self.set_app_id()
        elif slot == L_SET_PARENT:
            self.set_parent()
        elif slot == L_REQUEST_SHOW_WINDOW_MENU:
            show_menu_event = <wlr_xdg_toplevel_show_window_menu_event*>data
            self.request_show_window_menu(show_menu_event.serial,
                                          show_menu_event.x, show_menu_event.y)
        else:
            log.error("Error: unknown surface listener slot %i", slot)

    cdef void register_toplevel_handlers(self) noexcept:
        cdef wlr_xdg_toplevel *t = self.wlr_xdg_surface.toplevel
        log("register_toplevel_handlers() toplevel=%#x", <uintptr_t> t)
        if t == NULL:
            # no toplevel yet
            return
        if self.listeners[int(L_REQUEST_MOVE)].listener.link.next != NULL:
            # already done
            return

        log("Surface has toplevel, attaching toplevel handlers")
        self.add_listener(L_REQUEST_MAXIMIZE, &t.events.request_maximize)
        self.add_listener(L_REQUEST_FULLSCREEN, &t.events.request_fullscreen)
        self.add_listener(L_REQUEST_MINIMIZE, &t.events.request_minimize)
        self.add_listener(L_REQUEST_MOVE, &t.events.request_move)
        self.add_listener(L_REQUEST_RESIZE, &t.events.request_resize)
        self.add_listener(L_SET_TITLE, &t.events.set_title)
        self.add_listener(L_SET_APP_ID, &t.events.set_app_id)
        self.add_listener(L_SET_PARENT, &t.events.set_parent)
        self.add_listener(L_REQUEST_SHOW_WINDOW_MENU, &t.events.request_show_window_menu)

    cdef void map(self) noexcept:
        toplevel = self.wlr_xdg_surface.toplevel
        geometry = &self.wlr_xdg_surface.geometry
        self.register_toplevel_handlers()
        title = toplevel.title.decode("utf8") if (toplevel and toplevel.title) else ""
        app_id = toplevel.app_id.decode("utf8") if (toplevel and toplevel.app_id) else ""
        size = (geometry.width, geometry.height)
        if debug:
            log("XDG surface MAPPED: %r, size=%s", title, size)
        self._emit("map", self.wid, title, app_id, size)

    cdef void unmap(self) noexcept:
        self.unregister_toplevel_handlers()
        log("XDG surface UNMAPPED")
        self._emit("unmap", self.wid)

    cdef void destroy(self) noexcept:
        if self.wlr_xdg_surface == NULL:
            # idempotent: destroy already ran (e.g. registry pop triggered it).
            return
        cdef uintptr_t key = <uintptr_t> self.wlr_xdg_surface
        log("XDG surface DESTROYED, toplevel=%s", bool(self.wlr_xdg_surface.toplevel != NULL))
        # Detach all listeners while wlr_surface event lists are still valid.
        # We MUST do this here rather than rely on __dealloc__: surface_dispatch
        # holds a strong reference for the duration of the dispatch call, so the
        # dict-pop below would not drop refcount to zero until after this event
        # handler returns — by then wlroots' event lists are gone.
        self._detach_all()
        self._emit("destroy", self.wid)
        if debug:
            log("xdg surface dropped")
        surfaces.pop(key, None)
        # wlroots will free the wlr_xdg_surface struct as soon as we return from
        # this destroy event. Mark our pointer dead so any later Python-side
        # method calls (frame_done, resize, focus, ...) become safe no-ops
        # instead of UAFs. Other strong refs to this Surface (e.g. xpra Window
        # _gproperties["surface"], pending packets) outlive wlroots' free.
        self.wlr_xdg_surface = NULL

    cdef void request_move(self, uint32_t serial) noexcept:
        log("Surface REQUEST MOVE")
        self._emit("move", self.wid, serial)

    cdef void request_resize(self, uint32_t edges, uint32_t serial) noexcept:
        if debug:
            edge_names = tuple(edge_name for edge_val, edge_name in EDGES.items() if edges & edge_val)
            log("Surface REQUEST RESIZE edges: %d - %r", edges, edge_names)
        enumval = EDGES_MAP.get(edges, MoveResize.CANCEL)
        self._emit("resize", self.wid, serial, enumval)

    cdef void request_maximize(self) noexcept:
        if debug:
            log("Surface REQUEST MAXIMIZE")
        self._emit("maximize", self.wid)

    cdef void request_fullscreen(self) noexcept:
        if debug:
            log("Surface REQUEST FULLSCREEN")
        self._emit("fullscreen", self.wid)

    cdef void request_minimize(self) noexcept:
        if debug:
            log("Surface REQUEST MINIMIZE")
        self._emit("minimize", self.wid)

    cdef void set_title(self) noexcept:
        if self.wlr_xdg_surface.toplevel.title:
            self.title = self.wlr_xdg_surface.toplevel.title.decode("utf8")
            log("Surface %i SET TITLE: %s", self.wid, self.title)
            self._emit("title", self.wid, self.title)

    cdef void set_app_id(self) noexcept:
        if self.wlr_xdg_surface.toplevel.app_id:
            self.app_id = self.wlr_xdg_surface.toplevel.app_id.decode("utf8")
            log.info("Surface %i SET APP_ID: %s", self.wid, self.app_id)

    cdef void request_show_window_menu(self, uint32_t serial, int32_t x, int32_t y) noexcept:
        # Client asked the compositor to pop up a window-management context
        # menu (move/resize/close). xpra is a remote display: we don't render
        # the menu ourselves — relay to consumers so the server can decide.
        # No consumer today; left as an emit-only no-op.
        if debug:
            log("Surface %i REQUEST SHOW WINDOW MENU at (%i, %i) serial=%#x",
                self.wid, x, y, serial)
        self._emit("show-window-menu", self.wid, serial, x, y)

    cdef void set_parent(self) noexcept:
        # Fired after wlroots has updated wlr_xdg_toplevel.parent. NULL means
        # "no parent" (cleared). The parent itself is a wlr_xdg_toplevel*; we
        # map it to our Surface via its .base wlr_xdg_surface, which is what
        # we keyed the `surfaces` registry with.
        if self.wlr_xdg_surface == NULL or self.wlr_xdg_surface.toplevel == NULL:
            return
        cdef wlr_xdg_toplevel *parent = self.wlr_xdg_surface.toplevel.parent
        cdef unsigned long parent_wid = 0
        cdef Surface parent_surface
        if parent != NULL and parent.base != NULL:
            parent_surface = surfaces.get(<uintptr_t> parent.base)
            if parent_surface is not None:
                parent_wid = parent_surface.wid
        log("Surface %i SET PARENT: parent_wid=%i", self.wid, parent_wid)
        self._emit("set-parent", self.wid, parent_wid)

    cdef void commit(self) noexcept:
        if debug:
            log("xdg_surface_commit")
        xdg_surface = self.wlr_xdg_surface

        if xdg_surface.role == WLR_XDG_SURFACE_ROLE_TOPLEVEL and xdg_surface.toplevel != NULL:
            self.register_toplevel_handlers()
            # Fallback: If configure wasn't sent yet (toplevel wasn't ready), send it now
            if xdg_surface.initialized and not xdg_surface.configured:
                log("Surface initialized, sending first configure")
                wlr_xdg_toplevel_set_size(xdg_surface.toplevel, 0, 0)
                wlr_xdg_surface_schedule_configure(xdg_surface)

        size = (xdg_surface.geometry.width, xdg_surface.geometry.height)
        wlr_surf = xdg_surface.surface
        rects = []
        if wlr_surf.mapped:
            rects = get_damage_areas(&wlr_surf.buffer_damage)
            self.capture_surface_pixels()

        subsurfaces = collect_surfaces(wlr_surf)
        self._emit("commit", self.wid, bool(wlr_surf.mapped), size, rects, subsurfaces)

    cdef void capture_surface_pixels(self) noexcept:
        cdef wlr_surface *wlr_surface = self.wlr_xdg_surface.surface
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
        if debug:
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
        memset(<void *> &opts.src_box, 0, sizeof(wlr_box))
        cdef int *iptr
        iptr = <int*> &opts.src_box.x
        iptr[0] = self.wlr_xdg_surface.geometry.x
        iptr = <int*> &opts.src_box.y
        iptr[0] = self.wlr_xdg_surface.geometry.y
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
        self._emit("surface-image", self.wid, image)

    cdef void new_subsurface(self, wlr_subsurface *subsurface) noexcept:
        log("New SUBSURFACE created, parent wid=%#x", self.wid)
        log(" subsurface wlr_surface=%#x, parent wlr_surface=%#x",
            <uintptr_t>subsurface.surface, <uintptr_t>subsurface.parent)

        # Get dimensions if available
        width = subsurface.surface.current.width if subsurface.surface else 0
        height = subsurface.surface.current.height if subsurface.surface else 0

        wid = next_wid()
        log("allocated wid=%#x", wid)
        # TODO: allocate Surface and populate it
        self._emit("new-subsurface", self.wid, wid, <uintptr_t> subsurface.surface, width, height)

    cdef void unregister_toplevel_handlers(self) noexcept nogil:
        # Toplevel slots are contiguous: L_REQUEST_MOVE..L_REQUEST_SHOW_WINDOW_MENU.
        # L_NEW_SUBSURFACE is technically a main-listener slot but the prior
        # implementation also detached it on unmap; preserved for behaviour.
        self._detach_slot(L_NEW_SUBSURFACE)
        cdef int i
        for i in range(L_REQUEST_MOVE, L_REQUEST_SHOW_WINDOW_MENU + 1):
            self._detach_slot(i)

    def resize(self, width: int, height: int) -> None:
        cdef wlr_xdg_surface *surface = <wlr_xdg_surface*> self.wlr_xdg_surface
        if surface == NULL:
            log("%s.resize(%i, %i): surface destroyed; skipping", self, width, height)
            return
        # `surface.toplevel` is a union slot shared with `popup` — only safe to
        # treat as wlr_xdg_toplevel* when role is TOPLEVEL. Otherwise we'd be
        # passing a popup pointer to set_size and crash inside wlroots.
        if surface.role != WLR_XDG_SURFACE_ROLE_TOPLEVEL:
            log.warn("Warning: %s.resize(%i, %i) role=%d, not a toplevel; skipping", self, width, height, surface.role)
            return
        cdef wlr_xdg_toplevel *toplevel = surface.toplevel
        if toplevel == NULL:
            log("%s.resize(%i, %i): no toplevel yet, skipping", self, width, height)
            return
        log("wlr_xdg_toplevel_set_size(%#x, %i, %i)", <uintptr_t> toplevel, width, height)
        wlr_xdg_toplevel_set_size(toplevel, width, height)

    def focus(self, focused: bool) -> None:
        cdef wlr_xdg_surface *surface = <wlr_xdg_surface*> self.wlr_xdg_surface
        if surface == NULL:
            log("%s.focus(%s): surface destroyed; skipping", self, focused)
            return
        if surface.role != WLR_XDG_SURFACE_ROLE_TOPLEVEL:
            log.warn("Warning: %s.focus(%s): role=%d, not a toplevel; skipping", self, focused, surface.role)
            return
        cdef wlr_xdg_toplevel *toplevel = surface.toplevel
        if toplevel == NULL:
            log("%s.focus(%s): no toplevel yet, skipping", self, focused)
            return
        log("wlr_xdg_toplevel_set_activated(%#x, %s)", <uintptr_t> toplevel, focused)
        wlr_xdg_toplevel_set_activated(toplevel, focused)

    # __dealloc__ inherited from ListenerObject: detach + free the listeners array.


cdef list get_damage_areas(pixman_region32_t *damage):
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
