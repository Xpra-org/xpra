#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path

from xpra.util import envbool, csv
from xpra.log import Logger
log = Logger("codec", "loader")


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
def codec_import_check(name, description, top_module, class_module, classnames):
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
    classname = None
    try:
        #module is present
        try:
            log(" %s found, will check for %s in %s", top_module, classnames, class_module)
            ic =  __import__(class_module, {}, {}, classnames)
            try:
                #run init_module?
                init_module = getattr(ic, "init_module", None)
                log("%s: init_module=%s", class_module, init_module)
                if init_module:
                    init_module()

                if classnames:
                    for classname in classnames:
                        clazz = getattr(ic, classname)
                        log("%s: %s=%s", class_module, classname, clazz)

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
                        return None
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
        if classname:
            log.warn(" cannot load %s (%s): %s missing from %s",
                     name, description, classname, class_module, exc_info=True)
        else:
            log.warn(" cannot load %s (%s)",
                     name, description, exc_info=True)
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

def xpra_codec_import(name, description, top_module, class_module, classname):
    xpra_top_module = "xpra.codecs.%s" % top_module
    xpra_class_module = "%s.%s" % (xpra_top_module, class_module)
    if codec_import_check(name, description, xpra_top_module, xpra_class_module, classname):
        version_name = name
        if name.startswith("enc_") or name.startswith("dec_") or name.startswith("csc_"):
            version_name = name[4:]
        add_codec_version(version_name, xpra_class_module)


CODEC_OPTIONS = {
    #encoders:
    "enc_pillow"    : ("Pillow encoder",    "pillow",       "encoder", "encode"),
    "enc_webp"      : ("webp encoder",      "webp",         "encoder", "encode"),
    "enc_jpeg"      : ("JPEG encoder",      "jpeg",         "encoder", "encode"),
    #video encoders:
    "enc_vpx"       : ("vpx encoder",       "vpx",          "encoder", "Encoder"),
    "enc_x264"      : ("x264 encoder",      "enc_x264",     "encoder", "Encoder"),
    "enc_x265"      : ("x265 encoder",      "enc_x265",     "encoder", "Encoder"),
    "nvenc"         : ("nvenc encoder",     "nvenc",        "encoder", "Encoder"),
    "enc_ffmpeg"    : ("ffmpeg encoder",    "enc_ffmpeg",   "encoder", "Encoder"),
    #csc:
    "csc_swscale"   : ("swscale colorspace conversion", "csc_swscale", "colorspace_converter", "ColorspaceConverter"),
    "csc_libyuv"    : ("libyuv colorspace conversion", "csc_libyuv", "colorspace_converter", "ColorspaceConverter"),
    #decoders:
    "dec_pillow"    : ("Pillow decoder",    "pillow",       "decoder", "decompress"),
    "dec_webp"      : ("webp decoder",      "webp",         "decoder", "decompress"),
    "dec_jpeg"      : ("JPEG decoder",      "jpeg",         "decoder", "decompress_to_rgb", "decompress_to_yuv"),
    #video decoders:
    "dec_vpx"       : ("vpx decoder",       "vpx",          "decoder", "Decoder"),
    "dec_avcodec2"  : ("avcodec2 decoder",  "dec_avcodec2", "decoder", "Decoder"),
    }

def load_codec(name):
    if has_codec(name):
        return
    try:
        option = CODEC_OPTIONS[name]
        description, top_module, class_module = option[:3]
        classnames = option[3:]
    except KeyError:
        log.error("Error: invalid codec name '%s'", name)
    else:
        xpra_codec_import(name, description, top_module, class_module, classnames)


def load_codecs(encoders=True, decoders=True, csc=True, video=True):
    show = []
    log("loading codecs")

    def load(*names):
        for name in names:
            load_codec(name)

    if encoders:
        show += list(ENCODER_CODECS)
        load(*ENCODER_CODECS)
        if video:
            show += list(ENCODER_VIDEO_CODECS)
            load(*ENCODER_VIDEO_CODECS)
    if csc and video:
        show += list(CSC_CODECS)
        load(*CSC_CODECS)
    if decoders:
        show += list(DECODER_CODECS)
        load(*DECODER_CODECS)
        if video:
            show += list(DECODER_VIDEO_CODECS)
            load(*DECODER_VIDEO_CODECS)

    log("done loading codecs")
    log("found:")
    #print("codec_status=%s" % codecs)
    for name in sorted(ALL_CODECS):
        log("* %s : %s %s" % (name.ljust(20), str(name in codecs).ljust(10), codecs.get(name, "")))
    log("codecs versions:")
    for name, version in codec_versions.items():
        log("* %s : %s" % (name.ljust(20), version))


def get_codec_error(name):
    return codec_errors.get(name)

def get_codec(name):
    return codecs.get(name)

def get_codec_version(name):
    return codec_versions.get(name)

def has_codec(name):
    return name in codecs


CSC_CODECS = "csc_swscale", "csc_libyuv"
ENCODER_CODECS = "enc_pillow", "enc_webp", "enc_jpeg"
ENCODER_VIDEO_CODECS = "enc_vpx", "enc_x264", "enc_x265", "nvenc", "enc_ffmpeg"
DECODER_CODECS = "dec_pillow", "dec_webp", "dec_jpeg"
DECODER_VIDEO_CODECS = "dec_vpx", "dec_avcodec2"

ALL_CODECS = tuple(set(CSC_CODECS + ENCODER_CODECS + ENCODER_VIDEO_CODECS + DECODER_CODECS + DECODER_VIDEO_CODECS))


def get_rgb_compression_options():
    from xpra.net import compression
    compressors = compression.get_enabled_compressors()
    compressors = [x for x in compressors if x!="brotli"]
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
          "rgb"     : " + ".join(get_rgb_compression_options()) + " (24/32bpp)",
        }
    return ENCODINGS_TO_NAME.get(encoding, encoding)

def get_encoding_help(encoding):
    from xpra.net import compression
    compressors = compression.get_enabled_compressors()
    compressors = [x for x in compressors if x!="brotli"]
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
          "rgb"     : "Raw RGB pixels, lossless,"
                      +" compressed using %s (24bpp or 32bpp for transparency)" % (" or ".join(compressors)),
          }.get(encoding)


def encodings_help(encodings):
    from xpra.codecs.codec_constants import HELP_ORDER
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
    from xpra.log import enable_color, LOG_FORMAT, NOPREFIX_FORMAT
    from xpra.util import print_nested_dict, pver
    with program_context("Loader", "Encoding Info"):
        verbose = "-v" in sys.argv or "--verbose" in sys.argv
        format_string = NOPREFIX_FORMAT
        if verbose:
            format_string = LOG_FORMAT
            log.enable_debug()
        enable_color(format_string)

        load_codecs()
        #not really a codec, but gets used by codecs, so include version info:
        add_codec_version("numpy", "numpy")
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
                        print("                         colorspaces: %s" % csv(list(set(cs))))
                    elif name.find("enc")>=0 or name.find("dec")>=0:
                        encodings = mod.get_encodings()
                        print("                         encodings: %s" % csv(encodings))
                    try:
                        i = mod.get_info()
                        for k,v in sorted(i.items()):
                            print("                         %s = %s" % (k,v))
                    except Exception:
                        pass
                except Exception as e:
                    print("error getting extra information on %s: %s" % (name, e))
        print("")
        print("codecs versions:")
        def forcever(v):
            return pver(v, numsep=".", strsep=".").lstrip("v")
        print_nested_dict(codec_versions, vformat=forcever)
    return 0


if __name__ == "__main__":
    main()
