#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010-2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path

from xpra.util import envbool
from xpra.os_util import PYTHON3
from xpra.log import Logger
log = Logger("codec", "loader")
try:
    #this makes py2exe do the right thing:
    from xpra.codecs import codec_checks
    assert codec_checks
except:
    pass

if PYTHON3:
    unicode = str           #@ReservedAssignment

#these codecs may well not load because we
#do not require the libraries to be installed
NOWARN = ["nvenc", "enc_x265", "enc_ffmpeg"]

SELFTEST = envbool("XPRA_CODEC_SELFTEST", True)
FULL_SELFTEST = envbool("XPRA_CODEC_FULL_SELFTEST", False)

CODEC_FAIL_IMPORT = os.environ.get("XPRA_CODEC_FAIL_IMPORT", "").split(",")
CODEC_FAIL_SELFTEST = os.environ.get("XPRA_CODEC_FAIL_SELFTEST", "").split(",")

log("codec loader settings: SELFTEST=%s, FULL_SELFTEST=%s, CODEC_FAIL_IMPORT=%s, CODEC_FAIL_SELFTEST=%s",
        SELFTEST, FULL_SELFTEST, CODEC_FAIL_IMPORT, CODEC_FAIL_SELFTEST)

codec_errors = {}
codecs = {}
def codec_import_check(name, description, top_module, class_module, *classnames):
    log("%s:", name)
    log(" codec_import_check%s", (name, description, top_module, class_module, classnames))
    try:
        try:
            if name in CODEC_FAIL_IMPORT:
                raise ImportError("codec found in fail import list")
            __import__(top_module, {}, {}, [])
        except ImportError as e:
            log("failed to import %s (%s)", description, name)
            log("", exc_info=True)
            codec_errors[name] = str(e)
            return None
    except Exception as e:
        log.warn(" cannot load %s (%s):", name, description, exc_info=True)
        codec_errors[name] = str(e)
        return None
    try:
        #module is present
        classname = "?"
        try:
            log(" %s found, will check for %s in %s", top_module, classnames, class_module)
            for classname in classnames:
                ic =  __import__(class_module, {}, {}, classname)
                try:
                    #run init_module?
                    init_module = getattr(ic, "init_module", None)
                    log("%s: init_module=%s", class_module, init_module)
                    if init_module:
                        init_module()
                    selftest = getattr(ic, "selftest", None)
                    log("%s.selftest=%s", name, selftest)
                    if SELFTEST and selftest:
                        if name in CODEC_FAIL_SELFTEST:
                            raise ImportError("codec found in fail selftest list")
                        try:
                            selftest(FULL_SELFTEST)
                        except Exception as e:
                            log.warn("Warning: %s failed its self test", name)
                            for x in str(e).splitlines():
                                log.warn(" %s", x)
                            log("%s failed", selftest, exc_info=True)
                            continue
                finally:
                    cleanup_module = getattr(ic, "cleanup_module", None)
                    log("%s: cleanup_module=%s", class_module, cleanup_module)
                    if cleanup_module:
                        cleanup_module()
                #log.warn("codec_import_check(%s, ..)=%s" % (name, ic))
                log(" found %s : %s", name, ic)
                codecs[name] = ic
                return ic
        except ImportError as e:
            codec_errors[name] = str(e)
            l = log.error
            if name in NOWARN:
                l = log.debug
            l("Error importing %s (%s)", description, name)
            l(" %s", e)
            log("", exc_info=True)
    except Exception as e:
        codec_errors[name] = str(e)
        log.warn(" cannot load %s (%s): %s missing from %s", name, description, classname, class_module, exc_info=True)
    return None
codec_versions = {}
def add_codec_version(name, top_module, version="get_version()", alt_version="__version__"):
    try:
        fieldnames = [x for x in (version, alt_version) if x is not None]
        for fieldname in fieldnames:
            f = fieldname
            if f.endswith("()"):
                f = version[:-2]
            module = __import__(top_module, {}, {}, [f])
            if not hasattr(module, f):
                continue
            v = getattr(module, f)
            if fieldname.endswith("()") and v:
                v = v()
            global codec_versions
            codec_versions[name] = v
            #optional info:
            if hasattr(module, "get_info"):
                info = getattr(module, "get_info")
                log(" %s %s.%s=%s", name, top_module, info, info())
            return v
        if name in codecs:
            log.warn(" cannot find %s in %s", " or ".join(fieldnames), module)
        else:
            log(" no version information for missing codec %s", name)
    except ImportError as e:
        #not present
        log(" cannot import %s: %s", name, e)
        log("", exc_info=True)
    except Exception as e:
        log.warn("error during codec import: %s", e)
        log.warn("", exc_info=True)
    return None


loaded = None
def load_codecs(encoders=True, decoders=True, csc=True):
    global loaded
    if loaded:
        return
    loaded = True
    show = []
    log("loading codecs")
    if encoders or decoders:
        codec_import_check("PIL", "Python Imaging Library", "PIL", "PIL", "Image")
        add_codec_version("PIL", "PIL.Image", "PILLOW_VERSION", "VERSION")

    if encoders:
        show += list(ENCODER_CODECS)
        codec_import_check("enc_pillow", "Pillow encoder", "xpra.codecs.pillow", "xpra.codecs.pillow.encode", "encode")
        add_codec_version("enc_pillow", "xpra.codecs.pillow.encode")

        codec_import_check("enc_webp", "webp encoder", "xpra.codecs.webp", "xpra.codecs.webp.encode", "compress")
        add_codec_version("enc_webp", "xpra.codecs.webp.encode")

        codec_import_check("enc_jpeg", "JPEG decoder", "xpra.codecs.jpeg", "xpra.codecs.jpeg.encoder", "encoder")
        add_codec_version("enc_jpeg", "xpra.codecs.jpeg.encoder")

        codec_import_check("enc_vpx", "vpx encoder", "xpra.codecs.vpx", "xpra.codecs.vpx.encoder", "Encoder")
        add_codec_version("vpx", "xpra.codecs.vpx.decoder")

        codec_import_check("enc_x264", "x264 encoder", "xpra.codecs.enc_x264", "xpra.codecs.enc_x264.encoder", "Encoder")
        add_codec_version("x264", "xpra.codecs.enc_x264.encoder")

        codec_import_check("enc_x265", "x265 encoder", "xpra.codecs.enc_x265", "xpra.codecs.enc_x265.encoder", "Encoder")
        add_codec_version("x265", "xpra.codecs.enc_x265.encoder")

        codec_import_check("nvenc", "nvenc encoder", "xpra.codecs.nvenc", "xpra.codecs.nvenc.encoder", "Encoder")
        add_codec_version("nvenc", "xpra.codecs.nvenc.encoder")

        codec_import_check("enc_ffmpeg", "ffmpeg encoder", "xpra.codecs.enc_ffmpeg", "xpra.codecs.enc_ffmpeg.encoder", "Encoder")
        add_codec_version("ffmpeg", "xpra.codecs.enc_ffmpeg.encoder")

    if csc:
        show += list(CSC_CODECS)
        codec_import_check("csc_swscale", "swscale colorspace conversion", "xpra.codecs.csc_swscale", "xpra.codecs.csc_swscale.colorspace_converter", "ColorspaceConverter")
        add_codec_version("swscale", "xpra.codecs.csc_swscale.colorspace_converter")

        codec_import_check("csc_libyuv", "libyuv colorspace conversion", "xpra.codecs.csc_libyuv", "xpra.codecs.csc_libyuv.colorspace_converter", "ColorspaceConverter")
        add_codec_version("libyuv", "xpra.codecs.csc_libyuv.colorspace_converter")

    if decoders:
        show += list(DECODER_CODECS)
        codec_import_check("dec_pillow", "Pillow decoder", "xpra.codecs.pillow", "xpra.codecs.pillow.decode", "decode")
        add_codec_version("dec_pillow", "xpra.codecs.pillow.decode")

        codec_import_check("dec_webp", "webp decoder", "xpra.codecs.webp", "xpra.codecs.webp.decode", "decompress")
        add_codec_version("dec_webp", "xpra.codecs.webp.decode")

        codec_import_check("dec_jpeg", "JPEG decoder", "xpra.codecs.jpeg", "xpra.codecs.jpeg.decoder", "decoder")
        add_codec_version("dec_jpeg", "xpra.codecs.jpeg.decoder")

        codec_import_check("dec_vpx", "vpx decoder", "xpra.codecs.vpx", "xpra.codecs.vpx.decoder", "Decoder")
        add_codec_version("vpx", "xpra.codecs.vpx.encoder")

        codec_import_check("dec_avcodec2", "avcodec2 decoder", "xpra.codecs.dec_avcodec2", "xpra.codecs.dec_avcodec2.decoder", "Decoder")
        add_codec_version("avcodec2", "xpra.codecs.dec_avcodec2.decoder")

    #not really a codec, but gets used by codecs, so include version info:
    add_codec_version("numpy", "numpy")
    try:
        from xpra.codecs.argb.argb import buffer_api_version            #@UnresolvedImport
        codec_versions["buffer_api"] = buffer_api_version()
    except Exception as e:
        log("unknown buffer api version: %s", e)

    log("done loading codecs")
    log("found:")
    #print("codec_status=%s" % codecs)
    for name in sorted(ALL_CODECS):
        log("* %s : %s %s" % (name.ljust(20), str(name in codecs).ljust(10), codecs.get(name, "")))
    log("codecs versions:")
    for name, version in codec_versions.items():
        log("* %s : %s" % (name.ljust(20), version))


def get_codec_error(name):
    assert loaded
    return codec_errors.get(name)

def get_codec(name):
    assert loaded
    return codecs.get(name)

def get_codec_version(name):
    assert loaded
    return codec_versions.get(name)

def has_codec(name):
    assert loaded
    return name in codecs


CSC_CODECS = "csc_swscale", "csc_libyuv"
ENCODER_CODECS = "enc_pillow", "enc_vpx", "enc_webp", "enc_x264", "enc_x265", "nvenc", "enc_ffmpeg", "enc_jpeg"
DECODER_CODECS = "dec_pillow", "dec_vpx", "dec_webp", "dec_avcodec2", "dec_jpeg"

ALL_CODECS = tuple(set(CSC_CODECS + ENCODER_CODECS + DECODER_CODECS))

#note: this is just for defining the order of encodings,
#so we have both core encodings (rgb24/rgb32) and regular encodings (rgb) in here:
PREFERED_ENCODING_ORDER = ["h264", "vp9", "vp8", "mpeg4", "mpeg4+mp4", "h264+mp4", "mpeg4+mp4", "vp8+webm", "vp9+webm", "png", "png/P", "png/L", "webp", "rgb", "rgb24", "rgb32", "jpeg", "h265", "jpeg2000"]
#encoding order for edges (usually one pixel high or wide):
EDGE_ENCODING_ORDER = ["rgb24", "rgb32", "jpeg", "png", "webp", "png/P", "png/L", "rgb"]


def get_rgb_compression_options():
    from xpra.net import compression
    compressors = compression.get_enabled_compressors()
    RGB_COMP_OPTIONS  = ["Raw RGB"]
    if compressors:
        RGB_COMP_OPTIONS  += ["/".join(compressors)]
    return RGB_COMP_OPTIONS

def get_encoding_name(encoding):
    ENCODINGS_TO_NAME = {
          "auto"    : "automatic",
          "h264"    : "H.264",
          "h265"    : "H.265",
          "mpeg4"   : "MPEG4",
          "vp8"     : "VP8",
          "webp"    : "WebP",
          "vp9"     : "VP9",
          "png"     : "PNG (24/32bpp)",
          "png/P"   : "PNG (8bpp colour)",
          "png/L"   : "PNG (8bpp grayscale)",
          "jpeg"    : "JPEG",
          "jpeg2000": "JPEG 2000",
          "rgb"     : " + ".join(get_rgb_compression_options()) + " (24/32bpp)",
        }
    return ENCODINGS_TO_NAME.get(encoding, encoding)

def get_encoding_help(encoding):
    from xpra.net import compression
    compressors = compression.get_enabled_compressors()
    return {
          "auto"    : "automatic mode (recommended)",
          "h264"    : "H.264 video codec",
          "h265"    : "H.265 (HEVC) video codec (slow and buggy - do not use!)",
          "vp8"     : "VP8 video codec",
          "vp9"     : "VP9 video codec",
          "mpeg4"   : "MPEG-4 video codec",
          "png"     : "Portable Network Graphics (lossless, 24bpp or 32bpp for transparency)",
          "png/P"   : "Portable Network Graphics (lossy, 8bpp colour)",
          "png/L"   : "Portable Network Graphics (lossy, 8bpp grayscale)",
          "webp"    : "WebP compression (supports lossless and lossy modes)",
          "jpeg"    : "JPEG lossy compression",
          "jpeg2000": "JPEG 2000 lossy compression (slow)",
          "rgb"     : "Raw RGB pixels, lossless, compressed using %s (24bpp or 32bpp for transparency)" % (" or ".join(compressors)),
          }.get(encoding)

HELP_ORDER = ("auto", "h264", "h265", "vp8", "vp9", "mpeg4", "png", "png/P", "png/L", "webp", "rgb", "jpeg", "jpeg2000")

#those are currently so useless that we don't want the user to select them by mistake
PROBLEMATIC_ENCODINGS = ("h265", )


def encodings_help(encodings):
    h = []
    for e in HELP_ORDER:
        if e in encodings:
            h.append(encoding_help(e))
    return h

def encoding_help(encoding):
    ehelp = get_encoding_help(encoding) or ""
    return encoding.ljust(12) + ehelp



def main():
    from xpra.platform import program_context
    from xpra.log import enable_color
    from xpra.util import print_nested_dict, pver
    with program_context("Loader", "Encoding Info"):
        enable_color()
        verbose = "-v" in sys.argv or "--verbose" in sys.argv
        if verbose:
            log.enable_debug()

        load_codecs()
        print("codecs and csc modules found:")
        #print("codec_status=%s" % codecs)
        for name in sorted(ALL_CODECS):
            mod = codecs.get(name, "")
            f = mod
            if mod and hasattr(mod, "__file__"):
                f = mod.__file__
                if f.startswith(os.getcwd()):
                    f = f[len(os.getcwd()):]
                    if f.startswith(os.path.sep):
                        f = f[1:]
            print("* %s : %s" % (name.ljust(20), f))
            if mod and verbose:
                try:
                    if name.find("csc")>=0:
                        cs = list(mod.get_input_colorspaces())
                        for c in list(cs):
                            cs += list(mod.get_output_colorspaces(c))
                        print("                         colorspaces: %s" % ", ".join(list(set(cs))))
                    elif name.find("enc")>=0 or name.find("dec")>=0:
                        encodings = mod.get_encodings()
                        print("                         encodings: %s" % ", ".join(encodings))
                    try:
                        i = mod.get_info()
                        for k,v in sorted(i.items()):
                            print("                         %s = %s" % (k,v))
                    except:
                        pass
                except Exception as e:
                    print("error getting extra information on %s: %s" % (name, e))
        print("")
        print("codecs versions:")
        def forcever(v):
            return pver(v, numsep=".", strsep=".").lstrip("v")
        print_nested_dict(codec_versions, vformat=forcever)


if __name__ == "__main__":
    main()
