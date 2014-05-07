#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
from xpra.log import Logger
log = Logger("codec", "loader")

codec_errors = {}
codecs = {}
def codec_import_check(name, description, top_module, class_module, *classnames):
    log("%s:", name)
    log(" codec_import_check%s", (name, description, top_module, class_module, classnames))
    try:
        try:
            __import__(top_module, {}, {}, [])
        except ImportError, e:
            log(" cannot import %s (%s): %s", name, description, e)
            codec_errors[name] = e
            return None
        #module is present
        try:
            log(" %s found, will check for %s in %s", top_module, classnames, class_module)
            for classname in classnames:
                ic =  __import__(class_module, {}, {}, classname)
                #log.warn("codec_import_check(%s, ..)=%s" % (name, ic))
                log(" found %s : %s", name, ic)
                codecs[name] = ic
                return ic
        except ImportError, e:
            codec_errors[name] = e
            log.warn(" cannot import %s (%s): %s", name, description, e)
    except Exception, e:
        codec_errors[name] = e
        log.warn(" cannot load %s (%s): %s missing from %s: %s", name, description, classname, class_module, e)
    return None
codec_versions = {}
def add_codec_version(name, top_module, version="get_version()", alt_version=None):
    try:
        fieldnames = [x for x in (version, alt_version) if x is not None]
        for fieldname in fieldnames:
            if version.endswith("()"):
                fieldname = version[:-2]
            module = __import__(top_module, {}, {}, [fieldname])
            if not hasattr(module, fieldname):
                continue
            v = getattr(module, fieldname)
            if version.endswith("()") and v:
                v = v()
            global codec_versions
            codec_versions[name] = v
            #optional info:
            if hasattr(module, "get_info"):
                info = getattr(module, "get_info")
                log(" %s info(%s)=%s", name, top_module, info())
            return v
        if name in codecs:
            log.warn(" cannot find %s in %s", " or ".join(fieldnames), module)
        else:
            log(" no version information for missing codec %s", name)
    except ImportError, e:
        #not present
        log(" cannot import %s: %s", name, e)
    except Exception, e:
        log.warn("error during codec import: %s", e)
    return None


loaded = False
def load_codecs():
    global loaded
    if loaded:
        return
    loaded = True
    log("loading codecs")
    codec_import_check("PIL", "Python Imaging Library", "PIL", "PIL", "Image")
    add_codec_version("PIL", "PIL.Image", "PILLOW_VERSION", "VERSION")

    codec_import_check("enc_vpx", "vpx encoder", "xpra.codecs.vpx", "xpra.codecs.vpx.encoder", "Encoder")
    codec_import_check("dec_vpx", "vpx decoder", "xpra.codecs.vpx", "xpra.codecs.vpx.decoder", "Decoder")
    add_codec_version("vpx", "xpra.codecs.vpx.encoder")

    codec_import_check("enc_x264", "x264 encoder", "xpra.codecs.enc_x264", "xpra.codecs.enc_x264.encoder", "Encoder")
    add_codec_version("x264", "xpra.codecs.enc_x264.encoder")

    codec_import_check("enc_x265", "x265 encoder", "xpra.codecs.enc_x265", "xpra.codecs.enc_x265.encoder", "Encoder")
    add_codec_version("x265", "xpra.codecs.enc_x265.encoder")

    codec_import_check("nvenc", "nvenc encoder", "xpra.codecs.nvenc", "xpra.codecs.nvenc.encoder", "Encoder")
    add_codec_version("nvenc", "xpra.codecs.nvenc.encoder")

    codec_import_check("csc_swscale", "swscale colorspace conversion", "xpra.codecs.csc_swscale", "xpra.codecs.csc_swscale.colorspace_converter", "ColorspaceConverter")
    add_codec_version("swscale", "xpra.codecs.csc_swscale.colorspace_converter")

    codec_import_check("csc_cython", "cython colorspace conversion", "xpra.codecs.csc_cython", "xpra.codecs.csc_cython.colorspace_converter", "ColorspaceConverter")
    add_codec_version("cython", "xpra.codecs.csc_cython.colorspace_converter")

    codec_import_check("csc_opencl", "OpenCL colorspace conversion", "xpra.codecs.csc_opencl", "xpra.codecs.csc_opencl.colorspace_converter", "ColorspaceConverter")
    add_codec_version("opencl", "xpra.codecs.csc_opencl.colorspace_converter")

    #ffmpeg v1:
    codec_import_check("dec_avcodec", "avcodec decoder", "xpra.codecs.dec_avcodec", "xpra.codecs.dec_avcodec.decoder", "Decoder")
    add_codec_version("avcodec", "xpra.codecs.dec_avcodec.decoder")

    #ffmpeg v2:
    codec_import_check("dec_avcodec2", "avcodec2 decoder", "xpra.codecs.dec_avcodec2", "xpra.codecs.dec_avcodec2.decoder", "Decoder")
    add_codec_version("avcodec2", "xpra.codecs.dec_avcodec2.decoder")

    #webp via cython:
    codec_import_check("enc_webp", "webp encoder", "xpra.codecs.webp", "xpra.codecs.webp.encode", "compress")
    add_codec_version("webp", "xpra.codecs.webp.encode")

    #no bytearray (python 2.6 or later) or no bitmap handlers, no webm:
    from xpra.os_util import builtins
    webm_handlers = codec_import_check("webm_bitmap_handlers", "webp bitmap handler", "xpra.codecs.webm", "xpra.codecs.webm.handlers", "BitmapHandler")
    if ("bytearray" in builtins.__dict__) and webm_handlers:
        codec_import_check("enc_webm", "webp encoder", "xpra.codecs.webm", "xpra.codecs.webm.encode", \
                           "EncodeRGB", "EncodeRGBA", "EncodeBGR", "EncodeBGRA", \
                           "EncodeLosslessRGB", "EncodeLosslessRGBA", "EncodeLosslessBGRA", "EncodeLosslessBGR")

        v = add_codec_version("webm", "xpra.codecs.webm", "__VERSION__")
        MIN_V = "0.2.3"
        if v<MIN_V:
            log.warn("python-webm error: found version %s but the minimum required is %s", v, MIN_V)
            log.warn(" webm decoding has been disabled to prevent memory leaks")
        else:
            #these symbols are all available upstream as of libwebp 0.2:
            codec_import_check("dec_webm", "webp encoder", "xpra.codecs.webm", "xpra.codecs.webm.decode", "DecodeRGB", "DecodeRGBA", "DecodeBGR", "DecodeBGRA")

    log("done loading codecs")
    log("found:")
    #print("codec_status=%s" % codecs)
    for name in ALL_CODECS:
        log("* %s : %s %s" % (name.ljust(20), str(name in codecs).ljust(10), codecs.get(name, "")))
    log("codecs versions:")
    for name, version in codec_versions.items():
        log("* %s : %s" % (name.ljust(20), version))


def get_codec_error(name):
    return codec_errors.get(name)

def get_codec(name):
    load_codecs()
    return codecs.get(name)

def get_codec_version(name):
    load_codecs()
    return codec_versions.get(name)

def has_codec(name):
    load_codecs()
    return name in codecs

OLD_ENCODING_NAMES_TO_NEW = {"x264" : "h264", "vpx" : "vp8"}
NEW_ENCODING_NAMES_TO_OLD = {"h264" : "x264", "vp8" : "vpx"}
ALL_OLD_ENCODING_NAMES_TO_NEW = {"x264" : "h264", "vpx" : "vp8", "rgb24" : "rgb"}
ALL_NEW_ENCODING_NAMES_TO_OLD = {"h264" : "x264", "vp8" : "vpx", "rgb" : "rgb24"}

ALL_CODECS = "PIL", "enc_vpx", "dec_vpx", "enc_x264", "enc_x265", "nvenc", \
            "csc_swscale", "csc_cython", "csc_opencl", \
            "dec_avcodec", "dec_avcodec2", \
            "enc_webm", \
            "dec_webm", \
            "enc_webp"

#note: this is just for defining the order of encodings,
#so we have both core encodings (rgb24/rgb32) and regular encodings (rgb) in here:
PREFERED_ENCODING_ORDER = ["h264", "vp8", "png", "png/P", "png/L", "webp", "rgb", "rgb24", "rgb32", "jpeg", "h265", "vp9"]

compressors = ["zlib"]
try:
    import lz4      #@UnresolvedImport
    del lz4
    compressors.append("lz4")
except:
    pass

ENCODINGS_TO_NAME = {
      "h264"    : "H.264",
      "h265"    : "H.265",
      "vp8"     : "VP8",
      "vp9"     : "VP9",
      "png"     : "PNG (24/32bpp)",
      "png/P"   : "PNG (8bpp colour)",
      "png/L"   : "PNG (8bpp grayscale)",
      "webp"    : "WebP",
      "jpeg"    : "JPEG",
      "rgb"     : "Raw RGB + %s (24/32bpp)" % ("/".join(compressors)),
    }

ENCODINGS_HELP = {
      "h264"    : "H.264 video codec",
      "h265"    : "H.265 (HEVC) video codec (slow)",
      "vp8"     : "VP8 video codec",
      "vp9"     : "VP9 video codec (very slow - do not use!)",
      "png"     : "Portable Network Graphics (lossless, 24bpp or 32bpp for transparency)",
      "png/P"   : "Portable Network Graphics (lossy, 8bpp colour)",
      "png/L"   : "Portable Network Graphics (lossy, 8bpp grayscale)",
      "webp"    : "WebP compression (lossless or lossy)",
      "jpeg"    : "JPEG lossy compression",
      "rgb"     : "Raw RGB pixels, lossless, compressed using %s (24bpp or 32bpp for transparency)" % (" or ".join(compressors)),
      }

HELP_ORDER = ("h264", "h265", "vp8", "vp9", "png", "png/P", "png/L", "webp", "rgb", "jpeg")

def encodings_help(encodings):
    h = []
    for e in HELP_ORDER:
        if e in encodings:
            h.append(encoding_help(e))
    return h

def encoding_help(encoding):
    ehelp = ENCODINGS_HELP.get(encoding, "")
    return encoding.ljust(12) + ehelp



def main():
    from xpra.platform import init, clean
    try:
        init("Loader", "Encoding Info")
        import sys
        if "-v" in sys.argv or "--verbose" in sys.argv:
            log.enable_debug()

        load_codecs()
        print("codecs and csc modules found:")
        #print("codec_status=%s" % codecs)
        for name in ALL_CODECS:
            mod = codecs.get(name, "")
            if mod and hasattr(mod, "__file__"):
                mod = mod.__file__
                if mod.startswith(os.getcwd()):
                    mod = mod[len(os.getcwd()):]
                    if mod.startswith(os.path.sep):
                        mod = mod[1:]
            print("* %s : %s" % (name.ljust(20), mod))
        print("")
        print("codecs versions:")
        def pver(v):
            if type(v)==tuple:
                return ".".join([str(x) for x in v])
            elif type(v)==str and v.startswith("v"):
                return v[1:]
            return str(v)
        for name in sorted(codec_versions.keys()):
            version = codec_versions[name]
            print("* %s : %s" % (name.ljust(20), pver(version)))
    finally:
        #this will wait for input on win32:
        clean()

if __name__ == "__main__":
    main()
