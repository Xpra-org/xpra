# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic
from typing import List, Tuple

from xpra.x11.bindings.display_source import get_display_name   # @UnresolvedImport
from xpra.x11.bindings.core import call_context_check  # @UnresolvedImport
from xpra.x11.bindings.core cimport X11CoreBindingsInstance, import_check
from xpra.x11.bindings.ximage cimport XImageWrapper, roundup, BYTESPERPIXEL
from xpra.x11.bindings.xlib cimport (
    XImage, Display, Pixmap,
    XColor, Visual, VisualID, XVisualInfo, VisualIDMask,
    Status, Window, Drawable, Bool,
    XFree, XWindowAttributes,
    ZPixmap,
    DoRed, DoGreen, DoBlue,
    XGetVisualInfo,
)
from libc.stdint cimport uintptr_t

from xpra.log import Logger

import_check("shm")

log = Logger("x11", "bindings", "ximage", "xshm")
xshmdebug = Logger("x11", "bindings", "ximage", "xshm", "verbose")


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


ctypedef unsigned long CARD32
ctypedef CARD32 Colormap
DEF XNone = 0


cdef extern from "X11/Xlib.h":
    int XFreePixmap(Display *, Pixmap pixmap)

    void XQueryColors(Display *display, Colormap colormap, XColor defs_in_out[], int ncolors)
    VisualID XVisualIDFromVisual(Visual *visual)

    Status XGetWindowAttributes(Display * display, Window w, XWindowAttributes * attributes)

    void XDestroyImage(XImage *ximage)


cdef extern from "X11/Xutil.h":
    pass


cdef extern from "X11/extensions/XShm.h":
    unsigned int ShmCompletion
    ctypedef struct ShmSeg:
        pass
    ctypedef struct XShmSegmentInfo:
        ShmSeg shmseg   # resource id
        int shmid       # kernel id
        char *shmaddr   # address in client
        Bool readOnly   # how the server should attach it

    Bool XShmQueryExtension(Display *display)
    Bool XShmQueryVersion(Display *display, int *major, int *minor, Bool *pixmaps)

    Bool XShmAttach(Display *display, XShmSegmentInfo *shminfo)
    Bool XShmDetach(Display *display, XShmSegmentInfo *shminfo)

    XImage *XShmCreateImage(Display *display, Visual *visual,
                            unsigned int depth, int fmt, char *data,
                            XShmSegmentInfo *shminfo,
                            unsigned int width, unsigned int height)

    Bool XShmGetImage(Display *display, Drawable d, XImage *image,
                      int x, int y,
                      unsigned long plane_mask)

    int XShmGetEventBase(Display *display)


cdef class XShmWrapper:
    cdef Display *display
    cdef Visual *visual
    cdef Window window
    cdef unsigned int width
    cdef unsigned int height
    cdef unsigned int depth
    cdef XShmSegmentInfo shminfo
    cdef XImage *image
    cdef unsigned int ref_count
    cdef Bool got_image
    cdef Bool closed

    cdef void init(self, Display *display, Window xwindow, Visual *visual, unsigned int width, unsigned int height, unsigned int depth):
        self.display = display
        self.window = xwindow
        self.visual = visual
        self.width = width
        self.height = height
        self.depth = depth

    def __repr__(self):
        return "XShmWrapper(%#x - %ix%i)" % (self.window, self.width, self.height)

    def setup(self) -> Tuple[bool, bool, bool]:
        #returns:
        # (init_ok, may_retry_this_window, XShm_global_failure)
        self.ref_count = 0
        self.closed = False
        self.shminfo.shmaddr = <char *> -1

        self.image = XShmCreateImage(self.display, self.visual, self.depth,
                          ZPixmap, NULL, &self.shminfo,
                          self.width, self.height)
        xshmdebug("XShmWrapper.setup() XShmCreateImage(%ix%i-%i) %s", self.width, self.height, self.depth, self.image!=NULL)
        if self.image==NULL:
            log.error("XShmWrapper.setup() XShmCreateImage(%ix%i-%i) failed!", self.width, self.height, self.depth)
            self.cleanup()
            #if we cannot create an XShm XImage, we may try again
            #(it could be dimensions are too big?)
            return False, True, False
        # Get the shared memory:
        # (include an extra line to ensure we can read rowstride at a time,
        #  even on the last line, without reading past the end of the buffer)
        cdef size_t size = self.image.bytes_per_line * (self.image.height + 1)
        self.shminfo.shmid = shmget(IPC_PRIVATE, size, IPC_CREAT | 0o777)
        xshmdebug("XShmWrapper.setup() shmget(PRIVATE, %i bytes, %#x) shmid=%#x", size, IPC_CREAT | 0777, self.shminfo.shmid)
        if self.shminfo.shmid < 0:
            log.error("XShmWrapper.setup() shmget(PRIVATE, %i bytes, %#x) failed, bytes_per_line=%i, width=%i, height=%i", size, IPC_CREAT | 0777, self.image.bytes_per_line, self.width, self.height)
            self.cleanup()
            return False, False, False
        # Attach:
        self.image.data = <char *> shmat(self.shminfo.shmid, NULL, 0)
        self.shminfo.shmaddr = self.image.data
        xshmdebug("XShmWrapper.setup() shmat(%s, NULL, 0) %s", self.shminfo.shmid, self.shminfo.shmaddr != <char *> -1)
        if self.shminfo.shmaddr == <char *> -1:
            log.error("XShmWrapper.setup() shmat(%s, NULL, 0) failed!", self.shminfo.shmid)
            self.cleanup()
            #we may try again with this window, or any other window:
            #(as this really shouldn't happen at all)
            return False, True, False

        # set as read/write, and attach to the display:
        self.shminfo.readOnly = False
        cdef Bool a = XShmAttach(self.display, &self.shminfo)
        xshmdebug("XShmWrapper.setup() XShmAttach(..) %s", bool(a))
        if not a:
            log.error("XShmWrapper.setup() XShmAttach(..) failed!")
            self.cleanup()
            #we may try again with this window, or any other window:
            #(as this really shouldn't happen at all)
            return False, True, False
        return True, True, False

    def get_size(self) -> Tuple[int, int]:
        return self.width, self.height

    def get_image(self, Drawable drawable, int x, int y, int w, int h):
        assert self.image!=NULL, "cannot retrieve image wrapper: XImage is NULL!"
        if self.closed:
            return None
        cdef int maxw = self.width
        cdef int maxh = self.height
        if w+x<=0 or h+y<=0:
            log("XShmWrapper.get_image%s invalid position + dimensions", (drawable, x, y, w, h))
            return None
        if x<0:
            w += x
            x = 0
        elif x>=maxw:
            log("XShmWrapper.get_image%s x-value is outside image dimensions %ix%i", (drawable, x, y, w, h), self.width, self.height)
            return None
        if y<0:
            h += y
            y = 0
        elif y>=maxh:
            log("XShmWrapper.get_image%s y-value is outside image dimensions %ix%i", (drawable, x, y, w, h), self.width, self.height)
            return None
        #clamp size to image size:
        if x+w>maxw:
            w = maxw-x
            assert w>0
        if y+h>maxh:
            h = maxh-y
            assert h>0
        if not self.got_image:
            if not XShmGetImage(self.display, drawable, self.image, 0, 0, 0xFFFFFFFF):
                log("XShmWrapper.get_image(%#x, %i, %i, %i, %i) XShmGetImage failed!", drawable, x, y, w, h)
                return None
            self.got_image = True
        self.ref_count += 1
        cdef XShmImageWrapper imageWrapper = XShmImageWrapper(x, y, w, h)
        imageWrapper.set_image(self.image)
        imageWrapper.set_free_callback(self.free_image_callback)
        if self.depth==8:
            imageWrapper.set_palette(self.read_palette())
        xshmdebug("XShmWrapper.get_image(%#x, %i, %i, %i, %i)=%s (ref_count=%i)", drawable, x, y, w, h, imageWrapper, self.ref_count)
        return imageWrapper

    def read_palette(self) -> List[Tuple[int, int, int]]:
        cdef XWindowAttributes attrs
        cdef XVisualInfo vinfo_template
        cdef int count
        if not XGetWindowAttributes(self.display, self.window, &attrs):
            return None
        cdef Colormap colormap = attrs.colormap
        cdef VisualID visualid = XVisualIDFromVisual(attrs.visual)
        vinfo_template.visualid = visualid
        cdef XVisualInfo *vinfo = XGetVisualInfo(self.display, VisualIDMask, &vinfo_template, &count)
        if count!=1 or vinfo==NULL:
            log.error("Error: visual %i not found, count=%i, vinfo=%#x", visualid, count, <uintptr_t> vinfo)
            if vinfo:
                XFree(vinfo)
            return None
        log("visual: depth=%i, red mask=%#10x, green mask=%#10x, blue mask=%#10x, size=%i, bits per rgb=%i", vinfo.depth, vinfo.red_mask, vinfo.green_mask, vinfo.blue_mask, vinfo.colormap_size, vinfo.bits_per_rgb)
        cdef unsigned int size = vinfo.colormap_size
        XFree(vinfo)
        if size>256:
            log.error("invalid colormap size: %i", size)
            return None
        cdef XColor[256] colors
        cdef unsigned int i
        for i in range(size):
            colors[i].flags = DoRed | DoGreen | DoBlue
            colors[i].pixel = i
        for i in range(size, 256):
            colors[i].flags = 0
            colors[i].pixel = 0
        XQueryColors(self.display, colormap, colors, size)
        palette = [(colors[i].red, colors[i].green, colors[i].blue) for i in range(256)]
        return palette

    def discard(self) -> None:
        #force next get_image call to get a new image from the server
        self.got_image = False

    def __dealloc__(self):
        xshmdebug("XShmWrapper.__dealloc__() ref_count=%i", self.ref_count)
        self.cleanup()

    def cleanup(self) -> None:
        #ok, we want to free resources... problem is,
        #we may have handed out some XShmImageWrappers
        #and they will point to our Image XShm area.
        #so we have to wait until *they* are freed,
        #and rely on them telling us via the free_image_callback.
        xshmdebug("XShmWrapper.cleanup() ref_count=%i", self.ref_count)
        self.closed = True
        if self.ref_count==0:
            self.free()

    def free_image_callback(self) -> None:
        self.ref_count -= 1
        xshmdebug("XShmWrapper.free_image_callback() closed=%s, new ref_count=%i", self.closed, self.ref_count)
        if self.closed and self.ref_count==0:
            self.free()

    cdef void free(self):
        assert self.ref_count==0, "XShmWrapper %s cannot be freed: still has a ref count of %i" % (self, self.ref_count)
        assert self.closed, "XShmWrapper %s cannot be freed: it is not closed yet" % self
        has_shm = self.shminfo.shmaddr!=<char *> -1
        xshmdebug("XShmWrapper.free() has_shm=%s, image=%#x, shmid=%#x", has_shm, <uintptr_t> self.image, self.shminfo.shmid)
        if has_shm:
            XShmDetach(self.display, &self.shminfo)
        has_image = self.image!=NULL
        if has_image:
            XDestroyImage(self.image)
            self.image = NULL
        if has_shm:
            shmctl(self.shminfo.shmid, IPC_RMID, NULL)
            shmdt(self.shminfo.shmaddr)
            self.shminfo.shmaddr = <char *> -1
            self.shminfo.shmid = -1
        if has_shm or has_image:
            call_context_check("XShmWrapper.free")


cdef class XShmImageWrapper(XImageWrapper):

    cdef object free_callback

    def __init__(self, *args):
        self.free_callback = None

    def __repr__(self):
        return "XShmImageWrapper(%s: %s, %s, %s, %s)" % (self.pixel_format, self.x, self.y, self.width, self.height)

    cdef void *get_pixels_ptr(self):
        if self.pixels!=NULL:
            xshmdebug("XShmImageWrapper.get_pixels_ptr()=%#x (pixels) %s", <uintptr_t> self.pixels, self)
            return self.pixels
        cdef XImage *image = self.image             #
        if image==NULL:
            xshmdebug("XShm get_pixels_ptr XImage is NULL")
            return NULL
        assert self.height>0
        #calculate offset (assuming 4 bytes "pixelstride"):
        cdef unsigned char Bpp = BYTESPERPIXEL(self.depth)
        cdef void *ptr = image.data + (self.y * self.rowstride) + (Bpp * self.x)
        xshmdebug("XShmImageWrapper.get_pixels_ptr()=%#x %s", <uintptr_t> ptr, self)
        return ptr

    def freeze(self) -> bool:
        #we just force a restride, which will allocate a new pixel buffer:
        cdef unsigned int newstride = roundup(self.width*len(self.pixel_format), 4)
        self.timestamp = int(monotonic() * 1000)
        return self.restride(newstride)

    def free(self) -> None:
        #ensure we never try to XDestroyImage:
        self.image = NULL
        self.free_pixels()
        cb = self.free_callback
        if cb:
            self.free_callback = None
            cb()
        xshmdebug("XShmImageWrapper.free() done for %s, callback fired=%s", self, bool(cb))

    cdef void set_free_callback(self, object callback):
        self.free_callback = callback



cdef class XShmBindingsInstance(X11CoreBindingsInstance):
    cdef int has_xshm

    def __cinit__(self):
        self.has_xshm = XShmQueryExtension(self.display)
        dn = get_display_name()
        log(f"XShmQueryExtension()=%s on display {dn!r}", bool(self.has_xshm))
        if not self.has_xshm:
            log.warn(f"Warning: no XShm support on display {dn!r}")

    def has_XShm(self) -> bool:
        return bool(self.has_xshm)

    def get_XShmWrapper(self, Window xwindow):
        self.context_check("get_XShmWrapper")
        cdef XWindowAttributes attrs
        if XGetWindowAttributes(self.display, xwindow, &attrs)==0:
            return None
        xshm = XShmWrapper()
        xshm.init(self.display, xwindow, attrs.visual, attrs.width, attrs.height, attrs.depth)
        return xshm


cdef XShmBindingsInstance singleton = None


def XShmBindings() -> XShmBindingsInstance:
    global singleton
    if singleton is None:
        singleton = XShmBindingsInstance()
    return singleton

