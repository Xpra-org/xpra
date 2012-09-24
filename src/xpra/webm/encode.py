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

from ctypes import (c_int, c_float, c_void_p, byref, memmove,
    create_string_buffer)
from xpra.webm import _LIBRARY
from xpra.webm.handlers import WebPHandler


# -----------------------------------------------------------------------------
# Exceptions
# -----------------------------------------------------------------------------

class EncodeError(Exception):
    """
    Exception for encoding errors
    """
    pass


# -----------------------------------------------------------------------------
# Internal functions
# -----------------------------------------------------------------------------

# Set argument types
_LIBRARY.WebPEncodeRGB.argtypes = [c_void_p, c_int, c_int, c_int,
                                   c_float, c_void_p]
_LIBRARY.WebPEncodeBGR.argtypes = [c_void_p, c_int, c_int, c_int, c_float,
                                   c_void_p]
_LIBRARY.WebPEncodeRGBA.argtypes = [c_void_p, c_int, c_int, c_int, c_float,
                                    c_void_p]
_LIBRARY.WebPEncodeBGRA.argtypes = [c_void_p, c_int, c_int, c_int, c_float,
                                    c_void_p]

# Set return types
_LIBRARY.WebPEncodeRGB.restype = c_int
_LIBRARY.WebPEncodeBGR.restype = c_int
_LIBRARY.WebPEncodeRGBA.restype = c_int
_LIBRARY.WebPEncodeBGRA.restype = c_int


def _encode(func, image, quality):
    """
    Encode the image with the given quality using the given encoding
    function

    :param func: The encoding function
    :param image: The image to be encoded
    :param quality: The encode quality factor

    :type function: function
    :type image: BitmapHandler
    :type quality: float
    """
    # Call encode function
    data = str(image.bitmap)
    width = c_int(image.width)
    height = c_int(image.height)
    stride = c_int(image.stride)
    q_factor = c_float(quality)
    output_p = c_void_p()

    size = func(data, width, height, stride, q_factor, byref(output_p))

    # Check return size
    if size == 0:
        raise EncodeError

    # Convert output
    output = create_string_buffer(size)

    memmove(output, output_p, size)

    return WebPHandler(bytearray(output), image.width, image.height)


# -----------------------------------------------------------------------------
# Public functions
# -----------------------------------------------------------------------------

def EncodeRGB(image, quality=100):
    """
    Encode the given RGB image with the given quality

    :param image: The RGB image
    :param quality: The encode quality factor

    :type image: BitmapHandler
    :type quality: float
    """
    return _encode(_LIBRARY.WebPEncodeRGB, image, quality)

def EncodeRGBA(image, quality=100):
    """
    Encode the given RGBA image with the given quality

    :param image: The RGBA image
    :param quality: The encode quality factor

    :type image: BitmapHandler
    :type quality: float
    """
    return _encode(_LIBRARY.WebPEncodeRGBA, image, quality)

def EncodeBGRA(image, quality=100):
    """
    Encode the given BGRA image with the given quality

    :param image: The BGRA image
    :param quality: The encode quality factor

    :type image: BitmapHandler
    :type quality: float
    """
    return _encode(_LIBRARY.WebPEncodeBGRA, image, quality)

def EncodeBGR(image, quality=100):
    """
    Encode the given BGR image with the given quality

    :param image: The BGR image
    :param quality: The encode quality factor

    :type image: BitmapHandler
    :type quality: float
    """
    return _encode(_LIBRARY.WebPEncodeBGR, image, quality)
