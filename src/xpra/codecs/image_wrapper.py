# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2013-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import memoryview_to_bytes, monotonic_time

def clone_plane(plane):
    if isinstance(plane, memoryview):
        return plane.tobytes()
    return plane[:]


class ImageWrapper(object):

    PACKED = 0
    _3_PLANES = 3
    _4_PLANES = 4
    PLANE_OPTIONS = (PACKED, _3_PLANES, _4_PLANES)
    PLANE_NAMES = {PACKED       : "PACKED",
                   _3_PLANES    : "3_PLANES",
                   _4_PLANES    : "4_PLANES"}

    def __init__(self, x, y, width, height, pixels, pixel_format, depth, rowstride, bytesperpixel=4, planes=PACKED, thread_safe=True, palette=None):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.pixels = pixels
        self.pixel_format = pixel_format
        self.depth = depth
        self.rowstride = rowstride
        self.bytesperpixel = bytesperpixel
        self.planes = planes
        self.thread_safe = thread_safe
        self.freed = False
        self.timestamp = int(monotonic_time()*1000)
        self.palette = palette

    def _cn(self):
        try:
            return type(self).__name__
        except:
            return type(self)

    def __repr__(self):
        return "%s(%s:%s:%s)" % (self._cn(), self.pixel_format, self.get_geometry(), ImageWrapper.PLANE_NAMES.get(self.planes))

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

    def get_depth(self):
        return self.depth

    def get_bytesperpixel(self):
        return self.bytesperpixel

    def get_size(self):
        return self.rowstride * self.height

    def get_pixel_format(self):
        return self.pixel_format

    def get_pixels(self):
        return self.pixels

    def get_planes(self):
        return self.planes

    def get_palette(self):
        return self.palette

    def is_thread_safe(self):
        """ if True, free() and clone_pixel_data() can be called from any thread,
            if False, free() and clone_pixel_data() must be called from the same thread.
            Used by XImageWrapper to ensure X11 images are freed from the UI thread.
        """
        return self.thread_safe

    def get_timestamp(self):
        """ time in millis """
        return self.timestamp


    def set_timestamp(self, timestamp):
        self.timestamp = timestamp

    def set_planes(self, planes):
        self.planes = planes

    def set_rowstride(self, rowstride):
        self.rowstride = rowstride

    def set_pixel_format(self, pixel_format):
        self.pixel_format = pixel_format

    def set_palette(self, palette):
        self.palette = palette

    def set_pixels(self, pixels):
        assert not self.freed
        self.pixels = pixels

    def allocate_buffer(self, buf_len, free_existing=1):
        assert not self.freed
        #only defined for XImage wrappers:
        return 0

    def may_restride(self, *args):
        return self.restride()

    def restride(self, *args):
        assert not self.freed
        #not supported by the generic image wrapper:
        return False

    def freeze(self):
        assert not self.freed
        #some wrappers (XShm) need to be told to stop updating the pixel buffer
        return False

    def clone_pixel_data(self):
        assert not self.freed
        pixels = self.pixels
        planes = self.planes
        assert pixels, "no pixel data to clone"
        if planes == 0:
            #no planes, simple buffer:
            self.pixels = clone_plane(pixels)
        else:
            assert planes>0
            self.pixels = [clone_plane(pixels[i]) for i in range(planes)]
        self.thread_safe = True
        if self.freed:
            #could be a race since this can run threaded
            self.free()

    def get_sub_image(self, x, y, w, h):
        #raise NotImplementedError("no sub-images for %s" % type(self))
        assert w>0 and h>0, "invalid sub-image size: %ix%i" % (w, h)
        if x+w>self.width:
            raise Exception("invalid sub-image width: %i+%i greater than image width %i" % (x, w, self.width))
        if y+h>self.height:
            raise Exception("invalid sub-image height: %i+%i greater than image height %i" % (y, h, self.height))
        assert self.planes==0, "cannot sub-divide planar images!"
        #copy to local variables:
        pixels = self.pixels
        oldstride = self.rowstride
        pos = y*oldstride + x*4
        newstride = w*4
        lines = []
        for _ in range(h):
            lines.append(memoryview_to_bytes(pixels[pos:pos+newstride]))
            pos += oldstride
        return ImageWrapper(self.x+x, self.y+y, w, h, b"".join(lines), self.pixel_format, self.depth, newstride, planes=self.planes, thread_safe=True, palette=self.palette)

    def __del__(self):
        #print("ImageWrapper.__del__() calling %s" % self.free)
        self.free()

    def free(self):
        #print("ImageWrapper.free()")
        if not self.freed:
            self.freed = True
            self.planes = None
            self.pixels = None
            self.pixel_format = None
