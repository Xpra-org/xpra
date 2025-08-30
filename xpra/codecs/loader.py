#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path
from types import ModuleType
from typing import Any
from importlib import import_module
from collections.abc import Sequence, Iterable

from xpra.common import noop
from xpra.util.str_fn import csv, print_nested_dict, pver
from xpra.util.env import envbool, numpy_import_context
from xpra.os_util import OSX, WIN32
from xpra.util.version import parse_version
from xpra.codecs.constants import HELP_ORDER
from xpra.log import Logger, enable_color, LOG_FORMAT, NOPREFIX_FORMAT
log = Logger("codec", "loader")


# these codecs may well not load because we
# do not require the libraries to be installed
NOWARN = [
    "nvenc", "nvdec", "enc_nvjpeg",
    "dec_nvjpeg", "nvfbc", "dec_openh264",
    "enc_gstreamer", "dec_gstreamer",
    "csc_cython", "dec_avif", "enc_avif",
    "enc_amf",
]

SELFTEST = envbool("XPRA_CODEC_SELFTEST", True)
FULL_SELFTEST = envbool("XPRA_CODEC_FULL_SELFTEST", False)

CODEC_FAIL_IMPORT = os.environ.get("XPRA_CODEC_FAIL_IMPORT", "").split(",")
CODEC_FAIL_SELFTEST = os.environ.get("XPRA_CODEC_FAIL_SELFTEST", "").split(",")

log(f"codec loader settings: {SELFTEST=}, {FULL_SELFTEST=}, {CODEC_FAIL_IMPORT=}, {CODEC_FAIL_SELFTEST=}")


SKIP_LIST: Sequence[str] = ()
if OSX:
    SKIP_LIST = ("avif", "nvenc", "nvdec", "nvjpeg")


def autoprefix(prefix: str, name: str) -> str:
    return (name if (name.startswith(prefix) or name.endswith(prefix)) else f"{prefix}_{name}").replace("-", "_")


def filt(*values) -> tuple[str, ...]:
    return tuple(x for x in values if all(x.find(s) < 0 for s in SKIP_LIST))


def gfilt(generator) -> tuple[str, ...]:
    return filt(*generator)


CSC_CODECS: Sequence[str] = gfilt(f"csc_{x}" for x in ("cython", "libyuv"))
ENCODER_CODECS: Sequence[str] = gfilt(f"enc_{x}" for x in (
    "rgb", "pillow", "spng", "webp", "jpeg", "nvjpeg", "avif",
))
ENCODER_VIDEO_CODECS: Sequence[str] = gfilt(autoprefix("enc", x) for x in (
    "vpx", "x264", "openh264", "nvenc", "gstreamer", "amf", "remote",
))
DECODER_CODECS: Sequence[str] = gfilt(f"dec_{x}" for x in (
    "pillow", "spng", "webp", "jpeg", "nvjpeg", "avif", "gstreamer",
))
DECODER_VIDEO_CODECS: Sequence[str] = gfilt(autoprefix("dec", x) for x in (
    "vpx", "openh264", "nvdec", "aom",
))
SOURCES: Sequence[str] = filt("v4l2", "evdi", "drm", "nvfbc")

ALL_CODECS: Sequence[str] = filt(*set(
    CSC_CODECS + ENCODER_CODECS + ENCODER_VIDEO_CODECS + DECODER_CODECS + DECODER_VIDEO_CODECS + SOURCES)
)


codec_errors: dict[str, str] = {}
codecs: dict[str, ModuleType] = {}


def should_warn(name: str) -> bool:
    if name in NOWARN:
        return False
    if name in ("csc_cython", "dec_avif") or name.find("enc") >= 0 or name.startswith("nv"):
        try:
            import_module("xpra.server")
        except ImportError:
            # no server support,
            # probably a 'Light' build
            return False
    return True


def pillow_import_block() -> None:
    # the only ones we want to keep:
    # "Bmp", "Gif", "Ppm", "Png", "Jpeg", "Xpm"
    for image_plugin in (
        "Blp", "Cur", "Pcx", "Dcx", "Dds", "Eps", "Fits", "Fli",
        "Fpx", "Ftex", "Gbr", "Jpeg2K", "Icns", "Ico",
        "Im", "Imt",
        "Iptc", "McIdas", "Mic", "Mpeg", "Tiff", "Mpo", "Msp",
        "Palm", "Pcd", "Pdf", "Pixar", "Psd", "Qoi",
        "Sgi", "Spider", "Sun", "Tga",
        "Wmf", "Xbm", "XVThumb",
    ):
        # noinspection PyTypeChecker
        sys.modules[f"PIL.{image_plugin}ImagePlugin"] = None


PIL_BLOCK = envbool("XPRA_PIL_BLOCK", True)
if PIL_BLOCK:
    pillow_import_block()


def codec_import_check(name: str, description: str, top_module: str, class_module: str,
                       attrs: Sequence[str], options: dict):
    log(f"{name}:")
    log(" codec_import_check%s", (name, description, top_module, class_module, attrs))
    if any(name.find(s) >= 0 for s in SKIP_LIST):
        log(f" skipped from list: {csv(SKIP_LIST)}")
        return None
    try:
        if name in CODEC_FAIL_IMPORT:
            raise ImportError("codec found in fail import list")
        module = import_module(top_module)
        log(f"imported {module!r}")
    except ImportError as e:
        log(f"failed to import {name} ({description})")
        log("", exc_info=True)
        codec_errors[name] = str(e)
        return None
    except Exception as e:
        log.warn(f" cannot load {name} ({description}):", exc_info=True)
        codec_errors[name] = str(e)
        return None
    attr = None
    try:
        log(f" {top_module} found, will check for {attrs} in {class_module}")
        ic = import_module(class_module)

        init_module = getattr(ic, "init_module", noop)
        log(f"{ic}.init_module={init_module}")
        init_module(options)

        if log.is_debug_enabled():
            # try to enable debugging on the codec's own logger:
            module_logger = getattr(ic, "log", None)
            log(f"{class_module}.log={module_logger}")
            if module_logger:
                module_logger.enable_debug()

        for attr in attrs:
            try:
                clazz = getattr(ic, attr)
            except AttributeError:
                raise ImportError(f"cannot find {attr!r} in {ic}") from None
            log(f"{class_module}.{attr}={clazz}")

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

        log(f" found {name} : {ic}")
        codecs[name] = ic
        return ic
    except ImportError as e:
        codec_errors[name] = str(e)
        log_fn = log.error if should_warn(name) else log.debug
        log_fn(f"Error importing {name} ({description})")
        log_fn(f" {e}")
        log("", exc_info=True)
    except Exception as e:
        codec_errors[name] = str(e)
        if attr:
            log.warn(f" cannot load {name} ({description}): {attr} missing from {class_module}", exc_info=True)
        else:
            log.warn(f" cannot load {name} ({description})", exc_info=True)
    return None


codec_versions: dict[str, Iterable[Any]] = {}


def add_codec_version(name: str, top_module, version: str = "get_version()", alt_version: str = "__version__") -> None:
    try:
        fieldnames = [x for x in (version, alt_version) if x is not None]
        for fieldname in fieldnames:
            f = fieldname
            if f.endswith("()"):
                f = version[:-2]
            module = import_module(top_module)
            if not hasattr(module, f):
                continue
            v = getattr(module, f)
            log(f"{module}.{f}={v}")
            if fieldname.endswith("()") and v:
                log(f"calling {v}")
                v = v()
            codec_versions[name] = parse_version(v)
            # optional info:
            if hasattr(module, "get_info"):
                info = getattr(module, "get_info")
                log(f" {name} {top_module}.{info}={info()}")
            return
        if name in codecs:
            log.warn(f" cannot find %s in {top_module}", " or ".join(fieldnames))
        else:
            log(f" no version information for missing codec {name}")
    except ImportError as e:
        # not present
        log(f" cannot import {name}: {e}")
        log("", exc_info=True)
    except Exception as e:
        log.warn(f"error during {name} codec import: %s", e)
        log.warn("", exc_info=True)


platformname = sys.platform.rstrip("0123456789")


CODEC_OPTIONS: dict[str, tuple[str, str, str, str]] = {
    # encoders:
    "enc_rgb"       : ("RGB encoder",       "argb",         "encoder", "encode"),
    "enc_pillow"    : ("Pillow encoder",    "pillow",       "encoder", "encode"),
    "enc_spng"      : ("png encoder",       "spng",         "encoder", "encode"),
    "enc_webp"      : ("webp encoder",      "webp",         "encoder", "encode"),
    "enc_jpeg"      : ("JPEG encoder",      "jpeg",         "encoder", "encode"),
    "enc_avif"      : ("avif encoder",      "avif",         "encoder", "encode"),
    "enc_nvjpeg"    : ("nvjpeg encoder",    "nvidia.nvjpeg", "encoder", "encode"),
    # video encoders:
    "enc_vpx"       : ("vpx encoder",       "vpx",          "encoder", "Encoder"),
    "enc_x264"      : ("x264 encoder",      "x264",         "encoder", "Encoder"),
    "enc_openh264"  : ("openh264 encoder",  "openh264",     "encoder", "Encoder"),
    "nvenc"         : ("nvenc encoder",     "nvidia.nvenc", "encoder", "Encoder"),
    "enc_gstreamer" : ("gstreamer encoder", "gstreamer",    "encoder", "Encoder"),
    "enc_amf"       : ("amf encoder",       "amf",          "encoder", "Encoder"),
    "enc_remote"    : ("remote encoder",    "remote",       "encoder", "Encoder"),
    # csc:
    "csc_libyuv"    : ("libyuv colorspace conversion", "libyuv", "converter", "Converter"),
    "csc_cython"    : ("cython colorspace conversion", "csc_cython", "converter", "Converter"),
    # decoders:
    "dec_pillow"    : ("Pillow decoder",    "pillow",       "decoder", "decompress"),
    "dec_spng"      : ("png decoder",       "spng",         "decoder", "decompress"),
    "dec_webp"      : ("webp decoder",      "webp",         "decoder", "decompress_to_rgb,decompress_to_yuv"),
    "dec_jpeg"      : ("JPEG decoder",      "jpeg",         "decoder", "decompress_to_rgb,decompress_to_yuv"),
    "dec_avif"      : ("avif decoder",      "avif",         "decoder", "decompress"),
    "dec_nvjpeg"    : ("nvjpeg decoder",    "nvidia.nvjpeg", "decoder", "decompress"),
    # video decoders:
    "dec_vpx"       : ("vpx decoder",       "vpx",          "decoder", "Decoder"),
    "dec_openh264"  : ("openh264 decoder",  "openh264",     "decoder", "Decoder"),
    "nvdec"         : ("nvdec decoder",     "nvidia.nvdec", "decoder", "Decoder"),
    "dec_gstreamer" : ("gstreamer decoder", "gstreamer",    "decoder", "Decoder"),
    "dec_aom"       : ("aom decoder",       "aom",          "decoder", "Decoder"),
    # sources:
    "v4l2"          : ("v4l2 source",       "v4l2",         "virtual", "VirtualWebcam"),
    "evdi"          : ("evdi source",       "evdi",         "capture", "EvdiDevice"),
    "drm"           : ("drm device query",  "drm",          "drm",      "query"),
    "nvfbc"         : ("NVIDIA Capture SDK", "nvidia.nvfbc", f"capture_{platformname}", "NvFBC_SysCapture"),
}

NOLOAD: list[str] = []
if OSX:
    # none of the nvidia codecs are available on MacOS,
    # so don't bother trying:
    NOLOAD += ["nvenc", "enc_nvjpeg", "dec_nvjpeg", "nvfbc"]
if OSX or WIN32:
    # these sources can only be used on Linux
    # (and maybe on some BSDs?)
    NOLOAD += ["v4l2", "evdi", "drm"]


def load_codec(name: str, options: dict | None = None):
    log("load_codec(%s, %s)", name, options)
    name = name.replace("-", "_")
    if not has_codec(name):
        try:
            description, top_module, class_module, attrs_names = CODEC_OPTIONS[name]
            attrs = attrs_names.split(",")
        except KeyError:
            log("load_codec(%s)", name, exc_info=True)
            log.error("Error: invalid codec name '%s'", name)
            return None
        xpra_top_module = f"xpra.codecs.{top_module}"
        xpra_class_module = f"{xpra_top_module}.{class_module}"
        if codec_import_check(name, description, xpra_top_module, xpra_class_module, attrs, options or {}):
            version_name = name
            if name.startswith("enc_") or name.startswith("dec_") or name.startswith("csc_"):
                version_name = name[4:]
            add_codec_version(version_name, xpra_class_module)
    return get_codec(name)


def load_codecs(encoders=True, decoders=True, csc=True, video=True, sources=False) -> Sequence[str]:
    log("loading codecs")
    loaded: list[str] = []

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


def unload_codecs() -> None:
    global codecs
    log(f"unload_codecs() {codecs=}")
    copy = codecs
    codecs = {}
    for name, module in copy.items():
        cleanup_module = getattr(module, "cleanup_module", noop)
        try:
            log(f"{name} cleanup_module={cleanup_module}")
            cleanup_module()
        except RuntimeError as e:
            log(f"{cleanup_module}()", exc_info=True)
            log.warn(f"Warning: error during {name!r} module cleanup")
            log.warn(f" {e}")


def show_codecs(show: Iterable[str] = ()) -> None:
    for name in sorted(show or ALL_CODECS):
        log(f"* {name.ljust(20)} : {str(name in codecs).ljust(10)} {codecs.get(name, '')}")
    log("codecs versions:")
    for name in (show or codec_versions.keys()):
        version = codec_versions.get(name, "")
        log(f"* {name.ljust(20)} : {version}")


def get_codec_error(name: str) -> str:
    return codec_errors.get(name, "")


def get_codec(name: str):
    if name not in CODEC_OPTIONS:
        log.warn(f"Warning: invalid codec name {name}")
    return codecs.get(name)


def get_codec_version(name: str):
    return codec_versions.get(name)


def has_codec(name: str) -> bool:
    return name in codecs


def get_rgb_compression_options() -> list[str]:
    # pylint: disable=import-outside-toplevel
    from xpra.net import compression
    compressors = compression.get_enabled_compressors()
    compressors = tuple(x for x in compressors if x != "brotli")
    RGB_COMP_OPTIONS: list[str] = ["Raw RGB"]
    if compressors:
        RGB_COMP_OPTIONS += ["/".join(compressors)]
    return RGB_COMP_OPTIONS


def get_encoding_name(encoding: str) -> str:
    ENCODINGS_TO_NAME : dict[str, str] = {
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


def get_encoding_help(encoding: str) -> str:
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
        "rgb"     : f"Raw RGB pixels, lossless {compressors_str}(24bpp or 32bpp for transparency)",
        "scroll"  : "motion vectors, supplemented with picture codecs",
    }.get(encoding, "")


def encodings_help(encodings: Iterable[str]) -> list[str]:
    h = []
    for e in HELP_ORDER:
        if e in encodings:
            h.append(encoding_help(e))
    return h


def encoding_help(encoding: str) -> str:
    ehelp = get_encoding_help(encoding) or ""
    return encoding.ljust(12) + ehelp


def main(args) -> int:
    # pylint: disable=import-outside-toplevel
    from xpra.platform import program_context
    with program_context("Loader", "Encoding Info"):
        verbose = "-v" in args or "--verbose" in args
        args = [x for x in args if x not in ("-v", "--verbose")]
        format_string = NOPREFIX_FORMAT
        if verbose:
            global FULL_SELFTEST
            FULL_SELFTEST = True
            format_string = LOG_FORMAT
            log.enable_debug()
            from xpra.codecs.checks import log as check_log
            check_log.enable_debug()
        enable_color(format_string=format_string)

        from xpra.os_util import gi_import
        GLib = gi_import("GLib")
        main_loop = GLib.MainLoop()

        def load_in_thread() -> None:
            codecs = do_main_load(args)
            print_codecs(codecs)
            unload_codecs()
            main_loop.quit()

        from xpra.util.thread import start_thread
        start_thread(load_in_thread, "threaded loader")

        main_loop.run()
        return 0


def do_main_load(args) -> Sequence[str]:
    if len(args) > 1:
        names = []
        for x in args[1:]:
            name = x.lower().replace("-", "_")
            if name not in CODEC_OPTIONS:
                loose_matches = tuple(o for o in (
                    f"enc_{name}", f"dec_{name}", f"csc_{name}"
                ) if o in CODEC_OPTIONS)
                if len(loose_matches) == 1:
                    name = loose_matches[0]
                elif len(loose_matches) > 1:
                    log.warn(f"{x} matches: "+csv(loose_matches))
            load_codec(name)
            names.append(name)
        return tuple(names)
    try:
        load_codecs(sources=True)
    except KeyboardInterrupt:
        return ()
    # not really a codec, but gets used by codecs, so include version info:
    with numpy_import_context("codec loader"):
        add_codec_version("numpy", "numpy")
    return ALL_CODECS


def print_codecs(list_codecs: Sequence[str]) -> None:
    # use another logger for printing the results,
    # and use debug level by default, which shows up as green
    out = Logger("encoding")
    out.enable_debug()
    enable_color(format_string=NOPREFIX_FORMAT)
    out.info("modules found:")
    for name in sorted(list_codecs):
        mod : ModuleType | None = codecs.get(name)
        f = str(mod)
        if mod and hasattr(mod, "__file__"):
            f = getattr(mod, "__file__", f)
            if f.startswith(os.getcwd()):
                f = f[len(os.getcwd()):]
                if f.startswith(os.path.sep):
                    f = f[1:]
        if name in NOLOAD and not f:
            # don't show codecs from the NOLOAD list
            continue
        if mod:
            out.info(f"* {name.ljust(20)} : {f}")
            if log.is_debug_enabled():
                try:
                    if name.find("csc") >= 0:
                        cs = []
                        for spec in list(mod.get_specs()):
                            cs.append(spec.input_colorspace)
                        out(f"                         colorspaces: {csv(list(set(cs)))}")
                    elif name.find("enc") >= 0 or name.find("dec") >= 0:
                        encodings = mod.get_encodings()
                        out(f"                         encodings: {csv(encodings)}")
                    try:
                        i = mod.get_info()
                        for k, v in sorted(i.items()):
                            out(f"                         {k} = {v}")
                    except (AttributeError, RuntimeError):
                        pass
                except Exception as e:
                    log(f"{mod}", exc_info=True)
                    log.error(f"error getting extra information on {name}: {e}")
        elif name in codec_errors:
            write = out.error if should_warn(name) else out.debug
            write(f"* {name.ljust(20)} : {codec_errors[name]}")
    out("")
    out.info("codecs versions:")

    def forcever(v) -> str:
        return pver(v, numsep=".", strsep=".").lstrip("v")
    print_nested_dict(codec_versions, vformat=forcever, print_fn=out.info)


if __name__ == "__main__":
    main(sys.argv)
