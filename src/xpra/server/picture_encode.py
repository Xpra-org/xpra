# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("window", "encoding")

from xpra.net import compression
from xpra.codecs.argb.argb import bgra_to_rgb, bgra_to_rgba, argb_to_rgb, argb_to_rgba, r210_to_rgbx, r210_to_rgb, bgr565_to_rgbx, bgr565_to_rgb  #@UnresolvedImport
from xpra.codecs.loader import get_codec
from xpra.util import envbool
from xpra.os_util import memoryview_to_bytes, bytestostr, strtobytes, monotonic_time
#"pixels_to_bytes" gets patched up by the OSX shadow server
pixels_to_bytes = memoryview_to_bytes
try:
    from xpra.net.mmap_pipe import mmap_write
except:
    mmap_write = None               #no mmap

WEBP_PILLOW = envbool("XPRA_WEBP_PILLOW", False)


#give warning message just once per key then ignore:
encoding_warnings = set()
def warn_encoding_once(key, message):
    global encoding_warnings
    if key not in encoding_warnings:
        log.warn("Warning: "+message)
        encoding_warnings.add(key)


def webp_encode(image, rgb_formats, supports_transparency, quality, speed, content_type):
    pixel_format = image.get_pixel_format()
    #log("webp_encode%s", (coding, image, rgb_formats, supports_transparency, quality, speed))
    if pixel_format not in rgb_formats:
        wanted_formats = [x for x in rgb_formats if x in ("BGRA", "BGRX", "RGBA", "RGBX")]
        if not rgb_reformat(image, wanted_formats, supports_transparency):
            raise Exception("cannot find compatible rgb format to use for %s! (supported: %s)" % (pixel_format, rgb_formats))
        #get the new format:
        pixel_format = image.get_pixel_format()
    stride = image.get_rowstride()
    enc_webp = get_codec("enc_webp")
    #log("WEBP_PILLOW=%s, enc_webp=%s, stride=%s, pixel_format=%s", WEBP_PILLOW, enc_webp, stride, pixel_format)
    if not WEBP_PILLOW and enc_webp and stride>0 and stride%4==0 and pixel_format in ("BGRA", "BGRX", "RGBA", "RGBX"):
        #prefer Cython module:
        cdata, client_options = enc_webp.compress(image, quality, speed, supports_transparency, content_type)
        return "webp", compression.Compressed("webp", cdata), client_options, image.get_width(), image.get_height(), 0, 24
    #fallback using Pillow:
    enc_pillow = get_codec("enc_pillow")
    if enc_pillow:
        if not WEBP_PILLOW:
            log.warn("Warning: using PIL fallback for webp")
            log.warn(" enc_webp=%s, stride=%s, pixel format=%s", enc_webp, stride, image.get_pixel_format())
        for x in ("webp", "png"):
            if x in enc_pillow.get_encodings():
                return enc_pillow.encode(x, image, quality, speed, supports_transparency)
    raise Exception("BUG: cannot use 'webp' encoding and none of the PIL fallbacks are available!")


def rgb_encode(coding, image, rgb_formats, supports_transparency, speed, rgb_zlib=True, rgb_lz4=True, rgb_lzo=False):
    pixel_format = strtobytes(image.get_pixel_format())
    #log("rgb_encode%s pixel_format=%s, rgb_formats=%s", (coding, image, rgb_formats, supports_transparency, speed, rgb_zlib, rgb_lz4), pixel_format, rgb_formats)
    if pixel_format not in rgb_formats:
        log("rgb_encode reformatting because %s not in %s", pixel_format, rgb_formats)
        if not rgb_reformat(image, rgb_formats, supports_transparency):
            raise Exception("cannot find compatible rgb format to use for %s! (supported: %s)" % (pixel_format, rgb_formats))
        #get the new format:
        pixel_format = strtobytes(image.get_pixel_format())
        #switch encoding if necessary:
        if len(pixel_format)==4 and coding=="rgb24":
            coding = "rgb32"
        elif len(pixel_format)==3 and coding=="rgb32":
            coding = "rgb24"
    #always tell client which pixel format we are sending:
    options = {"rgb_format" : pixel_format}

    #we may want to re-stride:
    image.may_restride()

    #compress here and return a wrapper so network code knows it is already zlib compressed:
    pixels = image.get_pixels()
    assert pixels, "failed to get pixels from %s" % image
    width = image.get_width()
    height = image.get_height()
    stride = image.get_rowstride()

    #compression stage:
    level = 0
    algo = "not"
    l = len(pixels)
    if l>=512 and speed<100:
        if l>=32768:
            level = 1+max(0, min(8, int(100-speed)//12))
        else:
            #fewer pixels, make it more likely we won't bother compressing (speed>90):
            level = max(0, min(5, int(110-speed)//20))
    if level>0:
        if rgb_lz4 and compression.use_lz4:
            cwrapper = compression.compressed_wrapper(coding, pixels, lz4=True, level=level)
            algo = "lz4"
            level = 1
        elif rgb_lzo and compression.use_lzo:
            cwrapper = compression.compressed_wrapper(coding, pixels, lzo=True)
            algo = "lzo"
            level = 1
        elif rgb_zlib and compression.use_zlib:
            cwrapper = compression.compressed_wrapper(coding, pixels, zlib=True, level=level//2)
            algo = "zlib"
        else:
            cwrapper = None
        if cwrapper is None or len(cwrapper)>=(len(pixels)-32):
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
        cwrapper = compression.Compressed(coding, pixels_to_bytes(pixels), True)
    if pixel_format.upper().find(b"A")>=0 or pixel_format.upper().find(b"X")>=0:
        bpp = 32
    else:
        bpp = 24
    log("rgb_encode using level=%s for %5i pixels at %3i speed, %s compressed %4sx%-4s in %s/%s: %5s bytes down to %5s", level, l, speed, algo, image.get_width(), image.get_height(), coding, pixel_format, len(pixels), len(cwrapper.data))
    #wrap it using "Compressed" so the network layer receiving it
    #won't decompress it (leave it to the client's draw thread)
    return coding, cwrapper, options, width, height, stride, bpp


def argb_swap(image, rgb_formats, supports_transparency):
    """ use the argb codec to do the RGB byte swapping """
    pixel_format = bytestostr(image.get_pixel_format())
    #try to fallback to argb module
    #if we have one of the target pixel formats:
    pixels = image.get_pixels()
    assert pixels, "failed to get pixels from %s" % image
    rs = image.get_rowstride()
    if pixel_format=="r210":
        #r210 never contains any transparency at present
        #if supports_transparency and "RGBA" in rgb_formats:
        #    log("argb_swap: r210_to_rgba for %s on %s", pixel_format, type(pixels))
        #    image.set_pixels(r210_to_rgba(pixels))
        #    image.set_pixel_format("RGBA")
        #    return True
        if "RGB" in rgb_formats:
            log("argb_swap: r210_to_rgb for %s on %s", pixel_format, type(pixels))
            image.set_pixels(r210_to_rgb(pixels))
            image.set_pixel_format("RGB")
            image.set_rowstride(rs*3//4)
            return True
        if "RGBX" in rgb_formats:
            log("argb_swap: r210_to_rgbx for %s on %s", pixel_format, type(pixels))
            image.set_pixels(r210_to_rgbx(pixels))
            image.set_pixel_format("RGBX")
            return True
    elif pixel_format=="BGR565":
        if "RGB" in rgb_formats:
            log("argb_swap: bgr565_to_rgb for %s on %s", pixel_format, type(pixels))
            image.set_pixels(bgr565_to_rgb(pixels))
            image.set_pixel_format("RGB")
            image.set_rowstride(rs*3//2)
            return True
        if "RGBX" in rgb_formats:
            log("argb_swap: bgr565_to_rgbx for %s on %s", pixel_format, type(pixels))
            image.set_pixels(bgr565_to_rgbx(pixels))
            image.set_pixel_format("RGBX")
            image.set_rowstride(rs*2)
            return True
    elif pixel_format in ("BGRX", "BGRA"):
        if supports_transparency and "RGBA" in rgb_formats:
            log("argb_swap: bgra_to_rgba for %s on %s", pixel_format, type(pixels))
            image.set_pixels(bgra_to_rgba(pixels))
            image.set_pixel_format("RGBA")
            return True
        if "RGB" in rgb_formats:
            log("argb_swap: bgra_to_rgb for %s on %s", pixel_format, type(pixels))
            image.set_pixels(bgra_to_rgb(pixels))
            image.set_pixel_format("RGB")
            image.set_rowstride(rs*3//4)
            return True
    elif pixel_format in ("XRGB", "ARGB"):
        if supports_transparency and "RGBA" in rgb_formats:
            log("argb_swap: argb_to_rgba for %s on %s", pixel_format, type(pixels))
            image.set_pixels(argb_to_rgba(pixels))
            image.set_pixel_format("RGBA")
            return True
        if "RGB" in rgb_formats:
            log("argb_swap: argb_to_rgb for %s on %s", pixel_format, type(pixels))
            image.set_pixels(argb_to_rgb(pixels))
            image.set_pixel_format("RGB")
            image.set_rowstride(rs*3//4)
            return True
    warn_encoding_once(bytestostr(pixel_format)+"-format-not-handled", "no matching argb function: cannot convert %s to one of: %s" % (pixel_format, rgb_formats))
    return False


#source format  : [(PIL input format, output format), ..]
PIL_conv = {
             "XRGB"   : [("XRGB", "RGB")],
             #try to drop alpha channel since it isn't used:
             "BGRX"   : [("BGRX", "RGB"), ("BGRX", "RGBX")],
             #try with alpha first:
             "BGRA"   : [("BGRA", "RGBA"), ("BGRX", "RGB"), ("BGRX", "RGBX")],
             }
#as above but for clients which cannot handle alpha:
PIL_conv_noalpha = {
             "XRGB"   : [("XRGB", "RGB")],
             #try to drop alpha channel since it isn't used:
             "BGRX"   : [("BGRX", "RGB"), ("BGRX", "RGBX")],
             #try with alpha first:
             "BGRA"   : [("BGRX", "RGB"), ("BGRA", "RGBA"), ("BGRX", "RGBX")],
             }


def rgb_reformat(image, rgb_formats, supports_transparency):
    """ convert the RGB pixel data into a format supported by the client """
    #need to convert to a supported format!
    PIL = get_codec("PIL")
    pixel_format = bytestostr(image.get_pixel_format())
    pixels = image.get_pixels()
    assert pixels, "failed to get pixels from %s" % image
    if not PIL or pixel_format in ("r210", "BGR565"):
        #try to fallback to argb module
        #(required for r210 which is not handled by PIL directly)
        log("rgb_reformat: using argb_swap for %s", image)
        return argb_swap(image, rgb_formats, supports_transparency)
    if supports_transparency:
        modes = PIL_conv.get(pixel_format)
    else:
        modes = PIL_conv_noalpha.get(pixel_format)
    assert modes, "no PIL conversion from %s" % (pixel_format)
    target_rgb = [(im,om) for (im,om) in modes if om in rgb_formats]
    if len(target_rgb)==0:
        log("rgb_reformat: no matching target modes for converting %s to %s", image, rgb_formats)
        #try argb module:
        if argb_swap(image, rgb_formats, supports_transparency):
            return True
        warning_key = "rgb_reformat(%s, %s, %s)" % (pixel_format, rgb_formats, supports_transparency)
        warn_encoding_once(warning_key, "cannot convert %s to one of: %s" % (pixel_format, rgb_formats))
        return False
    input_format, target_format = target_rgb[0]
    start = monotonic_time()
    w = image.get_width()
    h = image.get_height()
    #PIL cannot use the memoryview directly:
    if isinstance(pixels, memoryview):
        pixels = pixels.tobytes()
    log("rgb_reformat: converting %s from %s to %s using PIL", image, input_format, target_format)
    img = PIL.Image.frombuffer(target_format, (w, h), pixels, "raw", input_format, image.get_rowstride())
    rowstride = w*len(target_format)    #number of characters is number of bytes per pixel!
    data = img.tobytes("raw", target_format)
    assert len(data)==rowstride*h, "expected %s bytes in %s format but got %s" % (rowstride*h, len(data))
    image.set_pixels(data)
    image.set_rowstride(rowstride)
    image.set_pixel_format(strtobytes(target_format))
    end = monotonic_time()
    log("rgb_reformat(%s, %s, %s) converted from %s (%s bytes) to %s (%s bytes) in %.1fms, rowstride=%s", image, rgb_formats, supports_transparency, pixel_format, len(pixels), target_format, len(data), (end-start)*1000.0, rowstride)
    return True


def mmap_send(mmap, mmap_size, image, rgb_formats, supports_transparency):
    if mmap_write is None:
        warn_encoding_once("mmap_write missing", "cannot use mmap!")
        return None
    if image.get_pixel_format() not in rgb_formats:
        if not rgb_reformat(image, rgb_formats, supports_transparency):
            warning_key = "mmap_send(%s)" % image.get_pixel_format()
            warn_encoding_once(warning_key, "cannot use mmap to send %s" % image.get_pixel_format())
            return None
    start = monotonic_time()
    data = image.get_pixels()
    assert data, "failed to get pixels from %s" % image
    mmap_data, mmap_free_size = mmap_write(mmap, mmap_size, data)
    elapsed = monotonic_time()-start+0.000000001 #make sure never zero!
    log("%s MBytes/s - %s bytes written to mmap in %.1f ms", int(len(data)/elapsed/1024/1024), len(data), 1000*elapsed)
    if mmap_data is None:
        return None
    #replace pixels with mmap info:
    return mmap_data, mmap_free_size, len(data)
