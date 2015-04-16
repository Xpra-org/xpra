# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2010-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
from math import sqrt

from xpra.log import Logger
log = Logger("window", "encoding")

from xpra.net import compression
from xpra.codecs.argb.argb import bgra_to_rgb, bgra_to_rgba, argb_to_rgb, argb_to_rgba, restride_image   #@UnresolvedImport
from xpra.os_util import StringIOClass
from xpra.codecs.loader import get_codec, get_codec_version
from xpra.codecs.codec_constants import get_PIL_encodings
from xpra.os_util import memoryview_to_bytes
try:
    from xpra.net.mmap_pipe import mmap_write
except:
    mmap_write = None               #no mmap


PIL = get_codec("PIL")
PIL_VERSION = get_codec_version("PIL")
PIL_can_optimize = PIL_VERSION>="2.2"

#give warning message just once per key then ignore:
encoding_warnings = set()
def warn_encoding_once(key, message):
    global encoding_warnings
    if key not in encoding_warnings:
        log.warn("Warning: "+message)
        encoding_warnings.add(key)


def webp_encode(coding, image, rgb_formats, supports_transparency, quality, speed, options):
    pixel_format = image.get_pixel_format()
    #log("rgb_encode%s pixel_format=%s, rgb_formats=%s", (coding, image, rgb_formats, supports_transparency, speed, rgb_zlib, rgb_lz4), pixel_format, rgb_formats)
    if pixel_format not in rgb_formats:
        if not rgb_reformat(image, rgb_formats, supports_transparency):
            raise Exception("cannot find compatible rgb format to use for %s! (supported: %s)" % (pixel_format, rgb_formats))
        #get the new format:
        pixel_format = image.get_pixel_format()
    stride = image.get_rowstride()
    enc_webp = get_codec("enc_webp")
    #log("webp_encode%s stride=%s, enc_webp=%s", (coding, image, rgb_formats, supports_transparency, quality, speed, options), stride, enc_webp)
    if enc_webp and stride>0 and stride%4==0 and image.get_pixel_format() in ("BGRA", "BGRX", "RGBA", "RGBX"):
        #prefer Cython module:
        alpha = supports_transparency and image.get_pixel_format().find("A")>=0
        w = image.get_width()
        h = image.get_height()
        if quality==100:
            #webp lossless is unbearibly slow for only marginal compression improvements,
            #so force max speed:
            speed = 100
        else:
            #normalize speed for webp: avoid low speeds!
            speed = int(sqrt(speed) * 10)
        speed = max(0, min(100, speed))
        cdata = enc_webp.compress(image.get_pixels(), w, h, stride=stride/4, quality=quality, speed=speed, has_alpha=alpha)
        client_options = {"speed"       : speed,
                          "rgb_format"  : pixel_format}
        if quality>=0 and quality<=100:
            client_options["quality"] = quality
        if alpha:
            client_options["has_alpha"] = True
        return "webp", compression.Compressed("webp", cdata), client_options, image.get_width(), image.get_height(), 0, 24
    #fallback to PIL
    log("using PIL fallback for webp: enc_webp=%s, stride=%s, pixel format=%s", enc_webp, stride, image.get_pixel_format())
    encs = get_PIL_encodings(PIL)
    for x in ("webp", "png"):
        if x in encs:
            return PIL_encode(x, image, quality, speed, supports_transparency)
    raise Exception("BUG: cannot use 'webp' encoding and none of the PIL fallbacks are available!")


def roundup(n, m):
    return (n + m - 1) & ~(m - 1)

def rgb_encode(coding, image, rgb_formats, supports_transparency, speed, rgb_zlib=True, rgb_lz4=True, rgb_lzo=False):
    pixel_format = image.get_pixel_format()
    #log("rgb_encode%s pixel_format=%s, rgb_formats=%s", (coding, image, rgb_formats, supports_transparency, speed, rgb_zlib, rgb_lz4), pixel_format, rgb_formats)
    if pixel_format not in rgb_formats:
        if not rgb_reformat(image, rgb_formats, supports_transparency):
            raise Exception("cannot find compatible rgb format to use for %s! (supported: %s)" % (pixel_format, rgb_formats))
        #get the new format:
        pixel_format = image.get_pixel_format()
        #switch encoding if necessary:
        if len(pixel_format)==4 and coding=="rgb24":
            coding = "rgb32"
        elif len(pixel_format)==3 and coding=="rgb32":
            coding = "rgb24"
    #always tell client which pixel format we are sending:
    options = {"rgb_format" : pixel_format}

    #we may want to re-stride:
    restride_image(image)

    #compress here and return a wrapper so network code knows it is already zlib compressed:
    pixels = image.get_pixels()
    width = image.get_width()
    height = image.get_height()
    stride = image.get_rowstride()

    #compression
    #by default, wire=raw:
    raw_data = str(pixels)
    wire_data = raw_data
    level = 0
    algo = "not"
    if len(pixels)>=256 and (rgb_zlib and compression.use_zlib) or (rgb_lz4 and compression.lz4) or (rgb_lzo and compression.use_lzo):
        level = max(0, min(5, int(115-speed)/20))
        if len(pixels)<1024:
            #fewer pixels, make it more likely we won't bother compressing:
            level = level // 2
    if level>0:
        if rgb_lz4 and compression.use_lz4:
            wire_data = compression.compressed_wrapper(coding, pixels, lz4=True)
            algo = "lz4"
            level = 1
        elif rgb_lzo and compression.use_lzo:
            wire_data = compression.compressed_wrapper(coding, pixels, lzo=True)
            algo = "lzo"
            level = 1
        else:
            assert rgb_zlib and compression.use_zlib
            wire_data = compression.compressed_wrapper(coding, pixels, zlib=True, level=level)
            algo = "zlib"
        raw_data = wire_data.data
        #log("%s/%s data compressed from %s bytes down to %s (%s%%) with lz4=%s",
        #         coding, pixel_format, len(pixels), len(raw_data), int(100.0*len(raw_data)/len(pixels)), self.rgb_lz4)
        if len(raw_data)>=(len(pixels)-32):
            #compressed is actually bigger! (use uncompressed)
            level = 0
            wire_data = str(pixels)
            raw_data = wire_data
        else:
            #add compressed marker:
            options[algo] = level
    if pixel_format.upper().find("A")>=0 or pixel_format.upper().find("X")>=0:
        bpp = 32
    else:
        bpp = 24
    log("rgb_encode using level=%s, %s compressed %sx%s in %s/%s: %s bytes down to %s", level, algo, image.get_width(), image.get_height(), coding, pixel_format, len(pixels), len(raw_data))
    #wrap it using "Compressed" so the network layer receiving it
    #won't decompress it (leave it to the client's draw thread)
    return coding, compression.Compressed(coding, raw_data, True), options, width, height, stride, bpp


def PIL_encode(coding, image, quality, speed, supports_transparency):
    assert PIL is not None, "Python PIL is not available"
    pixel_format = image.get_pixel_format()
    w = image.get_width()
    h = image.get_height()
    rgb = {
           "XRGB"   : "RGB",
           "BGRX"   : "RGB",
           "RGBA"   : "RGBA",
           "BGRA"   : "RGBA",
           }.get(pixel_format, pixel_format)
    bpp = 32
    #remove transparency if it cannot be handled:
    try:
        #PIL cannot use the memoryview directly:
        pixels = memoryview_to_bytes(image.get_pixels())
        #it is safe to use frombuffer() here since the convert()
        #calls below will not convert and modify the data in place
        #and we save the compressed data then discard the image
        im = PIL.Image.frombuffer(rgb, (w, h), pixels, "raw", pixel_format, image.get_rowstride())
        if coding.startswith("png") and not supports_transparency and rgb=="RGBA":
            im = im.convert("RGB")
            rgb = "RGB"
            bpp = 24
    except Exception as e:
        log.error("PIL_encode(%s) converting to %s failed", (w, h, coding, "%s bytes" % image.get_size(), pixel_format, image.get_rowstride()), rgb, exc_info=True)
        raise e
    buf = StringIOClass()
    client_options = {}
    #only optimize with Pillow>=2.2 and when speed is zero
    if coding in ("jpeg", "webp"):
        q = int(min(99, max(1, quality)))
        kwargs = im.info
        kwargs["quality"] = q
        client_options["quality"] = q
        if coding=="jpeg" and PIL_can_optimize and speed<70:
            #(optimizing jpeg is pretty cheap and worth doing)
            kwargs["optimize"] = True
            client_options["optimize"] = True
        im.save(buf, coding.upper(), **kwargs)
    else:
        assert coding in ("png", "png/P", "png/L"), "unsupported png encoding: %s" % coding
        if coding in ("png/L", "png/P") and supports_transparency and rgb=="RGBA":
            #grab alpha channel (the last one):
            #we use the last channel because we know it is RGBA,
            #otherwise we should do: alpha_index= image.getbands().index('A')
            alpha = im.split()[-1]
            #convert to simple on or off mask:
            #set all pixel values below 128 to 255, and the rest to 0
            def mask_value(a):
                if a<=128:
                    return 255
                return 0
            mask = PIL.Image.eval(alpha, mask_value)
        else:
            #no transparency
            mask = None
        if coding=="png/L":
            im = im.convert("L", palette=PIL.Image.ADAPTIVE, colors=255)
            bpp = 8
        elif coding=="png/P":
            #I wanted to use the "better" adaptive method,
            #but this does NOT work (produces a black image instead):
            #im.convert("P", palette=Image.ADAPTIVE)
            im = im.convert("P", palette=PIL.Image.WEB, colors=255)
            bpp = 8
        if mask:
            # paste the alpha mask to the color of index 255
            im.paste(255, mask)
        kwargs = im.info
        if mask is not None:
            client_options["transparency"] = 255
            kwargs["transparency"] = 255
        if PIL_can_optimize and speed==0:
            #optimizing png is very rarely worth doing
            kwargs["optimize"] = True
            client_options["optimize"] = True
        #level can range from 0 to 9, but anything above 5 is way too slow for small gains:
        #76-100   -> 1
        #51-76    -> 2
        #etc
        level = max(1, min(5, (125-speed)/25))
        kwargs["compress_level"] = level
        client_options["compress_level"] = level
        #default is good enough, no need to override, other options:
        #DEFAULT_STRATEGY, FILTERED, HUFFMAN_ONLY, RLE, FIXED
        #kwargs["compress_type"] = PIL.Image.DEFAULT_STRATEGY
        im.save(buf, "PNG", **kwargs)
    log("sending %sx%s %s as %s, mode=%s, options=%s", w, h, pixel_format, coding, im.mode, kwargs)
    data = buf.getvalue()
    buf.close()
    return coding, compression.Compressed(coding, data), client_options, image.get_width(), image.get_height(), 0, bpp


def argb_swap(image, rgb_formats, supports_transparency):
    """ use the argb codec to do the RGB byte swapping """
    pixel_format = image.get_pixel_format()
    #try to fallback to argb module
    #if we have one of the target pixel formats:
    pixels = image.get_pixels()
    rs = image.get_rowstride()
    if pixel_format in ("BGRX", "BGRA"):
        if supports_transparency and "RGBA" in rgb_formats:
            image.set_pixels(bgra_to_rgba(pixels))
            image.set_pixel_format("RGBA")
            return True
        if "RGB" in rgb_formats:
            image.set_pixels(bgra_to_rgb(pixels))
            image.set_pixel_format("RGB")
            image.set_rowstride(rs/4*3)
            return True
    if pixel_format in ("XRGB", "ARGB"):
        if supports_transparency and "RGBA" in rgb_formats:
            image.set_pixels(argb_to_rgba(pixels))
            image.set_pixel_format("RGBA")
            return True
        if "RGB" in rgb_formats:
            image.set_pixels(argb_to_rgb(pixels))
            image.set_pixel_format("RGB")
            image.set_rowstride(rs/4*3)
            return True
    warn_encoding_once(pixel_format+"-format-not-handled", "no matching argb function: cannot convert %s to one of: %s" % (pixel_format, rgb_formats))
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
    global PIL
    pixel_format = image.get_pixel_format()
    pixels = image.get_pixels()
    if not PIL:
        #try to fallback to argb module
        return argb_swap(image, rgb_formats, supports_transparency)
    if supports_transparency:
        modes = PIL_conv.get(pixel_format)
    else:
        modes = PIL_conv_noalpha.get(pixel_format)
    target_rgb = [(im,om) for (im,om) in modes if om in rgb_formats]
    if len(target_rgb)==0:
        #try argb module:
        if argb_swap(image, rgb_formats, supports_transparency):
            return True
        warning_key = "rgb_reformat(%s, %s, %s)" % (pixel_format, rgb_formats, supports_transparency)
        warn_encoding_once(warning_key, "cannot convert %s to one of: %s" % (pixel_format, rgb_formats))
        return False
    input_format, target_format = target_rgb[0]
    start = time.time()
    w = image.get_width()
    h = image.get_height()
    #PIL cannot use the memoryview directly:
    pixels = memoryview_to_bytes(pixels)
    img = PIL.Image.frombuffer(target_format, (w, h), pixels, "raw", input_format, image.get_rowstride())
    rowstride = w*len(target_format)    #number of characters is number of bytes per pixel!
    #use tobytes() if present, fallback to tostring():
    data_fn = getattr(img, "tobytes", getattr(img, "tostring"))
    data = data_fn("raw", target_format)
    assert len(data)==rowstride*h, "expected %s bytes in %s format but got %s" % (rowstride*h, len(data))
    image.set_pixels(data)
    image.set_rowstride(rowstride)
    image.set_pixel_format(target_format)
    end = time.time()
    log("rgb_reformat(%s, %s, %s) converted from %s (%s bytes) to %s (%s bytes) in %.1fms, rowstride=%s", image, rgb_formats, supports_transparency, pixel_format, len(pixels), target_format, len(data), (end-start)*1000.0, rowstride)
    return True


def mmap_encode(coding, image, options):
    """ Tightly coupled with mmap_send:
        mmap_send will place the mmap pointers in options,
        only those pointers are sent as data to the client.
    """
    data = options["mmap_data"]
    return "mmap", data, {"rgb_format" : image.get_pixel_format()}, image.get_width(), image.get_height(), image.get_rowstride(), 32

def mmap_send(mmap, mmap_size, image, rgb_formats, supports_transparency):
    if mmap_write is None:
        warn_encoding_once("mmap_write missing", "cannot use mmap!")
        return None
    if image.get_pixel_format() not in rgb_formats:
        if not rgb_reformat(image, rgb_formats, supports_transparency):
            warning_key = "mmap_send(%s)" % image.get_pixel_format()
            warn_encoding_once(warning_key, "cannot use mmap to send %s" % image.get_pixel_format())
            return None
    start = time.time()
    data = image.get_pixels()
    mmap_data, mmap_free_size = mmap_write(mmap, mmap_size, data)
    elapsed = time.time()-start+0.000000001 #make sure never zero!
    log("%s MBytes/s - %s bytes written to mmap in %.1f ms", int(len(data)/elapsed/1024/1024), len(data), 1000*elapsed)
    if mmap_data is None:
        return None
    #replace pixels with mmap info:
    return mmap_data, mmap_free_size, len(data)
