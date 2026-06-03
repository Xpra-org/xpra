# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# cython: language_level=3

from typing import Dict
from math import ceil, floor

from xpra.log import Logger
from xpra.util.str_fn import Ellipsizer
from xpra.codecs.image import ImageWrapper
from xpra.codecs.dmabuf.image import DMABufImageWrapper

from libc.string cimport memset
from libc.stdint cimport uintptr_t, uint32_t
from libc.time cimport timespec

from xpra.buffers.membuf cimport getbuf, MemBuf
from xpra.wayland.events cimport ListenerObject

cdef extern from "time.h":
    int clock_gettime(int clk_id, timespec *tp)
    cdef int CLOCK_MONOTONIC


from xpra.wayland.wlroots cimport (
    wlr_surface, wlr_buffer, wlr_texture, wlr_client_buffer, wlr_box, wlr_fbox,
    wlr_texture_read_pixels_options, wlr_texture_read_pixels, wlr_texture_preferred_read_format,
    wlr_dmabuf_attributes, wlr_buffer_get_dmabuf,
    wlr_surface_send_frame_done, wlr_surface_get_buffer_source_box,
    DRM_FORMAT_ARGB8888, DRM_FORMAT_ABGR8888, DRM_FORMAT_XRGB8888, DRM_FORMAT_XBGR8888,
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

    cdef tuple get_surface_size(self):
        if self.wlr_surface == NULL:
            return 0, 0
        return self.wlr_surface.current.width, self.wlr_surface.current.height

    def get_size(self) -> tuple[int, int]:
        return self.get_surface_size()

    cdef tuple get_buffer_source_geometry(self):
        return self.get_buffer_source_geometry_for_surface_rect(0, 0, 0, 0)

    cdef tuple get_buffer_source_geometry_for_surface_rect(self, int surface_x, int surface_y,
                                                           int surface_width, int surface_height):
        """Map a surface-local rectangle to the native buffer source rectangle.

        `wp_viewport.set_destination` changes surface-local dimensions while
        keeping the attached buffer at its native size; wlroots exposes that
        native source box here.
        """
        if self.wlr_surface == NULL:
            return 0, 0, 0, 0
        cdef wlr_fbox source_box
        wlr_surface_get_buffer_source_box(self.wlr_surface, &source_box)
        cdef double x1 = source_box.x
        cdef double y1 = source_box.y
        cdef double x2 = source_box.x + source_box.width
        cdef double y2 = source_box.y + source_box.height
        cdef int total_width = self.wlr_surface.current.width
        cdef int total_height = self.wlr_surface.current.height
        if surface_width > 0 and surface_height > 0 and total_width > 0 and total_height > 0:
            x1 = source_box.x + (source_box.width * surface_x / total_width)
            y1 = source_box.y + (source_box.height * surface_y / total_height)
            x2 = source_box.x + (source_box.width * (surface_x + surface_width) / total_width)
            y2 = source_box.y + (source_box.height * (surface_y + surface_height) / total_height)
            x1 = max(source_box.x, x1)
            y1 = max(source_box.y, y1)
            x2 = min(source_box.x + source_box.width, x2)
            y2 = min(source_box.y + source_box.height, y2)
        cdef int x = <int> floor(x1)
        cdef int y = <int> floor(y1)
        cdef int width = <int> ceil(x2) - x
        cdef int height = <int> ceil(y2) - y
        return x, y, max(0, width), max(0, height)

    def get_buffer_source_size(self) -> tuple[int, int]:
        return self.get_buffer_source_geometry()[2:4]

    def capture_pixels(self, int x=-1, int y=-1, int width=0, int height=0):
        """Copy the current buffer's pixels out as an ImageWrapper.
        Returns None if the surface is destroyed or has no committed buffer."""
        if self.wlr_surface == NULL:
            return None
        cdef wlr_client_buffer *client_buffer = self.wlr_surface.buffer
        if not client_buffer:
            return None

        source_geometry = None
        if x < 0 or y < 0 or width <= 0 or height <= 0:
            source_geometry = self.get_buffer_source_geometry()
            if x < 0:
                x = source_geometry[0]
            if y < 0:
                y = source_geometry[1]
            if width <= 0:
                width = source_geometry[2]
            if height <= 0:
                height = source_geometry[3]
        if width <= 0 or height <= 0:
            return None

        cdef wlr_buffer *source = client_buffer.source
        cdef wlr_dmabuf_attributes dmabuf
        if source != NULL and wlr_buffer_get_dmabuf(source, &dmabuf):
            if x != 0 or y != 0 or width != dmabuf.width or height != dmabuf.height:
                return self.download_texture_pixels(x, y, width, height)
            if debug:
                log("%s.capture_pixels: dmabuf %dx%d format=%#x modifier=%#x planes=%i",
                    self, dmabuf.width, dmabuf.height, dmabuf.format, dmabuf.modifier, dmabuf.n_planes)
            fds = tuple(dmabuf.fd[i] for i in range(dmabuf.n_planes))
            strides = tuple(dmabuf.stride[i] for i in range(dmabuf.n_planes))
            offsets = tuple(dmabuf.offset[i] for i in range(dmabuf.n_planes))
            image = DMABufImageWrapper(0, 0, dmabuf.width, dmabuf.height,
                                       dmabuf.format, dmabuf.modifier,
                                       fds, strides, offsets,
                                       lambda: self.download_texture_pixels(x, y, width, height))
            image.may_download()
            return image

        return self.download_texture_pixels(x, y, width, height)

    def download_texture_pixels(self, int x=-1, int y=-1, int width=0, int height=0):
        """Copy the current texture's pixels out as a CPU ImageWrapper."""
        if self.wlr_surface == NULL:
            return None
        cdef wlr_client_buffer *client_buffer = self.wlr_surface.buffer
        if not client_buffer:
            return None
        cdef wlr_texture *texture = client_buffer.texture
        if not texture:
            return None

        if x < 0 or y < 0 or width <= 0 or height <= 0:
            source_geometry = self.get_buffer_source_geometry()
            if x < 0:
                x = source_geometry[0]
            if y < 0:
                y = source_geometry[1]
            if width <= 0:
                width = source_geometry[2]
            if height <= 0:
                height = source_geometry[3]
        if width <= 0 or height <= 0:
            return None
        cdef int texture_width = texture.width
        cdef int texture_height = texture.height
        if x < 0 or y < 0 or x >= texture_width or y >= texture_height:
            return None
        width = min(width, texture_width - x)
        height = min(height, texture_height - y)

        cdef uint32_t read_width = width
        cdef uint32_t read_height = height
        cdef uint32_t stride = read_width * 4
        cdef uint32_t texture_size = stride * height
        cdef MemBuf texture_buffer = getbuf(texture_size, 0)
        if debug:
            log("%s.capture_pixels: %i,%i %dx%d (%d bytes)", self, x, y, read_width, read_height, texture_size)

        cdef uint32_t read_format = wlr_texture_preferred_read_format(texture)
        cdef str pixel_format
        if read_format == DRM_FORMAT_ABGR8888:
            pixel_format = "RGBA"
        elif read_format == DRM_FORMAT_XBGR8888:
            pixel_format = "RGBX"
        elif read_format == DRM_FORMAT_ARGB8888:
            pixel_format = "BGRA"
        elif read_format == DRM_FORMAT_XRGB8888:
            pixel_format = "BGRX"
        else:
            if debug:
                log("%s.capture_pixels: unsupported preferred read format %#x, using ABGR8888",
                    self, read_format)
            read_format = DRM_FORMAT_ABGR8888
            pixel_format = "RGBA"

        cdef wlr_texture_read_pixels_options opts
        opts.data = <void*> texture_buffer.get_mem()
        opts.format = read_format
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
        iptr[0] = read_width
        iptr = <int*> &opts.src_box.height
        iptr[0] = read_height

        cdef bint success
        with nogil:
            success = wlr_texture_read_pixels(texture, &opts)
        if not success:
            log.error("Error: failed to read texture pixels for %s", self)
            return None

        pixels = memoryview(texture_buffer)
        return ImageWrapper(0, 0, read_width, read_height, pixels, pixel_format, 32, stride)
