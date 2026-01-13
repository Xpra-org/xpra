# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time
import operator
from math import sqrt, ceil
from functools import reduce
from time import monotonic
from typing import Any
from collections.abc import Callable, Iterable, Sequence

from xpra.os_util import gi_import
from xpra.net.compression import Compressed, LargeStructure
from xpra.codecs.constants import (
    TransientCodecException, get_subsampling,
    RGB_FORMATS, PIXEL_SUBSAMPLING, COMPRESS_FMT_PREFIX,
    COMPRESS_FMT_SUFFIX, COMPRESS_FMT,
)
from xpra.codecs.image import ImageWrapper
from xpra.codecs.protocols import ColorspaceConverter
from xpra.server.window.compress import (
    WindowSource, DelayedRegions, get_encoder_type, free_image_wrapper,
    STRICT_MODE, LOSSLESS_WINDOW_TYPES,
    DOWNSCALE_THRESHOLD, DOWNSCALE, TEXT_QUALITY,
    LOG_ENCODERS,
)
from xpra.net.common import Packet
from xpra.util.rectangle import rectangle, merge_all
from xpra.server.window.video_subregion import VideoSubregion, VIDEO_SUBREGION
from xpra.server.window.video_scoring import get_pipeline_score
from xpra.codecs.constants import PREFERRED_ENCODING_ORDER, EDGE_ENCODING_ORDER, preforder, CSCSpec
from xpra.codecs.protocols import VideoEncoder
from xpra.codecs.loader import has_codec
from xpra.common import roundup, MIN_VREFRESH, MAX_VREFRESH, BACKWARDS_COMPATIBLE
from xpra.util.parsing import parse_scaling_value
from xpra.util.objects import typedict
from xpra.util.str_fn import csv, print_nested_dict
from xpra.util.env import envint, envbool, first_time
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("encoding")
csclog = Logger("csc")
scorelog = Logger("score")
scalinglog = Logger("scaling")
sublog = Logger("subregion")
videolog = Logger("video")
avsynclog = Logger("av-sync")
scrolllog = Logger("scroll")
compresslog = Logger("compress")
refreshlog = Logger("refresh")
regionrefreshlog = Logger("regionrefresh")
gstlog = Logger("gstreamer")


TEXT_USE_VIDEO = envbool("XPRA_TEXT_USE_VIDEO", False)
MAX_NONVIDEO_PIXELS = envint("XPRA_MAX_NONVIDEO_PIXELS", 1024*4)
MIN_VIDEO_FPS = envint("XPRA_MIN_VIDEO_FPS", 10)
MIN_VIDEO_EVENTS = envint("XPRA_MIN_VIDEO_EVENTS", 20)
ENCODE_QUEUE_MIN_GAP = envint("XPRA_ENCODE_QUEUE_MIN_GAP", 5)

VIDEO_TIMEOUT = envint("XPRA_VIDEO_TIMEOUT", 10)
VIDEO_NODETECT_TIMEOUT = envint("XPRA_VIDEO_NODETECT_TIMEOUT", 10*60)
TRACK_REGION = envbool("XPRA_VIDEO_TRACK_REGION", True)

FORCE_CSC_MODE = os.environ.get("XPRA_FORCE_CSC_MODE", "")   # ie: "YUV444P"
if FORCE_CSC_MODE and FORCE_CSC_MODE not in RGB_FORMATS and get_subsampling(FORCE_CSC_MODE) not in PIXEL_SUBSAMPLING:
    log.warn("ignoring invalid CSC mode specified: %s", FORCE_CSC_MODE)
    FORCE_CSC_MODE = ""
FORCE_CSC = bool(FORCE_CSC_MODE) or envbool("XPRA_FORCE_CSC", False)
SCALING = envbool("XPRA_SCALING", True)
SCALING_HARDCODED = parse_scaling_value(os.environ.get("XPRA_SCALING_HARDCODED", ""))
SCALING_PPS_TARGET = envint("XPRA_SCALING_PPS_TARGET", 25*1920*1080)
SCALING_MIN_PPS = envint("XPRA_SCALING_MIN_PPS", 25*320*240)
DEFAULT_SCALING_OPTIONS = (1, 10), (1, 5), (1, 4), (1, 3), (1, 2), (2, 3), (1, 1)

ALWAYS_FREEZE = envbool("XPRA_IMAGE_ALWAYS_FREEZE", False)


def parse_scaling_options_str(scaling_options_str: str) -> tuple:
    if not scaling_options_str:
        return ()
    # parse 1/10,1/5,1/4,1/3,1/2,2/3,1/1
    # or even: 1:10, 1:5, ...
    vs_options = []
    for option in scaling_options_str.split(","):
        try:
            if option.find("%") > 0:
                v = float(option[:option.find("%")])*100
                vs_options.append(v.as_integer_ratio())
            elif option.find("/") < 0:
                v = float(option)
                vs_options.append(v.as_integer_ratio())
            else:
                num, den = option.strip().split("/")
                vs_options.append((int(num), int(den)))
        except ValueError:
            scalinglog.warn("Warning: invalid scaling string '%s'", option.strip())
    if vs_options:
        return tuple(vs_options)
    return ()


SCALING_OPTIONS = parse_scaling_options_str(os.environ.get("XPRA_SCALING_OPTIONS", "")) or DEFAULT_SCALING_OPTIONS
scalinglog("scaling options: SCALING=%s, HARDCODED=%s, PPS_TARGET=%i, MIN_PPS=%i, OPTIONS=%s",
           SCALING, SCALING_HARDCODED, SCALING_PPS_TARGET, SCALING_MIN_PPS, SCALING_OPTIONS)

DEBUG_VIDEO_CLEAN = envbool("XPRA_DEBUG_VIDEO_CLEAN", False)

FORCE_AV_DELAY = envint("XPRA_FORCE_AV_DELAY", -1)
AV_SYNC_DEFAULT = envbool("XPRA_AV_SYNC_DEFAULT", False)
B_FRAMES = envbool("XPRA_B_FRAMES", True)
VIDEO_SKIP_EDGE = envbool("XPRA_VIDEO_SKIP_EDGE", False)
SCROLL_MIN_PERCENT = max(1, min(100, envint("XPRA_SCROLL_MIN_PERCENT", 30)))
MIN_SCROLL_IMAGE_SIZE = envint("XPRA_MIN_SCROLL_IMAGE_SIZE", 128)

STREAM_MODE = os.environ.get("XPRA_STREAM_MODE", "auto")
STREAM_CONTENT_TYPES = os.environ.get("XPRA_STREAM_CONTENT_TYPES", "desktop,video").split(",")
GSTREAMER_X11_TIMEOUT = envint("XPRA_GSTREAMER_X11_TIMEOUT", 500)

SAVE_VIDEO_PATH = os.environ.get("XPRA_SAVE_VIDEO_PATH", "")
SAVE_VIDEO_STREAMS = envbool("XPRA_SAVE_VIDEO_STREAMS", False)
SAVE_VIDEO_FRAMES = os.environ.get("XPRA_SAVE_VIDEO_FRAMES", "")
if SAVE_VIDEO_FRAMES not in ("png", "jpeg", ""):
    log.warn("Warning: invalid value for 'XPRA_SAVE_VIDEO_FRAMES'")
    log.warn(" only 'png' or 'jpeg' are allowed")
    SAVE_VIDEO_FRAMES = ""

COMPRESS_SCROLL_FMT = COMPRESS_FMT_PREFIX+" as %3i rectangles  (%5iKB to     0KB)"+COMPRESS_FMT_SUFFIX


def get_pipeline_score_info(score, scaling,
                            csc_scaling, csc_width: int, csc_height: int, csc_spec,
                            enc_in_format, encoder_scaling, enc_width: int, enc_height: int, encoder_spec)\
        -> dict[str, Any]:
    def specinfo(x):
        try:
            return x.codec_type
        except AttributeError:
            return repr(x)
    ei = {
        ""        : specinfo(encoder_spec),
        "width"   : enc_width,
        "height"  : enc_height,
    }
    if encoder_scaling != (1, 1):
        ei["scaling"] = encoder_scaling
    pi : dict[str, Any] = {
        "score"             : score,
        "format"            : str(enc_in_format),
        "encoder"           : ei,
    }
    if scaling != (1, 1):
        pi["scaling"] = scaling
    if csc_spec:
        csci : dict[str, Any] = {
            ""         : specinfo(csc_spec),
            "width"    : csc_width,
            "height"   : csc_height,
        }
        if csc_scaling != (1, 1):
            csci["scaling"] = csc_scaling
        pi["csc"] = csci
    else:
        pi["csc"] = "None"
    return pi


def save_video_frame(wid: int, image: ImageWrapper) -> None:
    t = monotonic()
    tstr = time.strftime("%H-%M-%S", time.localtime(t))
    filename = "W%i-VDO-%s.%03i.%s" % (wid, tstr, (t * 1000) % 1000, SAVE_VIDEO_FRAMES)
    if SAVE_VIDEO_PATH:
        filename = os.path.join(SAVE_VIDEO_PATH, filename)
    from xpra.codecs.debug import save_imagewrapper
    save_imagewrapper(image, filename)


class WindowVideoSource(WindowSource):
    """
        A WindowSource that handles video codecs.
    """

    def __init__(self, *args):
        self.supports_scrolling: bool = False
        # this will call init_vars():
        super().__init__(*args)
        self.scroll_min_percent: int = self.encoding_options.intget("scrolling.min-percent", SCROLL_MIN_PERCENT)
        self.scroll_preference: int = self.encoding_options.intget("scrolling.preference", 100)
        self.supports_video_b_frames: Sequence[str] = self.encoding_options.strtupleget("video_b_frames", ())
        self.video_max_size = self.encoding_options.inttupleget("video_max_size", (8192, 8192), 2, 2)
        self.video_stream_file = None

    def __repr__(self) -> str:
        return f"WindowVideoSource({self.wid:#x} : {self.window_dimensions})"

    def init_vars(self) -> None:
        super().init_vars()
        # these constraints get updated with real values
        # when we construct the video pipeline:
        self.min_w: int = 8
        self.min_h: int = 8
        self.max_w: int = 16384
        self.max_h: int = 16384
        self.width_mask: int = 0xFFFF
        self.height_mask: int = 0xFFFF
        self.actual_scaling = (1, 1)

        self.last_pipeline_params : tuple = ()
        self.last_pipeline_scores : tuple = ()
        self.last_pipeline_time: float = 0.0

        self.video_subregion = VideoSubregion(self.refresh_subregion, self.auto_refresh_delay, VIDEO_SUBREGION)
        self.video_subregion.supported = VIDEO_SUBREGION
        self.video_encodings: Sequence[str] = ()
        self.common_video_encodings: Sequence[str] = ()
        self.non_video_encodings: Sequence[str] = ()
        self.video_fallback_encodings: dict = {}
        self.edge_encoding: str = ""
        self.start_video_frame: int = 0
        self.gstreamer_timer: int = 0
        self.video_encoder_timer: int = 0
        self.b_frame_flush_timer: int = 0
        self.b_frame_flush_data : tuple = ()
        self.encode_from_queue_timer: int = 0
        self.encode_from_queue_due = 0
        self.scroll_data = None
        self.last_scroll_time = 0.0
        self.stream_mode = STREAM_MODE
        self.gstreamer_pipeline = None

        self._csc_encoder: ColorspaceConverter | None = None
        self._video_encoder: VideoEncoder | None = None
        self._last_pipeline_check = 0

    def do_init_encoders(self) -> None:
        super().do_init_encoders()
        self._csc_encoder = None
        self._video_encoder = None
        self._last_pipeline_check = 0

        def add(enc, encode_fn) -> None:
            self.insert_encoder(enc, enc, encode_fn)
        if has_codec("csc_libyuv"):
            # need libyuv to be able to handle 'grayscale' video:
            # (to convert ARGB to grayscale)
            add("grayscale", self.video_encode)
        if self._mmap:
            self.non_video_encodings = ()
            self.common_video_encodings = ()
            return
        # make sure we actually have encoders for these:
        vencs = self.video_helper.get_encodings()
        self.video_encodings = preforder(vencs)
        self.common_video_encodings = preforder(set(self.video_encodings) & set(self.core_encodings))
        log(f"do_init_encoders() video encodings({vencs})={self.video_encodings}")
        log(f"do_init_encoders() common video encodings={self.common_video_encodings}")
        video_enabled = []
        for x in self.common_video_encodings:
            self.append_encoder(x, self.video_encode)
            video_enabled.append(x)
        # video_encode() is used for more than just video encoders:
        # (always enable it and let it fall through)
        add("auto", self.video_encode)
        add("stream", self.video_encode)
        # these are used for non-video areas, ensure "jpeg" is used if available
        # as we may be dealing with large areas still, and we want speed:
        enc_options = set(self.server_core_encodings) & set(self._encoders.keys())
        nv_common = enc_options & set(self.core_encodings) & set(self.picture_encodings)
        self.non_video_encodings = preforder(nv_common)
        log("do_init_encoders()")
        log(f" server core encodings={self.server_core_encodings}")
        log(f" client core encodings={self.core_encodings}")
        log(f" video encodings={self.video_encodings}")
        log(f" common video encodings={self.common_video_encodings}")
        log(f" non video encodings={self.non_video_encodings}")
        if "scroll" in self.server_core_encodings:
            add("scroll", self.scroll_encode)

    def do_set_auto_refresh_delay(self, min_delay, delay) -> None:
        super().do_set_auto_refresh_delay(min_delay, delay)
        r = self.video_subregion
        if r:
            r.set_auto_refresh_delay(self.base_auto_refresh_delay)

    def update_av_sync_frame_delay(self) -> None:
        self.av_sync_frame_delay = 0
        ve = self._video_encoder
        if ve:
            # how many frames are buffered in the encoder, if any:
            d = ve.get_info().get("delayed", 0)
            if d > 0:
                # clamp the batch delay to a reasonable range:
                frame_delay = min(100, max(10, self.batch_config.delay))
                self.av_sync_frame_delay += frame_delay * d
            avsynclog("update_av_sync_frame_delay() video encoder=%s, delayed frames=%i, frame delay=%i",
                      ve, d, self.av_sync_frame_delay)
        self.may_update_av_sync_delay()

    def get_property_info(self) -> dict[str, Any]:
        i = super().get_property_info()
        if self.scaling_control is None:
            i["scaling.control"] = "auto"
        else:
            i["scaling.control"] = self.scaling_control
        i["scaling"] = self.scaling or (1, 1)
        return i

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        sr = self.video_subregion
        if sr:
            sri = sr.get_info()
            sri["video-mode"] = self.subregion_is_video()
            info["video_subregion"] = sri
        info["scaling"] = self.actual_scaling
        info["video-max-size"] = self.video_max_size
        info["stream-mode"] = self.stream_mode

        def addcinfo(prefix, x) -> None:
            if not x:
                return
            with log.trap_error(f"Error collecting codec information from {x}"):
                i = x.get_info()
                i[""] = x.get_type()
                info[prefix] = i
        addcinfo("csc", self._csc_encoder)
        addcinfo("encoder", self._video_encoder)
        info.setdefault("encodings", {}).update({
            "non-video"    : self.non_video_encodings,
            "video"        : self.common_video_encodings,
            "edge"         : self.edge_encoding,
        })
        einfo: dict[str, Any] = {
            "pipeline_param" : self.get_pipeline_info(),
            "scrolling"      : {
                "enabled"      : self.supports_scrolling,
                "min-percent"  : self.scroll_min_percent,
                "preference"   : self.scroll_preference,
                "event"       : int(self.last_scroll_event*1000),
                "time"        : int(self.last_scroll_time*1000),
            }
        }
        if self._last_pipeline_check > 0:
            einfo["pipeline_last_check"] = int(1000*(monotonic()-self._last_pipeline_check))
        lps = self.last_pipeline_scores
        if lps:
            popts : dict[int, dict[str, Any]] = {}
            for i, lp in enumerate(lps):
                popts[i] = get_pipeline_score_info(*lp)
            einfo["pipeline_option"] = popts
        info.setdefault("encoding", {}).update(einfo)
        return info

    def get_pipeline_info(self) -> dict[str, Any]:
        lp = self.last_pipeline_params
        if not lp:
            return {}
        encoding, width, height, src_format = lp
        return {
            "encoding"      : encoding,
            "dimensions"    : (width, height),
            "src_format"    : src_format
        }

    def suspend(self) -> None:
        super().suspend()
        # we'll create a new video pipeline when resumed:
        self.cleanup_codecs()

    def cleanup(self) -> None:
        super().cleanup()
        self.cleanup_codecs()
        self.stop_gstreamer_pipeline()

    def cleanup_codecs(self) -> None:
        """ Video encoders (x264, nvenc and vpx) and their csc helpers
            require us to run cleanup code to free the memory they use.
            We have to do this from the encode thread to be safe.
            (the encoder and csc module may be in use by that thread)
        """
        self.cancel_video_encoder_flush()
        self.video_context_clean()

    def video_context_clean(self) -> None:
        """ Calls clean() from the encode thread """
        csce = self._csc_encoder
        ve = self._video_encoder
        if csce or ve:
            if DEBUG_VIDEO_CLEAN:
                log.warn("video_context_clean() for wid %i: %s and %s", self.wid, csce, ve, backtrace=True)
            self._csc_encoder = None
            self._video_encoder = None

            def clean() -> None:
                if DEBUG_VIDEO_CLEAN:
                    log.warn("video_context_clean() done")
                self.csc_clean(csce)
                self.ve_clean(ve)
            self.call_in_encode_thread(False, clean)

    # noinspection PyMethodMayBeStatic
    def csc_clean(self, csce) -> None:
        if csce:
            csce.clean()

    def ve_clean(self, ve) -> None:
        self.cancel_video_encoder_timer()
        if ve:
            ve.clean()
            # only send eos if this video encoder is still current,
            # (otherwise, sending the new stream will have taken care of it already,
            # and sending eos then would close the new stream, not the old one!)
            if self._video_encoder == ve:
                log("sending eos for wid %i", self.wid)
                self.queue_packet(("eos", self.wid))
            if SAVE_VIDEO_STREAMS:
                self.close_video_stream_file()

    def close_video_stream_file(self) -> None:
        vsf = self.video_stream_file
        if vsf:
            self.video_stream_file = None
            with log.trap_error(f"Error closing video stream file {vsf}"):
                vsf.close()

    def ui_cleanup(self) -> None:
        super().ui_cleanup()
        self.video_subregion = None

    def set_new_encoding(self, encoding : str, strict=None) -> None:
        if self.encoding != encoding:
            # ensure we re-init the codecs asap:
            self.cleanup_codecs()
        super().set_new_encoding(encoding, strict)

    def insert_encoder(self, encoder_name : str, encoding : str, encode_fn : Callable) -> None:
        super().insert_encoder(encoder_name, encoding, encode_fn)
        # we don't want to use nvjpeg as fallback,
        # because it requires a GPU context
        # and the fallback should be reliable.
        # also, we only want picture encodings here,
        # and filtering using EDGE_ENCODING_ORDER gives us that.
        if encoder_name != "nvjpeg" and encoding in EDGE_ENCODING_ORDER:
            self.video_fallback_encodings.setdefault(encoding, []).insert(0, encode_fn)

    def update_encoding_selection(self, encoding="", exclude=None, init=False) -> None:
        # override so we don't use encodings that don't have valid csc modes:
        log("wvs.update_encoding_selection(%s, %s, %s) full_csc_modes=%s", encoding, exclude, init, self.full_csc_modes)
        if exclude is None:
            exclude = []
        videolog(f"encoding={encoding}, video_encodings={self.video_encodings}, core_encodings={self.core_encodings}")
        for x in self.video_encodings:
            if x not in self.core_encodings:
                log("video encoding %s not in core encodings", x)
                exclude.append(x)
                continue
            csc_modes = self.full_csc_modes.strtupleget(x)
            if (not csc_modes or x not in self.core_encodings) and first_time(f"nocsc-{x}-{self.wid:#x}"):
                exclude.append(x)
                msg_args = ("Warning: client does not support any csc modes with %s on window %i", x, self.wid)
                if x == "jpega" and not self.supports_transparency:
                    log(f"skipping {x} since client does not support transparency")
                elif not init and first_time(f"no-csc-{x}-{self.wid:#x}"):
                    log.warn(*msg_args)
                else:
                    log(*msg_args)
                log(" csc modes=%", self.full_csc_modes)
        self.common_video_encodings = preforder(set(self.video_encodings) & set(self.core_encodings))
        videolog("update_encoding_selection: common_video_encodings=%s, csc_encoder=%s, video_encoder=%s",
                 self.common_video_encodings, self._csc_encoder, self._video_encoder)
        if encoding in ("stream", "auto", "grayscale"):
            vh = self.video_helper
            if encoding in ("auto", "stream") and self.content_type in STREAM_CONTENT_TYPES and vh:
                accel = vh.get_gpu_encodings()
                common_accel = preforder(set(self.common_video_encodings) & set(accel.keys()))
                videolog(f"gpu {accel=} - {common_accel=}")
                if common_accel:
                    encoding = "stream"
                    accel_types: set[str] = set()
                    for gpu_encoding in common_accel:
                        for accel_option in accel.get(gpu_encoding, ()):
                            # 'gstreamer-vah264lpenc' -> 'gstreamer'
                            accel_types.add(accel_option.codec_type.split("-", 1)[0])
                    videolog(f"gpu encoder types: {accel_types}")
                    self.stream_mode = STREAM_MODE
                    # switch to GStreamer mode if all the GPU accelerated options require it:
                    if self.stream_mode == "auto" and len(accel_types) == 1 and tuple(accel_types)[0] == "gstreamer":
                        self.stream_mode = "gstreamer"
                    if first_time(f"gpu-stream-{self.wid:#x}"):
                        videolog.info(f"found GPU accelerated encoders for: {csv(common_accel)}")
                        videolog.info(f"switching to {encoding!r} encoding for {self.content_type!r} window {self.wid:#x}")
                        if self.stream_mode == "gstreamer":
                            videolog.info("using 'gstreamer' stream mode")
        super().update_encoding_selection(encoding, exclude, init)
        self.supports_scrolling = "scroll" in self.common_encodings

    def do_set_client_properties(self, properties: typedict) -> None:
        # client may restrict csc modes for specific windows
        self.supports_scrolling = "scroll" in self.common_encodings
        self.scroll_min_percent = properties.intget("scrolling.min-percent", self.scroll_min_percent)
        self.scroll_preference = properties.intget("scrolling.preference", self.scroll_preference)
        if VIDEO_SUBREGION:
            self.video_subregion.supported = properties.boolget("encoding.video_subregion", True)
        if properties.get("scaling.control") is not None:
            self.scaling_control = max(0, min(100, properties.intget("scaling.control", 0)))
        super().do_set_client_properties(properties)
        # encodings may have changed, so redo this:
        nv_common = set(self.picture_encodings) & set(self.core_encodings)
        log("common non-video (%s & %s)=%s", self.picture_encodings, self.core_encodings, nv_common)
        self.non_video_encodings = preforder(nv_common)
        if not VIDEO_SKIP_EDGE:
            try:
                self.edge_encoding = next(x for x in EDGE_ENCODING_ORDER if x in self.non_video_encodings)
            except StopIteration:
                self.edge_encoding = ""
        log("do_set_client_properties(%s)", properties)
        log(" full_csc_modes=%s, video_subregion=%s, non_video_encodings=%s, edge_encoding=%s, scaling_control=%s",
            self.full_csc_modes, self.video_subregion.supported,
            self.non_video_encodings, self.edge_encoding, self.scaling_control)

    def get_best_encoding_impl_default(self) -> Callable[..., str]:
        log("get_best_encoding_impl_default() window_type=%s, encoding=%s", self.window_type, self.encoding)
        if self.is_tray:
            log("using default for tray")
            return super().get_best_encoding_impl_default()
        if self.encoding == "stream":
            log("using stream encoding")
            return self.get_best_encoding_video
        if self.window_type.intersection(LOSSLESS_WINDOW_TYPES):
            log("using default for lossless window type %s", self.window_type)
            return super().get_best_encoding_impl_default()
        if self.encoding != "grayscale" or has_codec("csc_libyuv"):
            if self.common_video_encodings or self.supports_scrolling:
                log("using video encoding")
                return self.get_best_encoding_video
        log("using default best encoding")
        return super().get_best_encoding_impl_default()

    def get_best_encoding_video(self, w: int, h: int, options, current_encoding: str) -> str:
        """
            decide whether we send a full window update using the video encoder,
            or if a separate small region(s) is a better choice
        """
        def nonvideo(qdiff=0, info="") -> str:
            if qdiff:
                quality = options.get("quality", self._current_quality) + qdiff
                options["quality"] = max(self._fixed_min_quality, min(self._fixed_max_quality, quality))
            videolog("nonvideo(%s, %s)", qdiff, info)
            return WindowSource.get_auto_encoding(self, w, h, options)

        # log("get_best_encoding_video%s non_video_encodings=%s, common_video_encodings=%s, supports_scrolling=%s",
        #    (pixel_count, ww, wh, speed, quality, current_encoding),
        #     self.non_video_encodings, self.common_video_encodings, self.supports_scrolling)
        if not self.non_video_encodings:
            return current_encoding
        if not self.common_video_encodings and not self.supports_scrolling:
            return nonvideo(info="no common video encodings or scrolling")
        if self.is_tray:
            return nonvideo(100, "system tray")
        text_hint = self.content_type.find("text") >= 0
        if text_hint and not TEXT_USE_VIDEO:
            return nonvideo(100, info="text content-type")

        # ensure the dimensions we use for decision-making are the ones actually used:
        cww = w & self.width_mask
        cwh = h & self.height_mask
        if cww < 64 or cwh < 64:
            return nonvideo(info="area is too small")

        if self.encoding == "stream":
            return current_encoding

        video_hint = int(self.content_type.find("video") >= 0)
        if self.pixel_format:
            # if we have a hardware video encoder, use video more:
            self.update_pipeline_scores()
            for i, score_data in enumerate(self.last_pipeline_scores):
                encoder_spec = score_data[-1]
                if encoder_spec.gpu_cost > encoder_spec.cpu_cost:
                    videolog(f"found GPU accelerated encoder {encoder_spec}")
                    video_hint += 1+int(i == 0)
                    break
        rgbmax = self._rgb_auto_threshold
        videomin = cww*cwh // (1+video_hint*2)
        sr = self.video_subregion.rectangle
        if sr:
            videomin = min(videomin, sr.width * sr.height)
            rgbmax = min(rgbmax, sr.width*sr.height//2)
        elif text_hint:
            # TEXT_USE_VIDEO must be set,
            # but only use video if the whole area changed:
            videomin = cww*cwh
        else:
            videomin = min(640*480, cww*cwh) // (1+video_hint*2)
        # log(f"ww={ww}, wh={wh}, rgbmax={rgbmax}, videohint={video_hint},
        #    videomin={videomin}, sr={sr}, pixel_count={pixel_count}")
        pixel_count = w*h
        if pixel_count <= rgbmax:
            return nonvideo(info=f"low pixel count {pixel_count}")

        if current_encoding not in ("auto", "grayscale") and current_encoding not in self.common_video_encodings:
            return nonvideo(info=f"{current_encoding} not a supported video encoding")

        if cww < self.min_w or cww > self.max_w or cwh < self.min_h or cwh > self.max_h:
            return nonvideo(info="size out of range for video encoder")

        now = monotonic()
        if now-self.statistics.last_packet_time > 1:
            return nonvideo(info="no recent updates")
        if now-self.statistics.last_resized < 0.350:
            return nonvideo(info="resized recently")

        if sr and ((sr.width & self.width_mask) != cww or (sr.height & self.height_mask) != cwh):
            # we have a video region, and this is not it, so don't use video
            # raise the quality as the areas around video tend to not be updating as quickly
            return nonvideo(30, "not the video region")

        if not video_hint and not self.is_shadow:
            if now-self.global_statistics.last_congestion_time > 5:
                lde = tuple(self.statistics.last_damage_events)
                lim = now-4
                pixels_last_4secs = sum(w*h for when, _, _, w, h in lde if when > lim)
                if pixels_last_4secs < ((3+text_hint*6)*videomin):
                    return nonvideo(info="not enough frames")
                lim = now-1
                pixels_last_sec = sum(w*h for when, _, _, w, h in lde if when > lim)
                if pixels_last_sec < pixels_last_4secs//8:
                    # framerate is dropping?
                    return nonvideo(30, "framerate lowered")

            # calculate the threshold for using video vs small regions:
            speed = options.get("speed", self._current_speed)
            factors = (
                # speed multiplier:
                max(1, (speed-75)/5.0),
                # OR windows tend to be static:
                1 + int(self.is_OR or self.is_tray)*2,
                # gradual discount the first 9 frames, as the window may be temporary:
                max(1, 10-self._sequence),
                # if we have a video encoder already, make it more likely we'll use it:
                1.0 / (int(bool(self._video_encoder)) + 1),
            )
            max_nvp = int(reduce(operator.mul, factors, MAX_NONVIDEO_PIXELS))
            if pixel_count <= max_nvp:
                # below threshold
                return nonvideo(info=f"not enough pixels: {pixel_count}<{max_nvp}")
        return current_encoding

    def get_best_nonvideo_encoding(self, ww: int, wh: int, options: dict,
                                   current_encoding="", encoding_options=()) -> str:
        if self.encoding == "grayscale":
            return self.encoding_is_grayscale(ww, wh, options, current_encoding or self.encoding)
        # if we're here, then the window has no alpha (or the client cannot handle alpha)
        # and we can ignore the current encoding
        encoding_options = encoding_options or self.non_video_encodings
        depth = self.image_depth
        if (depth == 8 and "png/P" in encoding_options) or self.encoding == "png/P":
            return "png/P"
        if self.encoding == "png/L":
            return "png/L"
        if self._mmap:
            return "mmap"
        return super().do_get_auto_encoding(ww, wh, options, current_encoding or self.encoding, encoding_options)

    def do_damage(self, ww: int, wh: int, x: int, y: int, w: int, h: int, options: dict) -> None:
        if ww >= 64 and wh >= 64 and self.encoding == "stream" and self.stream_mode == "gstreamer":
            # in this mode, we start a pipeline once
            # and let it submit packets, bypassing all the usual logic:
            if self.gstreamer_pipeline or self.start_gstreamer_pipeline():
                gp = self.gstreamer_pipeline
                self.cancel_gstreamer_timer()
                if gp:
                    self.gstreamer_timer = GLib.timeout_add(GSTREAMER_X11_TIMEOUT, self.gstreamer_nodamage)
                    return
        vs = self.video_subregion
        if vs:
            r = vs.rectangle
            if r and r.intersects(x, y, w, h):
                # the damage will take care of scheduling it again
                vs.cancel_refresh_timer()
        super().do_damage(ww, wh, x, y, w, h, options)

    def gstreamer_nodamage(self) -> None:
        gstlog("gstreamer_nodamage() stopping")
        self.gstreamer_timer = 0
        self.stop_gstreamer_pipeline()

    def cancel_gstreamer_timer(self) -> None:
        gt = self.gstreamer_timer
        if gt:
            self.gstreamer_timer = 0
            GLib.source_remove(gt)

    def start_gstreamer_pipeline(self) -> bool:
        from xpra.gstreamer.common import plugin_str
        from xpra.codecs.gstreamer.capture import capture_and_encode
        attrs: dict[str, bool | int] = {
            "show-pointer": False,
            "do-timestamp": True,
            "use-damage": False,
        }
        try:
            xid = self.window.get_property("xid")
        except (TypeError, AttributeError):
            xid = 0
        if xid:
            attrs["xid"] = xid
        capture_element = plugin_str("ximagesrc", attrs)
        w, h = self.window_dimensions
        framerate = 0
        if self.batch_config.min_delay > 20:
            framerate = max(MIN_VREFRESH, min(MAX_VREFRESH, round(1000 / self.batch_config.min_delay)))
        self.gstreamer_pipeline = capture_and_encode(capture_element, self.encoding, self.full_csc_modes,
                                                     w, h, framerate)
        if not self.gstreamer_pipeline:
            return False
        self.gstreamer_pipeline.connect("new-image", self.new_gstreamer_frame)
        self.gstreamer_pipeline.start()
        gstlog("start_gstreamer_pipeline() %s started", self.gstreamer_pipeline)
        return True

    def stop_gstreamer_pipeline(self) -> None:
        gp = self.gstreamer_pipeline
        gstlog("stop_gstreamer_pipeline() gstreamer_pipeline=%s", gp)
        if gp:
            self.gstreamer_pipeline = None
            gp.stop()

    def new_gstreamer_frame(self, _capture_pipeline, coding: str, data, client_info: dict) -> None:
        gstlog(f"new_gstreamer_frame: {coding}")
        if not self.window.is_managed():
            return
        gp = self.gstreamer_pipeline
        if gp and (LOG_ENCODERS or compresslog.is_debug_enabled()):
            client_info["encoder"] = gp.encoder
        self.direct_queue_draw(coding, data, client_info)
        GLib.idle_add(self.gstreamer_continue_damage)

    def gstreamer_continue_damage(self) -> None:
        # ensures that more damage events will be emitted
        self.ui_thread_check()
        self.window.acknowledge_changes()

    def update_window_dimensions(self, ww: int, wh: int) -> None:
        super().update_window_dimensions(ww, wh)
        self.stop_gstreamer_pipeline()

    def cancel_damage(self, limit: int = 0) -> None:
        self.cancel_encode_from_queue()
        self.free_encode_queue_images()
        vsr = self.video_subregion
        if vsr:
            vsr.cancel_refresh_timer()
        self.free_scroll_data()
        self.last_scroll_time = 0
        super().cancel_damage(limit)
        self.cancel_gstreamer_timer()
        self.stop_gstreamer_pipeline()
        # we must clean the video encoder to ensure
        # we will resend a key frame because we may be missing a frame
        self.cleanup_codecs()

    def full_quality_refresh(self, damage_options: dict) -> None:
        vs = self.video_subregion
        if vs and vs.rectangle:
            if vs.detection:
                # reset the video region on full quality refresh
                vs.reset()
            else:
                # keep the region, but cancel the refresh:
                vs.cancel_refresh_timer()
        self.free_scroll_data()
        self.last_scroll_time = 0
        if self.non_video_encodings:
            # refresh the whole window in one go:
            damage_options["novideo"] = True
        super().full_quality_refresh(damage_options)

    def timer_full_refresh(self) -> None:
        self.free_scroll_data()
        self.last_scroll_time = 0
        super().timer_full_refresh()

    def quality_changed(self, window, *args) -> bool:
        super().quality_changed(window, args)
        self.video_context_clean()
        return True

    def speed_changed(self, window, *args) -> bool:
        super().speed_changed(window, args)
        self.video_context_clean()
        return True

    def client_decode_error(self, error: int | float, message: str) -> None:
        # maybe the stream is now corrupted..
        self.cleanup_codecs()
        super().client_decode_error(error, message)

    def get_refresh_exclude(self) -> rectangle | None:
        # exclude video region (if any) from lossless refresh:
        return self.video_subregion.rectangle

    def refresh_subregion(self, regions) -> bool:
        # callback from video subregion to trigger a refresh of some areas
        if not regions:
            regionrefreshlog("refresh_subregion(%s) nothing to refresh", regions)
            return False
        if not self.can_refresh():
            regionrefreshlog("refresh_subregion(%s) cannot refresh", regions)
            return False
        now = monotonic()
        if now-self.global_statistics.last_congestion_time < 5:
            regionrefreshlog("refresh_subregion(%s) skipping refresh due to congestion", regions)
            return False
        self.flush_video_encoder_now()
        encoding = self.auto_refresh_encodings[0]
        options = self.get_refresh_options()
        regionrefreshlog("refresh_subregion(%s) using %s and %s", regions, encoding, options)
        self.do_send_regions(now, regions, encoding, options,
                             get_best_encoding=self.get_refresh_subregion_encoding)
        return True

    def get_refresh_subregion_encoding(self, *_args) -> str:
        ww, wh = self.window_dimensions
        w, h = ww, wh
        vr = self.video_subregion.rectangle
        # could have been cleared by another thread:
        if vr:
            w, h = vr.width, vr.height
        options = {
            "speed": self.refresh_speed,
            "quality": self.refresh_quality,
        }
        return self.get_best_nonvideo_encoding(w, h, options,
                                               self.auto_refresh_encodings[0], self.auto_refresh_encodings)

    def remove_refresh_region(self, region: rectangle) -> None:
        # override so we can update the subregion timers / regions tracking:
        super().remove_refresh_region(region)
        self.video_subregion.remove_refresh_region(region)

    def add_refresh_region(self, region: rectangle) -> int:
        # Note: this does not run in the UI thread!
        # returns the number of pixels in the region update
        # don't refresh the video region as part of normal refresh,
        # use subregion refresh for that
        sarr = super().add_refresh_region
        vr = self.video_subregion.rectangle
        if vr is None:
            # no video region, normal code path:
            return sarr(region)
        if vr.contains_rect(region):
            # all of it is in the video region:
            self.video_subregion.add_video_refresh(region)
            return 0
        ir = vr.intersection_rect(region)
        if ir is None:
            # region is outside video region, normal code path:
            return sarr(region)
        # add intersection (rectangle in video region) to video refresh:
        self.video_subregion.add_video_refresh(ir)
        # add any rectangles not in the video region
        # (if any: keep track if we actually added anything)
        return sum(sarr(r) for r in region.subtract_rect(vr))

    def matches_video_subregion(self, width: int, height: int) -> rectangle | None:
        vr = self.video_subregion.rectangle
        if not vr:
            return None
        mw = abs(width - vr.width) & self.width_mask
        mh = abs(height - vr.height) & self.height_mask
        if mw != 0 or mh != 0:
            return None
        return vr

    def subregion_is_video(self) -> bool:
        vs = self.video_subregion
        if not vs:
            return False
        vr = vs.rectangle
        if not vr:
            return False
        events_count = self.statistics.damage_events_count - vs.set_at
        min_video_events = MIN_VIDEO_EVENTS
        min_video_fps = MIN_VIDEO_FPS
        if self.content_type.find("video") >= 0:
            min_video_events //= 2
            min_video_fps //= 2
        if events_count < min_video_events:
            return False
        if vs.fps < min_video_fps:
            return False
        return True

    def send_regions(self, damage_time: float, regions: Sequence[rectangle], coding: str, options: dict) -> None:
        """
            Overridden here so that we can try to intercept the `video_subregion` if one exists.
        """
        vr = self.video_subregion.rectangle
        # overrides the default method for finding the encoding of a region,
        # so we can ensure we don't use the video encoder when we don't want to:
        def send_nonvideo(regions=regions, encoding: str = coding, exclude_region=None,
                          get_best_encoding=self.get_best_nonvideo_encoding) -> None:
            if self.b_frame_flush_timer and exclude_region is None:
                # a b-frame is already due, don't clobber it!
                exclude_region = vr
            quality_pct = 100
            if vr:
                # give a boost if we have a video region and this is not video:
                quality_pct = 140
            novideo_options = self.assign_sq_options(options, quality_pct=quality_pct)
            self.do_send_regions(damage_time, regions, encoding, novideo_options,
                                 exclude_region=exclude_region, get_best_encoding=get_best_encoding)

        if self.is_tray:
            sublog("BUG? video for tray - don't use video region!")
            send_nonvideo(encoding="")
            return

        if coding not in ("auto", "stream", "grayscale") and coding not in self.video_encodings:
            sublog("not a video encoding: %s", coding)
            # keep current encoding selection function
            send_nonvideo(get_best_encoding=self.get_best_encoding)
            return

        if options.get("novideo"):
            sublog("video disabled in options")
            send_nonvideo(encoding="")
            return

        if not vr:
            sublog("no video region, we may use the video encoder for something else")
            self.do_send_regions(damage_time, regions, coding, options)
            return
        assert not self.full_frames_only

        actual_vr = None
        if vr in regions:
            # found the video region the easy way: exact match in list
            actual_vr = vr
        else:
            # find how many pixels are within the region (roughly):
            # find all unique regions that intersect with it:
            inter = tuple(x for x in (vr.intersection_rect(r) for r in regions) if x is not None)
            if inter:
                # merge all regions into one:
                in_region = merge_all(inter)
                pixels_in_region = vr.width*vr.height
                pixels_intersect = in_region.width*in_region.height
                if pixels_intersect >= pixels_in_region*40/100:
                    # we have at least 40% of the video region
                    # that needs refreshing, do it:
                    actual_vr = vr

            # still no luck?
            if actual_vr is None and TRACK_REGION:
                # try to find one that has the same dimensions:
                same_d = tuple(r for r in regions if r.width == vr.width and r.height == vr.height)
                if len(same_d) == 1:
                    # probably right..
                    actual_vr = same_d[0]
                elif len(same_d) > 1:
                    # find one that shares at least one coordinate:
                    same_c = tuple(r for r in same_d if r.x == vr.x or r.y == vr.y)
                    if len(same_c) == 1:
                        actual_vr = same_c[0]

        if actual_vr is None:
            sublog("send_regions: video region %s not found in: %s", vr, regions)
        else:
            # found the video region:
            # sanity check in case the window got resized since:
            ww, wh = self.window_dimensions
            if actual_vr.x+actual_vr.width > ww or actual_vr.y+actual_vr.height > wh:
                sublog("video region partially outside the window")
                send_nonvideo(encoding="")
                return
            # send this using the video encoder:
            video_options = self.assign_sq_options(options, quality_pct=70)
            # TODO: encode delay can be derived rather than hard-coded
            encode_delay = 50
            video_options["av-delay"] = max(0, self.get_frame_encode_delay(options) - encode_delay)
            self.process_damage_region(damage_time, actual_vr.x, actual_vr.y, actual_vr.width, actual_vr.height,
                                       coding, video_options)

            # now subtract this region from the rest:
            trimmed = []
            for r in regions:
                trimmed += r.subtract_rect(actual_vr)
            if not trimmed:
                sublog("send_regions: nothing left after removing video region %s", actual_vr)
                return
            sublog("send_regions: subtracted %s from %s gives us %s", actual_vr, regions, trimmed)
            regions = trimmed

        # merge existing damage delayed region if there is one:
        # (this codepath can fire from a video region refresh callback)
        dr = self._damage_delayed
        if dr:
            regions = dr.regions + regions
            damage_time = min(damage_time, dr.damage_time)
            self._damage_delayed = None
            self.cancel_expire_timer()
        # decide if we want to send the rest now or delay some more,
        # only delay once the video encoder has dealt with a few frames:
        event_count = max(0, self.statistics.damage_events_count - self.video_subregion.set_at)
        if not actual_vr or event_count < 100:
            delay = 0
        else:
            # non-video is delayed at least 50ms, 4 times the batch delay, but no more than non_max_wait:
            elapsed = int(1000.0*(monotonic()-damage_time))
            delay = max(self.batch_config.delay*4, self.batch_config.expire_delay)
            delay = min(delay, self.video_subregion.non_max_wait-elapsed)
            delay = int(delay)
        sublog("send_regions event_count=%s, actual_vr=%s, delay=%s",
               event_count, actual_vr, delay)
        if delay <= 25:
            send_nonvideo(regions=regions, encoding="", exclude_region=actual_vr)
        else:
            self._damage_delayed = DelayedRegions(damage_time, encoding=coding, options=options, regions=regions)
            sublog("send_regions: delaying non video regions %s some more by %ims", regions, delay)
            self.expire_timer = GLib.timeout_add(delay, self.expire_delayed_region)

    def must_encode_full_frame(self, encoding: str) -> bool:
        non_video = self.non_video_encodings
        r = self.full_frames_only or not non_video or (encoding in self.video_encodings and encoding not in non_video)
        log("must_encode_full_frame(%s)=%s full_frames_only=%s, non_video=%s, video=%s",
            encoding, r, self.full_frames_only, non_video, self.video_encodings)
        return r

    def process_damage_region(self, damage_time, x: int, y: int, w: int, h: int,
                              coding: str, options: dict, flush=0) -> bool:
        """
            Called by 'damage' or 'send_delayed_regions' to process a damage region.

            Actual damage region processing:
            we extract the rgb data from the pixmap and:
            * if doing av-sync, we place the data on the encode queue with a timer,
              when the timer fires, we queue the work for the damage thread
            * without av-sync, we just queue the work immediately
            The damage thread will call make_data_packet_cb which does the actual compression.
            This runs in the UI thread.
        """
        log("process_damage_region%s", (damage_time, x, y, w, h, coding, options, flush))
        if not coding:
            raise RuntimeError("no encoding specified")
        rgb_request_time = monotonic()
        image = self.get_damage_image(x, y, w, h)
        if image is None:
            return False
        log("get_damage_image%s took %ims", (x, y, w, h), 1000*(monotonic()-rgb_request_time))
        sequence = self._sequence

        w = image.get_width()
        h = image.get_height()
        eoptions = typedict(options)
        if self.send_window_size:
            eoptions["window-size"] = self.window_dimensions
        resize = self.scaled_size(image)
        if resize:
            sw, sh = resize
            eoptions["scaled-width"] = sw
            eoptions["scaled-height"] = sh

        # freeze if:
        # * we want av-sync
        # * the video encoder needs a thread safe image
        #   (the xshm backing may change from underneath us if we don't freeze it)
        av_delay = eoptions.intget("av-delay", 0)
        cve = self.common_video_encodings
        video_mode = coding in cve or (coding in ("auto", "stream") and cve)
        must_freeze = ALWAYS_FREEZE or av_delay > 0 or (video_mode and not image.is_thread_safe())
        log("process_damage_region: av_delay=%s, must_freeze=%s, size=%s, encoding=%s",
            av_delay, must_freeze, (w, h), coding)
        if must_freeze:
            image.freeze()

        def call_encode(ew: int, eh: int, eimage: ImageWrapper, encoding: str, flush: int) -> None:
            if self.is_cancelled(sequence):
                free_image_wrapper(image)
                log("call_encode: sequence %s is cancelled", sequence)
                return
            now = monotonic()
            log("process_damage_region: wid=%#x, sequence=%i, adding pixel data to encode queue (%4ix%-4i - %5s), elapsed time: %3.1f ms, request time: %3.1f ms, frame delay=%3ims",   # noqa: E501
                self.wid, sequence, ew, eh, encoding, 1000*(now-damage_time), 1000*(now-rgb_request_time), av_delay)
            item = (ew, eh, damage_time, now, eimage, encoding, sequence, eoptions, flush)
            if av_delay <= 0:
                self.call_in_encode_thread(True, self.make_data_packet_cb, *item)
            else:
                self.encode_queue.append(item)
                self.schedule_encode_from_queue(av_delay)
        # now figure out if we need to send edges separately:
        ee = self.edge_encoding
        ow = w
        oh = h
        w = w & self.width_mask
        h = h & self.height_mask
        regions = []
        if video_mode and ee:
            dw = ow - w
            dh = oh - h
            if dw > 0 and h > 0:
                sub = image.get_sub_image(w, 0, dw, oh)
                regions.append((dw, h, sub, ee))
            if dh > 0 and w > 0:
                sub = image.get_sub_image(0, h, ow, dh)
                regions.append((dw, h, sub, ee))
        # the main area:
        if w > 0 and h > 0:
            regions.append((w, h, image, coding))
        # process all regions:
        if regions:
            # ensure that the flush value ends at 0 on the last region:
            flush = max(len(regions)-1, flush or 0)
            for i, region in enumerate(regions):
                w, h, image, coding = region
                call_encode(w, h, image, coding, flush-i)
        return True

    def get_frame_encode_delay(self, options: dict) -> int:
        if not self.av_sync:
            return 0
        if FORCE_AV_DELAY >= 0:
            return FORCE_AV_DELAY
        content_type = options.get("content-type", self.content_type)
        if AV_SYNC_DEFAULT:
            # default to on, unless we're quite sure it should not be used:
            if any(content_type.find(x) >= 0 for x in ("text", "picture")):
                return 0
        else:
            # default to off unless content-type says otherwise:
            if content_type.find("audio") < 0:
                return 0
        l = len(self.encode_queue)
        if l >= self.encode_queue_max_size:
            # we must free some space!
            return 0
        return self.av_sync_delay

    def cancel_encode_from_queue(self) -> None:
        # free all items in the encode queue:
        self.encode_from_queue_due = 0
        eqt: int = self.encode_from_queue_timer
        avsynclog("cancel_encode_from_queue() timer=%s for wid=%#x", eqt, self.wid)
        if eqt:
            self.encode_from_queue_timer = 0
            GLib.source_remove(eqt)

    def free_encode_queue_images(self) -> None:
        eq = self.encode_queue
        avsynclog("free_encode_queue_images() freeing %i images for wid=%#x", len(eq), self.wid)
        if not eq:
            return
        self.encode_queue = []
        for item in eq:
            image = item[4]
            with log.trap_error(f"Error: cannot free image wrapper {image}"):
                free_image_wrapper(image)

    def schedule_encode_from_queue(self, av_delay: int) -> None:
        # must be called from the UI thread for synchronization
        # we ensure that the timer will fire no later than av_delay
        # re-scheduling it if it was due later than that
        due = monotonic()+av_delay/1000.0
        if self.encode_from_queue_due == 0 or due < self.encode_from_queue_due:
            self.cancel_encode_from_queue()
            self.encode_from_queue_due = due
            self.encode_from_queue_timer = GLib.timeout_add(av_delay, self.timer_encode_from_queue)

    def timer_encode_from_queue(self) -> None:
        self.encode_from_queue_timer = 0
        self.encode_from_queue_due = 0
        self.call_in_encode_thread(True, self.encode_from_queue)

    def encode_from_queue(self) -> None:
        # note: we use a queue here to ensure we preserve the order
        # (so we encode frames in the same order they were grabbed)
        eq = self.encode_queue
        avsynclog("encode_from_queue: %s items for wid=%#x", len(eq), self.wid)
        if not eq:
            return      # nothing to encode, must have been picked off already
        self.update_av_sync_delay()
        # find the first item which is due
        # in seconds, same as monotonic():
        if len(self.encode_queue) >= self.encode_queue_max_size:
            av_delay = 0        # we must free some space!
        elif FORCE_AV_DELAY > 0:
            av_delay = FORCE_AV_DELAY/1000.0
        else:
            av_delay = self.av_sync_delay/1000.0
        now = monotonic()
        still_due = []
        remove = []
        index = 0
        item = None
        sequence = None
        done_packet = False     # only one packet per iteration
        try:
            for index, item in enumerate(eq):
                # item = (w, h, damage_time, now, image, coding, sequence, options, flush)
                sequence = item[6]
                if self.is_cancelled(sequence):
                    free_image_wrapper(item[4])
                    remove.append(index)
                    continue
                ts = item[3]
                due = ts + av_delay
                if due <= now and not done_packet:
                    # found an item which is due
                    remove.append(index)
                    avsynclog("encode_from_queue: processing item %s/%s (overdue by %ims)",
                              index+1, len(self.encode_queue), int(1000*(now-due)))
                    self.make_data_packet_cb(*item)
                    done_packet = True
                else:
                    # we only process one item per call (see "done_packet")
                    # and just keep track of extra ones:
                    still_due.append(int(1000*(due-now)))
        except RuntimeError:
            if not self.is_cancelled(sequence):
                avsynclog.error("error processing encode queue at index %i", index)
                avsynclog.error("item=%s", item, exc_info=True)
        # remove the items we've dealt with:
        # (in reverse order since we pop them from the queue)
        if remove:
            for x in reversed(remove):
                eq.pop(x)
        # if there are still some items left in the queue, re-schedule:
        if not still_due:
            avsynclog("encode_from_queue: nothing due")
            return
        first_due = max(ENCODE_QUEUE_MIN_GAP, min(still_due))
        avsynclog("encode_from_queue: first due in %ims, due list=%s (av-sync delay=%i, actual=%i, for wid=%#x)",
                  first_due, still_due, self.av_sync_delay, av_delay, self.wid)
        GLib.idle_add(self.schedule_encode_from_queue, first_due)

    def update_encoding_video_subregion(self) -> None:
        """
        We may need to update the video subregion based on the change in encoding,
        this may result in rectangle(s) being added or removed from the refresh list
        as video region is managed separately.
        """
        vs = self.video_subregion
        if not vs:
            return
        if self.encoding == "stream":
            vs.reset()
            return
        if any((
            self.encoding not in ("auto", "grayscale") and self.encoding not in self.common_video_encodings,
            self.full_frames_only,
            STRICT_MODE,
            not self.non_video_encodings,
            not self.common_video_encodings,
            self.content_type.find("text") >= 0 and not TEXT_USE_VIDEO,
            self._mmap,
        )):
            # cannot use video subregions
            # FIXME: small race if a refresh timer is due when we change encoding - meh
            vs.reset()
            return
        old = vs.rectangle
        ww, wh = self.window_dimensions
        vs.identify_video_subregion(
            ww, wh,
            self.statistics.damage_events_count,
            self.statistics.last_damage_events,
            self.statistics.last_resized,
            self.children)
        newrect = vs.rectangle
        if ((newrect is None) ^ (old is None)) or newrect != old:
            if old is None and newrect and newrect.get_geometry() == (0, 0, ww, wh):
                # not actually changed!
                # the region is the whole window
                pass
            elif newrect is None and old and old.get_geometry() == (0, 0, ww, wh):
                # not actually changed!
                # the region is the whole window
                pass
            else:
                videolog("video subregion was %s, now %s (window size: %i,%i)", old, newrect, ww, wh)
                self.cleanup_codecs()
        if newrect:
            # remove this from regular refresh:
            if old is None or old != newrect:
                refreshlog("identified new video region: %s", newrect)
                # figure out if the new region had pending regular refreshes:
                subregion_needs_refresh = any(newrect.intersects_rect(x) for x in self.refresh_regions)
                if old:
                    # we don't bother subtracting new and old (too complicated)
                    refreshlog("scheduling refresh of old region: %s", old)
                    # this may also schedule a refresh:
                    super().add_refresh_region(old)
                super().remove_refresh_region(newrect)
                if not self.refresh_regions:
                    self.cancel_refresh_timer()
                if subregion_needs_refresh:
                    vs.add_video_refresh(newrect)
            else:
                refreshlog("video region unchanged: %s - no change in refresh", newrect)
        elif old:
            # add old region to regular refresh:
            refreshlog("video region cleared, scheduling refresh of old region: %s", old)
            self.add_refresh_region(old)
            vs.cancel_refresh_timer()

    def update_encoding_options(self, force_reload=False) -> None:
        """
            This is called when we want to force a full re-init (force_reload=True)
            or from the timer that allows to tune the quality and speed.
            (this tuning is done in `WindowSource.reconfigure`)
            Here we re-evaluate if the csc and video pipeline we are currently using
            is really the best one, and if not we invalidate it.
            This uses get_video_pipeline_options() to get a list of pipeline
            options with a score for each.

            Can be called from any thread.
        """
        super().update_encoding_options(force_reload)
        self.update_encoding_video_subregion()
        if force_reload:
            self.cleanup_codecs()
        self.update_pipeline_scores(force_reload)
        if not self.verify_csc_and_encoder() and not force_reload:
            self.cleanup_codecs()
        self._last_pipeline_check = monotonic()

    def update_pipeline_scores(self, force_reload=False) -> None:
        """
            Calculate pipeline scores using get_video_pipeline_options(),
            and schedule the cleanup of the current video pipeline elements
            which are no longer the best options.

            Can be called from any thread.
        """
        # start with simple sanity checks:
        if self._mmap:
            scorelog("cannot score: mmap enabled")
            return
        if self.is_cancelled():
            scorelog("cannot score: cancelled state")
            return
        if self.content_type.find("text") >= 0 and self.non_video_encodings and not TEXT_USE_VIDEO:
            scorelog("no pipelines for content-type %r", self.content_type)
            return
        if not self.pixel_format:
            scorelog("cannot score: no pixel format!")
            # we need to know what pixel format we create pipelines for!
            return

        def checknovideo(*info) -> None:
            # for whatever reason, we shouldn't be using a video encoding,
            # get_best_encoding() should ensure we don't end up with one
            # it duplicates some of these same checks
            scorelog(*info)
            self.cleanup_codecs()
        # which video encodings to evaluate:
        if self.encoding in ("auto", "stream", "grayscale"):
            if not self.common_video_encodings:
                checknovideo("no common video encodings")
                return
            eval_encodings = self.common_video_encodings
        else:
            if self.encoding not in self.common_video_encodings:
                checknovideo("non-video / unsupported encoding: %r", self.encoding)
                return
            eval_encodings = (self.encoding, )
        ww, wh = self.window_dimensions
        w = ww & self.width_mask
        h = wh & self.height_mask
        vs = self.video_subregion
        if vs:
            r = vs.rectangle
            if r:
                w = r.width & self.width_mask
                h = r.height & self.width_mask
        if w < self.min_w or w > self.max_w or h < self.min_h or h > self.max_h:
            checknovideo("out of bounds: %sx%s (min %sx%s, max %sx%s)",
                         w, h, self.min_w, self.min_h, self.max_w, self.max_h)
            return
        # more sanity checks to see if there is any point in finding a suitable video encoding pipeline:
        if self._sequence < 2:
            # too early, or too late!
            checknovideo(f"not scoring: sequence={self._sequence}")
            return

        # must copy reference to those objects because of threading races:
        ve = self._video_encoder
        csce = self._csc_encoder
        if ve is not None and ve.is_closed():
            scorelog(f"cannot score: video encoder {ve} is closed or closing")
            return
        if csce is not None and csce.is_closed():
            scorelog(f"cannot score: csc {csce} is closed or closing")
            return

        elapsed = monotonic()-self._last_pipeline_check
        max_elapsed = 0.75
        if self.is_idle:
            max_elapsed = 60
        params = (eval_encodings, w, h, self.pixel_format)
        if not force_reload and elapsed < max_elapsed and self.last_pipeline_params == params:
            # keep existing scores
            scorelog(" cannot score: only %ims since last check (idle=%s)", 1000*elapsed, self.is_idle)
            return

        scores = self.get_video_pipeline_options(*params)
        scorelog(f"update_pipeline_scores({force_reload})={scores}")

    def verify_csc_and_encoder(self) -> bool:
        """
        returns True only if the current video encoder and optional csc encoder
        match the best pipeline option.
        """
        scores = self.last_pipeline_scores
        scorelog("verify_csc_and_encoder() scores=%s", scores)
        if not scores:
            return False
        _, _, _, csc_width, csc_height, csc_spec, enc_in_format, _, enc_width, enc_height, encoder_spec = scores[0]
        csce = self._csc_encoder
        if csce:
            if csc_spec is None:
                scorelog(f" csc {csce} is no longer needed")
                return False
            if csce.is_closed():
                scorelog(f" csc {csce} is closed")
                return False
            if csce.get_dst_format() != enc_in_format:
                scorelog(f" change of csc output format from {csce.get_dst_format()} to {enc_in_format}")
                return False
            if csce.get_src_width() != csc_width or csce.get_src_height() != csc_height:
                scorelog(" change of csc input dimensions from %ix%i to %ix%i",
                         csce.get_src_width(), csce.get_src_height(), csc_width, csc_height)
                return False
            if csce.get_dst_width() != enc_width or csce.get_dst_height() != enc_height:
                scorelog(" change of csc output dimensions from %ix%i to %ix%i",
                         csce.get_dst_width(), csce.get_dst_height(), enc_width, enc_height)
                return False
        ve = self._video_encoder
        if ve:
            if ve.is_closed():
                scorelog(f" {ve} is closed")
                return False
            if ve.get_src_format() != enc_in_format:
                scorelog(" change of video input format from %s to %s",
                         ve.get_src_format(), enc_in_format)
                return False
            if ve.get_width() != enc_width or ve.get_height() != enc_height:
                scorelog(" change of video input dimensions from %ix%i to %ix%i",
                         ve.get_width(), ve.get_height(), enc_width, enc_height)
                return False
            if ve.get_type() != encoder_spec.codec_type:
                scorelog(f" found a better video encoder type than {ve.get_type()}: {encoder_spec.codec_type}")
                return False
        # everything is still valid:
        return True

    def get_video_pipeline_options(self, encodings: Iterable[str], width: int, height: int, src_format: str) -> tuple:
        """
            Given a picture format (width, height and src pixel format),
            we find all the pipeline options that will allow us to compress
            it using the given encodings.
            First, we try with direct encoders (for those that support the
            source pixel format natively), then we try all the combinations
            using csc encoders to convert to an intermediary format.
            Each solution is rated, and we return all of them in descending
            score (the best solution comes first).
            Because this function is expensive to call, we cache the results.
            This allows it to run more often from the timer thread.

            Can be called from any thread.
        """
        vh = self.video_helper
        if vh is None:
            return ()       # closing down

        target_q = int(self._current_quality)
        min_q = self._fixed_min_quality
        target_s = int(self._current_speed)
        min_s = self._fixed_min_speed
        text_hint = self.content_type.find("text") >= 0
        if text_hint:
            vmw = vmh = 16384
        else:
            vmw, vmh = self.video_max_size
        # tune quality target for (non-)video region:
        vr = self.matches_video_subregion(width, height)
        if vr and target_q < 100 and not text_hint:
            if self.subregion_is_video():
                # lower quality a bit more:
                fps = self.video_subregion.fps
                f = min(90, 2*fps)
                target_q = max(min_q, int(target_q*(100-f)//100))
                scorelog("lowering quality target %i by %i%% for video %s (fps=%i)", target_q, f, vr, fps)
            else:
                # not the video region, or not really video content, raise quality a bit:
                target_q = int(sqrt(target_q/100.0)*100)
                scorelog("raising quality for video encoding of non-video region")
        scorelog("get_video_pipeline_options%s speed: %s (min %s), quality: %s (min %s)",
                 (encodings, width, height, src_format), target_s, min_s, target_q, min_q)

        ffps = self.get_video_fps(width, height)
        cached_w = cached_h = 4096
        cached_scaling = [cached_w, cached_h, self.calculate_scaling(width, height, cached_w, cached_h)]
        scores = []
        all_no_match = {}
        csc_specs = vh.get_csc_specs(src_format)
        scorelog(f"csc for {src_format} source format: {csc_specs}")
        if FORCE_CSC:
            csc_specs = {FORCE_CSC_MODE : csc_specs.get(FORCE_CSC_MODE, ())}
            scorelog(f"{FORCE_CSC_MODE=} : {csc_specs=}")
        for encoding in encodings:
            # these are the CSC modes the client can handle for this encoding:
            # we must check that the output csc mode for each encoder is one of those
            supported_csc_modes = self.full_csc_modes.strtupleget(encoding)
            if not supported_csc_modes:
                scorelog(" no supported csc modes for %s", encoding)
                continue
            encoder_specs = vh.get_encoder_specs(encoding)
            if not encoder_specs:
                scorelog(" no encoder specs for %s", encoding)
                continue
            scorelog(f"encoders({encoding})={encoder_specs}, {supported_csc_modes=}")
            # if not specified as an encoding option,
            # discount encodings further down the list of preferred encodings:
            # (ie: prefer h264 to vp9)
            try:
                encoding_score_delta = len(PREFERRED_ENCODING_ORDER)//2-list(PREFERRED_ENCODING_ORDER).index(encoding)
            except ValueError:
                encoding_score_delta = 0
            encoding_score_delta = self.encoding_options.get(f"{encoding}.score-delta", encoding_score_delta)
            no_match = []

            def add_scores(info, csc_spec: CSCSpec | None, enc_in_format) -> None:
                # find encoders that take 'enc_in_format' as input:
                colorspace_specs = encoder_specs.get(enc_in_format)
                if not colorspace_specs:
                    scorelog(f"no encoders for {enc_in_format}")
                    no_match.append(info)
                    return
                # log("%s encoding from %s: %s", info, pixel_format, colorspace_specs)
                for encoder_spec in colorspace_specs:
                    # ensure that the output of the encoder can be processed by the client:
                    matches = tuple(x for x in encoder_spec.output_colorspaces if x in supported_csc_modes)
                    if not matches or self.is_cancelled():
                        scorelog(f"output colorspaces {encoder_spec.output_colorspaces} not supported")
                        no_match.append(encoder_spec.codec_type+" "+info)
                        continue
                    max_w = min(encoder_spec.max_w, vmw)
                    max_h = min(encoder_spec.max_h, vmh)
                    if (csc_spec and csc_spec.can_scale) or encoder_spec.can_scale:
                        if cached_scaling[0] >= width and cached_scaling[1] >= height:
                            scaling = cached_scaling[2]
                        else:
                            scaling = self.calculate_scaling(width, height, max_w, max_h)
                    else:
                        scaling = (1, 1)
                    score_delta = encoding_score_delta
                    lossy_csc = enc_in_format in ("NV12", "YUV420P", "YUV422P")
                    if scaling != (1, 1) or lossy_csc:
                        if text_hint:
                            # we should not be using scaling or csc with text!
                            score_delta -= 500
                        elif target_q >= 100:
                            # we want lossless, this would be far from it!
                            score_delta -= 250
                    if self.is_shadow and lossy_csc and scaling == (1, 1):
                        # avoid subsampling with shadow servers:
                        score_delta -= 40
                    vs = self.video_subregion
                    detection = bool(vs) and vs.detection
                    score_data = get_pipeline_score(enc_in_format, csc_spec, encoder_spec, width, height, scaling,
                                                    target_q, min_q, target_s, min_s,
                                                    self._csc_encoder, self._video_encoder,
                                                    score_delta, ffps, detection)
                    if score_data:
                        scores.append(score_data)
                    else:
                        scorelog(" no score data for %s",
                                 (enc_in_format, csc_spec, encoder_spec, width, height, scaling, ".."))
            if not FORCE_CSC or src_format == FORCE_CSC_MODE:
                add_scores(f"direct (no csc) {src_format}", None, src_format)

            # now add those that require a csc step:
            # log("%s can also be converted to %s using %s",
            #    pixel_format, [x[0] for x in csc_specs], set(x[1] for x in csc_specs))
            # we have csc module(s) that can get us from pixel_format to out_csc:
            for out_csc, l in csc_specs.items():
                for csc_spec in l:
                    add_scores(f"via {out_csc}", csc_spec, out_csc)
            all_no_match[encoding] = no_match
        if all_no_match:
            scorelog("no matching colorspace specs for %s", all_no_match)
        s = tuple(sorted(scores, key=lambda x: -x[0]))
        scorelog("get_video_pipeline_options%s scores=%s", (encodings, width, height, src_format), s)
        if self.is_cancelled():
            self.last_pipeline_params = ()
            self.last_pipeline_scores = ()
        else:
            self.last_pipeline_params = (encodings, width, height, src_format)
            self.last_pipeline_scores = s
        self.last_pipeline_time = monotonic()
        return s

    def get_video_fps(self, width: int, height: int) -> int:
        mvsub = self.matches_video_subregion(width, height)
        vs = self.video_subregion
        if vs and mvsub:
            # matches the video subregion,
            # for which we have the fps already:
            return self.video_subregion.fps
        return self.do_get_video_fps(width, height)

    def do_get_video_fps(self, width: int, height: int) -> int:
        now = monotonic()
        # calculate full frames per second (measured in pixels vs window size):
        stime = now-5           # only look at the last 5 seconds max
        lde = tuple((t, w, h) for t, _, _, w, h in tuple(self.statistics.last_damage_events) if t > stime)
        if len(lde) >= 10:
            # the first event's first element is the oldest event time:
            otime = lde[0][0]
            if now > otime:
                pixels = sum(w*h for _, w, h in lde)
                return int(pixels/(width*height)/(now - otime))
        return 0

    def calculate_scaling(self, width: int, height: int, max_w: int = 4096, max_h: int = 4096) -> tuple[int, int]:
        if width == 0 or height == 0:
            return 1, 1
        now = monotonic()
        crs = None
        if DOWNSCALE:
            crs = self.client_render_size

        def get_min_required_scaling(default_value=(1, 1)) -> tuple[int, int]:
            mw = max_w
            mh = max_h
            if crs:
                # if the client is going to downscale things anyway,
                # then there is no need to send at a higher resolution than that:
                crsw, crsh = crs
                if crsw < max_w:
                    mw = crsw
                if crsh < max_h:
                    mh = crsh
            if width <= mw and height <= mh:
                return default_value    # no problem
            # most encoders can't deal with that!
            # sort them from the smallest scaling value to the highest:
            sopts = {}
            for num, den in SCALING_OPTIONS:
                sopts[num/den] = num, den
            for ratio in reversed(sorted(sopts.keys())):
                num, den = sopts[ratio]
                if num == 1 and den == 1:
                    continue
                if width*num/den <= mw and height*num/den <= mh:
                    return num, den
            raise ValueError(f"BUG: failed to find a scaling value for window size {width}x{height}")

        def mrs(v=(1, 1), info="using minimum required scaling") -> tuple[int, int]:
            sv = get_min_required_scaling(v)
            if info:
                scalinglog("%s: %s", info, sv)
            return sv
        if not SCALING:
            if (width > max_w or height > max_h) and first_time("scaling-required"):
                if not SCALING:
                    scalinglog.warn("Warning: video scaling is disabled")
                else:
                    scalinglog.warn("Warning: video scaling is not supported by the client")
                scalinglog.warn(f" but the video size is too large: {width}x{height}")
                scalinglog.warn(f" the maximum supported is {max_w}x{max_h}")
            return 1, 1
        if SCALING_HARDCODED:
            return mrs(tuple(SCALING_HARDCODED), "using hardcoded scaling value")
        if self.scaling_control == 0:
            # video-scaling is disabled, only use scaling if we really have to:
            return mrs(info="scaling is disabled, using minimum")
        if self.scaling:
            # honour value requested for this window, unless we must scale more:
            return mrs(self.scaling, info="using scaling specified")
        if now-self.statistics.last_resized < 0.5:
            return mrs(self.actual_scaling, "unchanged scaling during resizing")
        if now-self.last_scroll_time < 5:
            return mrs(self.actual_scaling, "unchanged scaling during scrolling")
        if self.statistics.damage_events_count <= 50:
            # not enough data yet:
            return mrs(info="waiting for more events, using minimum")
        if self.content_type.find("text") >= 0 and TEXT_QUALITY > 90:
            return mrs(info="not downscaling text")

        # use heuristics to choose the best scaling ratio:
        mvsub = self.matches_video_subregion(width, height)
        video = self.content_type.find("video") >= 0 or (bool(mvsub) and self.subregion_is_video())
        ffps = self.get_video_fps(width, height)
        q = self._current_quality
        s = self._current_speed
        if self.scaling_control is None:
            # None == auto mode, derive from quality and speed only:
            # increase threshold when handling video
            q_noscaling = 65 + int(video)*30
            if q >= q_noscaling or ffps == 0:
                scaling = get_min_required_scaling()
            else:
                pps = ffps*width*height                 # Pixels/s
                if self.bandwidth_limit > 0:
                    # assume video compresses pixel data by ~95% (size is 20 times smaller)
                    # (and convert to bytes per second)
                    # ie: 240p minimum target
                    target = max(SCALING_MIN_PPS, self.bandwidth_limit//8*20)
                else:
                    target = SCALING_PPS_TARGET             # ie: 1080p
                if self.is_shadow:
                    # shadow servers look ugly when scaled:
                    target *= 16
                elif self.content_type.find("text") >= 0:
                    # try to avoid scaling:
                    target *= 4
                elif not video:
                    # downscale non-video content less:
                    target *= 2
                if self.image_depth == 30:
                    # high bit depth is normally used for high quality
                    target *= 10
                # high quality means less scaling:
                target = target * (100+max(0, q-video*30))**2 // 200**2
                # high speed means more scaling:
                target = target * 60**2 // (s+20)**2
                sscaling = {}
                mrs_num, mrs_den = get_min_required_scaling()
                min_ratio = mrs_num/mrs_den
                denom_mult = 1
                if crs:
                    # if the client will be downscaling to paint the window
                    # use this downscaling as minimum value:
                    crsw, crsh = crs
                    if crsw > 0 and crsh > 0 and width-crsw > DOWNSCALE_THRESHOLD and height-crsh > DOWNSCALE_THRESHOLD:
                        if width/crsw > height/crsh:
                            denom_mult = width/crsw
                        else:
                            denom_mult = height/crsh
                for num, denom in SCALING_OPTIONS:
                    # noinspection PyChainedComparisons
                    if denom_mult > 1.0 and 0.5 < (num/denom) < 1.0:
                        # skip ratios like 2/3
                        # since we want a whole multiple of the client scaling value
                        continue
                    # scaled pixels per second value:
                    denom *= denom_mult
                    spps = pps*(num**2)/(denom**2)
                    ratio = target/spps
                    # ideal ratio is 1, measure distance from 1:
                    score = round(abs(1-ratio)*100)
                    if self.actual_scaling == (num, denom):
                        # try to stick to the same settings longer:
                        # give it a score boost (lowest score wins):
                        elapsed = min(16.0, max(0.0, now - self.last_pipeline_time))
                        # gain will range from 4 (after 0 seconds) to 1 (after 9 seconds)
                        gain = sqrt(17 - elapsed)
                        score = round(score / gain)
                    if num/denom > min_ratio:
                        # higher than minimum, should not be used unless we have no choice:
                        score = round(score*100)
                    sscaling[score] = (num, denom)
                scalinglog("scaling scores%s wid=%#x, current=%s, pps=%s, target=%s, fps=%s, denom_mult=%s, scores=%s",
                           (width, height, max_w, max_h),
                           self.wid, self.actual_scaling, pps, target, ffps, denom_mult, sscaling)
                if sscaling:
                    highscore = sorted(sscaling.keys())[0]
                    scaling = sscaling[highscore]
                else:
                    scaling = get_min_required_scaling()
        else:
            # calculate scaling based on the "video-scaling" command line option,
            # which is named "scaling_control" here.
            # (from 1 to 100, from least to most aggressive)
            if mvsub:
                if video:
                    # enable scaling more aggressively
                    sc = (self.scaling_control+50)*2
                else:
                    sc = (self.scaling_control+25)
            else:
                # not the video region, so much less aggressive scaling:
                sc = max(0, (self.scaling_control-50)//2)

            # if scaling_control is high (scaling_control=100 -> er=2)
            # then we will match the heuristics more quickly:
            er = sc/50.0
            if self.actual_scaling != (1, 1):
                # if we are already downscaling, boost the score so we will stick with it a bit longer:
                # more so if we are downscaling a lot (1/3 -> er=1.5 + ..)
                er += (0.5 * self.actual_scaling[1] / self.actual_scaling[0])
            qs = s > (q-er*10) and q < (50+er*15)
            # scalinglog("calculate_scaling: er=%.1f, qs=%s, ffps=%s", er, qs, ffps)
            if self.fullscreen and (qs or ffps >= max(2, round(10-er*3))):
                scaling = 1, 3
            elif self.maximized and (qs or ffps >= max(2, round(10-er*3))):
                scaling = 1, 2
            elif width*height >= (2560-er*768)*1600 and (qs or ffps >= max(4, round(25-er*5))):
                scaling = 1, 3
            elif width*height >= (1920-er*384)*1200 and (qs or ffps >= max(5, round(30-er*10))):
                scaling = 2, 3
            elif width*height >= (1200-er*256)*1024 and (qs or ffps >= max(10, round(50-er*15))):
                scaling = 2, 3
            else:
                scaling = 1, 1
            if scaling:
                scalinglog("calculate_scaling value %s enabled by heuristics for %ix%i q=%i, s=%i, er=%.1f, qs=%s, ffps=%i, scaling-control(%i)=%i",   # noqa: E501
                           scaling, width, height, q, s, er, qs, ffps, self.scaling_control, sc)
        # sanity checks:
        if scaling is None:
            scaling = 1, 1
        v, u = scaling
        if v/u > 1.0:
            # never upscale before encoding!
            scaling = 1, 1
        elif v/u < 0.1:
            # don't downscale more than 10 times! (for each dimension - that's 100 times!)
            scaling = 1, 10
        scalinglog("calculate_scaling%s=%s (q=%s, s=%s, scaling_control=%s)",
                   (width, height, max_w, max_h), scaling, q, s, self.scaling_control)
        return scaling

    def check_pipeline(self, encodings: Sequence[str], width: int, height: int, src_format: str) -> bool:
        """
            Checks that the current pipeline is still valid
            for the given input. If not, close it and make a new one.

            Runs in the 'encode' thread.
        """
        if self.do_check_pipeline(encodings, width, height, src_format):
            return True  # OK!

        videolog("check_pipeline%s setting up a new pipeline as check failed - encodings=%s",
                 (encodings, width, height, src_format), encodings)
        # cleanup existing one if needed:
        self.csc_clean(self._csc_encoder)
        self.ve_clean(self._video_encoder)
        # and make a new one:
        w = width & self.width_mask
        h = height & self.height_mask
        scores = self.get_video_pipeline_options(encodings, w, h, src_format)
        if not scores:
            if not self.is_cancelled() and first_time(f"no-scores-{src_format}-{self.wid:#x}"):
                self.pipeline_setup_error(encodings, width, height, src_format,"no video pipeline options found")
            return False

        if self._current_quality == 100:
            # discard options with negative scores (usually subsampled or downscaled)
            positive_scores = tuple(filter(lambda option: option[0] >= 0, scores))
            if not positive_scores:
                videolog(f"no pipeline scores above 0 for quality={self._current_quality}, cannot use video")
                return False
            scores = positive_scores

        if self.setup_pipeline(scores, width, height, src_format):
            return True

        if not self.is_cancelled() and first_time(f"novideo-{src_format}-{self.wid:#x}"):
            self.pipeline_setup_error(encodings, width, height, src_format,"failed to setup a video pipeline", scores)
        return False

    def pipeline_setup_error(self, encodings: Sequence[str], width: int, height: int, src_format: str,
                             message: str, scores=()) -> None:
        vh = self.video_helper
        if self.is_cancelled() or not vh:
            return
        # just for diagnostics:
        supported_csc_modes = dict((encoding, self.full_csc_modes.strtupleget(encoding)) for encoding in encodings)
        all_encs: set[str] = set()
        for enc in encodings:
            encoder_specs = vh.get_encoder_specs(enc)
            for sublist in encoder_specs.values():
                all_encs.update(es.codec_type for es in sublist)
            for csc in supported_csc_modes:
                if csc not in encoder_specs:
                    continue
        videolog.error(f"Error: {message}")
        videolog.error(f" {csv(encodings)} encoding with source format {src_format!r}")
        videolog.error(f" {width}x{height} {self.image_depth}-bit")
        videolog.error(" all encoders: %s", csv(all_encs))
        for enc, modes in supported_csc_modes.items():
            videolog.error(f" client supported CSC modes for {enc!r}: %s", csv(modes))
        if FORCE_CSC:
            videolog.error(f" forced csc mode: {FORCE_CSC_MODE}")
        if scores:
            videolog.error(" tried the following options:")
            for option in scores:
                videolog.error(f" {option}")

    def do_check_pipeline(self, encodings: Sequence[str], width: int, height: int, src_format: str) -> bool:
        """
            Checks that the current pipeline is still valid
            for the given input.

            Runs in the 'encode' thread.
        """
        # use aliases, not because of threading (we are in the encode thread anyway)
        # but to make the code less dense:
        ve = self._video_encoder
        csce = self._csc_encoder
        if ve is None:
            videolog("do_check_pipeline: no current video encoder")
            return False
        if ve.is_closed():
            videolog("do_check_pipeline: current video encoder %s is closed", ve)
            return False
        if csce and csce.is_closed():
            videolog("do_check_pipeline: csc %s is closed", csce)
            return False

        if csce:
            csc_width = width & self.width_mask
            csc_height = height & self.height_mask
            if csce.get_src_format() != src_format:
                csclog("do_check_pipeline csc: switching source format from %s to %s",
                       csce.get_src_format(), src_format)
                return False
            if csce.get_src_width() != csc_width or csce.get_src_height() != csc_height:
                csclog("do_check_pipeline csc: window dimensions have changed from %sx%s to %sx%s, csc info=%s",
                       csce.get_src_width(), csce.get_src_height(), csc_width, csc_height, csce.get_info())
                return False
            if csce.get_dst_format() != ve.get_src_format():
                csclog.error("Error: CSC intermediate format mismatch,")
                csclog.error(" %s outputs %s but %s expects %sw",
                             csce.get_type(), csce.get_dst_format(), ve.get_type(), ve.get_src_format())
                csclog.error(" %s:", csce)
                print_nested_dict(csce.get_info(), "  ", print_fn=csclog.error)
                csclog.error(" %s:", ve)
                print_nested_dict(ve.get_info(), "  ", print_fn=csclog.error)
                return False

            # encoder will take its input from csc:
            encoder_src_width = csce.get_dst_width()
            encoder_src_height = csce.get_dst_height()
        else:
            # direct to video encoder without csc:
            encoder_src_width = width & self.width_mask
            encoder_src_height = height & self.height_mask

            if ve.get_src_format() != src_format:
                videolog("do_check_pipeline video: invalid source format %s, expected %s",
                         ve.get_src_format(), src_format)
                return False

        if ve.get_encoding() not in encodings:
            videolog("do_check_pipeline video: invalid encoding %s, expected one of: %s",
                     ve.get_encoding(), csv(encodings))
            return False
        if ve.get_width() != encoder_src_width or ve.get_height() != encoder_src_height:
            videolog("do_check_pipeline video: window dimensions have changed from %sx%s to %sx%s",
                     ve.get_width(), ve.get_height(), encoder_src_width, encoder_src_height)
            return False
        return True

    def setup_pipeline(self, scores: tuple, width: int, height: int, src_format: str) -> bool:
        """
            Given a list of pipeline options ordered by their score
            and an input format (width, height and source pixel format),
            we try to create a working video pipeline (csc + encoder),
            trying each option until one succeeds.
            (some may not be suitable because of scaling?)

            Runs in the 'encode' thread.
        """
        if width <= 0 or height <= 0:
            raise RuntimeError(f"invalid dimensions: {width}x{height}")
        start = monotonic()
        videolog("setup_pipeline%s", (scores, width, height, src_format))
        for option in scores:
            try:
                videolog("setup_pipeline: trying %s", option)
                if self.setup_pipeline_option(width, height, src_format, *option):
                    # success!
                    return True
                # skip cleanup below
                continue
            except TransientCodecException as e:
                if self.is_cancelled():
                    return False
                videolog.warn("Warning: setup_pipeline failed for")
                videolog.warn(" %s:", option)
                videolog.warn(" %s", e)
                del e
            except (RuntimeError, ValueError) as e:
                if self.is_cancelled():
                    videolog(f"ignoring {e} in cancelled state")
                    return False
                videolog.warn("Warning: failed to setup video pipeline %s", option, exc_info=True)
            # we're here because an exception occurred, cleanup before trying again:
            self.csc_clean(self._csc_encoder)
            self.ve_clean(self._video_encoder)
        end = monotonic()
        videolog("setup_pipeline(..) failed! took %.2fms", (end-start) * 1000)
        return False

    def setup_pipeline_option(self, width: int, height: int, src_format: str,
                              _score: int, scaling, _csc_scaling, csc_width: int, csc_height: int, csc_spec,
                              enc_in_format: str, encoder_scaling,
                              enc_width: int, enc_height: int, encoder_spec) -> bool:
        encoding = encoder_spec.encoding
        options = self.assign_sq_options(dict(self.encoding_options))
        min_w = 8
        min_h = 8
        max_w = 16384
        max_h = 16384
        if csc_spec:
            if encoder_scaling != (1, 1):
                # only the csc mask is relevant as input:
                width_mask = csc_spec.width_mask
                height_mask = csc_spec.height_mask
                # the csc output must satisfy the encoder mask:
                enc_width = enc_width & encoder_spec.width_mask
                enc_height = enc_height & encoder_spec.height_mask
            else:
                # we have to ensure that the video size matches both masks:
                width_mask = csc_spec.width_mask & encoder_spec.width_mask
                height_mask = csc_spec.height_mask & encoder_spec.height_mask
            min_w = max(min_w, csc_spec.min_w)
            min_h = max(min_h, csc_spec.min_h)
            max_w = min(max_w, csc_spec.max_w)
            max_h = min(max_h, csc_spec.max_h)
            # csc speed is not very important compared to encoding speed,
            # so make sure it never degrades quality
            speed = options.get("speed", self._current_speed)
            quality = options.get("quality", self._current_quality)
            csc_speed = max(1, min(speed, 100-quality/2.0))
            csc_options = typedict(options)
            csc_options["speed"] = csc_speed
            csc_options["full-range"] = encoder_spec.full_range
            csc_start = monotonic()
            csce = csc_spec.make_instance()
            csce.init_context(csc_width, csc_height, src_format,
                              enc_width, enc_height, enc_in_format, csc_options)
            csc_end = monotonic()
            csclog("setup_pipeline: csc=%s, info=%s, setup took %.2fms",
                   csce, csce.get_info(), (csc_end - csc_start) * 1000)
        else:
            csce = None
            # use the encoder's mask directly since that's all we have to worry about!
            width_mask = encoder_spec.width_mask
            height_mask = encoder_spec.height_mask
            # restrict limits:
            min_w = max(min_w, encoder_spec.min_w)
            min_h = max(min_h, encoder_spec.min_h)
            max_w = min(max_w, encoder_spec.max_w)
            max_h = min(max_h, encoder_spec.max_h)
            if encoder_scaling != (1, 1) and not encoder_spec.can_scale:
                videolog("scaling is now enabled, so skipping %s", encoder_spec)
                return False
        self._csc_encoder = csce
        enc_start = monotonic()
        # FIXME: filter dst_formats to only contain formats the encoder knows about?
        dst_formats = self.full_csc_modes.strtupleget(encoding)
        ve = encoder_spec.make_instance()
        options.update(self.get_video_encoder_options(encoding, width, height))
        if self.encoding == "grayscale":
            options["grayscale"] = True
        if encoder_scaling != (1, 1):
            n, d = encoder_scaling
            options["scaling"] = encoder_scaling
            options["scaled-width"] = enc_width*n//d
            options["scaled-height"] = enc_height*n//d
        options["dst-formats"] = dst_formats
        options["datagram"] = self.datagram

        ve.init_context(encoding, enc_width, enc_height, enc_in_format, typedict(options))
        # record new actual limits:
        self.actual_scaling = scaling
        self.width_mask = width_mask
        self.height_mask = height_mask
        self.min_w = min_w
        self.min_h = min_h
        self.max_w = max_w
        self.max_h = max_h
        enc_end = monotonic()
        self.start_video_frame = 0
        self._video_encoder = ve
        videolog("setup_pipeline: csc=%s, video encoder=%s, info: %s, setup took %.2fms",
                 csce, ve, ve.get_info(), (enc_end - enc_start) * 1000)
        scalinglog("setup_pipeline: scaling=%s, encoder_scaling=%s", scaling, encoder_scaling)
        return True

    def get_video_encoder_options(self, encoding, width, height) -> dict[str, Any]:
        # tweaks for "real" video:
        recentscroll = (monotonic() - self.last_scroll_time) < 5
        opts = {}
        if self.cuda_device_context:
            opts["cuda-device-context"] = self.cuda_device_context
        if not self._fixed_quality and not self._fixed_speed and self._fixed_min_quality < 50:
            # only allow bandwidth to drive video encoders
            # when we don't have strict quality or speed requirements:
            opts["bandwidth-limit"] = self.bandwidth_limit
        if self.content_type:
            content_type = self.content_type
        elif not recentscroll and self.matches_video_subregion(width, height) and self.subregion_is_video():
            content_type = "video"
        else:
            content_type = None
        if content_type:
            opts["content-type"] = content_type
            if content_type == "video":
                if B_FRAMES and (encoding in self.supports_video_b_frames):
                    opts["b-frames"] = True
        return opts

    def make_draw_packet(self, x: int, y: int, w: int, h: int,
                         coding: str, data, outstride: int, client_options: dict, options: typedict) -> Packet:
        # overridden so we can invalidate the scroll data:
        # log.error("make_draw_packet%s", (x, y, w, h, coding, "..", outstride, client_options)
        packet = super().make_draw_packet(x, y, w, h, coding, data, outstride, client_options, options)
        sd = self.scroll_data
        if sd and not options.boolget("scroll"):
            if client_options.get("scaled_size") or client_options.get("quality", 100) < 20:
                # don't scroll very low quality content, better to refresh it
                scrolllog("low quality %s update, invalidating all scroll data (scaled_size=%s, quality=%s)",
                          coding, client_options.get("scaled_size"), client_options.get("quality", 100))
                self.do_free_scroll_data()
            else:
                sd.invalidate(x, y, w, h)
        return packet

    def free_scroll_data(self) -> None:
        self.call_in_encode_thread(False, self.do_free_scroll_data)

    def do_free_scroll_data(self) -> None:
        sd = self.scroll_data
        scrolllog("do_free_scroll_data() scroll_data=%s", sd)
        if sd:
            self.scroll_data = None
            sd.free()

    def may_use_scrolling(self, image: ImageWrapper, options: typedict) -> bool:
        scrolllog("may_use_scrolling(%s, %s) supports_scrolling=%s, has_pixels=%s, content_type=%s, non-video=%s",
                  image, options, self.supports_scrolling, image.has_pixels(),
                  self.content_type, self.non_video_encodings)
        if self._mmap and self.encoding != "scroll":
            scrolllog("no scrolling: using mmap")
            return False
        if not self.supports_scrolling:
            scrolllog("no scrolling: not supported")
            return False
        if options.boolget("auto_refresh"):
            scrolllog("no scrolling: auto-refresh")
            return False
        # don't download the pixels if we have a GPU buffer,
        # since that means we're likely to be able to compress on the GPU too with NVENC:
        if not image.has_pixels():
            return False
        if self.content_type.find("video") >= 0 or not self.non_video_encodings:
            scrolllog("no scrolling: content is video")
            return False
        w = image.get_width()
        h = image.get_height()
        if w < MIN_SCROLL_IMAGE_SIZE or h < MIN_SCROLL_IMAGE_SIZE:
            scrolllog("no scrolling: image size %ix%i is too small, minimum is %ix%i",
                      w, h, MIN_SCROLL_IMAGE_SIZE, MIN_SCROLL_IMAGE_SIZE)
            return False
        scroll_data = self.scroll_data
        if self.b_frame_flush_timer and scroll_data:
            scrolllog("no scrolling: b_frame_flush_timer=%s", self.b_frame_flush_timer)
            self.do_free_scroll_data()
            return False
        speed = options.intget("speed", self._current_speed)
        if speed >= 50 or self.scroll_preference < 100:
            now = monotonic()
            scroll_event_elapsed = now-self.last_scroll_event
            scroll_encode_elapsed = now-self.last_scroll_time
            # how long since we last successfully used scroll encoding,
            # or seen a scroll mouse wheel event:
            scroll_elapsed = min(scroll_event_elapsed, scroll_encode_elapsed)
            max_time = 1+min((100-speed)/10, self.scroll_preference/20)
            if scroll_elapsed >= max_time:
                scrolllog("no scrolling: elapsed=%.1f, max time=%.1f", scroll_elapsed, max_time)
                return False
        return self.do_scroll_encode(image, options, self.scroll_min_percent)

    def scroll_encode(self, coding: str, image: ImageWrapper, options: typedict) -> None:
        assert coding == "scroll"
        self.do_scroll_encode(image, options, 0)
        # do_scroll_encode() sends the packets
        # so there is nothing to return:
        return None

    def do_scroll_encode(self, image: ImageWrapper, options: typedict, min_percent: int = 0) -> bool:
        if options.boolget("scroll"):
            scrolllog("no scrolling: detection has already been used on this image")
            return False
        w = image.get_width()
        h = image.get_height()
        if w >= 32000 or h >= 32000:
            scrolllog("no scrolling: the image is too large, %ix%i", w, h)
            return False
        start = monotonic()
        x = image.get_target_x()
        y = image.get_target_y()
        scroll_data = self.scroll_data
        try:
            if not scroll_data:
                from xpra.server.window.motion import ScrollData
                scroll_data = ScrollData()
                self.scroll_data = scroll_data
                scrolllog("new scroll data: %s", scroll_data)
            if not image.is_thread_safe():
                # what we really want is to check that the frame has been frozen,
                # so it doesn't get modified whilst we checksum or encode it,
                # the "thread_safe" flag gives us that for the X11 case in most cases,
                # (the other servers already copy the pixels from the "real" screen buffer)
                # TODO: use a separate flag? (ximage uses this flag to know if it is safe
                # to call image.free from another thread - which is theoretically more restrictive)
                newstride = roundup(image.get_width() * image.get_bytesperpixel(), 4)
                image.restride(newstride)
            bpp = image.get_bytesperpixel()
            pixels = image.get_pixels()
            if not pixels:
                return False
            stride = image.get_rowstride()
            scroll_data.update(pixels, x, y, w, h, stride, bpp)
            max_distance = min(1000, (100-min_percent)*h//100)
            scroll_data.calculate(max_distance)
            # marker telling us not to invalidate the scroll data from here on:
            options["scroll"] = True
            if min_percent > 0:
                max_zones = 20
                scroll, count = scroll_data.get_best_match()
                end = monotonic()
                match_pct = int(100*count/h)
                scrolllog("best scroll guess took %ims, matches %i%% of %i lines: %s",
                          (end - start) * 1000, match_pct, h, scroll)
            else:
                max_zones = 50
                match_pct = min_percent
            # if enough scrolling is detected, use scroll encoding for this frame:
            if match_pct >= min_percent:
                self.encode_scrolling(scroll_data, image, options, match_pct, max_zones)
                return True
        except (RuntimeError, ValueError):
            scrolllog("do_scroll_encode(%s, %s)", image, options, exc_info=True)
            if not self.is_cancelled():
                scrolllog.error("Error during scrolling detection")
                scrolllog.error(" with image=%s, options=%s", image, options, exc_info=True)
            # make sure we start again from scratch next time:
            self.do_free_scroll_data()
        return False

    def encode_scrolling(self, scroll_data, image: ImageWrapper, options: typedict,
                         match_pct: int, max_zones: int = 20) -> None:
        # generate all the packets for this screen update
        # using 'scroll' encoding and picture encodings for the other regions
        start = monotonic()
        options.pop("av-sync", None)
        # tells make_data_packet not to invalidate the scroll data:
        ww, wh = self.window_dimensions
        scrolllog("encode_scrolling([], %s, %s, %i, %i) window-dimensions=%s",
                  image, options, match_pct, max_zones, (ww, wh))
        x = image.get_target_x()
        y = image.get_target_y()
        w = image.get_width()
        h = image.get_height()
        raw_scroll, non_scroll = {}, {0: h}
        if x+w > ww or y+h > wh:
            # window may have been resized
            pass
        else:
            v = scroll_data.get_scroll_values()
            if v:
                raw_scroll, non_scroll = v
                if len(raw_scroll) >= max_zones or len(non_scroll) >= max_zones:
                    # avoid fragmentation, which is too costly
                    # (too many packets, too many loops through the encoder code)
                    scrolllog("too many items: %i scrolls, %i non-scrolls - sending just one image instead",
                              len(raw_scroll), len(non_scroll))
                    raw_scroll = {}
                    non_scroll = {0: h}
        scrolllog(" will send scroll data=%s, non-scroll=%s", raw_scroll, non_scroll)
        flush = len(non_scroll)
        # convert to a screen rectangle list for the client:
        scrolls: list[tuple[int, int, int, int, int, int]] = []
        for scroll, line_defs in raw_scroll.items():
            if scroll == 0:
                continue
            for line, count in line_defs.items():
                if y+line+scroll < 0:
                    raise RuntimeError(f"cannot scroll rectangle by {scroll} lines from {y}+{line}")
                if y+line+scroll > wh:
                    raise RuntimeError(f"cannot scroll rectangle {count} high "
                                       f"by {scroll} lines from {y}+{line} (window height is {wh})")
                scrolls.append((x, y+line, w, count, 0, scroll))
        del raw_scroll
        damage_time = options.floatget("damage-time")
        process_damage_time = options.floatget("process-damage-time")
        # send the scrolls if we have any
        # (zero change scrolls have been removed - so maybe there are none)
        if scrolls:
            client_options = {
                "flush": flush,
                "scroll": scrolls,
            }
            coding = "scroll"
            end = monotonic()
            bdata = LargeStructure(coding, scrolls) if BACKWARDS_COMPATIBLE else b""
            packet = self.make_draw_packet(x, y, w, h, coding, bdata, 0, client_options, options)
            self.queue_damage_packet(packet, damage_time, process_damage_time)
            compresslog(COMPRESS_SCROLL_FMT,
                        (end-start) * 1000, w, h, x, y, self.wid, coding,
                        len(scrolls), w * h * 4 / 1024,
                        self._damage_packet_sequence, client_options, options)
        del scrolls
        # send the rest as rectangles:
        if non_scroll:
            if self.content_type.find("text") >= 0:
                quality = 100
                options["quality"] = quality
            # boost quality a bit, because lossless saves refreshing,
            # more so if we have a high match percentage (less to send):
            elif self._fixed_quality <= 0:
                quality = options.get("quality", self._current_quality)
                quality = min(100, quality + max(60, match_pct)//2)
                options["quality"] = quality
            nsstart = monotonic()
            sel_options = dict(options)
            for sy, sh in non_scroll.items():
                substart = monotonic()
                sub = image.get_sub_image(0, sy, w, sh)
                encoding = self.get_best_nonvideo_encoding(w, sh, sel_options)
                if not encoding:
                    raise RuntimeError(f"no nonvideo encoding found for {w}x{sh} screen update")
                encode_fn = self._encoders[encoding]
                ret = encode_fn(encoding, sub, options)
                free_image_wrapper(sub)
                if not ret:
                    scrolllog("no result for %s encoding of %s with options %s", encoding, sub, options)
                    # cancelled?
                    return
                coding, data, client_options, outw, outh, outstride, _ = ret
                if not data:
                    raise RuntimeError(f"no data from {encoding} function {encode_fn}")
                flush -= 1
                client_options["flush"] = flush
                # if SAVE_TO_FILE:
                #    # hard-coded for BGRA!
                #    from xpra.os_util import memoryview_to_bytes
                #    from PIL import Image
                #    im = Image.frombuffer("RGBA", (w, sh), memoryview_to_bytes(sub.get_pixels()),
                #                          "raw", "BGRA", sub.get_rowstride(), 1)
                #    filename = "./scroll-%i-%i.png" % (self._sequence, len(non_scroll)-flush)
                #    im.save(filename, "png")
                #    log.info("saved scroll y=%i h=%i to %s", sy, sh, filename)
                packet = self.make_draw_packet(sub.get_target_x(), sub.get_target_y(), outw, outh,
                                               coding, data, outstride, client_options, options)
                self.queue_damage_packet(packet, damage_time, process_damage_time)
                psize = w*sh*4
                csize = len(data)
                compresslog(COMPRESS_FMT,
                            (monotonic() - substart) * 1000, w, sh, x+0, y+sy, self.wid, coding,
                            100 * csize / psize, ceil(psize / 1024), ceil(csize / 1024),
                            self._damage_packet_sequence, client_options, options)
            scrolllog("non-scroll (quality=%i, speed=%i) took %ims for %i rectangles",
                      self._current_quality, self._current_speed, (monotonic() - nsstart) * 1000, len(non_scroll))
        else:
            scrolllog("no non_scroll areas")
        if flush != 0:
            raise RuntimeError(f"flush counter mismatch: {flush}")
        self.last_scroll_time = monotonic()
        scrolllog("scroll encoding total time: %ims", (self.last_scroll_time-start)*1000)
        free_image_wrapper(image)

    def do_schedule_auto_refresh(self, encoding: str, scroll_data, region, client_options: dict, options: typedict) -> None:
        # for scroll encoding, data is a LargeStructure wrapper:
        if scroll_data:
            if not self.refresh_regions:
                return
            # check if any pending refreshes intersect the area containing the scroll data:
            if not any(region.intersects_rect(r) for r in self.refresh_regions):
                # nothing to do!
                return
            pixels_added = 0
            for x, y, w, h, dx, dy in scroll_data:
                # the region that moved
                src_rect = rectangle(x, y, w, h)
                for rect in self.refresh_regions:
                    inter = src_rect.intersection_rect(rect)
                    if inter:
                        dst_rect = rectangle(inter.x+dx, inter.y+dy, inter.width, inter.height)
                        pixels_added += self.add_refresh_region(dst_rect)
            if pixels_added:
                # if we end up with too many rectangles,
                # bail out and simplify:
                if len(self.refresh_regions) >= 200:
                    self.refresh_regions = [merge_all(self.refresh_regions)]
                refreshlog("updated refresh regions with scroll data: %i pixels added", pixels_added)
                refreshlog(" refresh_regions=%s", self.refresh_regions)
            # we don't change any of the refresh scheduling
            # if there are non-scroll packets following this one, they will
            # and if not then we're OK anyway
            return
        super().do_schedule_auto_refresh(encoding, scroll_data, region, client_options, options)

    def video_fallback(self, image: ImageWrapper, options, warn=False, info="") -> tuple:
        if warn and first_time(f"non-video-{self.wid:#x}"):
            videolog.warn("Warning: using non-video fallback encoding")
            videolog.warn(f" for {image} of window {self.wid:#x}")
            videolog.warn(f" {info}")
        else:
            videolog(f"video fallback: {info}")
        w = image.get_width()
        h = image.get_height()
        fallback_encodings = tuple(set(self.non_video_encodings).intersection(self.video_fallback_encodings.keys()))
        log("fallback encodings(%s, %s)=%s",
            self.non_video_encodings, self.video_fallback_encodings, fallback_encodings)
        encoding = self.do_get_auto_encoding(w, h, dict(options), "", fallback_encodings)
        if not encoding:
            return ()
        encoder = self.video_fallback_encodings[encoding][0]
        ret = encoder(encoding, image, options)
        if not ret:
            return ()
        if not LOG_ENCODERS and not compresslog.is_debug_enabled():
            return ret
        # coding, data, client_options, outw, outh, outstride, bpp = ret
        client_options = ret[2]
        if "encoder" not in client_options:
            # add encoder info to packet data:
            client_options["encoder"] = "fallback: " + ("mmap_encode" if encoder == self.mmap_encode
                                                        else get_encoder_type(encoder))
        return ret

    def video_encode(self, encoding: str, image: ImageWrapper, options: typedict) -> tuple:
        if self.is_cancelled():
            return ()
        if SAVE_VIDEO_FRAMES:
            save_video_frame(self.wid, image)
        depth = image.get_depth()
        try:
            if depth not in (24, 30, 32):
                return self.video_fallback(image, options, info=f"depth {depth} not supported")
            if not self.common_video_encodings:
                # we have to send using a non-video encoding as that's all we have!
                return self.video_fallback(image, options, info="no common video encodings")

            return self.do_video_encode(encoding, image, options)
        finally:
            free_image_wrapper(image)

    def do_video_encode(self, encoding: str, image: ImageWrapper, options: typedict) -> tuple:
        """
            This method is used by make_data_packet to encode frames using video encoders.
            Video encoders only deal with fixed dimensions,
            so we must clean and reinitialize the encoder if the window dimensions
            has changed.

            Runs in the 'encode' thread.
        """
        videolog("do_video_encode(%s, %s, %s)", encoding, image, options)
        x, y, w, h = image.get_geometry()[:4]
        src_format = image.get_pixel_format()
        if not src_format:
            log.warn("Warning: cannot encode an image without a valid pixel format!")
            log.warn(" %s", image)
            return ()
        if self.pixel_format != src_format:
            videolog.warn("Warning: image pixel format unexpectedly changed from %s to %s",
                          self.pixel_format, src_format)
            self.pixel_format = src_format

        # if the client doesn't support alpha,
        # use an rgb input format that ignores the alpha channel:
        if not self.supports_transparency and src_format.find("A") >= 0:
            # ie: "BGRA" -> "BGRX"
            src_format = src_format.replace("A", "X")

        if self.may_use_scrolling(image, options):
            # scroll encoding has dealt with this image
            return ()

        if self.encoding == "grayscale":
            from xpra.codecs.csc_libyuv.converter import argb_to_gray
            image = argb_to_gray(image)

        vh = self.video_helper
        if vh is None:
            return ()         # shortcut when closing down
        if encoding in ("auto", "stream", "grayscale"):
            encodings = self.common_video_encodings
        else:
            encodings = (encoding, )

        if not self.check_pipeline(encodings, w, h, src_format):
            return self.video_fallback(image, options, info="pipeline failed")
        ve = self._video_encoder
        if not ve:
            return self.video_fallback(image, options, warn=True, info="no video encoder instance")
        if not ve.is_ready():
            return self.video_fallback(image, options, warn=False, info=f"encoder {ve.get_type()!r} is not ready")

        # we're going to use the video encoder,
        # so make sure we don't time it out:
        self.cancel_video_encoder_timer()

        # dw and dh are the edges we don't handle here
        width = w & self.width_mask
        height = h & self.height_mask
        videolog("video_encode%s image size: %4ix%-4i, encoder/csc size: %4ix%-4i",
                 (encoding, image, options), w, h, width, height)

        csce, csc_image, csc, enc_width, enc_height = self.csc_image(image, width, height)

        start = monotonic()
        options.update(self.get_video_encoder_options(ve.get_encoding(), width, height))
        try:
            ret = ve.compress_image(csc_image, typedict(options))
        except Exception as e:
            videolog("%s.compress_image%s", ve, (csc_image, options), exc_info=True)
            if self.is_cancelled():
                return ()
            videolog.error("Error: failed to encode %s frame", ve.get_encoding())
            videolog.error(" using %s video encoder:", ve.get_type())
            videolog.estr(e)
            videolog.error(" source: %s", csc_image)
            videolog.error(" options:")
            print_nested_dict(options, prefix="   ", print_fn=videolog.error)
            videolog.error(" encoder:")
            print_nested_dict(ve.get_info(), prefix="   ", print_fn=videolog.error)
            if csce:
                videolog.error(" csc %s:", csce.get_type())
                print_nested_dict(csce.get_info(), prefix="   ", print_fn=videolog.error)
            return self.video_fallback(image, options, warn=False, info=f"compression failure: {e}")
        finally:
            if image != csc_image:
                free_image_wrapper(csc_image)
            del csc_image
        if not ret:
            if not self.is_cancelled():
                videolog.error("Error: %s video compression failed", encoding)
            return self.video_fallback(image, options, warn=True, info="no data")
        data, client_options = ret
        end = monotonic()
        if (LOG_ENCODERS or compresslog.is_debug_enabled()) and "csc-type" not in client_options:
            client_options["csc-type"] = csce.get_type() if csce else "none"

        # populate client options:
        frame = client_options.get("frame", 0)
        if frame < self.start_video_frame:
            # tell client not to bother updating the screen,
            # as it must have received a non-video frame already
            client_options["paint"] = False

        if frame == 0 and SAVE_VIDEO_STREAMS:
            self.close_video_stream_file()
            elapsed = monotonic()-self.start_time
            stream_filename = "window-%i-%.1f-%s.%s" % (self.wid, elapsed, ve.get_type(), ve.get_encoding())
            if SAVE_VIDEO_PATH:
                stream_filename = os.path.join(SAVE_VIDEO_PATH, stream_filename)
            self.video_stream_file = open(stream_filename, "wb")
            log.info("saving new %s stream for window %i to %s", ve.get_encoding(), self.wid, stream_filename)
        if self.video_stream_file and data:
            self.video_stream_file.write(data)
            self.video_stream_file.flush()

        # tell the client about scaling (the size of the encoded picture):
        # (unless the video encoder has already done so):
        scaled_size = None
        if csce and ("scaled_size" not in client_options) and (enc_width,enc_height) != (width, height):
            scaled_size = enc_width, enc_height
            client_options["scaled_size"] = scaled_size

        if LOG_ENCODERS or compresslog.is_debug_enabled():
            client_options["encoder"] = ve.get_type()

        # deal with delayed b-frames:
        delayed = client_options.get("delayed", 0)
        self.cancel_video_encoder_flush()
        if delayed > 0:
            self.schedule_video_encoder_flush(ve, csc, frame, x, y, scaled_size)
            if not data:
                if self.non_video_encodings and frame == 0:
                    # first frame has not been sent yet,
                    # so send something as non-video
                    # and skip painting this video frame when it does come out:
                    self.start_video_frame = delayed
                    return self.video_fallback(image, options, info="delayed frame")
                return ()
        else:
            # there are no delayed frames,
            # make sure we time out the encoder if no new frames come through:
            self.schedule_video_encoder_timer()
        actual_encoding = ve.get_encoding()
        videolog("video_encode %s encoder: %4s %4ix%-4i result is %7i bytes, %5i MPixels/s, client options=%s",
                 ve.get_type(), actual_encoding, enc_width, enc_height, len(data or ""),
                 (enc_width*enc_height/(end-start+0.000001)/1024.0/1024.0), client_options)
        if not data:
            if ve.is_closed():
                videolog("video encoder is closed: %s", ve)
                self.video_context_clean()
                return self.video_fallback(image, options, info=f"encoder {ve.get_type()} is closed")
            videolog.error("Error: %s video data is missing", encoding)
            return ()
        return actual_encoding, Compressed(actual_encoding, data), client_options, width, height, 0, 24

    def cancel_video_encoder_flush(self) -> None:
        self.cancel_video_encoder_flush_timer()
        self.b_frame_flush_data = ()

    def cancel_video_encoder_flush_timer(self) -> None:
        bft: int = self.b_frame_flush_timer
        if bft:
            self.b_frame_flush_timer = 0
            GLib.source_remove(bft)

    def schedule_video_encoder_flush(self, ve, csc, frame, x: int, y: int, scaled_size) -> None:
        flush_delay: int = max(150, min(500, int(self.batch_config.delay*10)))
        self.b_frame_flush_data = (ve, csc, frame, x, y, scaled_size)
        self.b_frame_flush_timer = GLib.timeout_add(flush_delay, self.flush_video_encoder)

    def flush_video_encoder_now(self) -> None:
        # this can be called before the timer is due
        self.cancel_video_encoder_flush_timer()
        self.flush_video_encoder()

    def flush_video_encoder(self) -> None:
        # this runs in the UI thread as scheduled by schedule_video_encoder_flush,
        # but we want to run from the encode thread to access the encoder:
        self.b_frame_flush_timer = 0
        if self.b_frame_flush_data:
            self.call_in_encode_thread(True, self.do_flush_video_encoder)

    def do_flush_video_encoder(self) -> None:
        flush_data = self.b_frame_flush_data
        videolog("do_flush_video_encoder: %s", flush_data)
        if not flush_data:
            return
        ve, csc, frame, x, y, scaled_size = flush_data
        if self._video_encoder != ve or ve.is_closed():
            return
        if frame == 0 and ve.get_type() == "x264":
            # x264 has problems if we try to re-use a context after flushing the first IDR frame
            self.ve_clean(self._video_encoder)
            if self.non_video_encodings:
                log("do_flush_video_encoder() scheduling novideo refresh")
                GLib.idle_add(self.refresh, {"novideo": True})
                videolog("flushed frame 0, novideo refresh requested")
            return
        w = ve.get_width()
        h = ve.get_height()
        encoding = ve.get_encoding()
        v = ve.flush(frame)
        if ve.is_closed():
            videolog("do_flush_video_encoder encoder %s is closed following the flush", ve)
            self.cleanup_codecs()
        if not v:
            videolog("do_flush_video_encoder: %s flush=%s", flush_data, v)
            return
        data, client_options = v
        if not data:
            videolog("do_flush_video_encoder: %s no data: %s", flush_data, v)
            return
        if self.video_stream_file:
            self.video_stream_file.write(data)
            self.video_stream_file.flush()
        if frame < self.start_video_frame:
            client_options["paint"] = False
        if scaled_size:
            client_options["scaled_size"] = scaled_size
        client_options["flush-encoder"] = True
        videolog("do_flush_video_encoder %s : (%s %s bytes, %s)",
                 flush_data, len(data or ()), type(data), client_options)
        now = monotonic()
        # warning: 'options' will be missing the "window-size",
        # so we may end up not honouring gravity during window resizing:
        options = typedict()
        packet = self.make_draw_packet(x, y, w, h, encoding, Compressed(encoding, data), 0,
                                       client_options, options)
        self.queue_damage_packet(packet, now, now)
        # check for more delayed frames since we want to support multiple b-frames:
        if not self.b_frame_flush_timer and client_options.get("delayed", 0) > 0:
            self.schedule_video_encoder_flush(ve, csc, frame, x, y, scaled_size)
        else:
            self.schedule_video_encoder_timer()

    def cancel_video_encoder_timer(self) -> None:
        vet: int = self.video_encoder_timer
        if vet:
            self.video_encoder_timer = 0
            GLib.source_remove(vet)

    def schedule_video_encoder_timer(self) -> None:
        if not self.video_encoder_timer:
            vs = self.video_subregion
            if vs and vs.detection:
                timeout = VIDEO_TIMEOUT
            else:
                timeout = VIDEO_NODETECT_TIMEOUT
            if timeout > 0:
                self.video_encoder_timer = GLib.timeout_add(timeout*1000, self.video_encoder_timeout)

    def video_encoder_timeout(self) -> None:
        videolog("video_encoder_timeout() will close video encoder=%s", self._video_encoder)
        self.video_encoder_timer = 0
        self.video_context_clean()

    def csc_image(self, image: ImageWrapper, width: int, height: int) -> tuple:
        """
            Takes a source image and converts it
            using the current csc_encoder.
            If there are no csc_encoders (because the video
            encoder can process the source format directly)
            then the image is returned unchanged.

            Runs in the 'encode' thread.
        """
        csce = self._csc_encoder
        if csce is None:
            # no csc step!
            return None, image, image.get_pixel_format(), width, height

        start = monotonic()
        csc_image = csce.convert_image(image)
        end = monotonic()
        csclog("csc_image(%s, %s, %s) converted to %s in %.1fms, %5i MPixels/s",
               image, width, height,
               csc_image, (1000.0*end-1000.0*start), (width*height/(end-start+0.000001)/1024.0/1024.0))
        if not csc_image:
            raise RuntimeError(f"csc_image: conversion of {image} to {csce.get_dst_format()} failed")
        cscf = csce.get_dst_format()
        actual = csc_image.get_pixel_format()
        if cscf != actual:
            raise RuntimeError(f"expected image pixel format {cscf} but got {actual}")
        return csce, csc_image, cscf, csce.get_dst_width(), csce.get_dst_height()
