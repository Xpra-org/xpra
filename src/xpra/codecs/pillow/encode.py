# This file is part of Xpra.
# Copyright (C) 2014-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time

from xpra.log import Logger
log = Logger("encoder", "pillow")

from xpra.util import envbool
from xpra.os_util import BytesIOClass, memoryview_to_bytes, bytestostr, _buffer
from xpra.net.compression import Compressed

from PIL import Image, ImagePalette     #@UnresolvedImport
from xpra.codecs.pillow import PIL_VERSION

SAVE_TO_FILE = envbool("XPRA_SAVE_TO_FILE")
ENCODE_FORMATS = os.environ.get("XPRA_PILLOW_ENCODE_FORMATS", "png,png/L,png/P,jpeg,webp,jpeg2000").split(",")


def get_version():
    return PIL_VERSION

def get_type():
    return "pillow"

def do_get_encodings():
    log("PIL.Image.SAVE=%s", Image.SAVE)
    encodings = []
    for encoding in ENCODE_FORMATS:
        #strip suffix (so "png/L" -> "png")
        stripped = encoding.split("/")[0].upper()
        if stripped in Image.SAVE:
            encodings.append(encoding)
    log("do_get_encodings()=%s", encodings)
    return encodings

def get_encodings():
    return ENCODINGS

ENCODINGS = do_get_encodings()

def get_info():
    return  {
            "version"       : get_version(),
            "encodings"     : get_encodings(),
            }


def encode(coding, image, quality, speed, supports_transparency):
    log("pillow.encode%s", (coding, image, quality, speed, supports_transparency))
    pixel_format = bytestostr(image.get_pixel_format())
    palette = None
    w = image.get_width()
    h = image.get_height()
    rgb = {
        "RLE8"  : "P",
        "XRGB"  : "RGB",
        "BGRX"  : "RGB",
        "RGBX"  : "RGB",
        "RGBA"  : "RGBA",
        "BGRA"  : "RGBA",
        "BGR"   : "RGB",
        }.get(pixel_format, pixel_format)
    bpp = 32
    #remove transparency if it cannot be handled,
    #and deal with non 24-bit formats:
    try:
        pixels = image.get_pixels()
        assert pixels, "failed to get pixels from %s" % image
        if pixel_format=="r210":
            from xpra.codecs.argb.argb import r210_to_rgba, r210_to_rgb #@UnresolvedImport
            if supports_transparency:
                pixels = r210_to_rgba(pixels)
                pixel_format = "RGBA"
                rgb = "RGBA"
            else:
                image.set_rowstride(image.get_rowstride()*3//4)
                pixels = r210_to_rgb(pixels)
                pixel_format = "RGB"
                rgb = "RGB"
                bpp = 24
        elif pixel_format=="BGR565":
            from xpra.codecs.argb.argb import bgr565_to_rgbx, bgr565_to_rgb    #@UnresolvedImport
            if supports_transparency:
                image.set_rowstride(image.get_rowstride()*2)
                pixels = bgr565_to_rgbx(pixels)
                pixel_format = "RGBA"
                rgb = "RGBA"
            else:
                image.set_rowstride(image.get_rowstride()*3//2)
                pixels = bgr565_to_rgb(pixels)
                pixel_format = "RGB"
                rgb = "RGB"
                bpp = 24
        elif pixel_format=="RLE8":
            pixel_format = "P"
            palette = image.get_palette()
            rp, gp, bp = [], [], []
            for r, g, b in palette:
                rp.append((r>>8) & 0xFF)
                gp.append((g>>8) & 0xFF)
                bp.append((b>>8) & 0xFF)
            palette = rp+gp+bp
        #PIL cannot use the memoryview directly:
        if type(pixels)!=_buffer:
            pixels = memoryview_to_bytes(pixels)
        #it is safe to use frombuffer() here since the convert()
        #calls below will not convert and modify the data in place
        #and we save the compressed data then discard the image
        im = Image.frombuffer(rgb, (w, h), pixels, "raw", pixel_format, image.get_rowstride(), 1)
        if palette:
            im.putpalette(palette)
            im.palette = ImagePalette.ImagePalette("RGB", palette = palette, size = len(palette))
        if coding.startswith("png") and not supports_transparency and rgb=="RGBA":
            im = im.convert("RGB")
            rgb = "RGB"
            bpp = 24
    except Exception:
        log.error("PIL_encode%s converting %s pixels from %s to %s failed", (w, h, coding, "%s bytes" % image.get_size(), pixel_format, image.get_rowstride()), type(pixels), pixel_format, rgb, exc_info=True)
        raise
    buf = BytesIOClass()
    client_options = {}
    if coding in ("jpeg", "webp", "jpeg2000"):
        #newer versions of pillow require explicit conversion to non-alpha:
        if pixel_format.find("A")>=0:
            im = im.convert("RGB")
        q = int(min(100, max(1, quality)))
        kwargs = im.info
        kwargs["quality"] = q
        client_options["quality"] = q
        if coding=="jpeg2000":
            kwargs["quality_mode"] = "rates"    #other option: "dB"
            kwargs["quality_layers"] = max(1, (100-q)*5)
        elif coding=="jpeg" and speed<50:
            #(optimizing jpeg is pretty cheap and worth doing)
            kwargs["optimize"] = True
            client_options["optimize"] = True
        elif coding=="webp" and q>=100:
            kwargs["lossless"] = 1
        pil_fmt = coding.upper()
    else:
        assert coding in ("png", "png/P", "png/L"), "unsupported encoding: %s" % coding
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
            mask = Image.eval(alpha, mask_value)
        else:
            #no transparency
            mask = None
        if coding=="png/L":
            im = im.convert("L", palette=Image.ADAPTIVE, colors=255)
            bpp = 8
        elif coding=="png/P":
            #I wanted to use the "better" adaptive method,
            #but this does NOT work (produces a black image instead):
            #im.convert("P", palette=Image.ADAPTIVE)
            im = im.convert("P", palette=Image.WEB, colors=255)
            bpp = 8
        if mask:
            # paste the alpha mask to the color of index 255
            im.paste(255, mask)
        kwargs = im.info
        if mask is not None:
            client_options["transparency"] = 255
            kwargs["transparency"] = 255
        if speed==0:
            #optimizing png is very rarely worth doing
            kwargs["optimize"] = True
            client_options["optimize"] = True
        #level can range from 0 to 9, but anything above 5 is way too slow for small gains:
        #76-100   -> 1
        #51-76    -> 2
        #etc
        level = max(1, min(5, (125-speed)//25))
        kwargs["compress_level"] = level
        #no need to expose to the client:
        #client_options["compress_level"] = level
        #default is good enough, no need to override, other options:
        #DEFAULT_STRATEGY, FILTERED, HUFFMAN_ONLY, RLE, FIXED
        #kwargs["compress_type"] = Image.DEFAULT_STRATEGY
        pil_fmt = "PNG"
    im.save(buf, pil_fmt, **kwargs)
    if SAVE_TO_FILE:
        filename = "./%s.%s" % (time.time(), pil_fmt)
        im.save(filename, pil_fmt)
        log.info("saved %s to %s", coding, filename)
    log("sending %sx%s %s as %s, mode=%s, options=%s", w, h, pixel_format, coding, im.mode, kwargs)
    data = buf.getvalue()
    buf.close()
    return coding, Compressed(coding, data), client_options, image.get_width(), image.get_height(), 0, bpp

def selftest(full=False):
    global ENCODINGS
    from xpra.os_util import hexstr
    from xpra.codecs.codec_checks import make_test_image
    img = make_test_image("BGRA", 32, 32)
    if full:
        vrange = (0, 50, 100)
    else:
        vrange = (50, )
    for encoding in tuple(ENCODINGS):
        try:
            for q in vrange:
                for s in vrange:
                    for alpha in (True, False):
                        v = encode(encoding, img, q, s, alpha)
                        assert v, "encode output was empty!"
                        cdata = v[1].data
                        log("encode(%s)=%s", (encoding, img, q, s, alpha), hexstr(cdata))
        except Exception as e:
            if encoding==u"jpeg2000":
                l = log.debug
            else:
                l = log.warn
            l("Pillow error saving %s with quality=%s, speed=%s, alpha=%s", encoding, q, s, alpha)
            l(" %s", e, exc_info=True)
            ENCODINGS.remove(encoding)
