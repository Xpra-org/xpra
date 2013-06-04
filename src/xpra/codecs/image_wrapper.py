# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


class ImageWrapper(object):

    def __init__(self, x, y, width, height, pixels, pixel_format, depth, rowstride, planes=1):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.pixels = pixels
        self.pixel_format = pixel_format
        self.depth = depth
        self.rowstride = rowstride
        self.planes = planes
        self.freed = False

    def __str__(self):
        return "%s(%s:%s)" % (type(self), self.pixel_format, self.get_geometry())

    def get_geometry(self):
        return self.x, self.y, self.width, self.height, self.depth

    def get_x(self):
        return self.x

    def get_y(self):
        return self.x

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height

    def get_rowstride(self):
        return self.rowstride

    def get_depth(self):
        return self.depth

    def get_size(self):
        return self.rowstride * self.height

    def get_pixel_format(self):
        return self.pixel_format

    def get_pixels(self):
        return self.pixels

    def get_planes(self):
        return self.planes


    def set_planes(self, planes):
        self.planes = planes

    def set_rowstride(self, rowstride):
        self.rowstride = rowstride

    def set_pixel_format(self, pixel_format):
        self.pixel_format = pixel_format

    def set_pixels(self, pixels):
        self.pixels = pixels

    def clone_pixel_data(self):
        if not self.freed:
            if self.planes == 0:
                #no planes, simple buffer:
                assert self.pixels, "no pixels!"
                self.pixels = self.pixels[:]
            else:
                assert self.planes>0
                for i in range(self.planes):
                    self.pixels[i] = self.pixels[i][:]

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
