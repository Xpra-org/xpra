# This file is part of Xpra.
# Copyright (C) 2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.codecs.rgb_transform import rgb_reformat
from xpra.codecs import rgb_transform
from xpra.net.compression import Compressed, LevelCompressed, compressed_wrapper
from xpra.log import Logger

log = Logger("encoder")


def get_version():
    return (4, 3)

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
    if pixel_format in ("BGRX", "BGRA", "RGBA"):
        rgb_formats = options.get("rgb_formats", ("BGRX", "BGRA", "RGBA"))
    elif pixel_format in ("RGB", "BGR"):
        rgb_formats = options.get("rgb_formats", ("RGB", "BGR"))
    else:
        raise Exception("unsupported pixel format %s" % pixel_format)
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
    client_options = {"rgb_format" : pixel_format}

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
    lz4 = options.get("lz4", False)
    if l>=512 and (lz4 or speed<100):
        if l>=4096:
            level = 1+max(0, min(7, int(100-speed)//14))
        else:
            #fewer pixels, make it more likely we won't bother compressing
            #and use a lower level (max=3)
            level = max(0, min(3, int(125-speed)//35))
    if level>0:
        zlib = options.get("zlib", False)
        can_inline = l<=32768
        cwrapper = compressed_wrapper(coding, pixels, level=level,
                                      zlib=zlib, lz4=lz4,
                                      brotli=False, none=False,
                                      can_inline=can_inline)
        if isinstance(cwrapper, LevelCompressed):
            #add compressed marker:
            client_options[cwrapper.algorithm] = cwrapper.level & 0xF
            #remove network layer compression marker
            #so that this data will be decompressed by the decode thread client side:
            cwrapper.level = 0
        elif can_inline and isinstance(pixels, memoryview):
            assert isinstance(cwrapper, Compressed)
            assert cwrapper.data==pixels
            #compression either did not work or was not enabled
            #and memoryview pixel data cannot be handled by the packet encoders
            #so we convert it to bytes so it can still be inlined with the packet data:
            cwrapper.data = rgb_transform.pixels_to_bytes(pixels)
    else:
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
    return coding, cwrapper, client_options, width, height, stride, bpp
