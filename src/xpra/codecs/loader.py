#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path
from xpra.log import Logger
log = Logger("codec", "loader")
try:
    #this makes py2exe do the right thing:
    from xpra.codecs import codec_checks
    assert codec_checks
except:
    pass

if sys.version > '3':
    unicode = str           #@ReservedAssignment

#these codecs may well not load because we
#do not require the libraries to be installed
NOWARN = ["nvenc4", "nvenc5", "opencl"]

RUN_SELF_TESTS = True

codec_errors = {}
codecs = {}
def codec_import_check(name, description, top_module, class_module, *classnames):
    log("%s:", name)
    log(" codec_import_check%s", (name, description, top_module, class_module, classnames))
    try:
        try:
            __import__(top_module, {}, {}, [])
        except ImportError as e:
            log(" cannot import %s (%s): %s", name, description, e)
            log("", exc_info=True)
            codec_errors[name] = e
            return None
        #module is present
        try:
            log(" %s found, will check for %s in %s", top_module, classnames, class_module)
            for classname in classnames:
                ic =  __import__(class_module, {}, {}, classname)
                selftest = getattr(ic, "selftest", None)
                log("%s.selftest=%s", name, selftest)
                if RUN_SELF_TESTS and selftest:
                    selftest()
                #log.warn("codec_import_check(%s, ..)=%s" % (name, ic))
                log(" found %s : %s", name, ic)
                codecs[name] = ic
                return ic
        except ImportError as e:
            codec_errors[name] = e
            l = log.warn
            if name in NOWARN:
                l = log.debug
            l(" cannot import %s (%s): %s", name, description, e)
            log("", exc_info=True)
    except Exception as e:
        codec_errors[name] = e
        log.warn(" cannot load %s (%s): %s missing from %s: %s", name, description, classname, class_module, e)
        log.warn("", exc_info=True)
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
        log("", exc_info=True)
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

        codec_import_check("enc_vpx", "vpx encoder", "xpra.codecs.vpx", "xpra.codecs.vpx.encoder", "Encoder")
        add_codec_version("vpx", "xpra.codecs.vpx.decoder")

        codec_import_check("enc_x264", "x264 encoder", "xpra.codecs.enc_x264", "xpra.codecs.enc_x264.encoder", "Encoder")
        add_codec_version("x264", "xpra.codecs.enc_x264.encoder")

        codec_import_check("enc_x265", "x265 encoder", "xpra.codecs.enc_x265", "xpra.codecs.enc_x265.encoder", "Encoder")
        add_codec_version("x265", "xpra.codecs.enc_x265.encoder")

        for v in (4, 5):
            codec_import_check("nvenc%s" % v, "nvenc encoder", "xpra.codecs.nvenc%s" % v, "xpra.codecs.nvenc%s.encoder" % v, "Encoder")
            add_codec_version("nvenc%s" % v, "xpra.codecs.nvenc%s.encoder" % v)

    if csc:
        show += list(CSC_CODECS)
        codec_import_check("csc_swscale", "swscale colorspace conversion", "xpra.codecs.csc_swscale", "xpra.codecs.csc_swscale.colorspace_converter", "ColorspaceConverter")
        add_codec_version("swscale", "xpra.codecs.csc_swscale.colorspace_converter")
    
        codec_import_check("csc_cython", "cython colorspace conversion", "xpra.codecs.csc_cython", "xpra.codecs.csc_cython.colorspace_converter", "ColorspaceConverter")
        add_codec_version("cython", "xpra.codecs.csc_cython.colorspace_converter")
    
        codec_import_check("csc_opencl", "OpenCL colorspace conversion", "xpra.codecs.csc_opencl", "xpra.codecs.csc_opencl.colorspace_converter", "ColorspaceConverter")
        add_codec_version("opencl", "xpra.codecs.csc_opencl.colorspace_converter")

    if decoders:
        show += list(DECODER_CODECS)
        codec_import_check("dec_pillow", "Pillow decoder", "xpra.codecs.pillow", "xpra.codecs.pillow.decode", "decode")
        add_codec_version("dec_pillow", "xpra.codecs.pillow.decode")

        codec_import_check("dec_webp", "webp decoder", "xpra.codecs.webp", "xpra.codecs.webp.decode", "decompress")
        add_codec_version("dec_webp", "xpra.codecs.webp.decode")

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
    for name in ALL_CODECS:
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


CSC_CODECS = "csc_swscale", "csc_cython", "csc_opencl"
ENCODER_CODECS = "enc_pillow", "enc_vpx", "enc_webp", "enc_x264", "enc_x265", "nvenc4", "nvenc5"
DECODER_CODECS = "dec_pillow", "dec_vpx", "dec_webp", "dec_avcodec2"

ALL_CODECS = tuple(set(CSC_CODECS + ENCODER_CODECS + DECODER_CODECS))

#note: this is just for defining the order of encodings,
#so we have both core encodings (rgb24/rgb32) and regular encodings (rgb) in here:
PREFERED_ENCODING_ORDER = ["h264", "vp9", "vp8", "png", "png/P", "png/L", "webp", "rgb", "rgb24", "rgb32", "jpeg", "h265"]
#encoding order for edges (usually one pixel high or wide):
EDGE_ENCODING_ORDER = ["rgb24", "rgb32", "jpeg", "png", "webp", "png/P", "png/L", "rgb"]


from xpra.net import compression
RGB_COMP_OPTIONS  = ["Raw RGB"]
if compression.get_enabled_compressors():
    RGB_COMP_OPTIONS  += ["/".join(compression.get_enabled_compressors())]

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
      "rgb"     : " + ".join(RGB_COMP_OPTIONS) + " (24/32bpp)",
    }

ENCODINGS_HELP = {
      "h264"    : "H.264 video codec",
      "h265"    : "H.265 (HEVC) video codec (slow and buggy - do not use!)",
      "vp8"     : "VP8 video codec",
      "vp9"     : "VP9 video codec",
      "png"     : "Portable Network Graphics (lossless, 24bpp or 32bpp for transparency)",
      "png/P"   : "Portable Network Graphics (lossy, 8bpp colour)",
      "png/L"   : "Portable Network Graphics (lossy, 8bpp grayscale)",
      "webp"    : "WebP compression (lossless or lossy)",
      "jpeg"    : "JPEG lossy compression",
      "rgb"     : "Raw RGB pixels, lossless, compressed using %s (24bpp or 32bpp for transparency)" % (" or ".join(compression.get_enabled_compressors())),
      }

HELP_ORDER = ("h264", "h265", "vp8", "vp9", "png", "png/P", "png/L", "webp", "rgb", "jpeg")

#those are currently so useless that we don't want the user to select them by mistake
PROBLEMATIC_ENCODINGS = ("h265", )


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
                        print("                         %s" % ", ".join(list(set(cs))))
                    elif name.find("enc")>=0 or name.find("dec")>=0:
                        encodings = mod.get_encodings()
                        print("                         %s" % ", ".join(encodings))
                    try:
                        i = mod.get_info()
                        print("                         %s" % i)
                    except:
                        pass
                except Exception as e:
                    print("error getting extra information on %s: %s" % (name, e))
        print("")
        print("codecs versions:")
        def pver(v):
            if type(v)==tuple:
                return ".".join([str(x) for x in v])
            elif type(v) in (str, unicode) and v.startswith("v"):
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
