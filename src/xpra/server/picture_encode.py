# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2010-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time

from xpra.log import Logger
log = Logger("window", "encoding")

from xpra.net.protocol import compressed_wrapper, Compressed, use_lz4
try:
    from xpra.codecs.xor import xor_str        #@UnresolvedImport
except Exception, e:
    log("cannot load xor module: %s", e)
    xor_str = None
try:
    from xpra.codecs.argb.argb import bgra_to_rgb, bgra_to_rgba, argb_to_rgb, argb_to_rgba   #@UnresolvedImport
except Exception, e:
    log("cannot load argb module: %s", e)
    bgra_to_rgb, bgra_to_rgba, argb_to_rgb, argb_to_rgba = (None,)*4
from xpra.os_util import StringIOClass
from xpra.codecs.loader import get_codec, get_codec_version, has_codec
try:
    from xpra.net.mmap_pipe import mmap_write
except:
    mmap_write = None               #no mmap


PIL = get_codec("PIL")
PIL_VERSION = get_codec_version("PIL")
enc_webp = get_codec("enc_webp")
webp_handlers = get_codec("webp_bitmap_handlers")


#give warning message just once per key then ignore:
encoding_warnings = set()
def warn_encoding_once(key, message):
    global encoding_warnings
    if key not in encoding_warnings:
        log.warn("Warning: "+message)
        encoding_warnings.add(key)


def webm_encode(image, quality):
    assert enc_webp and webp_handlers, "webp components are missing"

    BitmapHandler = webp_handlers.BitmapHandler
    handler_encs = {
                "RGB" : (BitmapHandler.RGB,     "EncodeRGB",  "EncodeLosslessRGB",  False),
                "BGR" : (BitmapHandler.BGR,     "EncodeBGR",  "EncodeLosslessBGR",  False),
                "RGBA": (BitmapHandler.RGBA,    "EncodeRGBA", "EncodeLosslessRGBA", True),
                "RGBX": (BitmapHandler.RGBA,    "EncodeRGBA", "EncodeLosslessRGBA", False),
                "BGRA": (BitmapHandler.BGRA,    "EncodeBGRA", "EncodeLosslessBGRA", True),
                "BGRX": (BitmapHandler.BGRA,    "EncodeBGRA", "EncodeLosslessBGRA", False),
                }
    pixel_format = image.get_pixel_format()
    h_e = handler_encs.get(pixel_format)
    assert h_e is not None, "cannot handle rgb format %s with webp!" % pixel_format
    bh, lossy_enc, lossless_enc, has_alpha = h_e
    q = max(1, quality)
    enc = None
    if q>=100 and has_codec("enc_webp_lossless"):
        enc = getattr(enc_webp, lossless_enc)
        kwargs = {}
        client_options = {}
        log("webm_encode(%s, %s) using lossless encoder=%s for %s", image, enc, pixel_format)
    if enc is None:
        enc = getattr(enc_webp, lossy_enc)
        kwargs = {"quality" : q}
        client_options = {"quality" : q}
        log("webm_encode(%s, %s) using lossy encoder=%s with quality=%s for %s", image, enc, q, pixel_format)
    handler = BitmapHandler(image.get_pixels(), bh, image.get_width(), image.get_height(), image.get_rowstride())
    bpp = 24
    if has_alpha:
        client_options["has_alpha"] = True
        bpp = 32
    return "webp", Compressed("webp", str(enc(handler, **kwargs).data)), client_options, image.get_width(), image.get_height(), 0, bpp


def rgb_encode(coding, image, rgb_formats, supports_transparency, speed, rgb_zlib, rgb_lz4, encoding_client_options, supports_rgb24zlib):
    pixel_format = image.get_pixel_format()
    #log("rgb_encode%s pixel_format=%s, rgb_formats=%s", (coding, image, rgb_formats, supports_transparency, speed, rgb_zlib, rgb_lz4, encoding_client_options, supports_rgb24zlib), pixel_format, rgb_formats)
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
    #compress here and return a wrapper so network code knows it is already zlib compressed:
    pixels = image.get_pixels()

    #compression
    #by default, wire=raw:
    raw_data = str(pixels)
    wire_data = raw_data
    level = 0
    algo = "not"
    if rgb_zlib or rgb_lz4:
        level = max(0, min(5, int(115-speed)/20))
        if len(pixels)<1024:
            #fewer pixels, make it more likely we won't bother compressing:
            level = level / 2
    if level>0:
        lz4 = use_lz4 and rgb_lz4 and level<=3
        wire_data = compressed_wrapper(coding, pixels, level=level, lz4=lz4)
        raw_data = wire_data.data
        #log("%s/%s data compressed from %s bytes down to %s (%s%%) with lz4=%s",
        #         coding, pixel_format, len(pixels), len(raw_data), int(100.0*len(raw_data)/len(pixels)), self.rgb_lz4)
        if len(raw_data)>=(len(pixels)-32):
            #compressed is actually bigger! (use uncompressed)
            level = 0
            wire_data = str(pixels)
            raw_data = wire_data
        else:
            if lz4:
                options["lz4"] = True
                algo = "lz4"
            else:
                options["zlib"] = level
                algo = "zlib"
    if pixel_format.upper().find("A")>=0 or pixel_format.upper().find("X")>=0:
        bpp = 32
    else:
        bpp = 24
    log("rgb_encode using level=%s, %s compressed %sx%s in %s/%s: %s bytes down to %s", level, algo, image.get_width(), image.get_height(), coding, pixel_format, len(pixels), len(raw_data))
    if not encoding_client_options or not supports_rgb24zlib:
        return  coding, wire_data, {}, image.get_width(), image.get_height(), image.get_rowstride(), bpp
    #wrap it using "Compressed" so the network layer receiving it
    #won't decompress it (leave it to the client's draw thread)
    return coding, Compressed(coding, raw_data), options, image.get_width(), image.get_height(), image.get_rowstride(), bpp


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
        #it is safe to use frombuffer() here since the convert()
        #calls below will not convert and modify the data in place
        #and we save the compressed data then discard the image
        im = PIL.Image.frombuffer(rgb, (w, h), image.get_pixels(), "raw", pixel_format, image.get_rowstride())
        if coding.startswith("png") and not supports_transparency and rgb=="RGBA":
            im = im.convert("RGB")
            rgb = "RGB"
            bpp = 24
    except Exception, e:
        log.error("PIL_encode(%s) converting to %s failed", (w, h, coding, "%s bytes" % image.get_size(), pixel_format, image.get_rowstride()), rgb, exc_info=True)
        raise e
    buf = StringIOClass()
    client_options = {}
    #only optimize with Pillow>=2.2 and when speed is zero
    optimize = speed==0 and PIL_VERSION>="2.2"    
    if coding in ("jpeg", "webp"):
        q = int(min(99, max(1, quality)))
        kwargs = im.info
        kwargs["quality"] = q
        if optimize:
            kwargs["optimize"] = True
        im.save(buf, coding.upper(), **kwargs)
        client_options["quality"] = q
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
        if optimize:
            kwargs["optimize"] = True
        im.save(buf, "PNG", **kwargs)
    log("sending %sx%s %s as %s, mode=%s, options=%s", w, h, pixel_format, coding, im.mode, kwargs)
    data = buf.getvalue()
    buf.close()
    return coding, Compressed(coding, data), client_options, image.get_width(), image.get_height(), 0, bpp


def argb_swap(image, rgb_formats, supports_transparency):
    """ use the argb codec to do the RGB byte swapping """
    pixel_format = image.get_pixel_format()
    if None in (bgra_to_rgb, bgra_to_rgba, argb_to_rgb, argb_to_rgba):
        warn_encoding_once("argb-module-missing", "no argb module, cannot convert %s to one of: %s" % (pixel_format, rgb_formats))
        return False

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
    img = PIL.Image.frombuffer(target_format, (w, h), pixels, "raw", input_format, image.get_rowstride())
    rowstride = w*len(target_format)    #number of characters is number of bytes per pixel!
    data = img.tostring("raw", target_format)
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
