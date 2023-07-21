# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
#pylint: disable-msg=E1101

from typing import Dict, Any, Tuple

from xpra.scripts.config import parse_bool_or_int, csvstrl
from xpra.util import envint
from xpra.os_util import bytestostr, OSX
from xpra.net.common import PacketType
from xpra.version_util import vtrim
from xpra.codecs.codec_constants import preforder, STREAM_ENCODINGS
from xpra.codecs.loader import get_codec, has_codec, codec_versions, load_codec
from xpra.codecs.video_helper import getVideoHelper
from xpra.server.mixins.stub_server_mixin import StubServerMixin
from xpra.server.source.windows import WindowsMixin
from xpra.log import Logger
from xpra.common import FULL_INFO

log = Logger("encoding")

INIT_DELAY = envint("XPRA_ENCODER_INIT_DELAY", 0)


class EncodingServer(StubServerMixin):
    """
    Mixin for adding encodings to a server
    """

    def __init__(self):
        self.default_quality = -1
        self.default_min_quality = 0
        self.default_speed = -1
        self.default_min_speed = 0
        self.allowed_encodings : Tuple[str,...] = ()
        self.core_encodings : Tuple[str,...] = ()
        self.encodings : Tuple[str,...] = ()
        self.lossless_encodings : Tuple[str,...] = ()
        self.lossless_mode_encodings : Tuple[str,...] = ()
        self.default_encoding : str = ""
        self.scaling_control = None
        self.video_encoders : Tuple[str,...] = ()
        self.csc_modules : Tuple[str,...] = ()

    def init(self, opts) -> None:
        self.encoding = opts.encoding
        self.allowed_encodings = opts.encodings
        self.default_quality = opts.quality
        self.default_min_quality = opts.min_quality
        self.default_speed = opts.speed
        self.default_min_speed = opts.min_speed
        if opts.video_scaling.lower() not in ("auto", "on"):
            self.scaling_control = parse_bool_or_int("video-scaling", opts.video_scaling)
        self.video_encoders = tuple(csvstrl(opts.video_encoders).split(","))
        self.csc_modules = tuple(csvstrl(opts.csc_modules).split(","))

    def setup(self) -> None:
        #essential codecs, load them early:
        load_codec("enc_rgb")
        load_codec("enc_pillow")
        ae = self.allowed_encodings
        if "webp" in ae:
            #try to load the fast webp encoder:
            load_codec("enc_webp")
        if "png" in ae or "png/L" in ae:
            #try to load the fast png encoder:
            load_codec("enc_spng")
        if "jpeg" in ae or "jpega" in ae:
            #try to load the fast jpeg encoders:
            load_codec("enc_jpeg")
        if "avif" in ae:
            load_codec("enc_avif")
        self.init_encodings()
        self.add_init_thread_callback(self.reinit_encodings)

    def reinit_encodings(self) -> None:
        self.init_encodings()
        #any window mapped before the threaded init completed
        #may need to re-initialize its list of encodings:
        log("reinit_encodings()")
        for ss in self._server_sources.values():
            if isinstance(ss, WindowsMixin):
                ss.reinit_encodings(self)

    def threaded_setup(self) -> None:
        if INIT_DELAY>0:
            from time import sleep
            sleep(INIT_DELAY)
        #load the slower codecs
        if "jpeg" in self.allowed_encodings and not OSX:
            load_codec("enc_nvjpeg")
        #load video codecs:
        getVideoHelper().set_modules(video_encoders=self.video_encoders, csc_modules=self.csc_modules)
        getVideoHelper().init()
        self.init_encodings()

    def cleanup(self) -> None:
        getVideoHelper().cleanup()


    def get_server_features(self, _source=None) -> Dict[str,Any]:
        return {
            "auto-video-encoding"   : True,     #from v4.0, clients assume this is available
            }

    def get_info(self, _proto)  -> Dict[str,Any]:
        info = {
            "encodings" : self.get_encoding_info(),
            "video"     : getVideoHelper().get_info(),
            }
        if FULL_INFO>0:
            for k,v in codec_versions.items():
                info.setdefault("encoding", {}).setdefault(k, {})["version"] = vtrim(v)
        return info

    def get_encoding_info(self)  -> Dict[str,Any]:
        return  {
             ""                     : self.encodings,
             "core"                 : self.core_encodings,
             "allowed"              : self.allowed_encodings,
             "lossless"             : self.lossless_encodings,
             "with_speed"           : tuple(set({"rgb32" : "rgb", "rgb24" : "rgb"}.get(x, x)
                                                for x in self.core_encodings if x in (
                                                    "h264", "vp8", "vp9",
                                                    "rgb24", "rgb32",
                                                    "png", "png/P", "png/L", "webp",
                                                    "scroll",
                                                    ))),
             "with_quality"         : tuple(x for x in self.core_encodings if x in (
                 "jpeg", "webp", "h264", "vp8", "vp9", "scroll")),
             "with_lossless_mode"   : self.lossless_mode_encodings,
             }

    def init_encodings(self) -> None:
        encs, core_encs = [], []
        log("init_encodings() allowed_encodings=%s", self.allowed_encodings)
        def add_encoding(encoding):
            log("add_encoding(%s)", encoding)
            enc = {"rgb32" : "rgb", "rgb24" : "rgb"}.get(encoding, encoding)
            if self.allowed_encodings is not None:
                if enc not in self.allowed_encodings and encoding not in self.allowed_encodings:
                    #not in whitelist (if it exists)
                    return
            if enc not in encs:
                encs.append(enc)
            if encoding not in core_encs:
                core_encs.append(encoding)
        def add_encodings(*encodings):
            log("add_encodings%s", encodings)
            for enc in encodings:
                add_encoding(enc)

        add_encodings("rgb24", "rgb32")
        try:
            from xpra.server.window.motion import ScrollData  # @UnresolvedImport
            assert ScrollData
            add_encoding("scroll")
        except (ImportError, TypeError) as e:
            log.error("Error: 'scroll' encoding is not available")
            log.estr(e)
        lossless = []
        if "scroll" in self.allowed_encodings and "scroll" not in self.lossless_mode_encodings:
            #scroll is lossless, but it also uses other picture codecs
            #and those allow changes in quality
            lossless.append("scroll")

        #video encoders (empty when first called - see threaded_init)
        ve = getVideoHelper().get_encodings()
        log("init_encodings() adding video encodings: %s", ve)
        add_encodings(*ve)  #ie: ["vp8", "h264"]
        #Pithon Imaging Library:
        enc_pillow = get_codec("enc_pillow")
        log("enc_pillow=%s", enc_pillow)
        if enc_pillow:
            pil_encs = enc_pillow.get_encodings()
            log("pillow encodings: %s", pil_encs)
            for encoding in pil_encs:
                if encoding!="webp":
                    add_encoding(encoding)
            #Note: webp will only be enabled if we have a Python-PIL fallback
            #(either "webp" or "png")
            if has_codec("enc_webp") and ("webp" in pil_encs or "png" in pil_encs):
                add_encodings("webp")
                if "webp" not in lossless:
                    lossless.append("webp")
        for codec_name in ("enc_avif", "enc_jpeg", "enc_nvjpeg"):
            codec = get_codec(codec_name)
            if codec:
                add_encodings(*codec.get_encodings())
        #look for video encodings with lossless mode:
        for enc in ve:
            for colorspace,especs in getVideoHelper().get_encoder_specs(enc).items():
                for espec in especs:
                    if espec.has_lossless_mode and enc not in lossless:
                        log("found lossless mode for encoding %s with %s and colorspace %s", enc, espec, colorspace)
                        lossless.append(enc)
                        break
        #now update the variables:
        encs.append("grayscale")
        if any(enc in encs for enc in STREAM_ENCODINGS):
            encs.append("stream")
        self.encodings = preforder(encs)
        self.core_encodings = preforder(core_encs)
        self.lossless_mode_encodings = preforder(lossless)
        self.lossless_encodings = preforder(enc for enc in self.core_encodings
                                   if (enc.startswith("png") or enc.startswith("rgb") or enc=="webp"))
        log("allowed encodings=%s, encodings=%s, core encodings=%s, lossless encodings=%s",
            self.allowed_encodings, encs, core_encs, self.lossless_encodings)
        self.default_encoding = self.encodings[0]
        #default encoding:
        if not self.encoding or str(self.encoding).lower() in ("auto", "none"):
            self.default_encoding = ""
        elif self.encoding in self.encodings:
            log.warn("ignored invalid default encoding option: %s", self.encoding)
            self.default_encoding = self.encoding


    def _process_encoding(self, proto, packet : PacketType) -> None:
        encoding = bytestostr(packet[1])
        ss = self.get_server_source(proto)
        if ss is None:
            return
        if len(packet)>=3:
            #client specified which windows this is for:
            in_wids = packet[2]
            wids = []
            wid_windows = {}
            for wid in in_wids:
                if wid not in self._id_to_window:
                    continue
                wids.append(wid)
                wid_windows[wid] = self._id_to_window.get(wid)
        else:
            #apply to all windows:
            wids = None
            wid_windows = self._id_to_window
        ss.set_encoding(encoding, wids)
        self._refresh_windows(proto, wid_windows, {})

    def _modify_sq(self, proto, packet) -> None:
        """ modify speed or quality """
        ss = self.get_server_source(proto)
        if not ss:
            return
        ptype = bytestostr(packet[0])
        assert ptype in (
            "quality", "min-quality", "max-quality",
            "speed", "min-speed", "max-speed",
            ), f"invalid packet type {ptype}"
        value = int(packet[1])
        log("Setting %s to %s", ptype, value)
        fn = getattr(ss, "set_%s" % ptype.replace("-", "_"))
        fn(value)
        self.call_idle_refresh_all_windows(proto)

    def call_idle_refresh_all_windows(self, proto) -> None:
        #we can't assume that the window server mixin is loaded:
        refresh = getattr(self, "_idle_refresh_all_windows", None)
        if refresh:
            refresh(proto)  # pylint: disable=not-callable


    def init_packet_handlers(self) -> None:
        self.add_packet_handler("encoding", self._process_encoding)
        for ptype in (
            "quality", "min-quality", "max-quality",
            "speed", "min-speed", "max-speed",
            ):
            self.add_packet_handler(ptype, self._modify_sq)
