# -*- coding: utf-8 -*-
"""
Copyright (c) 2011, Daniele Esposti <expo@expobrain.net>
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
    * Redistributions of source code must retain the above copyright
      notice, this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above copyright
      notice, this list of conditions and the following disclaimer in the
      documentation and/or other materials provided with the distribution.
    * The name of the contributors may be used to endorse or promote products
      derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY
DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""


class BitmapHandler(object):
    """
    Holds decode WebP image data and extra informations
    """
    RGB = 0
    RGBA = 1
    BGR = 2
    BGRA = 3
    YUV = 4

    FORMATS = (RGB, RGBA, BGR, BGRA, YUV)

    def __init__(self, bitmap, fmt, width, height, stride,
                 u_bitmap=None, v_bitmap=None, uv_stride= -1):
        """
        Constructor accepts the decode image data as a bitmap and its
        width/height.

        Passing a null image data, and invalid format or a non
        positive integer for width/height creates an instance to an invalid
        WebP image.

        If the image is in YUV format the bitmap parameter will be the Y(luma)
        component and the U/V chrominance component bitmap must be passed else
        the image will be invalid. The Y bitmap stride and the UV bitmap stride
        must be passed as well.

        :param bitmap: The image bitmap
        :param fmt: The image format
        :param width: The image width
        :param height: The mage height
        :param u_bitmap: The U chrominance component bitmap
        :param v_bitmap: The V chrominance component bitmap
        :param stride: The Y bitmap stride
        :param uv_stride: The UV stride

        :type bitmap: bytearray
        :type fmt: M{WebPImage.FORMATS}
        :type width: int
        :type height: int
        :type u_bitmap: bytearray
        :type v_bitmap: bytearray
        :type stride: int
        :type uv_stride: int
        """
        self.bitmap = bitmap
        self.u_bitmap = u_bitmap
        self.v_bitmap = v_bitmap
        self.stride = stride
        self.uv_stride = uv_stride
        self.format = fmt
        self.width = width
        self.height = height

        # Check if bitmap handler is valid
        is_valid = (isinstance(bitmap, bytearray)
                    and fmt in self.FORMATS
                    and width > -1
                    and height > -1)

        # Additional setups for YUV image
        if is_valid and fmt == self.YUV:
            # Check if YUV image is valid
            is_valid = (isinstance(u_bitmap, bytearray)
                        and isinstance(v_bitmap, bytearray)
                        and stride > -1
                        and uv_stride > -1)

        # Set valid flag
        self.is_valid = is_valid


class WebPHandlerError(IOError):
    pass


class WebPHandler(object):
    """
    Contains data relative to an WebP encoded image and allow loading and
    saving .webp files.

    The code is base on the documentation at
    http://code.google.com/speed/webp/docs/riff_container.html

    Public properties:

    * data        The WebP encoded image data
    * width       The image's width, -1 if the image s not valid
    * height      The image's height, -1 if the image s not valid
    * is_valid    True if the image's data is valid else False
    """

    @staticmethod
    def from_file(filename):
        """
        Load a .webp file and return the WebP handler

        :param filename: The file's name to be loaded
        :type filename: string
        :rtype: WebPHandler
        """
        from xpra.codecs.webm import decode

        data = file(filename, "rb").read()
        width, height = decode.GetInfo(data)

        return WebPHandler(bytearray(data), width, height)

    def __init__(self, data=None, width= -1, height= -1):
        """
        Constructor accepts the data, width and height of the WebP encoded
        image

        :param source: The image encoded data
        :param width: The image's width
        :param height: The image's height

        :type data: bytearray
        :type width: int
        :type height: int
        """
        # Public attributes
        self.data = data
        self.width = width
        self.height = height

    @property
    def is_valid(self):
        """
        Returns True if the current image is valid

        :rtype: bool
        """
        return self.data != None and (self.width > -1 and self.height > -1)
