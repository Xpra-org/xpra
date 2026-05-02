# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# cython: language_level=3

from libc.stdint cimport uintptr_t

from xpra.log import Logger
from xpra.wayland.wlroots cimport (
    wl_listener,
    wlr_subsurface,
    wlr_surface,
)
from xpra.wayland.wayland_surface cimport WaylandSurface, next_wid


log = Logger("wayland")
cdef bint debug = log.is_debug_enabled()


# Listener slots for Subsurface. Tracking the wl_surface (commit/destroy) is
# enough to drive damage forwarding and lifecycle. We can grow this as new
# needs come up (e.g. nested subsurface tracking via wl_surface.events.new_subsurface).
cdef enum SubsurfaceListener:
    L_COMMIT
    L_DESTROY            # underlying wl_surface destroy
    L_SUB_DESTROY        # subsurface-role destroy (role unassigned but wl_surface may live on)
    N_LISTENERS


cdef class Subsurface(WaylandSurface):

    def __init__(self):
        super().__init__(N_LISTENERS)
        self.wid = next_wid()

    cdef void attach(self, WaylandSurface parent, wlr_subsurface *subsurface):
        """Wire up listeners to the subsurface and its underlying wl_surface,
        and stash a back-pointer to the parent wrapper. The caller is
        responsible for ensuring `subsurface` is alive — typically called from
        the parent's wl_surface.events.new_subsurface handler."""
        if subsurface == NULL or subsurface.surface == NULL:
            return
        self.parent = parent
        self.wlr_subsurface = subsurface
        self.wlr_surface = subsurface.surface
        # The shared `surfaces` registry is keyed by wl_surface, so any code
        # path with a wl_surface pointer (e.g. nested subsurface lookups,
        # cursor tracking) can find this Subsurface uniformly.
        self.register()
        # Listen for the underlying wl_surface's commit and destroy, and the
        # subsurface-role destroy.
        self.add_listener(L_COMMIT, &subsurface.surface.events.commit)
        self.add_listener(L_DESTROY, &subsurface.surface.events.destroy)
        self.add_listener(L_SUB_DESTROY, &subsurface.events.destroy)

    cdef void dispatch(self, wl_listener *listener, void *data) noexcept:
        cdef int slot = self.slot_of(listener)
        if slot == L_COMMIT:
            self.commit()
        elif slot == L_DESTROY or slot == L_SUB_DESTROY:
            self.destroy()
        else:
            log.error("Error: unknown subsurface listener slot %i", slot)

    cdef void commit(self) noexcept:
        # Subsurface committed a new buffer / damage. Pull the pixels (the
        # base class capture_pixels reads from self.wlr_surface.buffer.texture)
        # and emit, so consumers can repaint just this child.
        if self.wlr_surface == NULL:
            return
        if not self.wlr_surface.mapped:
            return
        image = self.capture_pixels()
        if image is None:
            return
        if debug:
            log("%s commit: %s", self, image)
        self._emit("subsurface-image", self.wid, image)

    cdef void destroy(self) noexcept:
        if self.wlr_surface == NULL:
            # idempotent: either the wl_surface destroy or subsurface-role
            # destroy already ran (both can fire for the same teardown).
            return
        log("%s DESTROYED", self)
        self._detach_all()
        self._emit("destroy", self.wid)
        self.unregister()
        # wlroots will free both the wl_surface and the wlr_subsurface struct
        # the moment we return; null both pointers so any later Python-side
        # access (capture_pixels, frame_done, etc.) is a safe no-op.
        self.wlr_surface = NULL
        self.wlr_subsurface = NULL
        self.parent = None
