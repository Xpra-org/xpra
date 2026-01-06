# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic
from typing import Tuple, Dict

from xpra.x11.bindings.core import call_context_check  # @UnresolvedImport
from xpra.x11.bindings.core cimport X11CoreBindingsInstance, import_check
from xpra.x11.bindings.xlib cimport (
    XImage, Display, Pixmap,
    XColor, Visual, VisualID,
    Status, Window, Drawable, Bool,
    XWindowAttributes,
    MSBFirst, LSBFirst, ZPixmap,
    AllPlanes,
)
from xpra.buffers.membuf cimport memalign, memfree
from libc.stdlib cimport free
from libc.string cimport memcpy
from libc.stdint cimport uintptr_t

from xpra.log import Logger

import_check("image")

log = Logger("x11", "bindings", "ximage")
ximagedebug = Logger("x11", "bindings", "ximage", "verbose")


cdef extern from "Python.h":
    object PyMemoryView_FromMemory(char *mem, Py_ssize_t size, int flags)
    int PyObject_GetBuffer(object obj, Py_buffer *view, int flags)
    void PyBuffer_Release(Py_buffer *view)
    int PyBUF_ANY_CONTIGUOUS
    int PyBUF_READ
    int PyBUF_WRITE


cdef extern from "sys/ipc.h":
    ctypedef struct key_t:
        pass
    key_t IPC_PRIVATE
    int IPC_CREAT
    int IPC_RMID


cdef extern from "sys/shm.h":
    int shmget(key_t __key, size_t __size, int __shmflg)
    void *shmat(int __shmid, const void *__shmaddr, int __shmflg)
    int shmdt (const void *__shmaddr)
    ctypedef struct shmid_ds:
        pass
    int shmctl(int shmid, int cmd, shmid_ds *buf)


cdef extern from "errno.h" nogil:
    int errno
    int EINVAL


DEF XNone = 0


cdef extern from "X11/X.h":
    unsigned long NoSymbol


cdef extern from "X11/Xatom.h":
    int XA_RGB_DEFAULT_MAP
    int XA_RGB_BEST_MAP


cdef extern from "X11/Xlib.h":
    int XFreePixmap(Display *, Pixmap pixmap)

    void XQueryColors(Display *display, Colormap colormap, XColor defs_in_out[], int ncolors)
    VisualID XVisualIDFromVisual(Visual *visual)

    Status XGetWindowAttributes(Display * display, Window w, XWindowAttributes * attributes)


    XImage *XGetImage(Display *display, Drawable d,
            int x, int y, unsigned int width, unsigned int  height,
            unsigned long plane_mask, int fmt)

    void XDestroyImage(XImage *ximage)

    Status XGetGeometry(Display *display, Drawable d, Window *root_return,
                        int *x_return, int *y_return, unsigned int  *width_return, unsigned int *height_return,
                        unsigned int *border_width_return, unsigned int *depth_return)


cdef extern from "X11/Xutil.h":
    pass


SBFirst: Dict[int, str] = {
    MSBFirst : "MSBFirst",
    LSBFirst : "LSBFirst"
}

RLE8    = "RLE8"
RGB565  = "RGB565"
BGR565  = "BGR565"
XRGB    = "XRGB"
BGRX    = "BGRX"
ARGB    = "ARGB"
BGRA    = "BGRA"
RGB     = "RGB"
RGBA    = "RGBA"
RGBX    = "RGBX"
R210    = "R210"
r210    = "r210"

RGB_FORMATS = [XRGB, BGRX, ARGB, BGRA, RGB, RGBA, RGBX, R210, r210, RGB565, BGR565, RLE8]


cdef int ximage_counter = 0


cdef class XImageWrapper:
    """
        Presents X11 image pixels as in ImageWrapper
    """

    def __cinit__(self, unsigned int x, unsigned int y, unsigned int width, unsigned int height,
                        uintptr_t pixels=0, pixel_format="", unsigned int depth=24, unsigned int rowstride=0,
                        int planes=0, unsigned int bytesperpixel=4, thread_safe=False, sub=False,
                        palette=None, full_range=True):
        self.image = NULL
        self.pixels = NULL
        self.x = x
        self.y = y
        self.target_x = x
        self.target_y = y
        self.width = width
        self.height = height
        self.depth = depth
        self.bytesperpixel = bytesperpixel
        self.pixel_format = pixel_format
        self.rowstride = rowstride
        self.planes = planes
        self.thread_safe = thread_safe
        self.sub = sub
        self.pixels = <void *> pixels
        self.timestamp = int(monotonic()*1000)
        self.palette = palette
        self.full_range = int(full_range)
        self.aligned = False

    cdef void set_image(self, XImage* image):
        assert not self.sub
        assert image!=NULL
        global ximage_counter
        ximage_counter += 1
        self.thread_safe = 0
        self.image = image
        self.rowstride = image.bytes_per_line
        self.depth = image.depth
        if self.depth==24:
            self.bytesperpixel = 4
            if image.byte_order==MSBFirst:
                self.pixel_format = XRGB
            else:
                self.pixel_format = BGRX
        elif self.depth==16:
            self.bytesperpixel = 2
            if image.byte_order==MSBFirst:
                self.pixel_format = RGB565
            else:
                self.pixel_format = BGR565
        elif self.depth==8:
            self.bytesperpixel = 1
            self.pixel_format = RLE8
        elif self.depth==32:
            self.bytesperpixel = 4
            if image.byte_order==MSBFirst:
                self.pixel_format = ARGB
            else:
                self.pixel_format = BGRA
        elif self.depth==30:
            #log.warn("30bpp, byte_order=%i, bitmap_bit_order=%i, bits_per_pixel=%s", image.byte_order, image.bitmap_bit_order, image.bits_per_pixel)
            #log.warn("pad=%i, unit=%i, format=%i", image.bitmap_pad, image.bitmap_unit, image.format)
            #log.warn("masks: red=%#x, green=%#x, blue=%#x", image.red_mask, image.green_mask, image.blue_mask)
            self.bytesperpixel = 4
            if image.byte_order==MSBFirst:
                self.pixel_format = R210
            else:
                self.pixel_format = r210
        else:
            raise ValueError(f"invalid image depth: {self.depth} bpp")

    def __repr__(self):
        return "XImageWrapper(%s: %i, %i, %i, %i)" % (self.pixel_format, self.x, self.y, self.width, self.height)

    def get_geometry(self) -> Tuple[int, int, int, int, int]:
        return self.x, self.y, self.width, self.height, self.depth

    def get_target_x(self) -> int:
        return self.target_x

    def get_target_y(self) -> int:
        return self.target_y

    def set_target_x(self, unsigned int target_x):
        self.target_x = target_x

    def set_target_y(self, unsigned int target_y):
        self.target_y = target_y

    def get_x(self) -> int:
        return self.x

    def get_y(self) -> int:
        return self.y

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def get_rowstride(self) -> int:
        return self.rowstride

    def get_palette(self):
        return self.palette

    def get_full_range(self) -> bool:
        return bool(self.full_range)

    def get_planes(self) -> int:
        return self.planes

    def get_depth(self) -> int:
        return self.depth

    def get_bytesperpixel(self) -> int:
        return self.bytesperpixel

    def get_size(self) -> int:
        return self.rowstride * self.height

    def get_pixel_format(self):
        return self.pixel_format

    def get_pixels(self):
        cdef void *pix_ptr = self.get_pixels_ptr()
        if pix_ptr==NULL:
            return None
        cdef int flags = PyBUF_READ
        if self.pixels!=NULL:
            flags = PyBUF_WRITE
        return PyMemoryView_FromMemory(<char *> pix_ptr, self.get_size(), PyBUF_READ)

    def get_sub_image(self, unsigned int x, unsigned int y, unsigned int w, unsigned int h):
        if w<=0 or h<=0:
            raise ValueError(f"invalid sub-image size: {w}x{h}")
        if x+w>self.width:
            raise ValueError(f"invalid sub-image width: {x}+{w} greater than image width {self.width}")
        if y+h>self.height:
            raise ValueError(f"invalid sub-image height: {y}+{h} greater than image height {self.height}")
        cdef void *src = self.get_pixels_ptr()
        if src==NULL:
            raise ValueError("source image does not have any pixels!")
        cdef unsigned char Bpp = BYTESPERPIXEL(self.depth)
        cdef uintptr_t sub_ptr = (<uintptr_t> src) + x*Bpp + y*self.rowstride
        image = XImageWrapper(self.x+x, self.y+y, w, h, sub_ptr, self.pixel_format,
                             self.depth, self.rowstride, self.planes, self.bytesperpixel, True, True,
                             self.palette, self.full_range)
        image.set_target_x(self.target_x+x)
        image.set_target_y(self.target_y+y)
        return image

    cdef void* get_pixels_ptr(self):
        if self.pixels!=NULL:
            return self.pixels
        cdef XImage *image = self.image
        if image==NULL:
            log.warn("get_pixels_ptr: image is NULL!")
            return NULL
        if image.data is NULL:
            log.warn("get_pixels_ptr: image.data is NULL!")
        return image.data

    def get_gpu_buffer(self):
        return None

    def has_pixels(self) -> bool:
        if self.pixels!=NULL:
            return True
        cdef XImage *image = self.image
        if image==NULL:
            return False
        return image.data!=NULL

    def is_thread_safe(self) -> bool:
        return self.thread_safe

    def get_timestamp(self) -> int:
        """ time in millis """
        return self.timestamp

    def set_palette(self, palette) -> None:
        self.palette = palette

    def set_full_range(self, full_range: bool) -> None:
        self.full_range = int(full_range)

    def set_timestamp(self, timestamp) -> None:
        self.timestamp = timestamp

    def set_rowstride(self, unsigned int rowstride) -> None:
        self.rowstride = rowstride

    def set_pixel_format(self, pixel_format) -> None:
        assert pixel_format is not None and pixel_format in RGB_FORMATS, "invalid pixel format: %s" % pixel_format
        self.pixel_format = pixel_format

    def set_pixels(self, pixels) -> None:
        """ overrides the context of the image with the given pixels buffer """
        if self.pixels!=NULL:
            if not self.sub:
                free(self.pixels)
            self.pixels = NULL

        cdef Py_buffer py_buf
        if PyObject_GetBuffer(pixels, &py_buf, PyBUF_ANY_CONTIGUOUS):
            raise ValueError(f"failed to read pixel data from {type(pixels)}")

        #Note: we can't free the XImage, because it may
        #still be used somewhere else (see XShmWrapper)
        self.pixels = memalign(py_buf.len)
        if self.pixels == NULL:
            PyBuffer_Release(&py_buf)
            raise MemoryError("memalign failed for %i bytes" % py_buf.len)
        assert self.pixels!=NULL
        self.aligned = True
        #from now on, we own the buffer,
        #so we're no longer a direct sub-image,
        #and we must free the buffer later:
        self.sub = False
        if self.image==NULL:
            self.thread_safe = 1
            #we can now mark this object as thread safe
            #if we have already freed the XImage
            #which needs to be freed from the UI thread
            #but our new buffer is just a malloc buffer,
            #which is safe from any thread
        memcpy(self.pixels, py_buf.buf, py_buf.len)
        PyBuffer_Release(&py_buf)

    def free(self) -> None:
        ximagedebug("%s.free()", self)
        self.free_image()
        self.free_pixels()

    cdef void free_image(self):
        ximagedebug("%s.free_image() image=%#x", self, <uintptr_t> self.image)
        if self.image!=NULL:
            call_context_check("XImageWrapper.free_image")
            XDestroyImage(self.image)
            self.image = NULL
            global ximage_counter
            ximage_counter -= 1

    cdef void free_pixels(self):
        ximagedebug("%s.free_pixels() pixels=%#x", self, <uintptr_t> self.pixels)
        if self.pixels!=NULL:
            if not self.sub:
                if self.aligned:
                    memfree(self.pixels)
                else:
                    free(self.pixels)
            self.pixels = NULL

    def freeze(self) -> bool:
        #we don't need to do anything here because the non-XShm version
        #already uses a copy of the pixels
        return False

    def may_restride(self) -> bool:
        #if not given a newstride, assume it is optional and check if it is worth doing at all:
        if self.rowstride<=8 or self.height<=2:
            return False                                    #not worth it
        #use a reasonable stride: rounded up to 4
        cdef unsigned int newstride = roundup(self.width*len(self.pixel_format), 4)
        if newstride>=self.rowstride:
            return False                                    #not worth it
        cdef unsigned int newsize = newstride*self.height   #desirable size we could have
        cdef unsigned int size = self.rowstride*self.height
        if size-newsize<1024 or newsize*110/100>size:
            log("may_restride() not enough savings with new stride=%i vs %i: new size=%i vs %i", newstride, self.rowstride, newsize, size)
            return False
        return self.restride(newstride)

    def restride(self, const unsigned int rowstride) -> bool:
        #NOTE: this must be called from the UI thread!
        #start = monotonic()
        cdef unsigned int newsize = rowstride*self.height                #desirable size we could have
        cdef unsigned int size = self.rowstride*self.height
        #is it worth re-striding to save space:
        #(save at least 1KB and 10%)
        #Note: we could also change the pixel format whilst we're at it
        # and convert BGRX to RGB for example (assuming RGB is also supported by the client)
        cdef void *img_buf = self.get_pixels_ptr()
        assert img_buf!=NULL, "this image wrapper is empty!"
        cdef void *new_buf
        new_buf = memalign(newsize + rowstride)
        if new_buf == NULL:
            raise MemoryError("memalign failed for %i bytes!" % (newsize + rowstride))
        cdef void *to = new_buf
        cdef unsigned int oldstride = self.rowstride                     #using a local variable is faster
        #Note: we don't zero the buffer,
        #so if the newstride is bigger than oldstride, you get garbage..
        cdef unsigned int cpy_size
        if oldstride==rowstride:
            memcpy(to, img_buf, size)
        else:
            cpy_size = MIN(rowstride, oldstride)
            for _ in range(self.height):
                memcpy(to, img_buf, cpy_size)
                to += rowstride
                img_buf += oldstride
        #we can now free the pixels buffer if present
        #(but not the ximage - this is not running in the UI thread!)
        self.free_pixels()
        #set the new attributes:
        self.rowstride = rowstride
        self.pixels = <char *> new_buf
        self.aligned = True
        #without any X11 image to free, this is now thread safe:
        if self.image==NULL:
            self.thread_safe = 1
        #log("restride(%s) %s pixels re-stride saving %i%% from %s (%s bytes) to %s (%s bytes) took %.1fms",
        #    rowstride, self.pixel_format, 100-100*newsize/size, oldstride, size, rowstride, newsize, (monotonic()-start)*1000)
        return True


cdef int drawable_counter = 0


cdef class DrawableWrapper:
    cdef Display *display
    cdef Drawable drawable
    cdef unsigned int width
    cdef unsigned int height

    cdef void init(self, Display *display, Drawable drawable, unsigned int width, unsigned int height) noexcept:
        self.display = display
        self.drawable = drawable
        self.width = width
        self.height = height
        global drawable_counter
        drawable_counter += 1
        ximagedebug("%s xpixmap counter: %i", self, drawable_counter)

    def __repr__(self):
        return "DrawableWrapper(%#x, %i, %i)" % (self.drawable, self.width, self.height)

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def get_drawable(self) -> Drawable:
        return self.drawable

    def get_image(self, unsigned int x, unsigned int y, unsigned int width, unsigned int height):
        if not self.drawable:
            log.warn("%s.get_image%s", self, (x, y, width, height))
            return None
        ximagedebug("%s.get_image%s width=%i, height=%i", self, (x, y, width, height), self.width, self.height)
        if x >= self.width or y >= self.height:
            log("%s.get_image%s position outside image dimensions %ix%i", self, (x, y, width, height), self.width, self.height)
            return None
        # clamp size to image size:
        if x + width > self.width:
            width = self.width - x
        if y + height > self.height:
            height = self.height - y
        return get_image(self.display, self.drawable, x, y, width, height)

    def __dealloc__(self):
        self.do_cleanup()

    cdef void do_cleanup(self) noexcept:
        cdef drawable = self.drawable
        if drawable != 0:
            self.drawable = 0
            global drawable_counter
            drawable_counter -= 1

    def cleanup(self) -> None:
        ximagedebug("%s.cleanup()", self)
        self.do_cleanup()


cdef XImageWrapper get_image(Display * display, Drawable drawable, unsigned int x, unsigned int y, unsigned int width, unsigned int height):
    cdef XImage* ximage = XGetImage(display, drawable, x, y, width, height, AllPlanes, ZPixmap)
    #log.info("get_pixels(..) ximage==NULL : %s", ximage==NULL)
    if ximage==NULL:
        log("get_image(..) failed to get XImage for X11 drawable %#x", drawable)
        return None
    xi = XImageWrapper(x, y, width, height)
    xi.set_image(ximage)
    global ximage_counter
    ximagedebug("%s ximage counter: %i", xi, ximage_counter)
    return xi


cdef class XImageBindingsInstance(X11CoreBindingsInstance):

    def get_ximage(self, drawable, x, y, width, height):
        self.context_check("get_ximage")
        return get_image(self.display, drawable, x, y, width, height)

    def get_xwindow_pixmap_wrapper(self, xwindow):
        log("get_xwindow_pixmap_wrapper(%#x)", xwindow)
        return self.wrap_drawable(xwindow)

    def wrap_drawable(self, drawable):
        self.context_check("wrap_drawable")
        cdef Window root_window
        cdef int x, y
        cdef unsigned width, height, border, depth
        status = XGetGeometry(self.display, drawable, &root_window,
                              &x, &y, &width, &height, &border, &depth)
        if status == 0:
            log("failed to get dimensions for %#x", drawable)
            return None
        cdef DrawableWrapper pw = DrawableWrapper()
        pw.init(self.display, drawable, width, height)
        return pw


cdef XImageBindingsInstance singleton = None


def XImageBindings() -> XImageBindingsInstance:
    global singleton
    if singleton is None:
        singleton = XImageBindingsInstance()
    return singleton

