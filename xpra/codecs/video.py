#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import traceback
from threading import Lock
from typing import Any
from importlib.util import find_spec
from collections.abc import Callable, Sequence, Iterable

from xpra.common import Self
from xpra.codecs.constants import VideoSpec, CodecSpec, CSCSpec
from xpra.codecs.loader import load_codec, get_codec, get_codec_error, autoprefix, unload_codecs
from xpra.util.parsing import parse_simple_dict
from xpra.util.str_fn import csv, print_nested_dict
from xpra.log import Logger

log = Logger("codec", "video")

# the codec loader uses the names...
# but we need the module name to be able to probe without loading the codec:
CODEC_TO_MODULE: dict[str, str] = {
    "enc_vpx"       : "vpx.encoder",
    "dec_vpx"       : "vpx.decoder",
    "enc_x264"      : "x264.encoder",
    "enc_openh264"  : "openh264.encoder",
    "nvenc"         : "nvidia.nvenc",
    "nvdec"         : "nvidia.nvdec",
    "csc_cython"    : "csc_cython.converter",
    "csc_libyuv"    : "libyuv.converter",
    "dec_openh264"  : "openh264.decoder",
    "enc_jpeg"      : "jpeg.encoder",
    "enc_webp"      : "webp.encoder",
    "enc_nvjpeg"    : "nvidia.nvjpeg.encoder",
    "dec_nvjpeg"    : "nvidia.nvjpeg.decoder",
    "dec_gstreamer" : "gstreamer.decoder",
    "enc_gstreamer" : "gstreamer.encoder",
    "enc_remote"    : "remote.encoder",
}


def has_codec_module(module_name: str) -> bool:
    top_module = f"xpra.codecs.{module_name}"
    try:
        found = bool(find_spec(top_module))
        log("%s found: %s", module_name, found)
        return True
    except Exception as e:
        log("codec module %s cannot be loaded: %s", module_name, e)
        return False


def try_import_modules(prefix: str, *codec_names: str) -> list[str]:
    names = []
    for codec_name in codec_names:
        codec_name = autoprefix(prefix, codec_name)
        module_name = CODEC_TO_MODULE[codec_name]
        if has_codec_module(module_name):
            names.append(codec_name)
    return names


# all the codecs we know about:
ALL_VIDEO_ENCODER_OPTIONS: Sequence[str] = ("x264", "openh264", "vpx", "nvenc", "nvjpeg", "jpeg", "webp", "gstreamer", "remote")
HARDWARE_ENCODER_OPTIONS: Sequence[str] = ("nvenc", "nvjpeg")
ALL_CSC_MODULE_OPTIONS: Sequence[str] = ("cython", "libyuv")
ALL_VIDEO_DECODER_OPTIONS: Sequence[str] = ("openh264", "vpx", "gstreamer", "nvdec")

PREFERRED_ENCODER_ORDER: Sequence[str] = tuple(
    autoprefix("enc", x) for x in (
        "nvenc", "nvjpeg", "x264", "vpx", "jpeg", "webp", "gstreamer")
)
log("video: ALL_VIDEO_ENCODER_OPTIONS=%s", ALL_VIDEO_ENCODER_OPTIONS)
log("video: ALL_CSC_MODULE_OPTIONS=%s", ALL_CSC_MODULE_OPTIONS)
log("video: ALL_VIDEO_DECODER_OPTIONS=%s", ALL_VIDEO_DECODER_OPTIONS)
# for client side, using the gfx card for csc is a bit silly:
# use it for OpenGL or don't use it at all
# on top of that, there are compatibility problems with gtk at times: OpenCL AMD and TLS don't mix well


def get_encoder_module_name(x: str) -> str:
    return autoprefix("enc", x)


def get_decoder_module_name(x: str) -> str:
    return autoprefix("dec", x)


def get_csc_module_name(x: str) -> str:
    return autoprefix("csc", x)


def get_video_encoders(names=ALL_VIDEO_ENCODER_OPTIONS) -> list[str]:
    """ returns all the video encoders installed """
    return try_import_modules("enc", *names)


def get_csc_modules(names=ALL_CSC_MODULE_OPTIONS) -> list[str]:
    """ returns all the csc modules installed """
    return try_import_modules("csc", *names)


def get_video_decoders(names=ALL_VIDEO_DECODER_OPTIONS) -> list[str]:
    """ returns all the video decoders installed """
    return try_import_modules("dec", *names)


def get_hardware_encoders(names=HARDWARE_ENCODER_OPTIONS) -> list[str]:
    return try_import_modules("enc", *names)


def filt(prefix: str, name: str,
         inlist: Sequence[str],
         all_fn: Callable[[], list[str]],
         all_options: Iterable[str]) -> dict[str, dict[str, str]]:
    assert isinstance(inlist, Sequence), f"options for {prefix!r} is not a sequence"
    # log("filt%s", (prefix, name, inlist, all_fn, all_options))
    if "none" in inlist:
        return {}

    # replace the alias 'all' with the actual values:
    real_list = []
    for item in inlist:
        if item == "all":
            real_list += all_fn()
            continue
        # each entry can contain an encoder with options, ie:
        # "remote:uri=foo,timeout=5"
        # or multiple encoders, ie:
        # "vpx,x264"
        # but not both!
        if item.find(":") > 0:
            real_list.append(item)
        else:
            real_list += item.split(",")

    # auto prefix the module part:
    def ap(v: str) -> str:
        if v.startswith("-"):
            return "-"+autoprefix(prefix, v[1:])
        if v.startswith("no-"):
            return "-"+autoprefix(prefix, v[3:])
        parts = v.split(":", 1)
        if len(parts) == 1:
            return autoprefix(prefix, parts[0])
        return autoprefix(prefix, parts[0]) + ":" + parts[1]

    # auto prefix for a whole list:
    def apl(items: Iterable[str]) -> list[str]:
        return [ap(v) for v in items]

    # when comparing, ignore options:
    def noopt(item: str):
        return item.split(":", 1)[0]

    exclist = apl(x[1:] for x in real_list if x and x.startswith("-"))
    inclist = apl(x for x in real_list if x and not x.startswith("-"))
    if not inclist and exclist:
        inclist = apl(all_fn())
    lists = exclist + inclist
    all_list = apl(all_options)
    unknown = tuple(x for x in lists if noopt(ap(x)) not in CODEC_TO_MODULE and x.lower() != "none")
    if unknown:
        log.warn(f"Warning: ignoring unknown {name}: "+csv(unknown))
    notfound = tuple(x for x in lists if (x and noopt(ap(x)) not in all_list and x not in unknown and x != "none"))
    if notfound:
        log.warn(f"Warning: {name} not found: "+csv(notfound))
    allowed = apl(x for x in inclist if x not in exclist and x != "none")
    # now we can parse individual entries:
    values = {}
    for entry in allowed:
        codec, options = parse_video_option(entry)
        values[codec] = options
    return values


VdictEntry = dict[str, list[CodecSpec]]
Vdict = dict[str, VdictEntry]


# manual deep-ish copy: make new dictionaries and lists,
# but keep the same codec specs:
def deepish_clone_dict(indict: Vdict) -> Vdict:
    outd: Vdict = {}
    for enc, d in indict.items():
        for ifmt, l in d.items():
            for v in l:
                outd.setdefault(enc, {}).setdefault(ifmt, []).append(v)
    return outd


def modstatus(x: str, def_list: Sequence[str], active_list: dict):
    # the module is present
    if x in active_list:
        return "active"
    if x in def_list:
        return "disabled"
    return "not found"


def parse_video_option(value: str) -> tuple[str, dict[str, str]]:
    # ie: ["remote:uri=tcp://192.168.0.10:20000/", "enc_x264"]
    parts = value.split(":", 1)
    encoder = parts[0]
    if len(parts) == 1:
        return encoder, {}
    return encoder, parse_simple_dict(parts[1])


class VideoHelper:
    """
        This class is a bit like a registry of known encoders, csc modules and decoders.
        The main instance, obtained by calling getVideoHelper, can be initialized
        by the main class, using the command line arguments.
        We can also clone it to modify it (used by per client proxy encoders)
    """

    def __init__(self,
                 vencspecs: Vdict | None = None,
                 cscspecs: Vdict | None = None,
                 vdecspecs: Vdict | None = None,
                 init=False):
        self._video_encoder_specs: Vdict = vencspecs or {}
        self._csc_encoder_specs: Vdict = cscspecs or {}
        self._video_decoder_specs: Vdict = vdecspecs or {}
        self.video_encoders = []
        self.csc_modules = []
        self.video_decoders = []

        # bits needed to ensure we can initialize just once
        # even when called from multiple threads:
        self._initialized = init
        self._init_from = []
        self._lock = Lock()

    def is_initialized(self) -> bool:
        return self._initialized

    def enable_all_modules(self):
        self.set_modules(ALL_VIDEO_ENCODER_OPTIONS,
                         ALL_CSC_MODULE_OPTIONS,
                         ALL_VIDEO_DECODER_OPTIONS)

    def set_modules(self,
                    video_encoders: Sequence[str] = (),
                    csc_modules: Sequence[str] = (),
                    video_decoders: Sequence[str] = (),
                    ):
        log("set_modules%s", (video_encoders, csc_modules, video_decoders))
        if self._initialized:
            log.error("Error: video helper modules have already been initialized")
            for ifrom in self._init_from:
                log.error("from:")
                for tb in ifrom:
                    log.error(" %s", tb.strip("\n\r"))
            raise RuntimeError("too late to set modules, the helper is already initialized")
        self.video_encoders = filt("enc", "video encoders", video_encoders,
                                   get_video_encoders, ALL_VIDEO_ENCODER_OPTIONS)
        self.csc_modules = filt("csc", "csc modules", csc_modules,
                                get_csc_modules, ALL_CSC_MODULE_OPTIONS)
        self.video_decoders = filt("dec", "video decoders", video_decoders,
                                   get_video_decoders, ALL_VIDEO_DECODER_OPTIONS)
        log("VideoHelper.set_modules(%r, %r, %r) video encoders=%s, csc=%s, video decoders=%s",
            csv(video_encoders), csv(csc_modules), csv(video_decoders),
            self.video_encoders, self.csc_modules, self.video_decoders)

    def cleanup(self) -> None:
        with self._lock:
            # check again with lock held (in case of race):
            if not self._initialized:
                return
            self._video_encoder_specs = {}
            self._csc_encoder_specs = {}
            self._video_decoder_specs = {}
            self.video_encoders = []
            self.csc_modules = []
            self.video_decoders = []
            self._initialized = False

    def clone(self) -> Self:
        if not self._initialized:
            self.init()
        ves = deepish_clone_dict(self._video_encoder_specs)
        ces = deepish_clone_dict(self._csc_encoder_specs)
        vds = deepish_clone_dict(self._video_decoder_specs)
        return VideoHelper(ves, ces, vds, True)

    def get_info(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        if not (self.video_encoders or self.csc_modules or self.video_decoders):
            # shortcut out: nothing to show
            return d
        einfo = d.setdefault("encoding", {})
        dinfo = d.setdefault("decoding", {})
        cinfo = d.setdefault("csc", {})
        for encoding, encoder_specs in self._video_encoder_specs.items():
            for in_csc, specs in encoder_specs.items():
                for spec in specs:
                    einfo.setdefault(f"{in_csc}_to_{encoding}", []).append(spec.codec_type)
        for in_csc, out_specs in self._csc_encoder_specs.items():
            for out_csc, specs in out_specs.items():
                cinfo[f"{in_csc}_to_{out_csc}"] = [spec.codec_type for spec in specs]
        for encoding, decoder_specs in self._video_decoder_specs.items():
            for out_csc, decoders in decoder_specs.items():
                for decoder in decoders:
                    dinfo.setdefault(f"{encoding}_to_{out_csc}", []).append(decoder.codec_type)
        venc = einfo.setdefault("video-encoder", {})
        for x in ALL_VIDEO_ENCODER_OPTIONS:
            venc[x] = modstatus(get_encoder_module_name(x), get_video_encoders(), self.video_encoders)
        cscm = einfo.setdefault("csc-module", {})
        for x in ALL_CSC_MODULE_OPTIONS:
            cscm[x] = modstatus(get_csc_module_name(x), get_csc_modules(), self.csc_modules)
        d["gpu"] = {
            "encodings": tuple(self.get_gpu_encodings().keys()),
            "csc": tuple(self.get_gpu_csc().keys()),
            "decodings": tuple(self.get_gpu_decodings().keys()),
        }
        return d

    def init(self) -> None:
        log("VideoHelper.init()")
        with self._lock:
            self._init_from.append(traceback.format_stack())
            # check again with lock held (in case of race):
            log("VideoHelper.init() initialized=%s", self._initialized)
            if self._initialized:
                return
            self.init_video_encoders_options()
            self.init_csc_options()
            self.init_video_decoders_options()
            self._initialized = True
        log("VideoHelper.init() done")

    def get_gpu_options(self, codec_specs: Vdict, out_fmts=("*", )) -> dict[str, list[CodecSpec]]:
        gpu_fmts: dict[str, list[CodecSpec]] = {}
        for in_fmt, vdict in codec_specs.items():
            for out_fmt, codecs in vdict.items():
                if "*" not in out_fmts and out_fmt not in out_fmts:
                    continue
                for codec in codecs:
                    if codec.gpu_cost > codec.cpu_cost:
                        log(f"get_gpu_options {out_fmt}: {codec}")
                        gpu_fmts.setdefault(in_fmt, []).append(codec)
        log(f"get_gpu_options({codec_specs})={gpu_fmts}")
        return gpu_fmts

    def get_gpu_encodings(self) -> dict[str, list[CodecSpec]]:
        return self.get_gpu_options(self._video_encoder_specs)

    def get_gpu_csc(self) -> dict[str, list[CodecSpec]]:
        return self.get_gpu_options(self._csc_encoder_specs)

    def get_gpu_decodings(self) -> dict[str, list[CodecSpec]]:
        return self.get_gpu_options(self._video_decoder_specs)

    def get_encodings(self) -> Sequence[str]:
        return tuple(self._video_encoder_specs.keys())

    def get_decodings(self) -> Sequence[str]:
        return tuple(self._video_decoder_specs.keys())

    def get_csc_inputs(self) -> Sequence[str]:
        return tuple(self._csc_encoder_specs.keys())

    def get_encoder_specs(self, encoding: str) -> VdictEntry:
        return self._video_encoder_specs.get(encoding, {})

    def get_csc_specs(self, src_format: str) -> VdictEntry:
        return self._csc_encoder_specs.get(src_format, {})

    def get_decoder_specs(self, encoding: str) -> VdictEntry:
        return self._video_decoder_specs.get(encoding, {})

    def init_video_encoders_options(self) -> None:
        log("init_video_encoders_options() will try video encoders: %s", self.video_encoders or "none")
        if not self.video_encoders:
            return
        for x, options in self.video_encoders.items():
            try:
                mod = get_encoder_module_name(x)
                load_codec(mod, options)
                log(f" encoder for {x!r}: {mod!r}")
                try:
                    self.init_video_encoder_option(mod)
                except Exception as e:
                    log(f" init_video_encoder_option({mod!r}) error", exc_info=True)
                    log.warn(f"Warning: cannot load {mod!r} video encoder:")
                    log.warn(f" {e}")
                    del e
            except Exception as e:
                log(f"error on {x!r}",exc_info=True)
                log.warn(f"Warning: cannot add {x!r} encoder: {e}")
                del e
        log("found %i video encoder formats: %s",
            len(self._video_encoder_specs), csv(self._video_encoder_specs))

    def init_video_encoder_option(self, encoder_name: str) -> None:
        encoder_module = get_codec(encoder_name)
        log(f"init_video_encoder_option({encoder_name})")
        log(f" module={encoder_module!r}")
        if not encoder_module:
            log(f" video encoder {encoder_name!r} could not be loaded:")
            log(" %s", get_codec_error(encoder_name))
            return
        for spec in encoder_module.get_specs():
            self.add_encoder_spec(spec)
        log("video encoder options: %s", self._video_encoder_specs)

    def add_encoder_spec(self, spec: VideoSpec):
        encoding = spec.encoding
        colorspace = spec.input_colorspace
        self._video_encoder_specs.setdefault(encoding, {}).setdefault(colorspace, []).append(spec)

    def init_csc_options(self) -> None:
        log("init_csc_options() will try csc modules: %s", self.csc_modules or "none")
        if not self.csc_modules:
            return
        for x, options in self.csc_modules.items():
            try:
                mod = get_csc_module_name(x)
                load_codec(mod, options)
                self.init_csc_option(mod)
            except ImportError:
                log.warn(f"Warning: cannot add {x!r} csc", exc_info=True)
        log(" csc specs: %s", csv(self._csc_encoder_specs))
        for src_format, d in sorted(self._csc_encoder_specs.items()):
            log(f" {src_format!r} - {len(d)} options:")
            for dst_format, specs in sorted(d.items()):
                log("  * %7s via: %s", dst_format, csv(sorted(spec.codec_type for spec in specs)))
        log("csc options: %s", self._csc_encoder_specs)

    def init_csc_option(self, csc_name: str) -> None:
        csc_module = get_codec(csc_name)
        log(f"init_csc_option({csc_name!r})")
        log(f" module={csc_module!r}")
        if csc_module is None:
            log(f" csc module {csc_name!r} could not be loaded:")
            log(" %s", get_codec_error(csc_name))
            return
        specs = csc_module.get_specs()
        for spec in specs:
            self.add_csc_spec(spec)

    def add_csc_spec(self, spec: CSCSpec) -> None:
        in_csc = spec.input_colorspace
        for out_csc in spec.output_colorspaces:
            self._csc_encoder_specs.setdefault(in_csc, {}).setdefault(out_csc, []).append(spec)

    def init_video_decoders_options(self) -> None:
        log("init_video_decoders_options() will try video decoders: %s", self.video_decoders or "none")
        if not self.video_decoders:
            return
        for x, options in self.video_decoders.items():
            try:
                mod = get_decoder_module_name(x)
                load_codec(mod, options)
                self.init_video_decoder_option(mod)
            except ImportError:
                log.warn(f"Warning: cannot add {x!r} decoder", exc_info=True)
        log("found %s video decoder formats: %s",
            len(self._video_decoder_specs), csv(self._video_decoder_specs))
        log("video decoder options: %s", self._video_decoder_specs)

    def init_video_decoder_option(self, decoder_name: str) -> None:
        decoder_module = get_codec(decoder_name)
        log(f"init_video_decoder_option({decoder_name!r})")
        log(f" module={decoder_module!r}")
        if not decoder_module:
            log(" video decoder %s could not be loaded:", decoder_name)
            log(" %s", get_codec_error(decoder_name))
            return
        for spec in decoder_module.get_specs():
            self.add_decoder_spec(spec)

    def add_decoder_spec(self, decoder_spec: VideoSpec):
        encoding = decoder_spec.encoding
        colorspace = decoder_spec.input_colorspace
        self._video_decoder_specs.setdefault(encoding, {}).setdefault(colorspace, []).append(decoder_spec)

    def get_server_full_csc_modes(self, *client_supported_csc_modes: str) -> dict[str, list[str]]:
        """ given a list of CSC modes the client can handle,
            returns the CSC modes per encoding that the server can encode with.
            (taking into account the decoder's actual output colorspace for each encoding)
        """
        log("get_server_full_csc_modes(%s) decoder encodings=%s",
            client_supported_csc_modes, csv(self._video_decoder_specs.keys()))
        full_csc_modes: dict[str, list[str]] = {}
        for encoding, encoding_specs in self._video_decoder_specs.items():
            assert encoding_specs is not None
            for colorspace, decoder_specs in sorted(encoding_specs.items()):
                for decoder_spec in decoder_specs:
                    for output_colorspace in decoder_spec.output_colorspaces:
                        log("found decoder %12s for %5s with %7s mode, outputs '%s'",
                            decoder_spec.codec_type, encoding, colorspace, output_colorspace)
                        if output_colorspace in client_supported_csc_modes:
                            encoding_colorspaces = full_csc_modes.setdefault(encoding, [])
                            if colorspace not in encoding_colorspaces:
                                encoding_colorspaces.append(colorspace)
        log("get_server_full_csc_modes(%s)=%s", client_supported_csc_modes, full_csc_modes)
        return full_csc_modes

    def get_server_full_csc_modes_for_rgb(self, *target_rgb_modes: str) -> dict[str, list[str]]:
        """ given a list of RGB modes the client can handle,
            returns the CSC modes per encoding that the server can encode with,
            this will include the RGB modes themselves too.
        """
        log(f"get_server_full_csc_modes_for_rgb{target_rgb_modes!r}")
        supported_csc_modes = list(filter(lambda rgb_mode: rgb_mode != "*", target_rgb_modes))
        for src_format, specs in self._csc_encoder_specs.items():
            for dst_format, csc_specs in specs.items():
                if not csc_specs:
                    continue
                if dst_format in target_rgb_modes or "*" in target_rgb_modes:
                    supported_csc_modes.append(src_format)
                    break
        supported_csc_modes = sorted(supported_csc_modes)
        return self.get_server_full_csc_modes(*supported_csc_modes)


instance = None


def getVideoHelper() -> VideoHelper:
    global instance
    if instance is None:
        instance = VideoHelper()
    return instance


def main():
    # pylint: disable=import-outside-toplevel
    from xpra.log import enable_color, consume_verbose_argv
    from xpra.platform import program_context
    with program_context("Video Helper"):
        enable_color()
        consume_verbose_argv(sys.argv, "video", "encoding")
        vh = getVideoHelper()
        vh.enable_all_modules()
        vh.init()
        info = vh.get_info()
        print_nested_dict(info)
        unload_codecs()


if __name__ == "__main__":
    main()
