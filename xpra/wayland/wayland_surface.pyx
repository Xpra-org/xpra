# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# cython: language_level=3

from typing import Dict

from xpra.log import Logger
from xpra.util.str_fn import Ellipsizer
from xpra.codecs.image import ImageWrapper

from libc.string cimport memset
from libc.stdint cimport uintptr_t, uint32_t
from libc.time cimport timespec

from xpra.buffers.membuf cimport getbuf, MemBuf
from xpra.wayland.events cimport ListenerObject

cdef extern from "time.h":
    int clock_gettime(int clk_id, timespec *tp)
    cdef int CLOCK_MONOTONIC


from xpra.wayland.wlroots cimport (
    wlr_surface, wlr_texture, wlr_client_buffer, wlr_box,
    wlr_texture_read_pixels_options, wlr_texture_read_pixels,
    wlr_surface_send_frame_done,
    DRM_FORMAT_ABGR8888,
)


log = Logger("wayland")
cdef bint debug = log.is_debug_enabled()


# Single registry across every WaylandSurface subclass — keyed by the wl_surface
# pointer (the only field common to xdg_surfaces and subsurfaces). Holds a
# strong reference so wlroots-side listener pointers stay valid until the
# matching destroy path explicitly removes the entry.
surfaces: Dict[int, WaylandSurface] = {}


cdef unsigned long _wid_counter = 0

cdef unsigned long next_wid() noexcept:
    global _wid_counter
    _wid_counter += 1
    return _wid_counter


cdef class WaylandSurface(ListenerObject):

    def __cinit__(self):
        self._callbacks = {}

    def __repr__(self):
        return "%s(%i)" % (type(self).__name__, self.wid)

    # ---- subclasses populate self.wlr_surface, then call register() ----

    cdef void register(self):
        if self.wlr_surface == NULL:
            return
        surfaces[<uintptr_t> self.wlr_surface] = self

    cdef void unregister(self):
        if self.wlr_surface == NULL:
            return
        surfaces.pop(<uintptr_t> self.wlr_surface, None)

    # ---- public per-instance signals ----

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
        self._emit_args(event, args)

    cdef _emit_args(self, str event, tuple args):
        cdef list cbs = self._callbacks.get(event)
        if not cbs:
            return
        if debug:
            log("%s._emit(%s, %s) callbacks=%s", self, event, Ellipsizer(args), cbs)
        for cb in cbs:
            cb(*args)

    # ---- common wl_surface plumbing ----

    @property
    def wl_surface_ptr(self) -> int:
        """Raw wl_surface pointer; 0 once the surface has been destroyed."""
        return <uintptr_t> self.wlr_surface

    def frame_done(self) -> None:
        """Tell the wayland client we finished rendering this frame.
        No-op once the underlying wl_surface has been destroyed."""
        if self.wlr_surface == NULL:
            return
        cdef timespec now
        clock_gettime(CLOCK_MONOTONIC, &now)
        wlr_surface_send_frame_done(self.wlr_surface, &now)

    def capture_pixels(self, int x=0, int y=0):
        """Copy the current buffer's pixels out as an ImageWrapper.
        Returns None if the surface is destroyed or has no committed buffer."""
        if self.wlr_surface == NULL:
            return None
        cdef wlr_client_buffer *client_buffer = self.wlr_surface.buffer
        if not client_buffer:
            return None
        cdef wlr_texture *texture = client_buffer.texture
        if not texture:
            return None

        cdef uint32_t width = texture.width
        cdef uint32_t height = texture.height
        cdef uint32_t stride = width * 4
        cdef uint32_t texture_size = stride * height
        cdef MemBuf texture_buffer = getbuf(texture_size, 0)
        if debug:
            log("%s.capture_pixels: %dx%d (%d bytes)", self, width, height, texture_size)

        cdef wlr_texture_read_pixels_options opts
        opts.data = <void*> texture_buffer.get_mem()
        opts.format = DRM_FORMAT_ABGR8888
        opts.stride = stride
        opts.dst_x = 0
        opts.dst_y = 0
        # src_box is const in the C signature, but we can't init the struct
        # with the values we want; patch it through an int* alias.
        memset(<void *> &opts.src_box, 0, sizeof(wlr_box))
        cdef int *iptr
        iptr = <int*> &opts.src_box.x
        iptr[0] = x
        iptr = <int*> &opts.src_box.y
        iptr[0] = y
        iptr = <int*> &opts.src_box.width
        iptr[0] = width
        iptr = <int*> &opts.src_box.height
        iptr[0] = height

        cdef bint success
        with nogil:
            success = wlr_texture_read_pixels(texture, &opts)
        if not success:
            log.error("Error: failed to read texture pixels for %s", self)
            return None

        pixels = memoryview(texture_buffer)
        return ImageWrapper(0, 0, width, height, pixels, "BGRA", 32, stride)
