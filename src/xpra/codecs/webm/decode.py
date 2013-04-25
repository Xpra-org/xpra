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

from ctypes import (c_int, c_uint, create_string_buffer, memmove, c_void_p,
    POINTER)
from xpra.webm import _LIBRARY, PIXEL_ALPHA_SZ, PIXEL_SZ
from xpra.webm.handlers import BitmapHandler


# -----------------------------------------------------------------------------
# Exceptions
# -----------------------------------------------------------------------------
class HeaderError(Exception):
    """
    Exception for image header operations and manipulations
    """
    pass


# -----------------------------------------------------------------------------
# Internal functions
# -----------------------------------------------------------------------------

# Set function parameter types
_LIBRARY.WebPDecodeRGB.argtypes = [c_void_p, c_uint,
                                   POINTER(c_int), POINTER(c_int)]  # w, h
_LIBRARY.WebPDecodeRGBA.argtypes = [c_void_p, c_uint,
                                    POINTER(c_int), POINTER(c_int)]  # w, h
_LIBRARY.WebPDecodeBGR.argtypes = [c_void_p, c_uint,
                                   POINTER(c_int), POINTER(c_int)]  # w, h
_LIBRARY.WebPDecodeBGRA.argtypes = [c_void_p, c_uint,
                                   POINTER(c_int), POINTER(c_int)]  # w, h
_LIBRARY.WebPDecodeYUV.argtypes = [c_void_p, c_uint,
                                   POINTER(c_int), POINTER(c_int),  # w, h
                                   c_void_p, c_void_p,  # u, v
                                   POINTER(c_int),  # stride
                                   POINTER(c_int)]  # uv_stride
_LIBRARY.WebPGetInfo.argtypes = [c_void_p, c_uint,
                                 POINTER(c_int), POINTER(c_int)]  # w, h

# Set return types
_LIBRARY.WebPDecodeRGB.restype = c_void_p
_LIBRARY.WebPDecodeRGBA.restype = c_void_p
_LIBRARY.WebPDecodeBGR.restype = c_void_p
_LIBRARY.WebPDecodeBGRA.restype = c_void_p
_LIBRARY.WebPDecodeYUV.restype = c_void_p
_LIBRARY.WebPGetInfo.restype = c_uint


def _decode(data, decode_func, pixel_sz):
    """
    Decode the given WebP image data using given decode and with the given
    pixel size in bytes

    :param data: The original WebP image data
    :param decode_func: The decode function to be used
    :param pixel_sz: The pixel data size in bytes to calculate the decoded
                     image size buffer

    :type data: bytearray
    :type decode_func: function
    :type pixel_sz: int

    :rtype: tuple(bytearray, int, int)
    """
    # Prepare parameters
    width = c_int(-1)
    height = c_int(-1)
    size = len(data)

    # Decode image an return pointer to decoded data
    bitmap_p = decode_func(str(data), size, width, height)

    # Copy decoded data into a buffer
    width = width.value
    height = height.value
    size = width * height * pixel_sz
    bitmap = create_string_buffer(size)

    memmove(bitmap, bitmap_p, size)

    # End
    return (bytearray(bitmap), width, height)


# -----------------------------------------------------------------------------
# Public functions
# -----------------------------------------------------------------------------

def GetInfo(data):
    """
    Return the width and the height from the given WebP image data

    :param data: The original WebP image data
    :type data: bytearray
    :rtype: tuple(int, int)
    """
    # Call C function
    width = c_int(-1)
    height = c_int(-1)
    size = len(data)

    ret = _LIBRARY.WebPGetInfo(str(data), size, width, height)

    # Check return code
    if ret == 0:
        raise HeaderError

    # Return values
    return (width.value, height.value)


def DecodeRGB(data):
    """
    Decode the given WebP image data to a RGB bitmap

    :param data: The original WebP image data
    :type data: bytearray
    :rtype: WebPImage
    """
    bitmap, width, height = _decode(
        data, _LIBRARY.WebPDecodeRGB, PIXEL_SZ)

    return BitmapHandler(
        bitmap, BitmapHandler.RGB, width, height, PIXEL_SZ * width)


def DecodeBGR(data):
    """
    Decode the given WebP image data to a BGR bitmap

    :param data: The original WebP image data
    :type data: bytearray
    :rtype: WebPImage
    """
    bitmap, width, height = _decode(
        data, _LIBRARY.WebPDecodeBGR, PIXEL_SZ)

    return BitmapHandler(
        bitmap, BitmapHandler.BGR, width, height, PIXEL_SZ * width)

def DecodeBGRA(data):
    """
    Decode the given WebP image data to a BGRA bitmap

    :param data: The original WebP image data
    :type data: bytearray
    :rtype: WebPImage
    """
    bitmap, width, height = _decode(
        data, _LIBRARY.WebPDecodeBGRA, PIXEL_ALPHA_SZ)

    return BitmapHandler(
        bitmap, BitmapHandler.BGRA, width, height, PIXEL_ALPHA_SZ * width)

def DecodeRGBA(data):
    """
    Decode the given WebP image data to a RGBA bitmap

    :param data: The original WebP image data
    :type data: bytearray
    :rtype: WebPImage
    """
    bitmap, width, height = _decode(
        data, _LIBRARY.WebPDecodeRGBA, PIXEL_ALPHA_SZ)

    return BitmapHandler(
        bitmap, BitmapHandler.RGBA, width, height, PIXEL_ALPHA_SZ * width)

def DecodeYUV(data):
    """
    Decode the given WebP image data to a YUV bitmap

    :param data: The original WebP image data
    :type data: bytearray
    :rtype: WebPImage
    """
    # Prepare parameters
    width = c_int(-1)
    height = c_int(-1)
    size = len(data)
    u = create_string_buffer(0)
    v = create_string_buffer(0)
    stride = c_int(-1)
    uv_stride = c_int(-1)

    # Decode image an return pointer to decoded data
    bitmap_p = _LIBRARY.WebPDecodeYUV(
        str(data), size, width, height, u, v,
#        u, v,
        stride, uv_stride
    )

    # Convert data to Python types
    width = width.value
    height = height.value
    stride = stride.value
    uv_stride = uv_stride.value

    # Copy decoded data into a buffer
    size = stride * height
    bitmap = create_string_buffer(size)

    memmove(bitmap, bitmap_p, size)

    # Copy UV chrominace bitmap
    uv_size = uv_stride * height
    u_bitmap = create_string_buffer(uv_size)
    v_bitmap = create_string_buffer(uv_size)

    memmove(u_bitmap, u, uv_size)
    memmove(v_bitmap, v, uv_size)

    # End
    return BitmapHandler(
        bytearray(bitmap), BitmapHandler.YUV, width, height, stride,
        u_bitmap=bytearray(u_bitmap),
        v_bitmap=bytearray(v_bitmap),
        uv_stride=uv_stride
    )
