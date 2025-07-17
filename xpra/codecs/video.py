#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from types import ModuleType
from typing import Any
from importlib.util import find_spec
from collections.abc import Callable, Sequence, Iterable

from xpra.common import Self
from xpra.codecs.constants import VideoSpec, CodecSpec, CSCSpec
from xpra.codecs.loader import load_codec, autoprefix, unload_codecs, NOWARN
from xpra.util.parsing import parse_simple_dict
from xpra.util.str_fn import csv, print_nested_dict
from xpra.log import Logger

log = Logger("codec", "video")

# the codec loader uses the names...
# but we need the module name to be able to probe without loading the codec:
CODEC_TO_MODULE: dict[str, str] = {
    "enc_amf"       : "amf.encoder",
    "enc_vpx"       : "vpx.encoder",
    "dec_vpx"       : "vpx.decoder",
    "dec_aom"       : "aom.decoder",
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
ALL_VIDEO_ENCODER_OPTIONS: Sequence[str] = ("amf", "x264", "openh264", "vpx",
                                            "nvenc", "nvjpeg", "jpeg", "webp", "gstreamer", "remote")
HARDWARE_ENCODER_OPTIONS: Sequence[str] = ("nvenc", "nvjpeg")
ALL_CSC_MODULE_OPTIONS: Sequence[str] = ("cython", "libyuv")
ALL_VIDEO_DECODER_OPTIONS: Sequence[str] = ("openh264", "vpx", "gstreamer", "nvdec", "aom")

PREFERRED_ENCODER_ORDER: Sequence[str] = tuple(
    autoprefix("enc", x) for x in (
        "nvenc", "nvjpeg", "x264", "vpx", "jpeg", "webp", "gstreamer")
)
log("video: ALL_VIDEO_ENCODER_OPTIONS=%s", ALL_VIDEO_ENCODER_OPTIONS)
log("video: ALL_CSC_MODULE_OPTIONS=%s", ALL_CSC_MODULE_OPTIONS)
log("video: ALL_VIDEO_DECODER_OPTIONS=%s", ALL_VIDEO_DECODER_OPTIONS)


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
    log("filt%s", (prefix, name, inlist, all_fn, all_options))
    if "none" in inlist:
        return {}

    # replace the alias 'all' with the actual values:
    real_list = []
    for entry in inlist:
        # each entry can contain an encoder with options, ie:
        # "remote:uri=foo,timeout=5"
        # or multiple encoders, ie:
        # "vpx,x264"
        # but not both!
        if entry.find(":") > 0:
            items = [entry]
        else:
            items = entry.split(",")
        for item in items:
            # "no-xxxx" -> "-xxxx"
            if item.startswith("no-"):
                item = item[2:]
            if item == "all":
                real_list += all_fn()
            else:
                real_list.append(item)

    # auto prefix the module part:
    def ap(v: str) -> str:
        if v.startswith("-"):
            return "-"+autoprefix(prefix, v[1:])
        parts = v.split(":", 1)
        if len(parts) == 1:
            return autoprefix(prefix, parts[0])
        return autoprefix(prefix, parts[0]) + ":" + parts[1]

    # auto prefix for a whole list:
    def apl(items: Iterable[str]) -> list[str]:
        return [ap(v) for v in items]

    # when comparing, ignore options:
    def noopt(item_str: str):
        return item_str.lstrip("-").split(":", 1)[0]

    exclist = apl(x[1:] for x in real_list if x and x.startswith("-"))
    inclist = apl(x for x in real_list if x and not x.startswith("-"))
    if not inclist and exclist:
        inclist = apl(all_fn())
    lists = exclist + inclist
    all_list = apl(all_options)
    unknown = tuple(x for x in lists if noopt(x) not in CODEC_TO_MODULE and x.lower() != "none")
    if unknown:
        log.warn(f"Warning: ignoring unknown {name}: "+csv(unknown))
    notfound = tuple(x for x in lists if (x and noopt(x) not in all_list and x not in unknown and x != "none"))
    if notfound:
        log.warn(f"Warning: {name} not found: "+csv(notfound))
    allowed = apl(x for x in inclist if noopt(x) in all_list and noopt(x) not in exclist and x != "none")
    log(f"{inclist=}, {exclist=}, {all_list=} -> {allowed=}")
    # now we can parse individual entries:
    values = {}
    for entry in allowed:
        codec, options = parse_video_option(entry)
        values[codec] = options
    log(f"{name}={values}")
    return values


VdictEntry = dict[str, Sequence[CodecSpec]]
Vdict = dict[str, VdictEntry]

VModuleOptions = dict[str, dict[str, str]]


# manual deep-ish copy: make new dictionaries and lists,
# but keep the same codec specs:
def deepish_clone_dict(indict: Vdict) -> Vdict:
    outd: Vdict = {}
    for enc, d in indict.items():
        for ifmt, l in d.items():
            for v in l:
                outd.setdefault(enc, {}).setdefault(ifmt, []).append(v)
    return outd


def modstatus(x: str, def_list: Sequence[str], active_list: dict) -> str:
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


def init_modules(prefix: str, defs: VModuleOptions) -> dict[str, ModuleType]:
    log(f"init_modules({prefix!r}, {defs})")
    modules = {}
    for x, options in defs.items():
        try:
            mod_name = autoprefix(prefix, x)
            mod = load_codec(mod_name, options)
            log(f" {prefix!r} module for {x!r}: {mod_name!r}={mod}")
            if not mod:
                if mod_name not in NOWARN:
                    log.info(f" {x!r} not found")
                continue
            modules[mod_name] = mod
        except Exception as e:
            log(f"error on {x!r}", exc_info=True)
            log.warn(f"Warning: cannot add {x!r}: {e}")
    log(f"found %i {prefix!r} options: %s", len(modules), modules)
    return modules


def get_all_specs(modules: dict[str, ModuleType]) -> list:
    specs = []
    for mod in modules.values():
        specs += mod.get_specs()
    return specs


def get_gpu_options(codec_specs: Vdict, out_fmts=("*",)) -> dict[str, list[CodecSpec]]:
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


class VideoHelper:
    """
        This class is a bit like a registry of known encoders, csc modules and decoders.
        The main instance, obtained by calling getVideoHelper, can be initialized
        by the main class, using the command line arguments.
        We can also clone it to modify it (used by per client proxy encoders)
    """

    def __init__(self, encoders=None, csc=None, decoders=None):
        self.encoders: VModuleOptions = encoders or {}
        self.csc: VModuleOptions = csc or {}
        self.decoders: VModuleOptions = decoders or {}
        self.encoder_modules: dict[str, ModuleType] = {}
        self.csc_modules: dict[str, ModuleType] = {}
        self.decoder_modules: dict[str, ModuleType] = {}

    def init(self) -> None:
        self.encoder_modules = init_modules("enc", self.encoders)
        self.csc_modules = init_modules("csc", self.csc)
        self.decoder_modules = init_modules("dec", self.decoders)

    def enable_all_modules(self) -> None:
        self.set_modules(ALL_VIDEO_ENCODER_OPTIONS,
                         ALL_CSC_MODULE_OPTIONS,
                         ALL_VIDEO_DECODER_OPTIONS)

    def set_modules(self,
                    video_encoders: Sequence[str] = (),
                    csc_modules: Sequence[str] = (),
                    video_decoders: Sequence[str] = (),
                    ):
        log("set_modules%s", (video_encoders, csc_modules, video_decoders))
        self.encoders = filt("enc", "video encoders", video_encoders,
                             get_video_encoders, ALL_VIDEO_ENCODER_OPTIONS)
        self.csc = filt("csc", "csc modules", csc_modules,
                        get_csc_modules, ALL_CSC_MODULE_OPTIONS)
        self.decoders = filt("dec", "video decoders", video_decoders,
                             get_video_decoders, ALL_VIDEO_DECODER_OPTIONS)
        log("VideoHelper.set_modules(%r, %r, %r)", csv(video_encoders), csv(csc_modules), csv(video_decoders))
        log(" video encoders=%s", self.encoders)
        log(" csc modules=%s", self.csc)
        log(" video decoders=%s", self.decoders)

    def cleanup(self) -> None:
        self.encoders = {}
        self.csc = {}
        self.decoders = {}
        self.encoder_modules = {}
        self.csc_modules = {}
        self.decoder_modules = {}

    def clone(self) -> Self:
        return VideoHelper(self.encoders, self.csc, self.decoders)

    def get_info(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        if not (self.encoders or self.csc or self.decoders):
            # shortcut out: nothing to show
            return d
        einfo = d.setdefault("encoding", {})
        dinfo = d.setdefault("decoding", {})
        cinfo = d.setdefault("csc", {})
        for encoding, encoder_specs in self.get_video_encoding_options().items():
            for in_csc, specs in encoder_specs.items():
                for spec in specs:
                    einfo.setdefault(f"{in_csc}_to_{encoding}", []).append(spec.codec_type)
        for in_csc, out_specs in self.get_csc_options().items():
            for out_csc, specs in out_specs.items():
                cinfo[f"{in_csc}_to_{out_csc}"] = [spec.codec_type for spec in specs]
        for encoding, decoder_specs in self.get_video_decoding_options().items():
            for out_csc, decoders in decoder_specs.items():
                for decoder in decoders:
                    dinfo.setdefault(f"{encoding}_to_{out_csc}", []).append(decoder.codec_type)
        venc = einfo.setdefault("video-encoder", {})
        for x in ALL_VIDEO_ENCODER_OPTIONS:
            venc[x] = modstatus(autoprefix("enc", x), get_video_encoders(), self.encoders)
        vdec = einfo.setdefault("video-decoder", {})
        for x in ALL_VIDEO_DECODER_OPTIONS:
            vdec[x] = modstatus(autoprefix("dec", x), get_video_decoders(), self.encoders)
        cscm = einfo.setdefault("csc-module", {})
        for x in ALL_CSC_MODULE_OPTIONS:
            cscm[x] = modstatus(autoprefix("csc", x), get_csc_modules(), self.csc_modules)
        d["gpu"] = {
            "encodings": tuple(self.get_gpu_encodings().keys()),
            "csc": tuple(self.get_gpu_csc().keys()),
            "decodings": tuple(self.get_gpu_decodings().keys()),
        }
        return d

    def get_gpu_encodings(self) -> dict[str, Sequence[CodecSpec]]:
        return get_gpu_options(self.get_video_encoding_options())

    def get_gpu_csc(self) -> dict[str, Sequence[CodecSpec]]:
        return get_gpu_options(self.get_csc_options())

    def get_gpu_decodings(self) -> dict[str, Sequence[CodecSpec]]:
        return get_gpu_options(self.get_video_decoding_options())

    def get_encodings(self) -> Sequence[str]:
        return tuple(self.get_video_encoding_options().keys())

    def get_decodings(self) -> Sequence[str]:
        return tuple(self.get_video_decoding_options().keys())

    def get_csc_inputs(self) -> Sequence[str]:
        return tuple(self.get_csc_options().keys())

    def get_encoder_specs(self, encoding: str) -> VdictEntry:
        return self.get_video_encoding_options().get(encoding, {})

    def get_csc_specs(self, src_format: str) -> VdictEntry:
        return self.get_csc_options().get(src_format, {})

    def get_decoder_specs(self, encoding: str) -> VdictEntry:
        return self.get_video_decoding_options().get(encoding, {})

    def get_video_encoding_options(self) -> dict[str, dict[str, Sequence[VideoSpec]]]:
        log("get_video_encoding_options() will try video encoders: %s", self.encoder_modules or "none")
        ve_options: dict[str, dict[str, Sequence[VideoSpec]]] = {}
        for spec in get_all_specs(self.encoder_modules):
            ve_options.setdefault(spec.encoding, {}).setdefault(spec.input_colorspace, []).append(spec)
        log("get_video_encoding_options()=%s", ve_options)
        return ve_options

    def get_csc_options(self) -> dict[str, dict[str, Sequence[CSCSpec]]]:
        log("get_csc_options() will try csc modules: %s", self.csc_modules or "none")
        csc_options: dict[str, dict[str, Sequence[CSCSpec]]] = {}
        for spec in get_all_specs(self.csc_modules):
            in_csc = spec.input_colorspace
            for out_csc in spec.output_colorspaces:
                csc_options.setdefault(in_csc, {}).setdefault(out_csc, []).append(spec)
        log("get_csc_options()=%s", csc_options)
        return csc_options

    def get_video_decoding_options(self) -> dict[str, dict[str, Sequence[VideoSpec]]]:
        log("get_video_decoding_options() will try video decoders: %s", self.decoder_modules or "none")
        vd_options: dict[str, dict[str, Sequence[VideoSpec]]] = {}
        for spec in get_all_specs(self.decoder_modules):
            vd_options.setdefault(spec.encoding, {}).setdefault(spec.input_colorspace, []).append(spec)
        log("get_video_decoding_options()=%s", vd_options)
        return vd_options

    def get_server_full_csc_modes(self, *client_supported_csc_modes: str) -> dict[str, list[str]]:
        """ given a list of CSC modes the client can handle,
            returns the CSC modes per encoding that the server can encode with.
            (taking into account the decoder's actual output colorspace for each encoding)
        """
        dec_options = self.get_video_decoding_options()
        log("get_server_full_csc_modes(%s) decoder encodings=%s",
            client_supported_csc_modes, csv(dec_options.keys()))
        full_csc_modes: dict[str, list[str]] = {}
        for encoding, encoding_specs in dec_options.items():
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
        for src_format, specs in self.get_csc_options().items():
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


def main() -> int:
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
    return 0


if __name__ == "__main__":
    main()
