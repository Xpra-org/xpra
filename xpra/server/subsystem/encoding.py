# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from typing import Any
from collections.abc import Sequence

from xpra.util.env import envint
from xpra.os_util import OSX
from xpra.net.common import Packet
from xpra.util.version import vtrim
from xpra.util.parsing import parse_bool_or_int
from xpra.codecs.constants import preforder, STREAM_ENCODINGS, TRUE_LOSSLESS_ENCODINGS
from xpra.codecs.loader import get_codec, codec_versions, load_codec, unload_codecs
from xpra.codecs.video import getVideoHelper
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger
from xpra.common import FULL_INFO

log = Logger("encoding")

INIT_DELAY = envint("XPRA_ENCODER_INIT_DELAY", 0)

ENCODINGS_WITH_SPEED = (
    "h264", "vp8", "vp9",
    "rgb24", "rgb32",
    "png", "png/P", "png/L", "webp",
    "scroll",
)
ENCODINGS_WITH_QUALITY = (
    "jpeg", "webp",
    "h264", "vp8", "vp9",
    "scroll",
)

ENCODING_OPTIONS = (
    "quality", "min-quality", "max-quality",
    "speed", "min-speed", "max-speed",
)


class EncodingServer(StubServerMixin):
    """
    Mixin for adding encodings to a server
    """
    PREFIX = "encoding"

    def __init__(self):
        StubServerMixin.__init__(self)
        self.default_quality = -1
        self.default_min_quality = 0
        self.default_speed = -1
        self.default_min_speed = 0
        self.encoding = ""
        self.allowed_encodings: Sequence[str] = ()
        self.core_encodings: Sequence[str] = ()
        self.encodings: Sequence[str] = ()
        self.lossless_encodings: Sequence[str] = ()
        self.lossless_mode_encodings: Sequence[str] = ()
        self.default_encoding: str = ""
        self.scaling_control = None
        self.video = True

    def init(self, opts) -> None:
        self.encoding = opts.encoding
        self.allowed_encodings = opts.encodings
        self.default_quality = opts.quality
        self.default_min_quality = opts.min_quality
        self.default_speed = opts.speed
        self.default_min_speed = opts.min_speed
        self.video = opts.video
        if self.video:
            if opts.video_scaling.lower() not in ("auto", "on"):
                self.scaling_control = parse_bool_or_int("video-scaling", opts.video_scaling)
            getVideoHelper().set_modules(video_encoders=opts.video_encoders, csc_modules=opts.csc_modules)

    def setup(self) -> None:
        # essential codecs, load them early:
        load_codec("enc_rgb")
        load_codec("enc_pillow")
        ae = self.allowed_encodings
        if "webp" in ae:
            # try to load the fast webp encoder:
            load_codec("enc_webp")
        if "png" in ae or "png/L" in ae:
            # try to load the fast png encoder:
            load_codec("enc_spng")
        if "jpeg" in ae or "jpega" in ae:
            # try to load the fast jpeg encoders:
            load_codec("enc_jpeg")
        if "avif" in ae:
            load_codec("enc_avif")
        self.connect("init-thread-ended", self.reinit_encodings)
        self.init_encodings()

    def reinit_encodings(self, *args) -> None:
        self.init_encodings()
        # any window mapped before the threaded init completed
        # may need to re-initialize its list of encodings:
        log("reinit_encodings()", args)
        try:
            from xpra.server.source.window import WindowsConnection
        except ImportError:
            return
        for ss in self._server_sources.values():
            if isinstance(ss, WindowsConnection):
                ss.reinit_encodings(self)
                ss.reinit_encoders()

    def threaded_setup(self) -> None:
        if INIT_DELAY > 0:
            from time import sleep
            sleep(INIT_DELAY)
        # load the slower codecs
        if "jpeg" in self.allowed_encodings and not OSX:
            load_codec("enc_nvjpeg")
        if self.video:
            # load video codecs:
            getVideoHelper().init()
        self.init_encodings()

    def cleanup(self) -> None:
        getVideoHelper().cleanup()
        unload_codecs()

    def get_server_features(self, source=None) -> dict[str, Any]:
        wants = getattr(source, "wants", [])
        if "features" in wants:
            return {

            }
        return {}

    def get_info(self, _proto) -> dict[str, Any]:
        info = {
            "encodings": self.get_encoding_info(),
        }
        if self.video:
            info["video"] = getVideoHelper().get_info()
        if FULL_INFO > 0:
            for k, v in codec_versions.items():
                info.setdefault("encoding", {}).setdefault(k, {})["version"] = vtrim(v)
        return info

    def get_encoding_info(self) -> dict[str, Any]:
        info = {
            "": self.encodings,  # redundant since v6
            "core": self.core_encodings,
            "allowed": self.allowed_encodings,
            "lossless": self.lossless_encodings,
            "with_speed": tuple(set({"rgb32": "rgb", "rgb24": "rgb"}.get(x, x)
                                    for x in self.core_encodings if x in ENCODINGS_WITH_SPEED)),
            "with_quality": tuple(x for x in self.core_encodings if x in ENCODINGS_WITH_QUALITY),
            "with_lossless_mode": self.lossless_mode_encodings,
        }
        info.update(self.get_encoding_settings())
        return info

    def get_encoding_settings(self) -> dict[str, Any]:
        info = {}
        for prop, value in {
            "quality": self.default_quality,
            "min-quality": self.default_min_quality,
            "speed": self.default_speed,
            "min-speed": self.default_min_speed,
        }.items():
            if value > 0:
                info[prop] = value
        return info

    def init_encodings(self) -> None:
        encs: list[str] = []
        core_encs: list[str] = []
        lossless: list[str] = []
        log("init_encodings() allowed_encodings=%s", self.allowed_encodings)

        def add_encoding(encoding: str) -> None:
            log("add_encoding(%s)", encoding)
            enc = {"rgb32": "rgb", "rgb24": "rgb"}.get(encoding, encoding)
            if self.allowed_encodings is not None:
                if enc not in self.allowed_encodings and encoding not in self.allowed_encodings:
                    # not in whitelist (if it exists)
                    return
            if enc not in encs:
                encs.append(enc)
            if encoding not in core_encs:
                core_encs.append(encoding)
            if encoding in TRUE_LOSSLESS_ENCODINGS and encoding not in lossless:
                lossless.append(encoding)

        def add_encodings(*encodings: str) -> None:
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
        add_encoding("scroll")

        # video encoders (empty when first called - see threaded_init)
        ve = getVideoHelper().get_encodings()
        log("init_encodings() adding video encodings: %s", ve)
        add_encodings(*ve)  # ie: ["vp8", "h264"]
        # Pithon Imaging Library:
        enc_pillow = get_codec("enc_pillow")
        log("enc_pillow=%s", enc_pillow)
        if enc_pillow:
            pil_encs = enc_pillow.get_encodings()
            log("pillow encodings: %s", pil_encs)
            for encoding in pil_encs:
                add_encoding(encoding)
        for codec_name in ("enc_avif", "enc_jpeg", "enc_nvjpeg"):
            codec = get_codec(codec_name)
            if codec:
                add_encodings(*codec.get_encodings())
        # look for video encodings with lossless mode:
        for enc in ve:
            for colorspace, especs in getVideoHelper().get_encoder_specs(enc).items():
                for espec in especs:
                    if espec.has_lossless_mode and enc not in lossless:
                        log("found lossless mode for encoding %s with %s and colorspace %s", enc, espec, colorspace)
                        lossless.append(enc)
                        break
        # now update the variables:
        encs.append("grayscale")
        if any(enc in encs for enc in STREAM_ENCODINGS):
            encs.append("stream")
        self.encodings = preforder(encs)
        self.core_encodings = preforder(core_encs)
        self.lossless_mode_encodings = preforder(lossless)
        self.lossless_encodings = preforder(enc for enc in core_encs
                                            if (enc.startswith("png") or enc.startswith("rgb") or enc == "webp"))
        log("allowed encodings=%s, encodings=%s, core encodings=%s, lossless encodings=%s",
            self.allowed_encodings, encs, core_encs, self.lossless_encodings)
        self.default_encoding = self.encodings[0]
        # default encoding:
        if not self.encoding or str(self.encoding).lower() in ("auto", "none"):
            self.default_encoding = ""
        elif self.encoding in self.encodings:
            log.warn("ignored invalid default encoding option: %s", self.encoding)
            self.default_encoding = self.encoding

    def _process_encoding_set(self, proto, packet: Packet) -> None:
        encoding = packet.get_str(1)
        ss = self.get_server_source(proto)
        if ss is None:
            return
        if len(packet) >= 3:
            # client specified which windows this is for:
            in_wids = packet[2]
            wids = []
            wid_windows = {}
            for wid in in_wids:
                if wid not in self._id_to_window:
                    continue
                wids.append(wid)
                wid_windows[wid] = self._id_to_window.get(wid)
        else:
            # apply to all windows:
            wids = None
            wid_windows = self._id_to_window
        ss.set_encoding(encoding, wids)
        self._refresh_windows(proto, wid_windows, {})

    def _process_quality(self, proto, packet) -> None:
        self._modify_sq(proto, "quality", packet[1])

    def _process_min_quality(self, proto, packet) -> None:
        self._modify_sq(proto, "min-quality", packet[1])

    def _process_max_quality(self, proto, packet) -> None:
        self._modify_sq(proto, "max-quality", packet[1])

    def _process_speed(self, proto, packet) -> None:
        self._modify_sq(proto, "speed", packet[1])

    def _process_min_speed(self, proto, packet) -> None:
        self._modify_sq(proto, "min-speed", packet[1])

    def _process_max_speed(self, proto, packet) -> None:
        self._modify_sq(proto, "max-speed", packet[1])

    def _modify_sq(self, proto, attr: str, value: int) -> None:
        """ modify speed or quality attributes """
        ss = self.get_server_source(proto)
        if not ss:
            return
        assert attr in ENCODING_OPTIONS
        log("Setting %s to %s", attr, value)
        fn = getattr(ss, "set_%s" % attr.replace("-", "_"))
        fn(value)
        self.call_idle_refresh_all_windows(proto)

    def call_idle_refresh_all_windows(self, proto) -> None:
        # we can't assume that the window server mixin is loaded:
        refresh = getattr(self, "_idle_refresh_all_windows", None)
        if refresh:
            refresh(proto)  # pylint: disable=not-callable

    def _process_encoding_options(self, proto, packet) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            return
        updates = packet[1]
        for attr, value in updates.items():
            if attr not in ENCODING_OPTIONS:
                log.warn(f"Warning: {attr!r} is not a valid encoding option")
                continue
            log(f"setting {attr!r} to {value!r}")
            fn = getattr(ss, "set_%s" % attr.replace("-", "_"))
            fn(value)
        self.call_idle_refresh_all_windows(proto)

    def init_packet_handlers(self) -> None:
        self.add_packets(f"{EncodingServer.PREFIX}-set", f"{EncodingServer.PREFIX}-options")
        # legacy:
        self.add_packets(
            "quality", "min-quality", "max-quality",
            "speed", "min-speed", "max-speed",
        )
        self.add_legacy_alias("encodings", f"{EncodingServer.PREFIX}-set")
