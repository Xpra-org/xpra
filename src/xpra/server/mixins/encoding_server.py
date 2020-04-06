# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
#pylint: disable-msg=E1101

from xpra.scripts.config import parse_bool_or_int
from xpra.codecs.codec_constants import PREFERED_ENCODING_ORDER, PROBLEMATIC_ENCODINGS
from xpra.codecs.loader import get_codec, has_codec, codec_versions, load_codec
from xpra.codecs.video_helper import getVideoHelper
from xpra.server.mixins.stub_server_mixin import StubServerMixin
from xpra.log import Logger

log = Logger("encoding")


"""
Mixin for adding encodings to a server
"""
class EncodingServer(StubServerMixin):

    def __init__(self):
        self.default_quality = -1
        self.default_min_quality = 0
        self.default_speed = -1
        self.default_min_speed = 0
        self.allowed_encodings = None
        self.core_encodings = []
        self.encodings = []
        self.lossless_encodings = []
        self.lossless_mode_encodings = []
        self.default_encoding = None
        self.scaling_control = None

    def init(self, opts):
        self.encoding = opts.encoding
        self.allowed_encodings = opts.encodings
        self.default_quality = opts.quality
        self.default_min_quality = opts.min_quality
        self.default_speed = opts.speed
        self.default_min_speed = opts.min_speed
        if opts.video_scaling.lower() not in ("auto", "on"):
            self.scaling_control = parse_bool_or_int("video-scaling", opts.video_scaling)
        getVideoHelper().set_modules(video_encoders=opts.video_encoders, csc_modules=opts.csc_modules)

    def setup(self):
        #always load pillow early,
        #so we have png and jpeg support before calling threaded_setup
        load_codec("enc_pillow")
        self.init_encodings()

    def threaded_setup(self):
        #load video codecs:
        getVideoHelper().init()
        #and load the picture codecs:
        load_codec("enc_pillow")
        ae = self.allowed_encodings
        if "jpeg" in ae:
            #try to load the fast jpeg encoder:
            load_codec("enc_jpeg")
        if "webp" in ae:
            #try to load the fast webp encoder:
            load_codec("enc_webp")
        self.init_encodings()

    def cleanup(self):
        getVideoHelper().cleanup()


    def get_server_features(self, _source=None):
        return {
            "auto-video-encoding"   : True,     #from v4.0, clients assume this is available
            }

    def get_info(self, _proto) -> dict:
        info = {
            "encodings" : self.get_encoding_info(),
            "video"     : getVideoHelper().get_info(),
            }
        for k,v in codec_versions.items():
            info.setdefault("encoding", {}).setdefault(k, {})["version"] = v
        return info

    def get_encoding_info(self) -> dict:
        return  {
             ""                     : self.encodings,
             "core"                 : self.core_encodings,
             "allowed"              : self.allowed_encodings,
             "lossless"             : self.lossless_encodings,
             "problematic"          : [x for x in self.core_encodings if x in PROBLEMATIC_ENCODINGS],
             "with_speed"           : tuple(set({"rgb32" : "rgb", "rgb24" : "rgb"}.get(x, x)
                                                for x in self.core_encodings if x in (
                                                    "h264", "vp8", "vp9",
                                                    "rgb24", "rgb32",
                                                    "png", "png/P", "png/L", "webp",
                                                    ))),
             "with_quality"         : [x for x in self.core_encodings if x in ("jpeg", "webp", "h264", "vp8", "vp9")],
             "with_lossless_mode"   : self.lossless_mode_encodings,
             }

    def init_encodings(self):
        encs, core_encs = [], []
        log("init_encodings() allowed_encodings=%s", self.allowed_encodings)
        def add_encodings(encodings):
            log("add_encodings(%s)", encodings)
            for ce in encodings:
                e = {"rgb32" : "rgb", "rgb24" : "rgb"}.get(ce, ce)
                if self.allowed_encodings is not None and e not in self.allowed_encodings:
                    #not in whitelist (if it exists)
                    continue
                if e not in encs:
                    encs.append(e)
                if ce not in core_encs:
                    core_encs.append(ce)

        add_encodings(["rgb24", "rgb32"])

        #video encoders (empty when first called - see threaded_init)
        ve = getVideoHelper().get_encodings()
        log("init_encodings() adding video encodings: %s", ve)
        add_encodings(ve)  #ie: ["vp8", "h264"]
        #Pithon Imaging Libary:
        enc_pillow = get_codec("enc_pillow")
        if enc_pillow:
            pil_encs = enc_pillow.get_encodings()
            add_encodings(x for x in pil_encs if x!="webp")
            #Note: webp will only be enabled if we have a Python-PIL fallback
            #(either "webp" or "png")
            if has_codec("enc_webp") and ("webp" in pil_encs or "png" in pil_encs):
                add_encodings(["webp"])
                if "webp" not in self.lossless_mode_encodings:
                    self.lossless_mode_encodings.append("webp")
        #look for video encodings with lossless mode:
        for e in ve:
            for colorspace,especs in getVideoHelper().get_encoder_specs(e).items():
                for espec in especs:
                    if espec.has_lossless_mode:
                        if e not in self.lossless_mode_encodings:
                            log("found lossless mode for encoding %s with %s and colorspace %s", e, espec, colorspace)
                            self.lossless_mode_encodings.append(e)
                            break
        #now update the variables:
        self.encodings = encs
        self.core_encodings = core_encs
        self.lossless_encodings = [x for x in self.core_encodings
                                   if (x.startswith("png") or x.startswith("rgb") or x=="webp")]
        log("allowed encodings=%s, encodings=%s, core encodings=%s, lossless encodings=%s",
            self.allowed_encodings, encs, core_encs, self.lossless_encodings)
        pref = [x for x in PREFERED_ENCODING_ORDER if x in self.encodings]
        if pref:
            self.default_encoding = pref[0]
        else:
            self.default_encoding = None
        #default encoding:
        if not self.encoding or str(self.encoding).lower() in ("auto", "none"):
            self.default_encoding = None
        elif self.encoding in self.encodings:
            self.default_encoding = self.encoding
        else:
            log.warn("ignored invalid default encoding option: %s", self.encoding)


    def _process_encoding(self, proto, packet):
        encoding = packet[1].decode("latin1")
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

    def _process_quality(self, proto, packet):
        quality = packet[1]
        log("Setting quality to %s", quality)
        ss = self.get_server_source(proto)
        if ss:
            ss.set_quality(quality)
            self.call_idle_refresh_all_windows(proto)

    def _process_min_quality(self, proto, packet):
        min_quality = packet[1]
        log("Setting min quality to %s", min_quality)
        ss = self.get_server_source(proto)
        if ss:
            ss.set_min_quality(min_quality)
            self.call_idle_refresh_all_windows(proto)

    def _process_speed(self, proto, packet):
        speed = packet[1]
        log("Setting speed to ", speed)
        ss = self.get_server_source(proto)
        if ss:
            ss.set_speed(speed)
            self.call_idle_refresh_all_windows(proto)

    def _process_min_speed(self, proto, packet):
        min_speed = packet[1]
        log("Setting min speed to ", min_speed)
        ss = self.get_server_source(proto)
        if ss:
            ss.set_min_speed(min_speed)
            self.call_idle_refresh_all_windows(proto)


    def call_idle_refresh_all_windows(self, proto):
        #we can't assume that the window server mixin is loaded:
        refresh = getattr(self, "_idle_refresh_all_windows", None)
        if refresh:
            refresh(proto)


    def init_packet_handlers(self):
        self.add_packet_handlers({
            "quality"       : self._process_quality,
            "min-quality"   : self._process_min_quality,
            "speed"         : self._process_speed,
            "min-speed"     : self._process_min_speed,
            "encoding"      : self._process_encoding,
            })
