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

from handlers import BitmapHandler

"""
Porting of the YUVtoRGB converter code from the Chromium project. See
third_party/libwebp/yuv.c and /third_party/libwebp/yuv.h files for the original
source code.
"""


# -----------------------------------------------------------------------------
# Internal functions
# -----------------------------------------------------------------------------

# YUV conversion constants
YUV_FIX = 16                    # fixed-point precision
YUV_RANGE_MIN = -227            # min value of r/g/b output
YUV_RANGE_MAX = 256 + 226       # max value of r/g/b output
YUV_HALF = 1 << (YUV_FIX - 1)
VP8kVToR = [0] * 256
VP8kUToB = [0] * 256
VP8kVToG = [0] * 256
VP8kUToG = [0] * 256
VP8kClip = [0] * (YUV_RANGE_MAX - YUV_RANGE_MIN)


def _init_yuv_module():
    """
    Initialise the YUVtoRGB lookup tables
    """
    for i in xrange(256):
        VP8kVToR[i] = (89858 * (i - 128) + YUV_HALF) >> YUV_FIX
        VP8kUToG[i] = -22014 * (i - 128) + YUV_HALF
        VP8kVToG[i] = -45773 * (i - 128)
        VP8kUToB[i] = (113618 * (i - 128) + YUV_HALF) >> YUV_FIX

    for i in xrange(YUV_RANGE_MIN, YUV_RANGE_MAX):
        k = ((i - 16) * 76283 + YUV_HALF) >> YUV_FIX
        k = 0 if k < 0 else 255 if k > 255 else k

        VP8kClip[i - YUV_RANGE_MIN] = k


# Initialise YUVtoRGB lookup table on module loading
_init_yuv_module()


def _decode_YUV_image(image):
    """
    Decode the given image in YUV format to a RGB byte array

    :param image: The image in YUV format to be decoded
    :type image: BitmapHandler
    :rtype: bytearray
    """
    rgb_bitmap = bytearray()

    for h in xrange(image.height):
        for w in xrange(image.width):
            # Get luma
            i = h * image.stride + w
            y = image.bitmap[i]

            # WORKAROUND:
            # This is a workaround for YUV to RGB decoding to have a useful
            # grayscale image from the YUV data.
            # Remove this when the correct YUV to color RGB function is
            # found.
            rgb_bitmap.extend((y, y, y))

#            # Get chrominance
#            i = h * image.uv_stride + int(w/2)
#
#            if w % 2:
#                u = image.u_bitmap[i] & 0b1111
#                v = image.v_bitmap[i] & 0b1111
#            else:
#                u = image.u_bitmap[i] >> 4
#                v = image.v_bitmap[i] >> 4
#
#            # Calculate RGB values
#            r_off = VP8kVToR[v]
#            g_off = (VP8kVToG[v] + VP8kUToG[u]) >> YUV_FIX
#            b_off = VP8kUToB[u]
#
#            rgb_bitmap.append( VP8kClip[y + r_off - YUV_RANGE_MIN] )
#            rgb_bitmap.append( VP8kClip[y + g_off - YUV_RANGE_MIN] )
#            rgb_bitmap.append( VP8kClip[y + b_off - YUV_RANGE_MIN] )

    # End
    return rgb_bitmap


# -----------------------------------------------------------------------------
# Public functions
# -----------------------------------------------------------------------------

def YUVtoRGB(image):
    """
    Convert the given WebP image instance from a YUV format to an RGB format

    :param image: The WebP image in YUV format
    :type image: BitmapHandler
    :rtype: BitmapHandler
    """
    return BitmapHandler(
        _decode_YUV_image(image), BitmapHandler.RGB,
        image.width, image.height, image.width * 3
    )

def YUVtoRGBA(image):
    """
    Convert the given WebP image instance form YUV format to RGBA format

    :param image: The WebP image in YUV format
    :type image: BitmapHandler
    :rtype: BitmapHandler
    """
    rgb_bitmap = _decode_YUV_image(image)
    rgba_bitmap = bytearray()

    for i in xrange(len(rgb_bitmap) / 3):
        i *= 3

        rgba_bitmap.append(rgb_bitmap[i])
        rgba_bitmap.append(rgb_bitmap[i + 1])
        rgba_bitmap.append(rgb_bitmap[i + 2])
        rgba_bitmap.append(0xff)

    # Return the BitmapHandler in RGB format
    return BitmapHandler(
        rgba_bitmap, BitmapHandler.RGBA,
        image.width, image.height, image.width * 4
    )

def YUVtoBGR(image):
    """
    Convert the given WebP image instance form YUV format to BGR format

    :param image: The WebP image in YUV format
    :type image: BitmapHandler
    :rtype: BitmapHandler
    """
    rgb_bitmap = _decode_YUV_image(image)
    bgr_bitmap = bytearray()

    for i in xrange(len(rgb_bitmap) / 3):
        i *= 3

        bgr_bitmap.append(rgb_bitmap[i + 2])
        bgr_bitmap.append(rgb_bitmap[i + 1])
        bgr_bitmap.append(rgb_bitmap[i])

    # Return the BitmapHandler in BGR format
    return BitmapHandler(
        bgr_bitmap, BitmapHandler.BGR,
        image.width, image.height, image.width * 3
    )

def YUVtoBGRA(image):
    """
    Convert the given WebP image instance form YUV format to BGRA format

    :param image: The WebP image in YUV format
    :type image: BitmapHandler
    :rtype: BitmapHandler
    """
    rgb_bitmap = _decode_YUV_image(image)
    bgra_bitmap = bytearray()

    for i in xrange(len(rgb_bitmap) / 3):
        i *= 3

        bgra_bitmap.append(rgb_bitmap[i + 2])
        bgra_bitmap.append(rgb_bitmap[i + 1])
        bgra_bitmap.append(rgb_bitmap[i])
        bgra_bitmap.append(0xff)

    # Return the BitmapHandler in BGRA format
    return BitmapHandler(
        bgra_bitmap, BitmapHandler.BGRA,
        image.width, image.height, image.width * 4
    )
