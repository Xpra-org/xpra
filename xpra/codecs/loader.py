#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2010-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path
from types import ModuleType
from typing import Tuple, List, Dict, Any

from xpra.util import envbool, csv
from xpra.os_util import OSX, WIN32
from xpra.version_util import parse_version
from xpra.codecs.codec_constants import HELP_ORDER
from xpra.log import Logger
log = Logger("codec", "loader")


#these codecs may well not load because we
#do not require the libraries to be installed
NOWARN = ["nvenc", "nvdec", "enc_nvjpeg", "dec_nvjpeg", "nvfbc", "dec_openh264", "enc_ffmpeg", "enc_gstreamer", "dec_gstreamer", "csc_cython", "dec_avif", "enc_avif"]

SELFTEST = envbool("XPRA_CODEC_SELFTEST", True)
FULL_SELFTEST = envbool("XPRA_CODEC_FULL_SELFTEST", False)

CODEC_FAIL_IMPORT = os.environ.get("XPRA_CODEC_FAIL_IMPORT", "").split(",")
CODEC_FAIL_SELFTEST = os.environ.get("XPRA_CODEC_FAIL_SELFTEST", "").split(",")

log("codec loader settings: SELFTEST=%s, FULL_SELFTEST=%s, CODEC_FAIL_IMPORT=%s, CODEC_FAIL_SELFTEST=%s",
        SELFTEST, FULL_SELFTEST, CODEC_FAIL_IMPORT, CODEC_FAIL_SELFTEST)


SKIP_LIST : Tuple[str,...] = ()
if OSX:
    SKIP_LIST = ("avif", "nvenc", "nvdec", "nvjpeg")
def filt(*values) -> Tuple[str,...]:
    return tuple(x for x in values if all(x.find(s)<0 for s in SKIP_LIST))

CSC_CODECS : Tuple[str,...] = filt("csc_swscale", "csc_cython", "csc_libyuv")
ENCODER_CODECS : Tuple[str,...] = filt("enc_rgb", "enc_pillow", "enc_spng", "enc_webp", "enc_jpeg", "enc_nvjpeg", "enc_avif")
ENCODER_VIDEO_CODECS : Tuple[str,...] = filt("enc_vpx", "enc_x264", "enc_openh264", "nvenc", "enc_ffmpeg", "enc_gstreamer")
DECODER_CODECS : Tuple[str,...] = filt("dec_pillow", "dec_spng", "dec_webp", "dec_jpeg", "dec_nvjpeg", "dec_avif", "dec_gstreamer")
DECODER_VIDEO_CODECS : Tuple[str,...] = filt("dec_vpx", "dec_avcodec2", "dec_openh264", "nvdec")
SOURCES : Tuple[str,...] = filt("v4l2", "evdi", "drm", "nvfbc")

ALL_CODECS : Tuple[str,...] = filt(*set(
    CSC_CODECS +
    ENCODER_CODECS +
    ENCODER_VIDEO_CODECS +
    DECODER_CODECS +
    DECODER_VIDEO_CODECS +
    SOURCES))


codec_errors : Dict[str,str] = {}
codecs : Dict[str,ModuleType] = {}
def codec_import_check(name:str, description:str, top_module, class_module, classnames):
    log(f"{name}:")
    log(" codec_import_check%s", (name, description, top_module, class_module, classnames))
    if any(name.find(s)>=0 for s in SKIP_LIST):
        log(f" skipped from list: {csv(SKIP_LIST)}")
        return None
    try:
        try:
            if name in CODEC_FAIL_IMPORT:
                raise ImportError("codec found in fail import list")
            __import__(top_module, {}, {}, [])
        except ImportError as e:
            log(f"failed to import {name} ({description})")
            log("", exc_info=True)
            codec_errors[name] = str(e)
            return None
    except Exception as e:
        log.warn(f" cannot load {name} ({description}):", exc_info=True)
        codec_errors[name] = str(e)
        return None
    classname = None
    try:
        try:
            log(f" {top_module} found, will check for {classnames} in {class_module}")
            ic : ModuleType =  __import__(class_module, {}, {}, classnames)
            try:
                #run init_module?
                init_module = getattr(ic, "init_module", None)
                log(f"{class_module}.init_module={init_module}")
                if init_module:
                    init_module()

                if log.is_debug_enabled():
                    #try to enable debugging on the codec's own logger:
                    module_logger = getattr(ic, "log", None)
                    log(f"{class_module}.log={module_logger}")
                    if module_logger:
                        module_logger.enable_debug()

                if classnames:
                    for classname in classnames:
                        try:
                            clazz = getattr(ic, classname)
                        except AttributeError:
                            raise ImportError(f"cannot find {classname!r} in {ic}") from None
                        log(f"{class_module}.{classname}={clazz}")

                selftest = getattr(ic, "selftest", None)
                log(f"{name}.selftest={selftest}")
                if SELFTEST and selftest:
                    if name in CODEC_FAIL_SELFTEST:
                        raise ImportError("codec found in fail selftest list")
                    try:
                        selftest(FULL_SELFTEST)
                    except Exception as e:
                        log(f"{selftest} failed", exc_info=True)
                        if not isinstance(e, ImportError):
                            log.warn(f"Warning: {name} failed its self test")
                            for x in str(e).splitlines():
                                log.warn(f" {x}")
                        return None
            finally:
                cleanup_module = getattr(ic, "cleanup_module", None)
                log(f"{class_module} cleanup_module={cleanup_module}")
                if cleanup_module:
                    cleanup_module()
            #log.warn("codec_import_check(%s, ..)=%s" % (name, ic))
            log(f" found {name} : {ic}")
            codecs[name] = ic
            return ic
        except ImportError as e:
            codec_errors[name] = str(e)
            l = log.error
            if name in NOWARN:
                l = log.debug
            l(f"Error importing {name} ({description})")
            l(f" {e}")
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
codec_versions : Dict[str,Tuple[Any, ...]]= {}
def add_codec_version(name:str, top_module, version:str="get_version()", alt_version:str="__version__"):
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
            codec_versions[name] = parse_version(v)
            #optional info:
            if hasattr(module, "get_info"):
                info = getattr(module, "get_info")
                log(f" {name} {top_module}.{info}={info()}")
            return v
        if name in codecs:
            log.warn(f" cannot find %s in {top_module}", " or ".join(fieldnames))
        else:
            log(f" no version information for missing codec {name}")
    except ImportError as e:
        #not present
        log(f" cannot import {name}: {e}")
        log("", exc_info=True)
    except Exception as e:
        log.warn("error during codec import: %s", e)
        log.warn("", exc_info=True)
    return None

def xpra_codec_import(name:str, description:str, top_module, class_module, classnames):
    xpra_top_module = f"xpra.codecs.{top_module}"
    xpra_class_module = f"{xpra_top_module}.{class_module}"
    if codec_import_check(name, description, xpra_top_module, xpra_class_module, classnames):
        version_name = name
        if name.startswith("enc_") or name.startswith("dec_") or name.startswith("csc_"):
            version_name = name[4:]
        add_codec_version(version_name, xpra_class_module)

platformname = sys.platform.rstrip("0123456789")

CODEC_OPTIONS : Dict[str,Tuple[str,str,str,str]] = {
    #encoders:
    "enc_rgb"       : ("RGB encoder",       "argb",         "encoder", "encode"),
    "enc_pillow"    : ("Pillow encoder",    "pillow",       "encoder", "encode"),
    "enc_spng"      : ("png encoder",       "spng",         "encoder", "encode"),
    "enc_webp"      : ("webp encoder",      "webp",         "encoder", "encode"),
    "enc_jpeg"      : ("JPEG encoder",      "jpeg",         "encoder", "encode"),
    "enc_avif"      : ("avif encoder",      "avif",         "encoder", "encode"),
    "enc_nvjpeg"    : ("nvjpeg encoder",    "nvidia.nvjpeg","encoder", "encode"),
    #video encoders:
    "enc_vpx"       : ("vpx encoder",       "vpx",          "encoder", "Encoder"),
    "enc_x264"      : ("x264 encoder",      "x264",         "encoder", "Encoder"),
    "enc_openh264"  : ("openh264 encoder",  "openh264",     "encoder", "Encoder"),
    "nvenc"         : ("nvenc encoder",     "nvidia.nvenc", "encoder", "Encoder"),
    "enc_ffmpeg"    : ("ffmpeg encoder",    "ffmpeg",       "encoder", "Encoder"),
    "enc_gstreamer" : ("gstreamer encoder", "gstreamer",    "encoder", "Encoder"),
    #csc:
    "csc_swscale"   : ("swscale colorspace conversion", "ffmpeg", "colorspace_converter", "ColorspaceConverter"),
    "csc_libyuv"    : ("libyuv colorspace conversion", "libyuv", "colorspace_converter", "ColorspaceConverter"),
    "csc_cython"    : ("cython colorspace conversion", "csc_cython", "colorspace_converter", "ColorspaceConverter"),
    #decoders:
    "dec_pillow"    : ("Pillow decoder",    "pillow",       "decoder", "decompress"),
    "dec_spng"      : ("png decoder",       "spng",         "decoder", "decompress"),
    "dec_webp"      : ("webp decoder",      "webp",         "decoder", "decompress"),
    "dec_jpeg"      : ("JPEG decoder",      "jpeg",         "decoder", "decompress_to_rgb,decompress_to_yuv"),
    "dec_avif"      : ("avif decoder",      "avif",         "decoder", "decompress"),
    "dec_nvjpeg"    : ("nvjpeg decoder",    "nvidia.nvjpeg","decoder", "decompress"),
    #video decoders:
    "dec_vpx"       : ("vpx decoder",       "vpx",          "decoder", "Decoder"),
    "dec_avcodec2"  : ("avcodec2 decoder",  "ffmpeg",       "decoder", "Decoder"),
    "dec_openh264"  : ("openh264 decoder",  "openh264",     "decoder", "Decoder"),
    "nvdec"         : ("nvdec decoder",     "nvidia.nvdec", "decoder", "Decoder"),
    "dec_gstreamer" : ("gstreamer decoder", "gstreamer",    "decoder", "Decoder"),
    #sources:
    "v4l2"          : ("v4l2 source",       "v4l2",         "pusher", "Pusher"),
    "evdi"          : ("evdi source",       "evdi",         "capture", "EvdiDevice"),
    "drm"           : ("drm device query",  "drm",          "drm",      "query"),
    "nvfbc"         : ("NVIDIA Capture SDK","nvidia.nvfbc", f"fbc_capture_{platformname}", "NvFBC_SysCapture"),
    }

NOLOAD : List[str] = []
if OSX:
    #none of the nvidia codecs are available on MacOS,
    #so don't bother trying:
    NOLOAD += ["nvenc", "enc_nvjpeg", "dec_nvjpeg", "nvfbc"]
if OSX or WIN32:
    #these sources can only be used on Linux
    #(and maybe on some BSDs?)
    NOLOAD += ["v4l2", "evdi", "drm"]


def load_codec(name:str):
    log("load_codec(%s)", name)
    name = name.replace("-", "_")
    if not has_codec(name):
        try:
            description, top_module, class_module, classnames_str = CODEC_OPTIONS[name]
            classnames = classnames_str.split(",")
        except KeyError:
            log("load_codec(%s)", name, exc_info=True)
            log.error("Error: invalid codec name '%s'", name)
        else:
            xpra_codec_import(name, description, top_module, class_module, classnames)
    return get_codec(name)


def load_codecs(encoders=True, decoders=True, csc=True, video=True, sources=False) -> Tuple[str,...]:
    log("loading codecs")
    loaded : List[str] = []
    def load(*names):
        for name in names:
            if has_codec(name):
                continue
            if name in NOLOAD:
                log(f"{name} is in the NOLOAD list for this platform: {NOLOAD}")
                continue
            load_codec(name)
            if has_codec(name) and name not in loaded:
                loaded.append(name)

    if encoders:
        load(*ENCODER_CODECS)
        if video:
            load(*ENCODER_VIDEO_CODECS)
    if csc and video:
        load(*CSC_CODECS)
    if decoders:
        load(*DECODER_CODECS)
        if video:
            load(*DECODER_VIDEO_CODECS)
    if sources:
        load(*SOURCES)
    log("done loading codecs: %s", loaded)
    return tuple(loaded)

def show_codecs(show:Tuple[str,...]=()) -> None:
    #print("codec_status=%s" % codecs)
    for name in sorted(show or ALL_CODECS):
        log(f"* {name.ljust(20)} : {str(name in codecs).ljust(10)} {codecs.get(name, '')}")
    log("codecs versions:")
    for name in (show or codec_versions.keys()):
        version = codec_versions.get(name, "")
        log(f"* {name.ljust(20)} : {version}")


def get_codec_error(name:str) -> str:
    return codec_errors.get(name, "")

def get_codec(name:str):
    if name not in CODEC_OPTIONS:
        log.warn(f"Warning: invalid codec name {name}")
    return codecs.get(name)

def get_codec_version(name:str):
    return codec_versions.get(name)

def has_codec(name:str) -> bool:
    return name in codecs


def get_rgb_compression_options() -> List[str]:
    # pylint: disable=import-outside-toplevel
    from xpra.net import compression
    compressors = compression.get_enabled_compressors()
    compressors = tuple(x for x in compressors if x!="brotli")
    RGB_COMP_OPTIONS : List[str] = ["Raw RGB"]
    if compressors:
        RGB_COMP_OPTIONS  += ["/".join(compressors)]
    return RGB_COMP_OPTIONS

def get_encoding_name(encoding:str) -> str:
    ENCODINGS_TO_NAME : Dict[str,str] = {
          "auto"    : "automatic",
          "stream"  : "video stream",
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
          "jpega"   : "JPEG with alpha",
          "avif"    : "AVIF",
          "av1"     : "AV1",
          "rgb"     : " + ".join(get_rgb_compression_options()) + " (24/32bpp)",
        }
    return ENCODINGS_TO_NAME.get(encoding, encoding)

def get_encoding_help(encoding:str) -> str:
    # pylint: disable=import-outside-toplevel
    from xpra.net import compression
    compressors = [x for x in compression.get_enabled_compressors()
                   if x not in ("brotli", "none")]
    compressors_str = ""
    if compressors:
        compressors_str = ", may be compressed using "+(" or ".join(compressors))+" "
    return {
          "auto"    : "automatic mode (recommended)",
          "stream"  : "video stream",
          "grayscale" : "same as 'auto' but in grayscale mode",
          "h264"    : "H.264 video codec",
          "h265"    : "H.265 (HEVC) video codec (not recommended)",
          "vp8"     : "VP8 video codec",
          "vp9"     : "VP9 video codec",
          "mpeg4"   : "MPEG-4 video codec",
          "png"     : "Portable Network Graphics (lossless, 24bpp or 32bpp for transparency)",
          "png/P"   : "Portable Network Graphics (lossy, 8bpp colour)",
          "png/L"   : "Portable Network Graphics (lossy, 8bpp grayscale)",
          "webp"    : "WebP compression (supports lossless and lossy modes)",
          "jpeg"    : "JPEG lossy compression",
          "jpega"   : "JPEG lossy compression, with alpha channel",
          "avif"    : "AVIF: AV1 Image File Format",
          "av1"     : "AV1: AOMedia Video 1",
          "rgb"     : "Raw RGB pixels, lossless"
                      +f"{compressors_str}(24bpp or 32bpp for transparency)",
          "scroll"  : "motion vectors, supplemented with picture codecs",
          }.get(encoding, "")


def encodings_help(encodings) -> List[str]:
    h = []
    for e in HELP_ORDER:
        if e in encodings:
            h.append(encoding_help(e))
    return h

def encoding_help(encoding:str) -> str:
    ehelp = get_encoding_help(encoding) or ""
    return encoding.ljust(12) + ehelp



def main(args) -> int:
    # pylint: disable=import-outside-toplevel
    from xpra.platform import program_context
    from xpra.log import enable_color, LOG_FORMAT, NOPREFIX_FORMAT
    from xpra.util import print_nested_dict, pver
    with program_context("Loader", "Encoding Info"):
        verbose = "-v" in args or "--verbose" in args
        args = [x for x in args if x not in ("-v", "--verbose")]
        format_string = NOPREFIX_FORMAT
        if verbose:
            global FULL_SELFTEST
            FULL_SELFTEST = True
            format_string = LOG_FORMAT
            log.enable_debug()
            from xpra.codecs.codec_checks import log as check_log
            check_log.enable_debug()
        enable_color(format_string=format_string)

        if len(args)>1:
            names = []
            for x in args[1:]:
                name = x.lower().replace("-", "_")
                if name not in CODEC_OPTIONS:
                    loose_matches = tuple(o for o in (f"enc_{name}", f"dec_{name}", f"csc_{name}") if o in CODEC_OPTIONS)
                    if len(loose_matches)==1:
                        name = loose_matches[0]
                    elif len(loose_matches)>1:
                        log.warn(f"{x} matches: "+csv(loose_matches))
                load_codec(name)
                names.append(name)
            list_codecs = tuple(names)
        else:
            try:
                load_codecs(sources=True)
            except KeyboardInterrupt:
                return 1
            list_codecs = ALL_CODECS
            #not really a codec, but gets used by codecs, so include version info:
            add_codec_version("numpy", "numpy")

        #use another logger for printing the results,
        #and use debug level by default, which shows up as green
        out = Logger("encoding")
        out.enable_debug()
        enable_color(format_string=NOPREFIX_FORMAT)
        out.info("modules found:")
        #print("codec_status=%s" % codecs)
        for name in sorted(list_codecs):
            mod : Optional[ModuleType] = codecs.get(name)
            f = str(mod)
            if mod and hasattr(mod, "__file__"):
                f = getattr(mod, "__file__", f)
                if f.startswith(os.getcwd()):
                    f = f[len(os.getcwd()):]
                    if f.startswith(os.path.sep):
                        f = f[1:]
            if name in NOLOAD and not f:
                #don't show codecs from the NOLOAD list
                continue
            if mod:
                out(f"* {name.ljust(20)} : {f}")
                if verbose:
                    try:
                        if name.find("csc")>=0:
                            cs = list(mod.get_input_colorspaces())
                            for c in list(cs):
                                cs += list(mod.get_output_colorspaces(c))
                            out(f"                         colorspaces: {csv(list(set(cs)))}")
                        elif name.find("enc")>=0 or name.find("dec")>=0:
                            encodings = mod.get_encodings()
                            out(f"                         encodings: {csv(encodings)}")
                        try:
                            i = mod.get_info()
                            for k,v in sorted(i.items()):
                                out(f"                         {k} = {v}")
                        except Exception:
                            pass
                    except Exception as e:
                        log(f"{mod}", exc_info=True)
                        log.error(f"error getting extra information on {name}: {e}")
            elif name in codec_errors:
                out.error(f"* {name.ljust(20)} : {codec_errors[name]}")
        out("")
        out.info("codecs versions:")
        def forcever(v):
            return pver(v, numsep=".", strsep=".").lstrip("v")
        print_nested_dict(codec_versions, vformat=forcever, print_fn=out)
    return 0


if __name__ == "__main__":
    main(sys.argv)
