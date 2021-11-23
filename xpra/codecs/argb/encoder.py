# This file is part of Xpra.
# Copyright (C) 2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.codecs.rgb_transform import rgb_reformat
from xpra.codecs import rgb_transform
from xpra.net.compression import Compressed, compressed_wrapper
from xpra.log import Logger

log = Logger("encoder")


def get_version():
    return 4, 3

def get_type() -> str:
    return "rgb"

def get_encodings():
    return "rgb24", "rgb32"

def get_info() -> dict:
    return  {
            "version"       : get_version(),
            "encodings"     : get_encodings(),
            }


def encode(coding : str, image, options : dict):
    pixel_format = image.get_pixel_format()
    #log("rgb_encode%s pixel_format=%s, rgb_formats=%s",
    #    (coding, image, rgb_formats, supports_transparency, speed, rgb_zlib, rgb_lz4), pixel_format, rgb_formats)
    rgb_formats = options.get("rgb_formats", ("BGRX", "BGRA"))
    supports_transparency = options.get("alpha", True)
    if pixel_format not in rgb_formats:
        log("rgb_encode reformatting because %s not in %s, supports_transparency=%s",
            pixel_format, rgb_formats, supports_transparency)
        if not rgb_reformat(image, rgb_formats, supports_transparency):
            raise Exception("cannot find compatible rgb format to use for %s! (supported: %s)" % (
                pixel_format, rgb_formats))
        #get the new format:
        pixel_format = image.get_pixel_format()
        #switch encoding if necessary:
        if len(pixel_format)==4:
            coding = "rgb32"
        elif len(pixel_format)==3:
            coding = "rgb24"
        else:
            raise Exception("invalid pixel format %s" % pixel_format)
    #we may still want to re-stride:
    image.may_restride()
    #always tell client which pixel format we are sending:
    options = {"rgb_format" : pixel_format}

    #compress here and return a wrapper so network code knows it is already zlib compressed:
    pixels = image.get_pixels()
    assert pixels, "failed to get pixels from %s" % image
    width = image.get_width()
    height = image.get_height()
    stride = image.get_rowstride()
    speed = options.get("speed", 50)

    #compression stage:
    level = 0
    algo = "not"
    l = len(pixels)
    if l>=512 and speed<100:
        if l>=4096:
            #speed=99 -> level=1, speed=0 -> level=9
            level = 1+max(0, min(8, int(100-speed)//12))
        else:
            #fewer pixels, make it more likely we won't bother compressing
            #and use a lower level (max=5)
            level = max(0, min(5, int(115-speed)//20))
    if level>0:
        zlib = options.get("zlib", False)
        lz4 = options.get("lz4", False)
        cwrapper = compressed_wrapper(coding, pixels, level=level,
                                      zlib=zlib, lz4=lz4,
                                      brotli=False, none=True)
        algo = cwrapper.algorithm
        if algo=="none" or len(cwrapper)>=(len(pixels)-32):
            #no compression is enabled, or compressed is actually bigger!
            #(fall through to uncompressed)
            level = 0
        else:
            #add compressed marker:
            options[algo] = level
            #remove network layer compression marker
            #so that this data will be decompressed by the decode thread client side:
            cwrapper.level = 0
    if level==0:
        #can't pass a raw buffer to bencode / rencode,
        #and even if we could, the image containing those pixels may be freed by the time we get to the encoder
        algo = "not"
        cwrapper = Compressed(coding, rgb_transform.pixels_to_bytes(pixels), True)
    if pixel_format.find("A")>=0 or pixel_format.find("X")>=0:
        bpp = 32
    else:
        bpp = 24
    log("rgb_encode using level=%s for %5i bytes at %3i speed, %s compressed %4sx%-4s in %s/%s: %5s bytes down to %5s",
        level, l, speed, algo, width, height, coding, pixel_format, len(pixels), len(cwrapper.data))
    #wrap it using "Compressed" so the network layer receiving it
    #won't decompress it (leave it to the client's draw thread)
    return coding, cwrapper, options, width, height, stride, bpp
