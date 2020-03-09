# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2013-2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util import roundup
from xpra.os_util import memoryview_to_bytes, monotonic_time

def clone_plane(plane):
    if isinstance(plane, memoryview):
        return plane.tobytes()
    return plane[:]


class ImageWrapper:

    PACKED = 0
    PLANAR_3 = 3
    PLANAR_4 = 4
    PLANE_OPTIONS = (PACKED, PLANAR_3, PLANAR_4)
    PLANE_NAMES = {
        PACKED      : "PACKED",
        PLANAR_3    : "3_PLANES",
        PLANAR_4    : "4_PLANES",
        }

    def __init__(self, x : int, y : int, width : int, height : int, pixels, pixel_format, depth : int, rowstride : int,
                 bytesperpixel : int=4, planes : int=PACKED, thread_safe : bool=True, palette=None):
        self.x = x
        self.y = y
        self.target_x = x
        self.target_y = y
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
        assert x>=0 and y>=0 and width>0 and height>0

    def _cn(self):
        try:
            return type(self).__name__
        except AttributeError:  # pragma: no cover
            return type(self)

    def __repr__(self):
        return "%s(%s:%s:%s)" % (self._cn(), self.pixel_format, self.get_geometry(),
                                 ImageWrapper.PLANE_NAMES.get(self.planes))

    def get_geometry(self):
        return self.x, self.y, self.width, self.height, self.depth

    def get_x(self) -> int:
        return self.x

    def get_y(self) -> int:
        return self.y

    def get_target_x(self) -> int:
        return self.target_x

    def get_target_y(self) -> int:
        return self.target_y

    def set_target_x(self, target_x : int):
        self.target_x = target_x

    def set_target_y(self, target_y : int):
        self.target_y = target_y

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def get_rowstride(self) -> int:
        return self.rowstride

    def get_depth(self) -> int:
        return self.depth

    def get_bytesperpixel(self) -> int:
        return self.bytesperpixel

    def get_size(self) -> int:
        return self.rowstride * self.height

    def get_pixel_format(self):
        return self.pixel_format

    def get_pixels(self):
        return self.pixels

    def get_planes(self) -> int:
        return self.planes

    def get_palette(self):
        return self.palette

    def get_gpu_buffer(self):
        return None

    def has_pixels(self) -> bool:
        return bool(self.pixels)

    def is_thread_safe(self) -> bool:
        """ if True, free() and clone_pixel_data() can be called from any thread,
            if False, free() and clone_pixel_data() must be called from the same thread.
            Used by XImageWrapper to ensure X11 images are freed from the UI thread.
        """
        return self.thread_safe

    def get_timestamp(self) -> int:
        """ time in millis """
        return self.timestamp


    def set_timestamp(self, timestamp : int):
        self.timestamp = timestamp

    def set_planes(self, planes : int):
        self.planes = planes

    def set_rowstride(self, rowstride : int):
        self.rowstride = rowstride

    def set_pixel_format(self, pixel_format):
        self.pixel_format = pixel_format

    def set_palette(self, palette):
        self.palette = palette

    def set_pixels(self, pixels):
        assert not self.freed
        self.pixels = pixels

    def allocate_buffer(self, _buf_len, _free_existing=1):
        assert not self.freed
        #only defined for XImage wrappers:
        return 0

    def may_restride(self) -> bool:
        newstride = roundup(self.width*self.bytesperpixel, 4)
        if self.rowstride>newstride:
            return self.restride(newstride)
        return False

    def restride(self, rowstride : int) -> bool:
        assert not self.freed
        if self.planes>0:
            #not supported yet for planar images
            return False
        pixels = self.pixels
        assert pixels, "no pixel data to restride"
        oldstride = self.rowstride
        pos = 0
        lines = []
        for _ in range(self.height):
            lines.append(memoryview_to_bytes(pixels[pos:pos+rowstride]))
            pos += oldstride
        if self.height>0 and oldstride<rowstride:
            #the last few lines may need padding if the new rowstride is bigger
            #(usually just the last line)
            #we do this here to avoid slowing down the main loop above
            #as this should be a rarer case
            for h in range(self.height):
                i = -(1+h)
                line = lines[i]
                if len(line)<rowstride:
                    lines[i] = line + b"\0"*(rowstride-len(line))
                else:
                    break
        self.rowstride = rowstride
        self.pixels = b"".join(lines)
        return True

    def freeze(self) -> bool:
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
        if self.freed:  # pragma: no cover
            #could be a race since this can run threaded
            self.free()

    def get_sub_image(self, x : int, y : int, w : int, h : int):
        #raise NotImplementedError("no sub-images for %s" % type(self))
        assert w>0 and h>0, "invalid sub-image size: %ix%i" % (w, h)
        if x+w>self.width:
            raise Exception("invalid sub-image width: %i+%i greater than image width %i" % (x, w, self.width))
        if y+h>self.height:
            raise Exception("invalid sub-image height: %i+%i greater than image height %i" % (y, h, self.height))
        assert self.planes==0, "cannot sub-divide planar images!"
        if x==0 and y==0 and w==self.width and h==self.height:
            #same dimensions, use the same wrapper
            return self
        #copy to local variables:
        pixels = self.pixels
        oldstride = self.rowstride
        pos = y*oldstride + x*self.bytesperpixel
        newstride = w*self.bytesperpixel
        lines = []
        for _ in range(h):
            lines.append(memoryview_to_bytes(pixels[pos:pos+newstride]))
            pos += oldstride
        image = ImageWrapper(self.x+x, self.y+y, w, h, b"".join(lines), self.pixel_format, self.depth, newstride,
                            planes=self.planes, thread_safe=True, palette=self.palette)
        image.set_target_x(self.target_x+x)
        image.set_target_y(self.target_y+y)
        return image

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
