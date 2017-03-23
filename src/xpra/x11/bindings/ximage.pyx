# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import errno as pyerrno
from libc.stdint cimport uint64_t, uintptr_t
from xpra.buffers.membuf cimport memory_as_pybuffer, object_as_buffer
from xpra.os_util import monotonic_time

from xpra.log import Logger
xshmlog = Logger("x11", "bindings", "ximage", "xshm")
log = Logger("x11", "bindings", "ximage")
xshmdebug = Logger("x11", "bindings", "ximage", "xshm", "verbose")
ximagedebug = Logger("x11", "bindings", "ximage", "verbose")


cdef inline unsigned int roundup(unsigned int n, unsigned int m):
    return (n + m - 1) & ~(m - 1)

cdef inline unsigned char BYTESPERPIXEL(unsigned int depth):
    if depth>=24 and depth<=32:
        return 4
    elif depth==16:
        return 2
    elif depth==8:
        return 1
    #shouldn't happen!
    return roundup(depth, 8)//8

cdef inline unsigned int MIN(unsigned int a, unsigned int b):
    if a<=b:
        return a
    return b


###################################
# Headers, python magic
###################################
cdef extern from "string.h":
    void *memcpy(void * destination, void * source, size_t num) nogil

cdef extern from "stdlib.h":
    int posix_memalign(void **memptr, size_t alignment, size_t size)
    void free(void* mem)

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

include "constants.pxi"
ctypedef unsigned long CARD32
ctypedef unsigned short CARD16
ctypedef unsigned char CARD8
ctypedef CARD32 Colormap

cdef extern from "X11/X.h":
    unsigned long NoSymbol

cdef extern from "X11/Xatom.h":
    int XA_RGB_DEFAULT_MAP
    int XA_RGB_BEST_MAP

cdef extern from "X11/Xlib.h":
    ctypedef struct Display:
        pass
    # To make it easier to translate stuff in the X header files into
    # appropriate pyrex declarations, without having to untangle the typedefs
    # over and over again, here are some convenience typedefs.  (Yes, CARD32
    # really is 64 bits on 64-bit systems.  Why? Because CARD32 was defined
    # as a long.. and a long is now 64-bit, it was easier to do this than
    # to change a lot of existing X11 client code)
    ctypedef CARD32 XID

    ctypedef int Bool
    ctypedef int Status
    ctypedef CARD32 Atom
    ctypedef XID Drawable
    ctypedef XID Window
    ctypedef XID Pixmap

    ctypedef CARD32 VisualID

    ctypedef struct Visual:
        void    *ext_data       #XExtData *ext_data;     /* hook for extension to hang data */
        VisualID visualid
        int c_class
        unsigned long red_mask
        unsigned long green_mask
        unsigned long blue_mask
        int bits_per_rgb
        int map_entries

    ctypedef struct XVisualInfo:
        Visual *visual
        VisualID visualid
        int screen
        unsigned int depth
        int c_class
        unsigned long red_mask
        unsigned long green_mask
        unsigned long blue_mask
        int colormap_size
        int bits_per_rgb

    ctypedef struct XColor:
        unsigned long pixel                 # pixel value
        unsigned short red, green, blue     # rgb values
        char flags                          # DoRed, DoGreen, DoBlue

    int VisualIDMask
    #query colors flags:
    int DoRed
    int DoGreen
    int DoBlue
    void XQueryColors(Display *display, Colormap colormap, XColor defs_in_out[], int ncolors)
    VisualID XVisualIDFromVisual(Visual *visual)
    XVisualInfo *XGetVisualInfo(Display *display, long vinfo_mask, XVisualInfo *vinfo_template, int *nitems_return)

    int XFree(void * data)

    ctypedef struct XWindowAttributes:
        int x, y, width, height, depth, border_width
        Visual *visual
        Colormap colormap
        Bool map_installed
    Status XGetWindowAttributes(Display * display, Window w, XWindowAttributes * attributes)

    ctypedef char* XPointer

    ctypedef struct XImage:
        int width
        int height
        int xoffset             # number of pixels offset in X direction
        int format              # XYBitmap, XYPixmap, ZPixmap
        char *data              # pointer to image data
        int byte_order          # data byte order, LSBFirst, MSBFirst
        int bitmap_unit         # quant. of scanline 8, 16, 32
        int bitmap_bit_order    # LSBFirst, MSBFirst
        int bitmap_pad          # 8, 16, 32 either XY or ZPixmap
        int depth               # depth of image
        int bytes_per_line      # accelerator to next scanline
        int bits_per_pixel      # bits per pixel (ZPixmap)
        unsigned long red_mask  # bits in z arrangement
        unsigned long green_mask
        unsigned long blue_mask
        XPointer *obdata
        void *funcs

    unsigned long AllPlanes
    int XYPixmap
    int ZPixmap
    int MSBFirst
    int LSBFirst

    XImage *XGetImage(Display *display, Drawable d,
            int x, int y, unsigned int width, unsigned int  height,
            unsigned long plane_mask, int format)

    void XDestroyImage(XImage *ximage)

    Status XGetGeometry(Display *display, Drawable d, Window *root_return,
                        int *x_return, int *y_return, unsigned int  *width_return, unsigned int *height_return,
                        unsigned int *border_width_return, unsigned int *depth_return)

cdef extern from "X11/Xutil.h":
    pass

cdef extern from "X11/extensions/Xcomposite.h":
    Bool XCompositeQueryExtension(Display *, int *, int *)
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
                            unsigned int depth, int format, char *data,
                            XShmSegmentInfo *shminfo,
                            unsigned int width, unsigned int height)

    Bool XShmGetImage(Display *display, Drawable d, XImage *image,
                      int x, int y,
                      unsigned long plane_mask)

    int XShmGetEventBase(Display *display)


SBFirst = {
           MSBFirst : "MSBFirst",
           LSBFirst : "LSBFirst"
           }

cdef const char *RLE8 = "RLE8"
cdef const char *RGB565 = "RGB565"
cdef const char *BGR565 = "BGR565"
cdef const char *XRGB = "XRGB"
cdef const char *BGRX = "BGRX"
cdef const char *ARGB = "ARGB"
cdef const char *BGRA = "BGRA"
cdef const char *RGB = "RGB"
cdef const char *RGBA = "RGBA"
cdef const char *RGBX = "RGBX"
cdef const char *R210 = "R210"
cdef const char *r210 = "r210"

RGB_FORMATS = [XRGB, BGRX, ARGB, BGRA, RGB, RGBA, RGBX, R210, r210, RGB565, BGR565, RLE8]


cdef int ximage_counter = 0

cdef class XImageWrapper(object):
    """
        Presents X11 image pixels as in ImageWrapper
    """

    cdef XImage *image                              #@DuplicatedSignature
    cdef unsigned int x
    cdef unsigned int y
    cdef unsigned int width                                  #@DuplicatedSignature
    cdef unsigned int height                                 #@DuplicatedSignature
    cdef unsigned int depth                                  #@DuplicatedSignature
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

    def __cinit__(self, unsigned int x, unsigned int y, unsigned int width, unsigned int height, uintptr_t pixels=0, pixel_format="", unsigned int depth=24, unsigned int rowstride=0, int planes=0, unsigned int bytesperpixel=4, thread_safe=False, sub=False, palette=None):
        self.image = NULL
        self.pixels = NULL
        self.x = x
        self.y = y
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
        self.timestamp = int(monotonic_time()*1000)
        self.palette = palette

    cdef set_image(self, XImage* image):
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
            self.bytesperpixel = 4
            if image.byte_order==MSBFirst:
                self.pixel_format = R210
            else:
                self.pixel_format = r210
        else:
            raise Exception("invalid image depth: %i bpp" % self.depth)

    def __repr__(self):
        return "XImageWrapper(%s: %i, %i, %i, %i)" % (self.pixel_format, self.x, self.y, self.width, self.height)

    def get_geometry(self):
        return self.x, self.y, self.width, self.height, self.depth

    def get_x(self):
        return self.x

    def get_y(self):
        return self.y

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height

    def get_rowstride(self):
        return self.rowstride

    def get_palette(self):
        return self.palette

    def get_planes(self):
        return self.planes

    def get_depth(self):
        return self.depth

    def get_bytesperpixel(self):
        return self.bytesperpixel

    def get_size(self):
        return self.rowstride * self.height

    def get_pixel_format(self):
        return self.pixel_format

    def get_pixels(self):
        cdef void *pix_ptr = self.get_pixels_ptr()
        if pix_ptr==NULL:
            return None
        return memory_as_pybuffer(pix_ptr, self.get_size(), False)

    def get_sub_image(self, unsigned int x, unsigned int y, unsigned int w, unsigned int h):
        assert w>0 and h>0, "invalid sub-image size: %ix%i" % (w, h)
        if x+w>self.width:
            raise Exception("invalid sub-image width: %i+%i greater than image width %i" % (x, w, self.width))
        if y+h>self.height:
            raise Exception("invalid sub-image height: %i+%i greater than image height %i" % (y, h, self.height))
        cdef void *src = self.get_pixels_ptr()
        if src==NULL:
            raise Exception("source image does not have pixels!")
        cdef unsigned char Bpp = BYTESPERPIXEL(self.depth)
        cdef uintptr_t sub_ptr = (<uintptr_t> src) + x*Bpp + y*self.rowstride
        return XImageWrapper(self.x+x, self.y+y, w, h, sub_ptr, self.pixel_format, self.depth, self.rowstride, self.planes, self.bytesperpixel, True, True, self.palette)

    cdef void *get_pixels_ptr(self):
        if self.pixels!=NULL:
            return self.pixels
        cdef XImage *image = self.image
        if image==NULL:
            log.warn("get_pixels_ptr: image is NULL!")
            return NULL
        if image.data is NULL:
            log.warn("get_pixels_ptr: image.data is NULL!")
        return image.data

    def is_thread_safe(self):
        return self.thread_safe

    def get_timestamp(self):
        """ time in millis """
        return self.timestamp


    def set_palette(self, palette):
        self.palette = palette

    def set_timestamp(self, timestamp):
        self.timestamp = timestamp

    def set_rowstride(self, rowstride):
        self.rowstride = rowstride

    def set_pixel_format(self, pixel_format):
        assert pixel_format is not None and pixel_format in RGB_FORMATS, "invalid pixel format: %s" % pixel_format
        self.pixel_format = pixel_format

    def set_pixels(self, pixels):
        """ overrides the context of the image with the given pixels buffer """
        cdef const unsigned char * buf = NULL
        cdef Py_ssize_t buf_len = 0
        assert object_as_buffer(pixels, <const void**> &buf, &buf_len)==0
        if self.pixels!=NULL:
            if not self.sub:
                free(self.pixels)
            self.pixels = NULL
        #Note: we can't free the XImage, because it may
        #still be used somewhere else (see XShmWrapper)
        if posix_memalign(<void **> &self.pixels, 64, buf_len):
            raise Exception("posix_memalign failed!")
        assert self.pixels!=NULL
        if self.image==NULL:
            self.thread_safe = 1
            #we can now mark this object as thread safe
            #if we have already freed the XImage
            #which needs to be freed from the UI thread
            #but our new buffer is just a malloc buffer,
            #which is safe from any thread
        memcpy(self.pixels, buf, buf_len)


    def free(self):                                     #@DuplicatedSignature
        ximagedebug("%s.free()", self)
        self.free_image()
        self.free_pixels()

    cdef free_image(self):
        ximagedebug("%s.free_image() image=%#x", self, <uintptr_t> self.image)
        if self.image!=NULL:
            XDestroyImage(self.image)
            self.image = NULL
            global ximage_counter
            ximage_counter -= 1

    cdef free_pixels(self):
        ximagedebug("%s.free_pixels() pixels=%#x", self, <uintptr_t> self.pixels)
        if self.pixels!=NULL:
            if not self.sub:
                free(self.pixels)
            self.pixels = NULL

    def freeze(self):
        #we don't need to do anything here because the non-XShm version
        #already uses a copy of the pixels
        return False

    def may_restride(self):
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

    def restride(self, const unsigned int rowstride):
        #NOTE: this must be called from the UI thread!
        #start = monotonic_time()
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
            raise Exception("posix_memalign failed!")
        cdef unsigned int ry
        cdef void *to = new_buf
        cdef unsigned int oldstride = self.rowstride                     #using a local variable is faster
        #Note: we don't zero the buffer,
        #so if the newstride is bigger than oldstride, you get garbage..
        cdef unsigned int cpy_size
        if oldstride==rowstride:
            memcpy(to, img_buf, size)
        else:
            cpy_size = MIN(rowstride, oldstride)
            for ry in range(self.height):
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
        #    rowstride, self.pixel_format, 100-100*newsize/size, oldstride, size, rowstride, newsize, (monotonic_time()-start)*1000)
        return True


cdef class XShmWrapper(object):
    cdef Display *display                              #@DuplicatedSignature
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

    cdef init(self, Display *display, Window xwindow, Visual *visual, unsigned int width, unsigned int height, unsigned int depth):
        self.display = display
        self.window = xwindow
        self.visual = visual
        self.width = width
        self.height = height
        self.depth = depth

    def __repr__(self):
        return "XShmWrapper(%#x - %ix%i)" % (self.window, self.width, self.height)

    def setup(self):
        #returns:
        # (init_ok, may_retry_this_window, XShm_global_failure)
        cdef size_t size
        cdef Bool a
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
        size = self.image.bytes_per_line * (self.image.height + 1)
        self.shminfo.shmid = shmget(IPC_PRIVATE, size, IPC_CREAT | 0777)
        xshmdebug("XShmWrapper.setup() shmget(PRIVATE, %i bytes, %#x) shmid=%#x", size, IPC_CREAT | 0777, self.shminfo.shmid)
        if self.shminfo.shmid < 0:
            xshmlog.error("XShmWrapper.setup() shmget(PRIVATE, %i bytes, %#x) failed, bytes_per_line=%i, width=%i, height=%i", size, IPC_CREAT | 0777, self.image.bytes_per_line, self.width, self.height)
            self.cleanup()
            #only try again if we get EINVAL,
            #the other error codes probably mean this is never going to work..
            return False, errno==pyerrno.EINVAL, errno!=pyerrno.EINVAL
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
        a = XShmAttach(self.display, &self.shminfo)
        xshmdebug("XShmWrapper.setup() XShmAttach(..) %s", bool(a))
        if not a:
            xshmlog.error("XShmWrapper.setup() XShmAttach(..) failed!")
            self.cleanup()
            #we may try again with this window, or any other window:
            #(as this really shouldn't happen at all)
            return False, True, False
        return True, True, False

    def get_size(self):                                     #@DuplicatedSignature
        return self.width, self.height

    def get_image(self, Drawable drawable, unsigned int x, unsigned int y, unsigned int w, unsigned int h):
        assert self.image!=NULL, "cannot retrieve image wrapper: XImage is NULL!"
        if self.closed:
            return None
        if x>=self.width or y>=self.height:
            xshmlog("XShmWrapper.get_image%s position outside image dimensions %ix%i", (drawable, x, y, w, h), self.width, self.height)
            return None
        #clamp size to image size:
        if x+w>self.width:
            w = self.width-x
        if y+h>self.height:
            h = self.height-y
        if not self.got_image:
            if not XShmGetImage(self.display, drawable, self.image, 0, 0, 0xFFFFFFFF):
                xshmlog("XShmWrapper.get_image(%#x, %i, %i, %i, %i) XShmGetImage failed!", drawable, x, y, w, h)
                return None
            self.got_image = True
        self.ref_count += 1
        cdef XShmImageWrapper imageWrapper
        imageWrapper = XShmImageWrapper(x, y, w, h)
        imageWrapper.set_image(self.image)
        imageWrapper.set_free_callback(self.free_image_callback)
        if self.depth==8:
            imageWrapper.set_palette(self.read_palette())
        xshmdebug("XShmWrapper.get_image(%#x, %i, %i, %i, %i)=%s (ref_count=%i)", drawable, x, y, w, h, imageWrapper, self.ref_count)
        return imageWrapper

    def read_palette(self):
        #FIXME: we assume screen is zero
        cdef Colormap colormap = 0
        cdef XWindowAttributes attrs
        cdef VisualID visualid
        cdef XVisualInfo vinfo_template
        cdef XVisualInfo *vinfo
        cdef int count = 0
        if not XGetWindowAttributes(self.display, self.window, &attrs):
            return None
        colormap = attrs.colormap
        visualid = XVisualIDFromVisual(attrs.visual)
        vinfo_template.visualid = visualid
        vinfo = XGetVisualInfo(self.display, VisualIDMask, &vinfo_template, &count)
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
        XQueryColors(self.display, colormap, colors, size)
        palette = [(colors[i].red, colors[i].green, colors[i].blue) for i in range(256)]
        return palette

    def discard(self):
        #force next get_image call to get a new image from the server
        self.got_image = False

    def __dealloc__(self):                              #@DuplicatedSignature
        xshmdebug("XShmWrapper.__dealloc__() ref_count=%i", self.ref_count)
        self.cleanup()

    def cleanup(self):
        #ok, we want to free resources... problem is,
        #we may have handed out some XShmImageWrappers
        #and they will point to our Image XShm area.
        #so we have to wait until *they* are freed,
        #and rely on them telling us via the free_image_callback.
        xshmdebug("XShmWrapper.cleanup() ref_count=%i", self.ref_count)
        self.closed = True
        if self.ref_count==0:
            self.free()

    def free_image_callback(self):                               #@DuplicatedSignature
        self.ref_count -= 1
        xshmdebug("XShmWrapper.free_image_callback() closed=%s, new ref_count=%i", self.closed, self.ref_count)
        if self.closed and self.ref_count==0:
            self.free()

    cdef free(self):                                     #@DuplicatedSignature
        assert self.ref_count==0, "XShmWrapper %s cannot be freed: still has a ref count of %i" % (self, self.ref_count)
        assert self.closed, "XShmWrapper %s cannot be freed: it is not closed yet" % self
        has_shm = self.shminfo.shmaddr!=<char *> -1
        xshmdebug("XShmWrapper.free() has_shm=%s, image=%#x, shmid=%#x", has_shm, <uintptr_t> self.image, self.shminfo.shmid)
        if has_shm:
            XShmDetach(self.display, &self.shminfo)
        if self.image!=NULL:
            XDestroyImage(self.image)
            self.image = NULL
        if has_shm:
            shmctl(self.shminfo.shmid, IPC_RMID, NULL)
            shmdt(self.shminfo.shmaddr)
            self.shminfo.shmaddr = <char *> -1
            self.shminfo.shmid = -1


cdef class XShmImageWrapper(XImageWrapper):

    cdef object free_callback

    def __init__(self, *args):                      #@DuplicatedSignature
        self.free_callback = None

    def __repr__(self):                             #@DuplicatedSignature
        return "XShmImageWrapper(%s: %s, %s, %s, %s)" % (self.pixel_format, self.x, self.y, self.width, self.height)

    cdef void *get_pixels_ptr(self):                #@DuplicatedSignature
        if self.pixels!=NULL:
            xshmdebug("XShmImageWrapper.get_pixels_ptr()=%#x (pixels) %s", <uintptr_t> self.pixels, self)
            return self.pixels
        cdef XImage *image = self.image             #
        if image==NULL:
            xshmdebug.warn("Warning: XShm get_pixels_ptr XImage is NULL")
            return NULL
        assert self.height>0
        #calculate offset (assuming 4 bytes "pixelstride"):
        cdef unsigned char Bpp = BYTESPERPIXEL(self.depth)
        cdef void *ptr = image.data + (self.y * self.rowstride) + (Bpp * self.x)
        xshmdebug("XShmImageWrapper.get_pixels_ptr()=%#x %s", <uintptr_t> ptr, self)
        return ptr

    def freeze(self):                               #@DuplicatedSignature
        #we just force a restride, which will allocate a new pixel buffer:
        cdef newstride = roundup(self.width*len(self.pixel_format), 4)
        return self.restride(newstride)

    def free(self):                                 #@DuplicatedSignature
        #ensure we never try to XDestroyImage:
        self.image = NULL
        self.free_pixels()
        cb = self.free_callback
        if cb:
            self.free_callback = None
            cb()
        xshmdebug("XShmImageWrapper.free() done for %s, callback fired=%s", self, bool(cb))

    cdef set_free_callback(self, object callback):
        self.free_callback = callback


cdef int xpixmap_counter = 0

cdef class PixmapWrapper(object):
    cdef Display *display
    cdef Pixmap pixmap
    cdef unsigned int width                          #@DuplicatedSignature
    cdef unsigned int height                         #@DuplicatedSignature

    "Reference count an X Pixmap that needs explicit cleanup."
    cdef init(self, Display *display, Pixmap pixmap, unsigned int width, unsigned int height):     #@DuplicatedSignature
        self.display = display
        self.pixmap = pixmap
        self.width = width
        self.height = height
        global xpixmap_counter
        xpixmap_counter += 1
        ximagedebug("%s xpixmap counter: %i", self, xpixmap_counter)

    def __repr__(self):                     #@DuplicatedSignature
        return "PixmapWrapper(%#x, %i, %i)" % (self.pixmap, self.width, self.height)

    def get_width(self):                    #@DuplicatedSignature
        return self.width

    def get_height(self):                   #@DuplicatedSignature
        return self.height

    def get_pixmap(self):
        return self.pixmap

    def get_image(self, unsigned int x, unsigned int y, unsigned int width, unsigned int height):                #@DuplicatedSignature
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

    def __dealloc__(self):                  #@DuplicatedSignature
        self.do_cleanup()

    cdef do_cleanup(self):                  #@DuplicatedSignature
        if self.pixmap!=0:
            XFreePixmap(self.display, self.pixmap)
            self.pixmap = 0
            global xpixmap_counter
            xpixmap_counter -= 1

    def cleanup(self):                      #@DuplicatedSignature
        ximagedebug("%s.cleanup()", self)
        self.do_cleanup()



cdef get_image(Display * display, Drawable drawable, unsigned int x, unsigned int y, unsigned int width, unsigned int height):
    cdef XImage* ximage
    ximage = XGetImage(display, drawable, x, y, width, height, AllPlanes, ZPixmap)
    #log.info("get_pixels(..) ximage==NULL : %s", ximage==NULL)
    if ximage==NULL:
        log("get_image(..) failed to get XImage for X11 drawable %#x", drawable)
        return None
    xi = XImageWrapper(x, y, width, height)
    xi.set_image(ximage)
    global ximage_counter
    ximagedebug("%s ximage counter: %i", xi, ximage_counter)
    return xi


cdef xcomposite_name_window_pixmap(Display * xdisplay, Window xwindow):
    cdef Window root_window
    cdef int x, y
    cdef unsigned int width, height, border, depth
    cdef Status status
    cdef Pixmap xpixmap
    cdef PixmapWrapper pw
    xpixmap = XCompositeNameWindowPixmap(xdisplay, xwindow)
    if xpixmap==XNone:
        return None
    status = XGetGeometry(xdisplay, xpixmap, &root_window,
                        &x, &y, &width, &height, &border, &depth)
    if status==0:
        log("failed to get pixmap dimensions for %#x", xpixmap)
        XFreePixmap(xdisplay, xpixmap)
        return None
    pw = PixmapWrapper()
    pw.init(xdisplay, xpixmap, width, height)
    return pw

cdef window_pixmap_wrapper(Display *xdisplay, Window xwindow):
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

from core_bindings cimport _X11CoreBindings

cdef _XImageBindings singleton = None
def XImageBindings():
    global singleton
    if singleton is None:
        singleton = _XImageBindings()
    return singleton

cdef class _XImageBindings(_X11CoreBindings):
    cdef int has_xshm

    def __cinit__(self):
        self.has_xshm = XShmQueryExtension(self.display)
        log("XShmQueryExtension()=%s", bool(self.has_xshm))

    def has_XShm(self):
        return self.has_xshm

    def get_XShmWrapper(self, xwindow):
        cdef XWindowAttributes attrs
        if XGetWindowAttributes(self.display, xwindow, &attrs)==0:
            return None
        xshm = XShmWrapper()
        xshm.init(self.display, xwindow, attrs.visual, attrs.width, attrs.height, attrs.depth)
        return xshm

    def get_ximage(self, drawable, x, y, width, height):      #@DuplicatedSignature
        return get_image(self.display, drawable, x, y, width, height)

    def get_xcomposite_pixmap(self, xwindow):
        return xcomposite_name_window_pixmap(self.display, xwindow)

    def get_xwindow_pixmap_wrapper(self, xwindow):
        return window_pixmap_wrapper(self.display, xwindow)
