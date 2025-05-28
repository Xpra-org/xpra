# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic
from typing import List, Tuple, Dict

from xpra.x11.bindings.display_source import get_display_name   # @UnresolvedImport
from xpra.log import Logger


from xpra.x11.bindings.core import call_context_check  # @UnresolvedImport
from xpra.x11.bindings.core cimport X11CoreBindingsInstance
from xpra.x11.bindings.xlib cimport (
    XImage, Display, Pixmap,
    XColor, Visual, VisualID, XVisualInfo, VisualIDMask,
    Status, Window, Drawable, Bool,
    XFree, XWindowAttributes,
    MSBFirst, LSBFirst, ZPixmap,
    DoRed, DoGreen, DoBlue, AllPlanes,
    XGetVisualInfo,
)
from libc.stdlib cimport free
from libc.string cimport memcpy
from libc.stdint cimport uint64_t, uintptr_t

xshmlog = Logger("x11", "bindings", "ximage", "xshm")
log = Logger("x11", "bindings", "ximage")
xshmdebug = Logger("x11", "bindings", "ximage", "xshm", "verbose")
ximagedebug = Logger("x11", "bindings", "ximage", "verbose")


cdef inline unsigned int roundup(unsigned int n, unsigned int m) noexcept:
    return (n + m - 1) & ~(m - 1)


cdef inline unsigned char BYTESPERPIXEL(unsigned int depth) noexcept:
    if depth>=24 and depth<=32:
        return 4
    elif depth==16:
        return 2
    elif depth==8:
        return 1
    #shouldn't happen!
    return roundup(depth, 8)//8


cdef inline unsigned int MIN(unsigned int a, unsigned int b) noexcept:
    if a<=b:
        return a
    return b


###################################
# Headers, python magic
###################################
cdef extern from "Python.h":
    object PyMemoryView_FromMemory(char *mem, Py_ssize_t size, int flags)
    int PyObject_GetBuffer(object obj, Py_buffer *view, int flags)
    void PyBuffer_Release(Py_buffer *view)
    int PyBUF_ANY_CONTIGUOUS
    int PyBUF_READ
    int PyBUF_WRITE

cdef extern from "stdlib.h":
    int posix_memalign(void **memptr, size_t alignment, size_t size)

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

ctypedef unsigned long CARD32
ctypedef unsigned short CARD16
ctypedef CARD32 Colormap
DEF XNone = 0

cdef extern from "X11/X.h":
    unsigned long NoSymbol

cdef extern from "X11/Xatom.h":
    int XA_RGB_DEFAULT_MAP
    int XA_RGB_BEST_MAP

cdef extern from "X11/Xlib.h":
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

cdef extern from "X11/extensions/Xcomposite.h":
    Bool XCompositeQueryExtension(Display *, int * major, int * minor)
    Status XCompositeQueryVersion(Display *, int * major, int * minor)
    int XFreePixmap(Display *, Pixmap pixmap)
    Pixmap XCompositeNameWindowPixmap(Display *xdisplay, Window xwindow)

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

    cdef XImage *image
    cdef unsigned int x
    cdef unsigned int y
    cdef unsigned int target_x
    cdef unsigned int target_y
    cdef unsigned int width
    cdef unsigned int height
    cdef unsigned int depth
    cdef unsigned int rowstride
    cdef unsigned int planes
    cdef unsigned int bytesperpixel
    cdef unsigned char thread_safe
    cdef unsigned char sub
    cdef object pixel_format
    cdef void *pixels
    cdef object del_callback
    cdef uint64_t timestamp
    cdef object palette
    cdef unsigned char full_range

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

    def get_bytesperpixel(self):
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
        if posix_memalign(<void **> &self.pixels, 64, py_buf.len):
            PyBuffer_Release(&py_buf)
            raise RuntimeError("posix_memalign failed!")
        assert self.pixels!=NULL
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
        if posix_memalign(<void **> &new_buf, 64, (newsize+rowstride)):
            raise RuntimeError("posix_memalign failed!")
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
        #without any X11 image to free, this is now thread safe:
        if self.image==NULL:
            self.thread_safe = 1
        #log("restride(%s) %s pixels re-stride saving %i%% from %s (%s bytes) to %s (%s bytes) took %.1fms",
        #    rowstride, self.pixel_format, 100-100*newsize/size, oldstride, size, rowstride, newsize, (monotonic()-start)*1000)
        return True


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
            xshmlog.error("XShmWrapper.setup() XShmCreateImage(%ix%i-%i) failed!", self.width, self.height, self.depth)
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
            xshmlog.error("XShmWrapper.setup() shmget(PRIVATE, %i bytes, %#x) failed, bytes_per_line=%i, width=%i, height=%i", size, IPC_CREAT | 0777, self.image.bytes_per_line, self.width, self.height)
            self.cleanup()
            #only try again if we get EINVAL,
            #the other error codes probably mean this is never going to work..
            return False, errno==EINVAL, errno!=EINVAL
        # Attach:
        self.image.data = <char *> shmat(self.shminfo.shmid, NULL, 0)
        self.shminfo.shmaddr = self.image.data
        xshmdebug("XShmWrapper.setup() shmat(%s, NULL, 0) %s", self.shminfo.shmid, self.shminfo.shmaddr != <char *> -1)
        if self.shminfo.shmaddr == <char *> -1:
            xshmlog.error("XShmWrapper.setup() shmat(%s, NULL, 0) failed!", self.shminfo.shmid)
            self.cleanup()
            #we may try again with this window, or any other window:
            #(as this really shouldn't happen at all)
            return False, True, False

        # set as read/write, and attach to the display:
        self.shminfo.readOnly = False
        cdef Bool a = XShmAttach(self.display, &self.shminfo)
        xshmdebug("XShmWrapper.setup() XShmAttach(..) %s", bool(a))
        if not a:
            xshmlog.error("XShmWrapper.setup() XShmAttach(..) failed!")
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
            xshmlog("XShmWrapper.get_image%s invalid position + dimensions", (drawable, x, y, w, h))
            return None
        if x<0:
            w += x
            x = 0
        elif x>=maxw:
            xshmlog("XShmWrapper.get_image%s x-value is outside image dimensions %ix%i", (drawable, x, y, w, h), self.width, self.height)
            return None
        if y<0:
            h += y
            y = 0
        elif y>=maxh:
            xshmlog("XShmWrapper.get_image%s y-value is outside image dimensions %ix%i", (drawable, x, y, w, h), self.width, self.height)
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
                xshmlog("XShmWrapper.get_image(%#x, %i, %i, %i, %i) XShmGetImage failed!", drawable, x, y, w, h)
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


cdef int xpixmap_counter = 0


cdef class PixmapWrapper:
    cdef Display *display
    cdef Pixmap pixmap
    cdef unsigned int width
    cdef unsigned int height

    "Reference count an X Pixmap that needs explicit cleanup."
    cdef void init(self, Display *display, Pixmap pixmap, unsigned int width, unsigned int height):
        self.display = display
        self.pixmap = pixmap
        self.width = width
        self.height = height
        global xpixmap_counter
        xpixmap_counter += 1
        ximagedebug("%s xpixmap counter: %i", self, xpixmap_counter)

    def __repr__(self):
        return "PixmapWrapper(%#x, %i, %i)" % (self.pixmap, self.width, self.height)

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def get_pixmap(self) -> Pixmap:
        return self.pixmap

    def get_image(self, unsigned int x, unsigned int y, unsigned int width, unsigned int height):
        if not self.pixmap:
            log.warn("%s.get_image%s", self, (x, y, width, height))
            return  None
        ximagedebug("%s.get_image%s width=%i, height=%i", self, (x, y, width, height), self.width, self.height)
        if x>=self.width or y>=self.height:
            log("%s.get_image%s position outside image dimensions %ix%i", self, (x, y, width, height), self.width, self.height)
            return None
        #clamp size to image size:
        if x+width>self.width:
            width = self.width-x
        if y+height>self.height:
            height = self.height-y
        return get_image(self.display, self.pixmap, x, y, width, height)

    def __dealloc__(self):
        self.do_cleanup()

    cdef void do_cleanup(self):
        if self.pixmap!=0:
            XFreePixmap(self.display, self.pixmap)
            self.pixmap = 0
            global xpixmap_counter
            xpixmap_counter -= 1

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


cdef object xcomposite_name_window_pixmap(Display * xdisplay, Window xwindow):
    cdef Window root_window
    cdef int x, y
    cdef unsigned int width, height, border, depth
    cdef Pixmap xpixmap = XCompositeNameWindowPixmap(xdisplay, xwindow)
    if xpixmap==XNone:
        return None
    cdef Status status = XGetGeometry(xdisplay, xpixmap, &root_window,
                        &x, &y, &width, &height, &border, &depth)
    if status==0:
        log("failed to get pixmap dimensions for %#x", xpixmap)
        XFreePixmap(xdisplay, xpixmap)
        return None
    cdef PixmapWrapper pw = PixmapWrapper()
    pw.init(xdisplay, xpixmap, width, height)
    return pw


cdef object window_pixmap_wrapper(Display *xdisplay, Window xwindow):
    cdef Window root_window
    cdef int x, y
    cdef unsigned width, height, border, depth
    status = XGetGeometry(xdisplay, xwindow, &root_window,
                        &x, &y, &width, &height, &border, &depth)
    if status==0:
        log("failed to get window dimensions for %#x", xwindow)
        return None
    cdef PixmapWrapper pw = PixmapWrapper()
    pw.init(xdisplay, xwindow, width, height)
    return pw


cdef class XImageBindingsInstance(X11CoreBindingsInstance):
    cdef int has_xshm

    def __cinit__(self):
        self.has_xshm = XShmQueryExtension(self.display)
        dn = get_display_name()
        xshmlog("XShmQueryExtension()=%s on display {dn!r}", bool(self.has_xshm))
        if not self.has_xshm:
            xshmlog.warn(f"Warning: no XShm support on display {dn!r}")

    def has_XShm(self) -> bool:
        return bool(self.has_xshm)

    def get_XShmWrapper(self, xwindow):
        self.context_check("get_XShmWrapper")
        cdef XWindowAttributes attrs
        if XGetWindowAttributes(self.display, xwindow, &attrs)==0:
            return None
        xshm = XShmWrapper()
        xshm.init(self.display, xwindow, attrs.visual, attrs.width, attrs.height, attrs.depth)
        return xshm

    def get_ximage(self, drawable, x, y, width, height):
        self.context_check("get_ximage")
        return get_image(self.display, drawable, x, y, width, height)

    def get_xcomposite_pixmap(self, xwindow):
        self.context_check("get_xcomposite_pixmap")
        return xcomposite_name_window_pixmap(self.display, xwindow)

    def get_xwindow_pixmap_wrapper(self, xwindow):
        self.context_check("get_xwindow_pixmap_wrapper")
        return window_pixmap_wrapper(self.display, xwindow)


cdef XImageBindingsInstance singleton = None


def XImageBindings() -> XImageBindingsInstance:
    global singleton
    if singleton is None:
        singleton = XImageBindingsInstance()
    return singleton

