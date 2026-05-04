# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# cython: language_level=3

from libc.stdint cimport uintptr_t

from xpra.log import Logger
from xpra.wayland.wayland_surface cimport WaylandSurface, next_wid
from xpra.wayland.wlroots cimport (
    wl_listener,
    wlr_xdg_popup,
    wlr_xdg_popup_get_position,
    wlr_xdg_surface_schedule_configure,
)


log = Logger("wayland")
cdef bint debug = log.is_debug_enabled()


cdef enum PopupListener:
    L_MAP
    L_UNMAP
    L_COMMIT
    L_DESTROY
    L_POPUP_DESTROY
    L_REPOSITION
    N_LISTENERS


cdef class Popup(WaylandSurface):

    def __init__(self):
        super().__init__(N_LISTENERS)
        self.wid = next_wid()
        self.x = 0
        self.y = 0

    def __repr__(self):
        parent_wid = getattr(self.parent, "wid", 0)
        return "Popup(%i parent=%i)" % (self.wid, parent_wid)

    @property
    def xdg_surface_ptr(self) -> int:
        return <uintptr_t> self.wlr_xdg_surface

    @property
    def parent_wid(self) -> int:
        return getattr(self.parent, "wid", 0)

    def get_parent(self):
        return self.parent

    def get_position(self) -> tuple[int, int]:
        return self.position()

    def resize(self, width: int, height: int) -> None:
        log("%s.resize(%i, %i): popup size is controlled by the Wayland client",
            self, width, height)

    def focus(self, focused: bool) -> None:
        log("%s.focus(%s): popup has no xdg_toplevel activation state",
            self, focused)

    cdef tuple position(self):
        cdef double x = 0
        cdef double y = 0
        if self.wlr_xdg_popup != NULL:
            wlr_xdg_popup_get_position(self.wlr_xdg_popup, &x, &y)
        return round(x), round(y)

    cdef void attach(self, WaylandSurface parent, wlr_xdg_popup *popup):
        if popup == NULL or popup.base == NULL or popup.base.surface == NULL:
            return
        self.parent = parent
        self.wlr_xdg_popup = popup
        self.wlr_xdg_surface = popup.base
        self.wlr_surface = popup.base.surface
        self.register()
        self.x, self.y = self.position()
        self.add_listener(L_MAP, &self.wlr_surface.events.map)
        self.add_listener(L_UNMAP, &self.wlr_surface.events.unmap)
        self.add_listener(L_COMMIT, &self.wlr_surface.events.commit)
        self.add_listener(L_DESTROY, &self.wlr_surface.events.destroy)
        self.add_listener(L_POPUP_DESTROY, &popup.events.destroy)
        self.add_listener(L_REPOSITION, &popup.events.reposition)

    cdef void dispatch(self, wl_listener *listener, void *data) noexcept:
        cdef int slot = self.slot_of(listener)
        if slot == L_MAP:
            self.map()
        elif slot == L_UNMAP:
            self.unmap()
        elif slot == L_COMMIT:
            self.commit()
        elif slot == L_DESTROY or slot == L_POPUP_DESTROY:
            self.destroy()
        elif slot == L_REPOSITION:
            self.reposition()
        else:
            log.error("Error: unknown popup listener slot %i", slot)

    cdef void map(self) noexcept:
        cdef int width = 0
        cdef int height = 0
        if self.wlr_xdg_surface != NULL:
            self.x, self.y = self.position()
            width = self.wlr_xdg_surface.geometry.width
            height = self.wlr_xdg_surface.geometry.height
        log("XDG popup MAPPED: wid=%i parent=%i position=%s size=%s",
            self.wid, getattr(self.parent, "wid", 0), (self.x, self.y), (width, height))
        self._emit("map", self.wid, (self.x, self.y), (width, height))

    cdef void unmap(self) noexcept:
        log("XDG popup UNMAPPED: wid=%i", self.wid)
        self._emit("unmap", self.wid)

    cdef void commit(self) noexcept:
        if self.wlr_xdg_surface == NULL or self.wlr_surface == NULL:
            return
        if self.wlr_xdg_surface.initialized and not self.wlr_xdg_surface.configured:
            wlr_xdg_surface_schedule_configure(self.wlr_xdg_surface)
        self.x, self.y = self.position()
        cdef int width = self.wlr_xdg_surface.geometry.width
        cdef int height = self.wlr_xdg_surface.geometry.height
        image = None
        if self.wlr_surface.mapped:
            image = self.capture_pixels(self.wlr_xdg_surface.geometry.x,
                                        self.wlr_xdg_surface.geometry.y)
        self._emit("commit", self.wid, bool(self.wlr_surface.mapped),
                   (self.x, self.y), (width, height), image is not None)
        if image is not None:
            self._emit("surface-image", self.wid, image)

    cdef void reposition(self) noexcept:
        cdef tuple old_pos = (self.x, self.y)
        self.x, self.y = self.position()
        if debug:
            log("XDG popup REPOSITION: wid=%i %s -> %s", self.wid, old_pos, (self.x, self.y))
        self._emit("reposition", self.wid, (self.x, self.y))

    cdef void destroy(self) noexcept:
        if self.wlr_surface == NULL:
            return
        log("XDG popup DESTROYED: wid=%i", self.wid)
        self._detach_all()
        self._emit("destroy", self.wid)
        self.unregister()
        self.wlr_surface = NULL
        self.wlr_xdg_surface = NULL
        self.wlr_xdg_popup = NULL
        self.parent = None
