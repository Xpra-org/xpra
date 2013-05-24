# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


class ImageWrapper(object):

    def __init__(self, x, y, width, height, pixels, rgb_format, depth, rowstride):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.pixels = pixels
        self.rgb_format = rgb_format
        self.depth = depth
        self.rowstride = rowstride

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

    def get_rgb_format(self):
        return self.rgb_format

    def get_pixels(self):
        return self.pixels


    def set_rowstride(self, rowstride):
        self.rowstride = rowstride

    def set_rgb_format(self, rgb_format):
        self.rgb_format = rgb_format

    def set_pixels(self, pixels):
        self.pixels = pixels
