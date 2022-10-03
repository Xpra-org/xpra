# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2013-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time
import operator
import traceback
import threading
from math import sqrt
from functools import reduce
from time import monotonic

from xpra.net.compression import Compressed, LargeStructure
from xpra.codecs.codec_constants import TransientCodecException, RGB_FORMATS, PIXEL_SUBSAMPLING
from xpra.server.window.window_source import (
    WindowSource, DelayedRegions,
    STRICT_MODE, AUTO_REFRESH_SPEED, AUTO_REFRESH_QUALITY, LOSSLESS_WINDOW_TYPES,
    DOWNSCALE_THRESHOLD, DOWNSCALE,
    COMPRESS_FMT_PREFIX, COMPRESS_FMT_SUFFIX, COMPRESS_FMT,
    LOG_ENCODERS,
    )
from xpra.rectangle import rectangle, merge_all          #@UnresolvedImport
from xpra.server.window.motion import ScrollData                    #@UnresolvedImport
from xpra.server.window.video_subregion import VideoSubregion, VIDEO_SUBREGION
from xpra.server.window.video_scoring import get_pipeline_score
from xpra.codecs.codec_constants import PREFERRED_ENCODING_ORDER, EDGE_ENCODING_ORDER
from xpra.codecs.loader import has_codec
from xpra.util import parse_scaling_value, engs, envint, envbool, csv, roundup, print_nested_dict, first_time, typedict
from xpra.log import Logger

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


TEXT_USE_VIDEO = envbool("XPRA_TEXT_USE_VIDEO", False)
MAX_NONVIDEO_PIXELS = envint("XPRA_MAX_NONVIDEO_PIXELS", 1024*4)
MIN_VIDEO_FPS = envint("XPRA_MIN_VIDEO_FPS", 10)
MIN_VIDEO_EVENTS = envint("XPRA_MIN_VIDEO_EVENTS", 20)
ENCODE_QUEUE_MIN_GAP = envint("XPRA_ENCODE_QUEUE_MIN_GAP", 5)

VIDEO_TIMEOUT = envint("XPRA_VIDEO_TIMEOUT", 10)
VIDEO_NODETECT_TIMEOUT = envint("XPRA_VIDEO_NODETECT_TIMEOUT", 10*60)

FORCE_CSC_MODE = os.environ.get("XPRA_FORCE_CSC_MODE", "")   #ie: "YUV444P"
if FORCE_CSC_MODE and FORCE_CSC_MODE not in RGB_FORMATS and FORCE_CSC_MODE not in PIXEL_SUBSAMPLING:
    log.warn("ignoring invalid CSC mode specified: %s", FORCE_CSC_MODE)
    FORCE_CSC_MODE = ""
FORCE_CSC = bool(FORCE_CSC_MODE) or envbool("XPRA_FORCE_CSC", False)
SCALING = envbool("XPRA_SCALING", True)
SCALING_HARDCODED = parse_scaling_value(os.environ.get("XPRA_SCALING_HARDCODED", ""))
SCALING_PPS_TARGET = envint("XPRA_SCALING_PPS_TARGET", 25*1920*1080)
SCALING_MIN_PPS = envint("XPRA_SCALING_MIN_PPS", 25*320*240)
SCALING_OPTIONS = (1, 10), (1, 5), (1, 4), (1, 3), (1, 2), (2, 3), (1, 1)
def parse_scaling_options_str(scaling_options_str):
    if not scaling_options_str:
        return SCALING_OPTIONS
    #parse 1/10,1/5,1/4,1/3,1/2,2/3,1/1
    #or even: 1:10, 1:5, ...
    vs_options = []
    for option in scaling_options_str.split(","):
        try:
            if option.find("%")>0:
                v = float(option[:option.find("%")])*100
                vs_options.append(v.as_integer_ratio())
            elif option.find("/")<0:
                v = float(option)
                vs_options.append(v.as_integer_ratio())
            else:
                num, den = option.strip().split("/")
                vs_options.append((int(num), int(den)))
        except ValueError:
            scalinglog.warn("Warning: invalid scaling string '%s'", option.strip())
    if vs_options:
        return tuple(vs_options)
    return SCALING_OPTIONS
SCALING_OPTIONS = parse_scaling_options_str(os.environ.get("XPRA_SCALING_OPTIONS"))
scalinglog("scaling options: SCALING=%s, HARDCODED=%s, PPS_TARGET=%i, MIN_PPS=%i, OPTIONS=%s",
           SCALING, SCALING_HARDCODED, SCALING_PPS_TARGET, SCALING_MIN_PPS, SCALING_OPTIONS)

DEBUG_VIDEO_CLEAN = envbool("XPRA_DEBUG_VIDEO_CLEAN", False)

FORCE_AV_DELAY = envint("XPRA_FORCE_AV_DELAY", -1)
AV_SYNC_DEFAULT = envbool("XPRA_AV_SYNC_DEFAULT", False)
B_FRAMES = envbool("XPRA_B_FRAMES", True)
VIDEO_SKIP_EDGE = envbool("XPRA_VIDEO_SKIP_EDGE", False)
SCROLL_MIN_PERCENT = max(1, min(100, envint("XPRA_SCROLL_MIN_PERCENT", 30)))
MIN_SCROLL_IMAGE_SIZE = envint("XPRA_MIN_SCROLL_IMAGE_SIZE", 128)

SAVE_VIDEO_PATH = os.environ.get("XPRA_SAVE_VIDEO_PATH", "")
SAVE_VIDEO_STREAMS = envbool("XPRA_SAVE_VIDEO_STREAMS", False)
SAVE_VIDEO_FRAMES = os.environ.get("XPRA_SAVE_VIDEO_FRAMES")
if SAVE_VIDEO_FRAMES not in ("png", "jpeg", None):
    log.warn("Warning: invalid value for 'XPRA_SAVE_VIDEO_FRAMES'")
    log.warn(" only 'png' or 'jpeg' are allowed")
    SAVE_VIDEO_FRAMES = None

COMPRESS_SCROLL_FMT = COMPRESS_FMT_PREFIX+" as %3i rectangles  (%5iKB to     0KB)"+COMPRESS_FMT_SUFFIX

WINDOW_FOCUS_VIDEO_ENCODER = envbool("XPRA_WINDOW_FOCUS_VIDEO_ENCODER", True)



class WindowVideoSource(WindowSource):
    """
        A WindowSource that handles video codecs.
    """

    def __init__(self, *args):
        #this will call init_vars():
        self.supports_scrolling = False
        self.video_subregion = None
        super().__init__(*args)
        self.supports_eos = self.encoding_options.boolget("eos")
        self.supports_scrolling = "scroll" in self.common_encodings or (
            #for older clients, we check an encoding option:
            "scroll" in self.server_core_encodings and self.encoding_options.boolget("scrolling") and not STRICT_MODE)
        self.scroll_min_percent = self.encoding_options.intget("scrolling.min-percent", SCROLL_MIN_PERCENT)
        self.scroll_preference = self.encoding_options.intget("scrolling.preference", 100)
        self.supports_video_b_frames = self.encoding_options.strtupleget("video_b_frames", ())
        self.video_max_size = self.encoding_options.inttupleget("video_max_size", (8192, 8192), 2, 2)
        self.video_subregion = VideoSubregion(self.timeout_add, self.source_remove, self.refresh_subregion, self.auto_refresh_delay, VIDEO_SUBREGION)
        self.video_stream_file = None

    def init_encoders(self):
        super().init_encoders()
        self._csc_encoder = None
        self._video_encoder = None
        self._last_pipeline_check = 0
        if has_codec("csc_libyuv"):
            #need libyuv to be able to handle 'grayscale' video:
            #(to convert ARGB to grayscale)
            self.add_encoder("grayscale", self.video_encode)
        if self._mmap_size>0:
            self.non_video_encodings = ()
            self.common_video_encodings = ()
            return
        self.video_encodings = tuple(x for x in self.video_helper.get_encodings() if x in self.server_core_encodings)
        video_enabled = []
        for x in self.video_encodings:
            self.append_encoder(x, self.video_encode)
            video_enabled.append(x)
        #video_encode() is used for more than just video encoders:
        #(always enable it and let it fall through)
        self.add_encoder("auto", self.video_encode)
        #these are used for non-video areas, ensure "jpeg" is used if available
        #as we may be dealing with large areas still, and we want speed:
        nv_common = (set(self.server_core_encodings) & set(self.core_encodings)) - set(self.video_encodings)
        self.non_video_encodings = tuple(x for x in PREFERRED_ENCODING_ORDER
                                         if x in nv_common)
        self.common_video_encodings = tuple(x for x in PREFERRED_ENCODING_ORDER
                                            if x in self.video_encodings and x in self.core_encodings)
        if "scroll" in self.server_core_encodings:
            self.add_encoder("scroll", self.scroll_encode)

    def __repr__(self):
        return "WindowVideoSource(%s : %s)" % (self.wid, self.window_dimensions)

    def init_vars(self):
        super().init_vars()
        #these constraints get updated with real values
        #when we construct the video pipeline:
        self.min_w = 1
        self.min_h = 1
        self.max_w = 16384
        self.max_h = 16384
        self.width_mask = 0xFFFF
        self.height_mask = 0xFFFF
        self.actual_scaling = (1, 1)

        self.last_pipeline_params = None
        self.last_pipeline_scores = ()
        self.last_pipeline_time = 0

        self.video_encodings = ()
        self.common_video_encodings = ()
        self.non_video_encodings = ()
        self.edge_encoding = None
        self.start_video_frame = 0
        self.video_encoder_timer = None
        self.b_frame_flush_timer = None
        self.b_frame_flush_data = None
        self.encode_from_queue_timer = None
        self.encode_from_queue_due = 0
        self.scroll_data = None
        self.last_scroll_time = 0

        self._csc_encoder = None
        self._video_encoder = None
        self._last_pipeline_check = 0

    def do_set_auto_refresh_delay(self, min_delay, delay):
        super().do_set_auto_refresh_delay(min_delay, delay)
        r = self.video_subregion
        if r:
            r.set_auto_refresh_delay(self.base_auto_refresh_delay)

    def update_av_sync_frame_delay(self):
        self.av_sync_frame_delay = 0
        ve = self._video_encoder
        if ve:
            #how many frames are buffered in the encoder, if any:
            d = ve.get_info().get("delayed", 0)
            if d>0:
                #clamp the batch delay to a reasonable range:
                frame_delay = min(100, max(10, self.batch_config.delay))
                self.av_sync_frame_delay += frame_delay * d
            avsynclog("update_av_sync_frame_delay() video encoder=%s, delayed frames=%i, frame delay=%i",
                      ve, d, self.av_sync_frame_delay)
        self.may_update_av_sync_delay()


    def get_property_info(self) -> dict:
        i = super().get_property_info()
        if self.scaling_control is None:
            i["scaling.control"] = "auto"
        else:
            i["scaling.control"] = self.scaling_control
        i["scaling"] = self.scaling or (1, 1)
        return i

    def get_info(self) -> dict:
        info = super().get_info()
        sr = self.video_subregion
        if sr:
            sri = sr.get_info()
            sri["video-mode"] = self.subregion_is_video()
            info["video_subregion"] = sri
        info["scaling"] = self.actual_scaling
        info["video-max-size"] = self.video_max_size
        def addcinfo(prefix, x):
            if not x:
                return
            try:
                i = x.get_info()
                i[""] = x.get_type()
                info[prefix] = i
            except Exception:
                log.error("Error collecting codec information from %s", x, exc_info=True)
        addcinfo("csc", self._csc_encoder)
        addcinfo("encoder", self._video_encoder)
        info.setdefault("encodings", {}).update({
                                                 "non-video"    : self.non_video_encodings,
                                                 "video"        : self.common_video_encodings,
                                                 "edge"         : self.edge_encoding or "",
                                                 "eos"          : self.supports_eos,
                                                 })
        einfo = {
                 "pipeline_param" : self.get_pipeline_info(),
                 "scrolling"      : {
                     "enabled"      : self.supports_scrolling,
                     "min-percent"  : self.scroll_min_percent,
                     "preference"   : self.scroll_preference,
                     "event"        : int(self.last_scroll_event*1000),
                     "time"         : int(self.last_scroll_time*1000),
                     }
                 }
        if self._last_pipeline_check>0:
            einfo["pipeline_last_check"] = int(1000*(monotonic()-self._last_pipeline_check))
        lps = self.last_pipeline_scores
        if lps:
            popts = einfo.setdefault("pipeline_option", {})
            for i, lp in enumerate(lps):
                popts[i] = self.get_pipeline_score_info(*lp)
        info.setdefault("encoding", {}).update(einfo)
        return info

    def get_pipeline_info(self) -> dict:
        lp = self.last_pipeline_params
        if not lp:
            return {}
        encoding, width, height, src_format = lp
        return {
                "encoding"      : encoding,
                "dimensions"    : (width, height),
                "src_format"    : src_format
                }

    def get_pipeline_score_info(self, score, scaling, csc_scaling, csc_width, csc_height, csc_spec, enc_in_format, encoder_scaling, enc_width, enc_height, encoder_spec):
        def specinfo(x):
            try:
                return x.codec_type
            except AttributeError:
                return repr(x)
        pi  = {
               "score"             : score,
               "scaling"           : scaling,
               "format"            : str(enc_in_format),
               "encoder"           : {
                                      ""        : specinfo(encoder_spec),
                                      "scaling" : encoder_scaling,
                                      "width"   : enc_width,
                                      "height"  : enc_height,
                                      },
               }
        if csc_spec:
            pi["csc"] = {
                         ""         : specinfo(csc_spec),
                         "scaling"  : csc_scaling,
                         "width"    : csc_width,
                         "height"   : csc_height,
                         }
        else:
            pi["csc"] = "None"
        return pi


    def suspend(self):
        super().suspend()
        #we'll create a new video pipeline when resumed:
        self.cleanup_codecs()


    def cleanup(self):
        super().cleanup()
        self.cleanup_codecs()

    def cleanup_codecs(self):
        """ Video encoders (x264, nvenc and vpx) and their csc helpers
            require us to run cleanup code to free the memory they use.
            We have to do this from the encode thread to be safe.
            (the encoder and csc module may be in use by that thread)
        """
        self.cancel_video_encoder_flush()
        self.video_context_clean()

    def video_context_clean(self):
        """ Calls clean() from the encode thread """
        csce = self._csc_encoder
        ve = self._video_encoder
        if csce or ve:
            if DEBUG_VIDEO_CLEAN:
                log.warn("video_context_clean() for wid %i: %s and %s", self.wid, csce, ve)
                for x in traceback.extract_stack():
                    log.warn(" %s", x)
            self._csc_encoder = None
            self._video_encoder = None
            def clean():
                if DEBUG_VIDEO_CLEAN:
                    log.warn("video_context_clean() done")
                self.csc_clean(csce)
                self.ve_clean(ve)
            self.call_in_encode_thread(False, clean)

    def csc_clean(self, csce):
        if csce:
            csce.clean()

    def ve_clean(self, ve):
        self.cancel_video_encoder_timer()
        if ve:
            ve.clean()
            #only send eos if this video encoder is still current,
            #(otherwise, sending the new stream will have taken care of it already,
            # and sending eos then would close the new stream, not the old one!)
            if self.supports_eos and self._video_encoder==ve:
                log("sending eos for wid %i", self.wid)
                self.queue_packet(("eos", self.wid))
            if SAVE_VIDEO_STREAMS:
                self.close_video_stream_file()

    def close_video_stream_file(self):
        vsf = self.video_stream_file
        if vsf:
            self.video_stream_file = None
            try:
                vsf.close()
            except OSError:
                log.error("Error closing video stream file", exc_info=True)

    def ui_cleanup(self):
        super().ui_cleanup()
        self.video_subregion = None


    def set_new_encoding(self, encoding, strict=None):
        if self.encoding!=encoding:
            #ensure we re-init the codecs asap:
            self.cleanup_codecs()
        super().set_new_encoding(encoding, strict)

    def update_encoding_selection(self, encoding=None, exclude=None, init=False):
        #override so we don't use encodings that don't have valid csc modes:
        log("wvs.update_encoding_selection(%s, %s, %s) full_csc_modes=%s", encoding, exclude, init, self.full_csc_modes)
        if exclude is None:
            exclude = []
        for x in self.video_encodings:
            if x not in self.core_encodings:
                log("video encoding %s not in core encodings", x)
                exclude.append(x)
                continue
            csc_modes = self.full_csc_modes.strtupleget(x)
            if not csc_modes or x not in self.core_encodings:
                exclude.append(x)
                msg_args = ("Warning: client does not support any csc modes with %s on window %i", x, self.wid)
                if not init and first_time("no-csc-%s-%i" % (x, self.wid)):
                    log.warn(*msg_args)
                else:
                    log(*msg_args)
                log(" csc modes=%", self.full_csc_modes)
        self.common_video_encodings = tuple(x for x in PREFERRED_ENCODING_ORDER
                                            if x in self.video_encodings and x in self.core_encodings)
        log("update_encoding_options: common_video_encodings=%s, csc_encoder=%s, video_encoder=%s",
            self.common_video_encodings, self._csc_encoder, self._video_encoder)
        super().update_encoding_selection(encoding, exclude, init)

    def do_set_client_properties(self, properties):
        #client may restrict csc modes for specific windows
        self.supports_scrolling = "scroll" in self.common_encodings or (
            #for older clients, we check an encoding option:
            "scroll" in self.server_core_encodings and properties.boolget("scrolling", self.supports_scrolling) and not STRICT_MODE)
        self.scroll_min_percent = properties.intget("scrolling.min-percent", self.scroll_min_percent)
        self.scroll_preference = properties.intget("scrolling.preference", self.scroll_preference)
        self.video_subregion.supported = properties.boolget("encoding.video_subregion", VIDEO_SUBREGION) and VIDEO_SUBREGION
        if properties.get("scaling.control") is not None:
            self.scaling_control = max(0, min(100, properties.intget("scaling.control", 0)))
        super().do_set_client_properties(properties)
        #encodings may have changed, so redo this:
        nv_common = set(self.picture_encodings) & set(self.core_encodings)
        log("nv_common(%s & %s)=%s", self.picture_encodings, self.core_encodings, nv_common)
        self.non_video_encodings = tuple(x for x in PREFERRED_ENCODING_ORDER if x in nv_common)
        if not VIDEO_SKIP_EDGE:
            try:
                self.edge_encoding = next(x for x in EDGE_ENCODING_ORDER if x in self.non_video_encodings)
            except StopIteration:
                self.edge_encoding = None
        log("do_set_client_properties(%s) full_csc_modes=%s, video_subregion=%s, non_video_encodings=%s, edge_encoding=%s, scaling_control=%s",
            properties, self.full_csc_modes, self.video_subregion.supported, self.non_video_encodings, self.edge_encoding, self.scaling_control)

    def get_best_encoding_impl_default(self):
        log("get_best_encoding_impl_default() window_type=%s, encoding=%s", self.window_type, self.encoding)
        if self.window_type.intersection(LOSSLESS_WINDOW_TYPES):
            return super().get_best_encoding_impl_default()
        if self.encoding!="grayscale" or has_codec("csc_libyuv"):
            if self.common_video_encodings or self.supports_scrolling:
                return self.get_best_encoding_video
        return super().get_best_encoding_impl_default()


    def get_best_encoding_video(self, ww, wh, options, current_encoding):
        """
            decide whether we send a full window update using the video encoder,
            or if a separate small region(s) is a better choice
        """
        log("get_best_encoding_video(..)")
        pixel_count = ww*wh
        def nonvideo(qdiff=None, info=""):
            if qdiff:
                quality = options.get("quality", self._current_quality) + qdiff
                options["quality"] = max(self._fixed_min_quality, min(self._fixed_max_quality, quality))
            log("nonvideo(%s, %s)", qdiff, info)
            return WindowSource.get_auto_encoding(self, ww, wh, options)

        #log("get_best_encoding_video%s non_video_encodings=%s, common_video_encodings=%s, supports_scrolling=%s",
        #    (pixel_count, ww, wh, speed, quality, current_encoding),
        #     self.non_video_encodings, self.common_video_encodings, self.supports_scrolling)
        if not self.non_video_encodings:
            return current_encoding
        if not self.common_video_encodings and not self.supports_scrolling:
            return nonvideo(info="no common video encodings")
        if self.is_tray:
            return nonvideo(100, "system tray")
        text_hint = self.content_type.find("text")>=0
        if text_hint and not TEXT_USE_VIDEO and not (WINDOW_FOCUS_VIDEO_ENCODER and self.has_focus):
            return nonvideo(100, info="text content-type")

        #ensure the dimensions we use for decision making are the ones actually used:
        cww = ww & self.width_mask
        cwh = wh & self.height_mask
        video_hint = self.content_type.find("video")>=0 or (WINDOW_FOCUS_VIDEO_ENCODER and self.has_focus)

        rgbmax = self._rgb_auto_threshold
        videomin = cww*cwh // (1+video_hint*2)
        sr = self.video_subregion.rectangle
        if sr:
            videomin = min(videomin, sr.width * sr.height)
            rgbmax = min(rgbmax, sr.width*sr.height//2)
        elif not text_hint:
            videomin = min(640*480, cww*cwh)
        if not (WINDOW_FOCUS_VIDEO_ENCODER and self.has_focus) and (pixel_count<=rgbmax or cww<8 or cwh<8):
            return nonvideo(info="low pixel count")

        if current_encoding not in ("auto", "grayscale") and current_encoding not in self.common_video_encodings:
            return nonvideo(info="%s not a supported video encoding" % current_encoding)

        if cww*cwh<=MAX_NONVIDEO_PIXELS or cww<16 or cwh<16:
            return nonvideo(info="window is too small")

        if cww<self.min_w or cww>self.max_w or cwh<self.min_h or cwh>self.max_h:
            return nonvideo(info="size out of range for video encoder")

        now = monotonic()
        if now-self.statistics.last_packet_time>1:
            return nonvideo(info="no recent updates")
        if now-self.statistics.last_resized<0.350:
            return nonvideo(info="resized recently")

        if sr and ((sr.width&self.width_mask)!=cww or (sr.height&self.height_mask)!=cwh):
            #we have a video region, and this is not it, so don't use video
            #raise the quality as the areas around video tend to not be updating as quickly
            return nonvideo(30, "not the video region")

        if not video_hint and not self.is_shadow:
            if now-self.global_statistics.last_congestion_time>5:
                lde = tuple(self.statistics.last_damage_events)
                lim = now-4
                pixels_last_4secs = sum(w*h for when,_,_,w,h in lde if when>lim)
                if pixels_last_4secs<((3+text_hint*6)*videomin):
                    return nonvideo(info="not enough frames")
                lim = now-1
                pixels_last_sec = sum(w*h for when,_,_,w,h in lde if when>lim)
                if pixels_last_sec<pixels_last_4secs//8:
                    #framerate is dropping?
                    return nonvideo(30, "framerate lowered")

            #calculate the threshold for using video vs small regions:
            speed = options.get("speed", self._current_speed)
            factors = (
                max(1, (speed-75)/5.0),                      #speed multiplier
                1 + int(self.is_OR or self.is_tray)*2,       #OR windows tend to be static
                max(1, 10-self._sequence),                   #gradual discount the first 9 frames, as the window may be temporary
                1.0 / (int(bool(self._video_encoder)) + 1),  #if we have a video encoder already, make it more likely we'll use it:
                )
            max_nvp = int(reduce(operator.mul, factors, MAX_NONVIDEO_PIXELS))
            if pixel_count<=max_nvp:
                #below threshold
                return nonvideo(info="not enough pixels")
        return current_encoding

    def get_best_nonvideo_encoding(self, ww, wh, options, current_encoding=None, encoding_options=()):
        if self.encoding=="grayscale":
            return self.encoding_is_grayscale(ww, wh, options, current_encoding or self.encoding)
        #if we're here, then the window has no alpha (or the client cannot handle alpha)
        #and we can ignore the current encoding
        encoding_options = encoding_options or self.non_video_encodings
        depth = self.image_depth
        if depth==8 and "png/P" in encoding_options:
            return "png/P"
        if self._mmap_size>0:
            return "mmap"
        return super().do_get_auto_encoding(ww, wh, options, current_encoding or self.encoding, encoding_options)


    def do_damage(self, ww, wh, x, y, w, h, options):
        vs = self.video_subregion
        if vs:
            r = vs.rectangle
            if r and r.intersects(x, y, w, h):
                #the damage will take care of scheduling it again
                vs.cancel_refresh_timer()
        super().do_damage(ww, wh, x, y, w, h, options)


    def cancel_damage(self, limit=0):
        self.cancel_encode_from_queue()
        self.free_encode_queue_images()
        vsr = self.video_subregion
        if vsr:
            vsr.cancel_refresh_timer()
        self.free_scroll_data()
        self.last_scroll_time = 0
        super().cancel_damage(limit)
        #we must clean the video encoder to ensure
        #we will resend a key frame because we may be missing a frame
        self.cleanup_codecs()


    def full_quality_refresh(self, damage_options):
        vs = self.video_subregion
        if vs and vs.rectangle:
            if vs.detection:
                #reset the video region on full quality refresh
                vs.reset()
            else:
                #keep the region, but cancel the refresh:
                vs.cancel_refresh_timer()
        self.free_scroll_data()
        self.last_scroll_time = 0
        if self.non_video_encodings:
            #refresh the whole window in one go:
            damage_options["novideo"] = True
        super().full_quality_refresh(damage_options)

    def timer_full_refresh(self):
        self.free_scroll_data()
        self.last_scroll_time = 0
        super().timer_full_refresh()


    def quality_changed(self, window, *args):
        super().quality_changed(window, args)
        self.video_context_clean()
        return True

    def speed_changed(self, window, *args):
        super().speed_changed(window, args)
        self.video_context_clean()
        return True


    def client_decode_error(self, error, message):
        #maybe the stream is now corrupted..
        self.cleanup_codecs()
        super().client_decode_error(error, message)


    def get_refresh_exclude(self):
        #exclude video region (if any) from lossless refresh:
        return self.video_subregion.rectangle

    def refresh_subregion(self, regions):
        #callback from video subregion to trigger a refresh of some areas
        if not regions:
            regionrefreshlog("refresh_subregion(%s) nothing to refresh", regions)
            return False
        if not self.can_refresh():
            regionrefreshlog("refresh_subregion(%s) cannot refresh", regions)
            return False
        now = monotonic()
        if now-self.global_statistics.last_congestion_time<5:
            regionrefreshlog("refresh_subregion(%s) skipping refresh due to congestion", regions)
            return False
        self.flush_video_encoder_now()
        encoding = self.auto_refresh_encodings[0]
        options = self.get_refresh_options()
        regionrefreshlog("refresh_subregion(%s) using %s and %s", regions, encoding, options)
        super().do_send_delayed_regions(now, regions, encoding, options,
                                        get_best_encoding=self.get_refresh_subregion_encoding)
        return True

    def get_refresh_subregion_encoding(self, *_args):
        ww, wh = self.window_dimensions
        w, h = ww, wh
        vr = self.video_subregion.rectangle
        #could have been cleared by another thread:
        if vr:
            w, h = vr.width, vr.height
        options = {
            "speed"     : AUTO_REFRESH_SPEED,
            "quality"   : AUTO_REFRESH_QUALITY,
            }
        return self.get_best_nonvideo_encoding(w, h, options,
                                               self.auto_refresh_encodings[0], self.auto_refresh_encodings)

    def remove_refresh_region(self, region):
        #override so we can update the subregion timers / regions tracking:
        super().remove_refresh_region(region)
        self.video_subregion.remove_refresh_region(region)

    def add_refresh_region(self, region):
        #Note: this does not run in the UI thread!
        #returns the number of pixels in the region update
        #don't refresh the video region as part of normal refresh,
        #use subregion refresh for that
        sarr = super().add_refresh_region
        vr = self.video_subregion.rectangle
        if vr is None:
            #no video region, normal code path:
            return sarr(region)
        if vr.contains_rect(region):
            #all of it is in the video region:
            self.video_subregion.add_video_refresh(region)
            return 0
        ir = vr.intersection_rect(region)
        if ir is None:
            #region is outside video region, normal code path:
            return sarr(region)
        #add intersection (rectangle in video region) to video refresh:
        self.video_subregion.add_video_refresh(ir)
        #add any rectangles not in the video region
        #(if any: keep track if we actually added anything)
        return sum(sarr(r) for r in region.subtract_rect(vr))

    def matches_video_subregion(self, width, height):
        vr = self.video_subregion.rectangle
        if not vr:
            return None
        mw = abs(width - vr.width) & self.width_mask
        mh = abs(height - vr.height) & self.height_mask
        if mw!=0 or mh!=0:
            return None
        return vr

    def subregion_is_video(self):
        if WINDOW_FOCUS_VIDEO_ENCODER and self.has_focus:
            return True
        vs = self.video_subregion
        if not vs:
            return False
        vr = vs.rectangle
        if not vr:
            return False
        events_count = self.statistics.damage_events_count - vs.set_at
        min_video_events = MIN_VIDEO_EVENTS
        min_video_fps = MIN_VIDEO_FPS
        if self.content_type.find("video")>=0:
            min_video_events //= 2
            min_video_fps //= 2
        if events_count<min_video_events:
            return False
        if vs.fps<min_video_fps:
            return False
        return True


    def do_send_delayed_regions(self, damage_time, regions, coding, options):
        """
            Overriden here so we can try to intercept the video_subregion if one exists.
        """
        vr = self.video_subregion.rectangle
        #overrides the default method for finding the encoding of a region
        #so we can ensure we don't use the video encoder when we don't want to:
        def send_nonvideo(regions=regions, encoding=coding, exclude_region=None,
                          get_best_encoding=self.get_best_nonvideo_encoding):
            if self.b_frame_flush_timer and exclude_region is None:
                #a b-frame is already due, don't clobber it!
                exclude_region = vr
            quality_pct = 100
            if vr:
                #give a boost if we have a video region and this is not video:
                quality_pct = 140
            novideo_options = self.assign_sq_options(options, quality_pct=quality_pct)
            WindowSource.do_send_delayed_regions(self, damage_time, regions, encoding, novideo_options,
                                                 exclude_region=exclude_region, get_best_encoding=get_best_encoding)

        if self.is_tray:
            sublog("BUG? video for tray - don't use video region!")
            send_nonvideo(encoding=None)
            return

        if coding not in ("auto", "grayscale") and coding not in self.video_encodings:
            sublog("not a video encoding: %s" % coding)
            #keep current encoding selection function
            send_nonvideo(get_best_encoding=self.get_best_encoding)
            return

        if options.get("novideo"):
            sublog("video disabled in options")
            send_nonvideo(encoding=None)
            return

        if not vr:
            sublog("no video region, we may use the video encoder for something else")
            super().do_send_delayed_regions(damage_time, regions, coding, options)
            return
        assert not self.full_frames_only

        actual_vr = None
        if vr in regions or (WINDOW_FOCUS_VIDEO_ENCODER and self.has_focus):
            #found the video region the easy way: exact match in list
            actual_vr = vr
        else:
            #find how many pixels are within the region (roughly):
            #find all unique regions that intersect with it:
            inter = tuple(x for x in (vr.intersection_rect(r) for r in regions) if x is not None)
            if inter:
                #merge all regions into one:
                in_region = merge_all(inter)
                pixels_in_region = vr.width*vr.height
                pixels_intersect = in_region.width*in_region.height
                if pixels_intersect>=pixels_in_region*40/100:
                    #we have at least 40% of the video region
                    #that needs refreshing, do it:
                    actual_vr = vr

            #still no luck?
            if actual_vr is None:
                #try to find one that has the same dimensions:
                same_d = tuple(r for r in regions if r.width==vr.width and r.height==vr.height)
                if len(same_d)==1:
                    #probably right..
                    actual_vr = same_d[0]
                elif len(same_d)>1:
                    #find one that shares at least one coordinate:
                    same_c = tuple(r for r in same_d if r.x==vr.x or r.y==vr.y)
                    if len(same_c)==1:
                        actual_vr = same_c[0]

        if actual_vr is None:
            sublog("do_send_delayed_regions: video region %s not found in: %s", vr, regions)
        else:
            #found the video region:
            #sanity check in case the window got resized since:
            ww, wh = self.window.get_dimensions()
            if actual_vr.x+actual_vr.width>ww or actual_vr.y+actual_vr.height>wh:
                sublog("video region partially outside the window")
                send_nonvideo(encoding=None)
                return
            #send this using the video encoder:
            video_options = self.assign_sq_options(options, quality_pct=70)
            #TODO: encode delay can be derived rather than hard-coded
            encode_delay = 50
            video_options["av-delay"] = max(0, self.get_frame_encode_delay(options) - encode_delay)
            sublog("send data using video encoder, opts%s", (damage_time, actual_vr.x, actual_vr.y, actual_vr.width, actual_vr.height, coding, video_options, 0))
            self.process_damage_region(damage_time, actual_vr.x, actual_vr.y, actual_vr.width, actual_vr.height,
                                       coding, video_options)

            #now subtract this region from the rest:
            trimmed = []
            for r in regions:
                trimmed += r.subtract_rect(actual_vr)
            if not trimmed:
                sublog("do_send_delayed_regions: nothing left after removing video region %s", actual_vr)
                return
            sublog("do_send_delayed_regions: subtracted %s from %s gives us %s", actual_vr, regions, trimmed)
            regions = trimmed

        #merge existing damage delayed region if there is one:
        #(this codepath can fire from a video region refresh callback)
        dr = self._damage_delayed
        if dr:
            regions = dr.regions + regions
            damage_time = min(damage_time, dr.damage_time)
            self._damage_delayed = None
            self.cancel_expire_timer()
        #decide if we want to send the rest now or delay some more,
        #only delay once the video encoder has dealt with a few frames:
        event_count = max(0, self.statistics.damage_events_count - self.video_subregion.set_at)
        if not actual_vr or event_count<100:
            delay = 0
        else:
            #non-video is delayed at least 50ms, 4 times the batch delay, but no more than non_max_wait:
            elapsed = int(1000.0*(monotonic()-damage_time))
            delay = max(self.batch_config.delay*4, self.batch_config.expire_delay)
            delay = min(delay, self.video_subregion.non_max_wait-elapsed)
            delay = int(delay)
        sublog("do_send_delayed_regions event_count=%s, actual_vr=%s, delay=%s",
               event_count, actual_vr, delay)
        if delay<=25:
            send_nonvideo(regions=regions, encoding=None, exclude_region=actual_vr)
        else:
            self._damage_delayed = DelayedRegions(damage_time, regions, coding, options=options)
            sublog("do_send_delayed_regions: delaying non video regions %s some more by %ims", regions, delay)
            self.expire_timer = self.timeout_add(delay, self.expire_delayed_region)

    def must_encode_full_frame(self, encoding):
        non_video = self.non_video_encodings
        r = self.full_frames_only or not non_video or (encoding in self.video_encodings and encoding not in non_video)
        log("must_encode_full_frame(%s)=%s full_frames_only=%s, non_video=%s, video=%s",
                 encoding, r, self.full_frames_only, non_video, self.video_encodings)
        return r


    def process_damage_region(self, damage_time, x, y, w, h, coding, options, flush=None):
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
        assert self.ui_thread == threading.current_thread()
        assert coding is not None
        rgb_request_time = monotonic()
        image = self.get_damage_image(x, y, w, h)
        if image is None:
            return False
        log("get_damage_image%s took %ims", (x, y, w, h), 1000*(monotonic()-rgb_request_time))
        sequence = self._sequence

        w = image.get_width()
        h = image.get_height()
        if self.send_window_size:
            options["window-size"] = self.window_dimensions
        resize = self.scaled_size(image)
        if resize:
            sw, sh = resize
            options["scaled-width"] = sw
            options["scaled-height"] = sh

        #freeze if:
        # * we want av-sync
        # * the video encoder needs a thread safe image
        #   (the xshm backing may change from underneath us if we don't freeze it)
        av_delay = options.get("av-delay", 0)
        video_mode = coding in self.common_video_encodings or (coding=="auto" and self.common_video_encodings)
        must_freeze = av_delay>0 or (video_mode and not image.is_thread_safe())
        log("process_damage_region: av_delay=%s, must_freeze=%s, size=%s, encoding=%s",
            av_delay, must_freeze, (w, h), coding)
        if must_freeze:
            image.freeze()
        def call_encode(ew, eh, eimage, encoding, flush):
            if self.is_cancelled(sequence):
                self.free_image_wrapper(image)
                log("call_encode: sequence %s is cancelled", sequence)
                return
            now = monotonic()
            log("process_damage_region: wid=%i, sequence=%i, adding pixel data to encode queue (%4ix%-4i - %5s), elapsed time: %3.1f ms, request time: %3.1f ms, frame delay=%3ims",
                    self.wid, sequence, ew, eh, encoding, 1000*(now-damage_time), 1000*(now-rgb_request_time), av_delay)
            item = (ew, eh, damage_time, now, eimage, encoding, sequence, options, flush)
            if av_delay<=0:
                self.call_in_encode_thread(True, self.make_data_packet_cb, *item)
            else:
                self.encode_queue.append(item)
                self.schedule_encode_from_queue(av_delay)
        #now figure out if we need to send edges separately:
        ee = self.edge_encoding
        ow = w
        oh = h
        w = w & self.width_mask
        h = h & self.height_mask
        regions = []
        if video_mode and ee:
            dw = ow - w
            dh = oh - h
            if dw>0 and h>0:
                sub = image.get_sub_image(w, 0, dw, oh)
                regions.append((dw, h, sub, ee))
            if dh>0 and w>0:
                sub = image.get_sub_image(0, h, ow, dh)
                regions.append((dw, h, sub, ee))
        #the main area:
        if w>0 and h>0:
            regions.append((w, h, image, coding))
        #process all regions:
        if regions:
            #ensure that the flush value ends at 0 on the last region:
            flush = max(len(regions)-1, flush or 0)
            for i, region in enumerate(regions):
                w, h, image, coding = region
                call_encode(w, h, image, coding, flush-i)
        return True

    def get_frame_encode_delay(self, options):
        if not self.av_sync:
            return 0
        if FORCE_AV_DELAY>=0:
            return FORCE_AV_DELAY
        content_type = options.get("content-type", self.content_type)
        if AV_SYNC_DEFAULT:
            #default to on, unless we're quite sure it should not be used:
            if any(content_type.find(x)>=0 for x in ("text", "picture")):
                return 0
        else:
            #default to off unless content-type says otherwise:
            if content_type.find("audio")<0:
                return 0
        l = len(self.encode_queue)
        if l>=self.encode_queue_max_size:
            #we must free some space!
            return 0
        return self.av_sync_delay

    def cancel_encode_from_queue(self):
        #free all items in the encode queue:
        self.encode_from_queue_due = 0
        eqt = self.encode_from_queue_timer
        avsynclog("cancel_encode_from_queue() timer=%s for wid=%i", eqt, self.wid)
        if eqt:
            self.encode_from_queue_timer = None
            self.source_remove(eqt)

    def free_encode_queue_images(self):
        eq = self.encode_queue
        avsynclog("free_encode_queue_images() freeing %i images for wid=%i", len(eq), self.wid)
        if not eq:
            return
        self.encode_queue = []
        for item in eq:
            try:
                self.free_image_wrapper(item[4])
            except Exception:
                log.error("Error: cannot free image wrapper %s", item[4], exc_info=True)

    def schedule_encode_from_queue(self, av_delay):
        #must be called from the UI thread for synchronization
        #we ensure that the timer will fire no later than av_delay
        #re-scheduling it if it was due later than that
        due = monotonic()+av_delay/1000.0
        if self.encode_from_queue_due==0 or due<self.encode_from_queue_due:
            self.cancel_encode_from_queue()
            self.encode_from_queue_due = due
            self.encode_from_queue_timer = self.timeout_add(av_delay, self.timer_encode_from_queue)

    def timer_encode_from_queue(self):
        self.encode_from_queue_timer = None
        self.encode_from_queue_due = 0
        self.call_in_encode_thread(True, self.encode_from_queue)

    def encode_from_queue(self):
        #note: we use a queue here to ensure we preserve the order
        #(so we encode frames in the same order they were grabbed)
        eq = self.encode_queue
        avsynclog("encode_from_queue: %s items for wid=%i", len(eq), self.wid)
        if not eq:
            return      #nothing to encode, must have been picked off already
        self.update_av_sync_delay()
        #find the first item which is due
        #in seconds, same as monotonic():
        if len(self.encode_queue)>=self.encode_queue_max_size:
            av_delay = 0        #we must free some space!
        elif FORCE_AV_DELAY>0:
            av_delay = FORCE_AV_DELAY/1000.0
        else:
            av_delay = self.av_sync_delay/1000.0
        now = monotonic()
        still_due = []
        remove = []
        index = 0
        item = None
        sequence = None
        done_packet = False     #only one packet per iteration
        try:
            for index,item in enumerate(eq):
                #item = (w, h, damage_time, now, image, coding, sequence, options, flush)
                sequence = item[6]
                if self.is_cancelled(sequence):
                    self.free_image_wrapper(item[4])
                    remove.append(index)
                    continue
                ts = item[3]
                due = ts + av_delay
                if due<=now and not done_packet:
                    #found an item which is due
                    remove.append(index)
                    avsynclog("encode_from_queue: processing item %s/%s (overdue by %ims)",
                              index+1, len(self.encode_queue), int(1000*(now-due)))
                    self.make_data_packet_cb(*item)
                    done_packet = True
                else:
                    #we only process only one item per call (see "done_packet")
                    #and just keep track of extra ones:
                    still_due.append(int(1000*(due-now)))
        except Exception:
            if not self.is_cancelled(sequence):
                avsynclog.error("error processing encode queue at index %i", index)
                avsynclog.error("item=%s", item, exc_info=True)
        #remove the items we've dealt with:
        #(in reverse order since we pop them from the queue)
        if remove:
            for x in reversed(remove):
                eq.pop(x)
        #if there are still some items left in the queue, re-schedule:
        if not still_due:
            avsynclog("encode_from_queue: nothing due")
            return
        first_due = max(ENCODE_QUEUE_MIN_GAP, min(still_due))
        avsynclog("encode_from_queue: first due in %ims, due list=%s (av-sync delay=%i, actual=%i, for wid=%i)",
                  first_due, still_due, self.av_sync_delay, av_delay, self.wid)
        self.idle_add(self.schedule_encode_from_queue, first_due)

    def update_encoding_options(self, force_reload=False):
        """
            This is called when we want to force a full re-init (force_reload=True)
            or from the timer that allows to tune the quality and speed.
            (this tuning is done in WindowSource.reconfigure)
            Here we re-evaluate if the pipeline we are currently using
            is really the best one, and if not we invalidate it.
            This uses get_video_pipeline_options() to get a list of pipeline
            options with a score for each.

            Can be called from any thread.
        """
        super().update_encoding_options(force_reload)
        vs = self.video_subregion
        log("update_encoding_options(%s): vs: %s, check %s", force_reload, vs, (True if vs else False))
        if vs:
            if not (WINDOW_FOCUS_VIDEO_ENCODER and self.has_focus) and \
                ((self.encoding not in ("auto", "grayscale") and self.encoding not in self.common_video_encodings) or \
                self.full_frames_only or STRICT_MODE or not self.non_video_encodings or not self.common_video_encodings or \
                self.content_type.find("text")>=0 or \
                self._mmap_size>0):
                #cannot use video subregions
                #FIXME: small race if a refresh timer is due when we change encoding - meh
                log("cannot use video subregions, reset")
                vs.reset()
            else:
                old = vs.rectangle
                ww, wh = self.window_dimensions
                

                log("update_encoding_options check setregion override")
                if WINDOW_FOCUS_VIDEO_ENCODER and self.has_focus:
                    vs.set_detection(False)
                    vs.set_region(0, 0, ww, wh)
                else:
                    vs.identify_video_subregion(ww, wh,
                                            self.statistics.damage_events_count,
                                            self.statistics.last_damage_events,
                                            self.statistics.last_resized,
                                            self.children)

                log("vs after identify: %s", vs)

                newrect = vs.rectangle
                if ((newrect is None) ^ (old is None)) or newrect!=old:
                    if old is None and newrect and newrect.get_geometry()==(0, 0, ww, wh):
                        #not actually changed!
                        #the region is the whole window
                        pass
                    elif newrect is None and old and old.get_geometry()==(0, 0, ww, wh):
                        #not actually changed!
                        #the region is the whole window
                        pass
                    else:
                        videolog("video subregion was %s, now %s (window size: %i,%i)", old, newrect, ww, wh)
                        self.cleanup_codecs()
                if newrect:
                    #remove this from regular refresh:
                    if old is None or old!=newrect:
                        refreshlog("identified new video region: %s", newrect)
                        #figure out if the new region had pending regular refreshes:
                        subregion_needs_refresh = any(newrect.intersects_rect(x) for x in self.refresh_regions)
                        if old:
                            #we don't bother subtracting new and old (too complicated)
                            refreshlog("scheduling refresh of old region: %s", old)
                            #this may also schedule a refresh:
                            super().add_refresh_region(old)
                        super().remove_refresh_region(newrect)
                        if not self.refresh_regions:
                            self.cancel_refresh_timer()
                        if subregion_needs_refresh:
                            vs.add_video_refresh(newrect)
                    else:
                        refreshlog("video region unchanged: %s - no change in refresh", newrect)
                elif old:
                    #add old region to regular refresh:
                    refreshlog("video region cleared, scheduling refresh of old region: %s", old)
                    self.add_refresh_region(old)
                    vs.cancel_refresh_timer()
        if force_reload:
            self.cleanup_codecs()
        self.check_pipeline_score(force_reload)

    def check_pipeline_score(self, force_reload):
        """
            Calculate pipeline scores using get_video_pipeline_options(),
            and schedule the cleanup of the current video pipeline elements
            which are no longer the best options.

            Can be called from any thread.
        """
        if self._mmap_size>0:
            scorelog("cannot score: mmap enabled")
            return

        if WINDOW_FOCUS_VIDEO_ENCODER and self.has_focus:
            scorelog("found has_focus and is true")

        if self.content_type.find("text")>=0 and self.non_video_encodings and not (WINDOW_FOCUS_VIDEO_ENCODER and self.has_focus):
            scorelog("no pipelines for 'text' content-type")
            return
        elapsed = monotonic()-self._last_pipeline_check
        max_elapsed = 0.75
        if self.is_idle:
            max_elapsed = 60
        if not force_reload and elapsed<max_elapsed:
            scorelog("cannot score: only %ims since last check (idle=%s)", 1000*elapsed, self.is_idle)
            #already checked not long ago
            return
        if not self.pixel_format:
            scorelog("cannot score: no pixel format!")
            #we need to know what pixel format we create pipelines for!
            return
        def checknovideo(*info):
            #for whatever reason, we shouldn't be using a video encoding,
            #get_best_encoding() should ensure we don't end up with one
            #it duplicates some of these same checks
            scorelog(*info)
            self.cleanup_codecs()
        #do some sanity checks to see if there is any point in finding a suitable video encoding pipeline:
        if self._sequence<2 or self.is_cancelled():
            #too early, or too late!
            return checknovideo("sequence=%s (cancelled=%s)", self._sequence, self._damage_cancelled)
        #which video encodings to evaluate:
        if self.encoding in ("auto", "grayscale"):
            if not self.common_video_encodings:
                return checknovideo("no common video encodings")
            eval_encodings = self.common_video_encodings
        else:
            if self.encoding not in self.common_video_encodings:
                return checknovideo("non-video / unsupported encoding: %s", self.encoding)
            eval_encodings = [self.encoding]
        ww, wh = self.window_dimensions
        w = ww & self.width_mask
        h = wh & self.height_mask
        vs = self.video_subregion
        if vs:
            r = vs.rectangle
            if r:
                w = r.width & self.width_mask
                h = r.height & self.width_mask
        if w<self.min_w or w>self.max_w or h<self.min_h or h>self.max_h:
            return checknovideo("out of bounds: %sx%s (min %sx%s, max %sx%s)",
                                w, h, self.min_w, self.min_h, self.max_w, self.max_h)
        #if monotonic()-self.statistics.last_resized<0.500:
        #    return checknovideo("resized just %.1f seconds ago", monotonic()-self.statistics.last_resized)

        #must copy reference to those objects because of threading races:
        ve = self._video_encoder
        csce = self._csc_encoder
        if ve is not None and ve.is_closed():
            scorelog("cannot score: video encoder %s is closed or closing", ve)
            return
        if csce is not None and csce.is_closed():
            scorelog("cannot score: csc %s is closed or closing", csce)
            return

        scores = self.get_video_pipeline_options(eval_encodings, w, h, self.pixel_format, force_reload)
        if not scores:
            scorelog("check_pipeline_score(%s) no pipeline options found!", force_reload)
            return

        scorelog("check_pipeline_score(%s) best=%s", force_reload, scores[0])
        _, _, _, csc_width, csc_height, csc_spec, enc_in_format, _, enc_width, enc_height, encoder_spec = scores[0]
        clean = False
        if csce:
            if csc_spec is None:
                scorelog("check_pipeline_score(%s) csc is no longer needed: %s",
                         force_reload, scores[0])
                clean = True
            elif csce.get_dst_format()!=enc_in_format:
                scorelog("check_pipeline_score(%s) change of csc output format from %s to %s",
                         force_reload, csce.get_dst_format(), enc_in_format)
                clean = True
            elif csce.get_src_width()!=csc_width or csce.get_src_height()!=csc_height:
                scorelog("check_pipeline_score(%s) change of csc input dimensions from %ix%i to %ix%i",
                         force_reload, csce.get_src_width(), csce.get_src_height(), csc_width, csc_height)
                clean = True
            elif csce.get_dst_width()!=enc_width or csce.get_dst_height()!=enc_height:
                scorelog("check_pipeline_score(%s) change of csc ouput dimensions from %ix%i to %ix%i",
                         force_reload, csce.get_dst_width(), csce.get_dst_height(), enc_width, enc_height)
                clean = True
        if ve is None or clean:
            pass    #nothing to check or clean
        elif ve.get_src_format()!=enc_in_format:
            scorelog("check_pipeline_score(%s) change of video input format from %s to %s",
                     force_reload, ve.get_src_format(), enc_in_format)
            clean = True
        elif ve.get_width()!=enc_width or ve.get_height()!=enc_height:
            if hasattr(ve, 'can_ignore_dim_changes') and ve.can_ignore_dim_changes():
                pass
            else:
                scorelog("check_pipeline_score(%s) change of video input dimensions from %ix%i to %ix%i",
                        force_reload, ve.get_width(), ve.get_height(), enc_width, enc_height)
                clean = True
        elif not isinstance(ve, encoder_spec.codec_class):
            scorelog("check_pipeline_score(%s) found a better video encoder class than %s: %s",
                     force_reload, type(ve), scores[0])
            clean = True
        if clean:
            self.video_context_clean()
        self._last_pipeline_check = monotonic()


    def get_video_pipeline_options(self, encodings, width, height, src_format, force_refresh=False):
        """
            Given a picture format (width, height and src pixel format),
            we find all the pipeline options that will allow us to compress
            it using the given encodings.
            First, we try with direct encoders (for those that support the
            source pixel format natively), then we try all the combinations
            using csc encoders to convert to an intermediary format.
            Each solution is rated and we return all of them in descending
            score (best solution comes first).
            Because this function is expensive to call, we cache the results.
            This allows it to run more often from the timer thread.

            Can be called from any thread.
        """
        if not force_refresh and (monotonic()-self.last_pipeline_time<1) and self.last_pipeline_params and self.last_pipeline_params==(encodings, width, height, src_format):
            #keep existing scores
            scorelog("get_video_pipeline_options%s using cached values from %ims ago",
                     (encodings, width, height, src_format, force_refresh), 1000.0*(monotonic()-self.last_pipeline_time))
            return self.last_pipeline_scores
        scorelog("get_video_pipeline_options%s last params=%s, full_csc_modes=%s",
                 (encodings, width, height, src_format, force_refresh), self.last_pipeline_params, self.full_csc_modes)

        vh = self.video_helper
        if vh is None:
            return ()       #closing down

        target_q = int(self._current_quality)
        min_q = self._fixed_min_quality
        target_s = int(self._current_speed)
        min_s = self._fixed_min_speed
        #tune quality target for (non-)video region:
        vr = self.matches_video_subregion(width, height)
        if vr and target_q<100:
            if self.subregion_is_video():
                #lower quality a bit more:
                fps = self.video_subregion.fps
                f = min(90, 2*fps)
                target_q = max(min_q, int(target_q*(100-f)//100))
                scorelog("lowering quality target %i by %i%% for video %s (fps=%i)", target_q, f, vr, fps)
            else:
                #not the video region, or not really video content, raise quality a bit:
                target_q = int(sqrt(target_q/100.0)*100)
                scorelog("raising quality for video encoding of non-video region")
        scorelog("get_video_pipeline_options%s speed: %s (min %s), quality: %s (min %s)",
                 (encodings, width, height, src_format), target_s, min_s, target_q, min_q)
        vmw, vmh = self.video_max_size
        ffps = self.get_video_fps(width, height)
        scores = []
        for encoding in encodings:
            #these are the CSC modes the client can handle for this encoding:
            #we must check that the output csc mode for each encoder is one of those
            supported_csc_modes = self.full_csc_modes.strtupleget(encoding)
            if not supported_csc_modes:
                scorelog(" no supported csc modes for %s", encoding)
                continue
            encoder_specs = vh.get_encoder_specs(encoding)
            if not encoder_specs:
                scorelog(" no encoder specs for %s", encoding)
                continue
            #if not specified as an encoding option,
            #discount encodings further down the list of preferred encodings:
            #(ie: prefer h264 to vp9)
            try:
                encoding_score_delta = len(PREFERRED_ENCODING_ORDER)//2-PREFERRED_ENCODING_ORDER.index(encoding)
            except ValueError:
                encoding_score_delta = 0
            encoding_score_delta = self.encoding_options.get("%s.score-delta" % encoding, encoding_score_delta)
            def add_scores(info, csc_spec, enc_in_format):
                #find encoders that take 'enc_in_format' as input:
                colorspace_specs = encoder_specs.get(enc_in_format)
                if not colorspace_specs:
                    scorelog(" no matching colorspace specs for %s - %s", enc_in_format, info)
                    return
                #log("%s encoding from %s: %s", info, pixel_format, colorspace_specs)
                for encoder_spec in colorspace_specs:
                    #ensure that the output of the encoder can be processed by the client:
                    matches = tuple(x for x in encoder_spec.output_colorspaces if x in supported_csc_modes)
                    if not matches or self.is_cancelled():
                        scorelog(" no matches for %s (%s and %s) - %s",
                                 encoder_spec, encoder_spec.output_colorspaces, supported_csc_modes, info)
                        continue
                    max_w = min(encoder_spec.max_w, vmw)
                    max_h = min(encoder_spec.max_h, vmh)
                    if (csc_spec and csc_spec.can_scale) or encoder_spec.can_scale:
                        scaling = self.calculate_scaling(width, height, max_w, max_h)
                    else:
                        scaling = (1, 1)
                    score_delta = encoding_score_delta
                    if self.is_shadow and enc_in_format in ("NV12", "YUV420P", "YUV422P") and scaling==(1, 1):
                        #avoid subsampling with shadow servers:
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
            if not FORCE_CSC or src_format==FORCE_CSC_MODE:
                add_scores("direct (no csc)", None, src_format)

            #now add those that require a csc step:
            csc_specs = vh.get_csc_specs(src_format)
            if csc_specs:
                #log("%s can also be converted to %s using %s",
                #    pixel_format, [x[0] for x in csc_specs], set(x[1] for x in csc_specs))
                #we have csc module(s) that can get us from pixel_format to out_csc:
                for out_csc, l in csc_specs.items():
                    if not bool(FORCE_CSC_MODE) or FORCE_CSC_MODE==out_csc:
                        for csc_spec in l:
                            add_scores("via %s" % out_csc, csc_spec, out_csc)
        s = sorted(scores, key=lambda x : -x[0])
        scorelog("get_video_pipeline_options%s scores=%s", (encodings, width, height, src_format), s)
        if self.is_cancelled():
            self.last_pipeline_params = None
            self.last_pipeline_scores = ()
        else:
            self.last_pipeline_params = (encodings, width, height, src_format)
            self.last_pipeline_scores = s
        self.last_pipeline_time = monotonic()
        return s


    def get_video_fps(self, width, height):
        mvsub = self.matches_video_subregion(width, height)
        vs = self.video_subregion
        if vs and mvsub:
            #matches the video subregion,
            #for which we have the fps already:
            return self.video_subregion.fps
        return self.do_get_video_fps(width, height)

    def do_get_video_fps(self, width, height):
        now = monotonic()
        #calculate full frames per second (measured in pixels vs window size):
        stime = now-5           #only look at the last 5 seconds max
        lde = tuple((t,w,h) for t,_,_,w,h in tuple(self.statistics.last_damage_events) if t>stime)
        if len(lde)>=10:
            #the first event's first element is the oldest event time:
            otime = lde[0][0]
            if now>otime:
                pixels = sum(w*h for _,w,h in lde)
                return int(pixels/(width*height)/(now - otime))
        return 0

    def calculate_scaling(self, width, height, max_w=4096, max_h=4096):
        if width==0 or height==0:
            return (1, 1)
        q = self._current_quality
        s = self._current_speed
        now = monotonic()
        crs = None
        if DOWNSCALE:
            crs = self.client_render_size
        def get_min_required_scaling(default_value=(1, 1)):
            mw = max_w
            mh = max_h
            if crs:
                #if the client is going to downscale things anyway,
                #then there is no need to send at a higher resolution than that:
                crsw, crsh = crs
                if crsw<max_w:
                    mw = crsw
                if crsh<max_h:
                    mh = crsh
            if width<=mw and height<=mh:
                return default_value    #no problem
            #most encoders can't deal with that!
            #sort them from smallest scaling to highest:
            sopts = {}
            for num, den in SCALING_OPTIONS:
                sopts[num/den] = (num, den)
            for ratio in reversed(sorted(sopts.keys())):
                num, den = sopts[ratio]
                if num==1 and den==1:
                    continue
                if width*num/den<=mw and height*num/den<=mh:
                    return (num, den)
            raise Exception("BUG: failed to find a scaling value for window size %sx%s" % (width, height))
        if not SCALING:
            if (width>max_w or height>max_h) and first_time("scaling-required"):
                if not SCALING:
                    scalinglog.warn("Warning: video scaling is disabled")
                else:
                    scalinglog.warn("Warning: video scaling is not supported by the client")
                scalinglog.warn(" but the video size is too large: %ix%i", width, height)
                scalinglog.warn(" the maximum supported is %ix%i", max_w, max_h)
            scaling = 1, 1
        elif SCALING_HARDCODED:
            scaling = get_min_required_scaling(tuple(SCALING_HARDCODED))
            scalinglog("using hardcoded scaling value: %s", scaling)
        elif self.scaling_control==0:
            #video-scaling is disabled, only use scaling if we really have to:
            scaling = get_min_required_scaling()
        elif self.scaling:
            #honour value requested for this window, unless we must scale more:
            scaling = get_min_required_scaling(self.scaling)
        elif (now-self.statistics.last_resized<0.5) or (now-self.last_scroll_time)<5:
            #don't change during window resize or scrolling:
            scaling = get_min_required_scaling(self.actual_scaling)
        elif self.statistics.damage_events_count<=50:
            #not enough data yet:
            scaling = get_min_required_scaling()
        else:
            #use heuristics to choose the best scaling ratio:
            mvsub = self.matches_video_subregion(width, height)
            video = self.content_type.find("video")>=0 or (bool(mvsub) and self.subregion_is_video())
            ffps = self.get_video_fps(width, height)

            if self.scaling_control is None:
                #None==auto mode, derive from quality and speed only:
                #increase threshold when handling video
                q_noscaling = 65 + int(video)*30
                if q>=q_noscaling or ffps==0:
                    scaling = get_min_required_scaling()
                else:
                    pps = ffps*width*height                 #Pixels/s
                    if self.bandwidth_limit>0:
                        #assume video compresses pixel data by ~95% (size is 20 times smaller)
                        #(and convert to bytes per second)
                        #ie: 240p minimum target
                        target = max(SCALING_MIN_PPS, self.bandwidth_limit//8*20)
                    else:
                        target = SCALING_PPS_TARGET             #ie: 1080p
                    if self.is_shadow:
                        #shadow servers look ugly when scaled:
                        target *= 16
                    elif self.content_type.find("text")>=0:
                        #try to avoid scaling:
                        target *= 4
                    elif not video:
                        #downscale non-video content less:
                        target *= 2
                    if self.image_depth==30:
                        #high bit depth is normally used for high quality
                        target *= 10
                    #high quality means less scaling:
                    target = target * (10+max(0, q-video*30))**2 // 50**2
                    #high speed means more scaling:
                    target = target * 60**2 // (s+20)**2
                    sscaling = {}
                    mrs = get_min_required_scaling()
                    min_ratio = mrs[0]/mrs[1]
                    denom_mult = 1
                    if crs:
                        #if the client will be downscaling to paint the window
                        #use this downscaling as minimum value:
                        crsw, crsh = crs
                        if crsw>0 and crsh>0 and width-crsw>DOWNSCALE_THRESHOLD and height-crsh>DOWNSCALE_THRESHOLD:
                            if width/crsw>height/crsh:
                                denom_mult = width/crsw
                            else:
                                denom_mult = height/crsh
                    for num, denom in SCALING_OPTIONS:
                        if denom_mult>1 and 0.5<(num/denom)<1:
                            #skip ratios like 2/3
                            #since we want a whole multiple of the client scaling value
                            continue
                        #scaled pixels per second value:
                        denom *= denom_mult
                        spps = pps*(num**2)/(denom**2)
                        ratio = target/spps
                        #ideal ratio is 1, measure distance from 1:
                        score = int(abs(1-ratio)*100)
                        if self.actual_scaling and self.actual_scaling==(num, denom) and (num!=1 or denom!=1):
                            #if we are already downscaling,
                            #try to stick to the same value longer:
                            #give it a score boost (lowest score wins):
                            score = int(score/1.5)
                        if num/denom>min_ratio:
                            #higher than minimum, should not be used unless we have no choice:
                            score = int(score*100)
                        sscaling[score] = (num, denom)
                    scalinglog("calculate_scaling%s wid=%i, pps=%s, target=%s, denom_mult=%s, scores=%s",
                               (width, height, max_w, max_h), self.wid, pps, target, denom_mult, sscaling)
                    if sscaling:
                        highscore = sorted(sscaling.keys())[0]
                        scaling = sscaling[highscore]
                    else:
                        scaling = get_min_required_scaling()
            else:
                #calculate scaling based on the "video-scaling" command line option,
                #which is named "scaling_control" here.
                #(from 1 to 100, from least to most aggressive)
                if mvsub:
                    if video:
                        #enable scaling more aggressively
                        sc = (self.scaling_control+50)*2
                    else:
                        sc = (self.scaling_control+25)
                else:
                    #not the video region, so much less aggressive scaling:
                    sc = max(0, (self.scaling_control-50)//2)

                #if scaling_control is high (scaling_control=100 -> er=2)
                #then we will match the heuristics more quickly:
                er = sc/50.0
                if self.actual_scaling!=(1, 1):
                    #if we are already downscaling, boost so we will stick with it a bit longer:
                    #more so if we are downscaling a lot (1/3 -> er=1.5 + ..)
                    er += (0.5 * self.actual_scaling[1] / self.actual_scaling[0])
                qs = s>(q-er*10) and q<(50+er*15)
                #scalinglog("calculate_scaling: er=%.1f, qs=%s, ffps=%s", er, qs, ffps)
                if self.fullscreen and (qs or ffps>=max(2, 10-er*3)):
                    scaling = 1,3
                elif self.maximized and (qs or ffps>=max(2, 10-er*3)):
                    scaling = 1,2
                elif width*height>=(2560-er*768)*1600 and (qs or ffps>=max(4, 25-er*5)):
                    scaling = 1,3
                elif width*height>=(1920-er*384)*1200 and (qs or ffps>=max(5, 30-er*10)):
                    scaling = 2,3
                elif width*height>=(1200-er*256)*1024 and (qs or ffps>=max(10, 50-er*15)):
                    scaling = 2,3
                else:
                    scaling = 1,1
                if scaling:
                    scalinglog("calculate_scaling value %s enabled by heuristics for %ix%i q=%i, s=%i, er=%.1f, qs=%s, ffps=%i, scaling-control(%i)=%i",
                               scaling, width, height, q, s, er, qs, ffps, self.scaling_control, sc)
        #sanity checks:
        if scaling is None:
            scaling = 1, 1
        v, u = scaling
        if v/u>1.0:
            #never upscale before encoding!
            scaling = 1, 1
        elif v/u<0.1:
            #don't downscale more than 10 times! (for each dimension - that's 100 times!)
            scaling = 1, 10
        scalinglog("calculate_scaling%s=%s (q=%s, s=%s, scaling_control=%s)",
                   (width, height, max_w, max_h), scaling, q, s, self.scaling_control)
        return scaling


    def check_pipeline(self, encoding, width, height, src_format):
        """
            Checks that the current pipeline is still valid
            for the given input. If not, close it and make a new one.

            Runs in the 'encode' thread.
        """
        if encoding in ("auto", "grayscale"):
            encodings = self.common_video_encodings
        else:
            encodings = [encoding]
        if self.do_check_pipeline(encodings, width, height, src_format):
            return True  #OK!

        videolog("check_pipeline%s setting up a new pipeline as check failed - encodings=%s",
                 (encoding, width, height, src_format), encodings)
        #cleanup existing one if needed:
        self.csc_clean(self._csc_encoder)
        self.ve_clean(self._video_encoder)
        #and make a new one:
        w = width & self.width_mask
        h = height & self.height_mask
        scores = self.get_video_pipeline_options(encodings, w, h, src_format)
        return self.setup_pipeline(scores, width, height, src_format)

    def do_check_pipeline(self, encodings, width, height, src_format):
        """
            Checks that the current pipeline is still valid
            for the given input.

            Runs in the 'encode' thread.
        """
        #use aliases, not because of threading (we are in the encode thread anyway)
        #but to make the code less dense:
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
            if csce.get_src_format()!=src_format:
                csclog("do_check_pipeline csc: switching source format from %s to %s",
                                    csce.get_src_format(), src_format)
                return False
            if csce.get_src_width()!=csc_width or csce.get_src_height()!=csc_height:
                csclog("do_check_pipeline csc: window dimensions have changed from %sx%s to %sx%s, csc info=%s",
                                    csce.get_src_width(), csce.get_src_height(), csc_width, csc_height, csce.get_info())
                return False
            if csce.get_dst_format()!=ve.get_src_format():
                csclog.error("Error: CSC intermediate format mismatch,")
                csclog.error(" %s outputs %s but %s expects %sw",
                             csce.get_type(), csce.get_dst_format(), ve.get_type(), ve.get_src_format())
                csclog.error(" %s:", csce)
                print_nested_dict(csce.get_info(), "  ", print_fn=csclog.error)
                csclog.error(" %s:", ve)
                print_nested_dict(ve.get_info(), "  ", print_fn=csclog.error)
                return False

            #encoder will take its input from csc:
            encoder_src_width = csce.get_dst_width()
            encoder_src_height = csce.get_dst_height()
        else:
            #direct to video encoder without csc:
            encoder_src_width = width & self.width_mask
            encoder_src_height = height & self.height_mask

            if ve.get_src_format()!=src_format:
                videolog("do_check_pipeline video: invalid source format %s, expected %s",
                                                ve.get_src_format(), src_format)
                return False

        if ve.get_encoding() not in encodings:
            videolog("do_check_pipeline video: invalid encoding %s, expected one of: %s",
                                            ve.get_encoding(), csv(encodings))
            return False
        if ve.get_width()!=encoder_src_width or ve.get_height()!=encoder_src_height:
            if hasattr(ve, 'can_ignore_dim_changes') and ve.can_ignore_dim_changes():
                pass
            else: 
                videolog("do_check_pipeline video: window dimensions have changed from %sx%s to %sx%s",
                                                ve.get_width(), ve.get_height(), encoder_src_width, encoder_src_height)
                return False
        return True


    def setup_pipeline(self, scores, width, height, src_format):
        """
            Given a list of pipeline options ordered by their score
            and an input format (width, height and source pixel format),
            we try to create a working video pipeline (csc + encoder),
            trying each option until one succeeds.
            (some may not be suitable because of scaling?)

            Runs in the 'encode' thread.
        """
        assert width>0 and height>0, "invalid dimensions: %sx%s" % (width, height)
        start = monotonic()
        if not scores:
            if not self.is_cancelled():
                videolog.error("Error: no video pipeline options found for %s %i-bit at %ix%i",
                               src_format, self.image_depth, width, height)
            return False
        videolog("setup_pipeline%s", (scores, width, height, src_format))
        for option in scores:
            try:
                videolog("setup_pipeline: trying %s", option)
                if self.setup_pipeline_option(width, height, src_format, *option):
                    #success!
                    return True
                #skip cleanup below
                continue
            except TransientCodecException as e:
                if self.is_cancelled():
                    return False
                videolog.warn("Warning: setup_pipeline failed for")
                videolog.warn(" %s:", option)
                videolog.warn(" %s", e)
                del e
            except Exception:
                if self.is_cancelled():
                    return False
                videolog.warn("Warning: failed to setup video pipeline %s", option, exc_info=True)
            #we're here because an exception occurred, cleanup before trying again:
            self.csc_clean(self._csc_encoder)
            self.ve_clean(self._video_encoder)
        end = monotonic()
        if not self.is_cancelled():
            videolog("setup_pipeline(..) failed! took %.2fms", (end-start)*1000.0)
            videolog.error("Error: failed to setup a video pipeline for %s at %ix%i", src_format, width, height)
            videolog.error(" tried the following option%s", engs(scores))
            for option in scores:
                videolog.error(" %s", option)
        return False

    def setup_pipeline_option(self, width, height, src_format,
                      _score, scaling, _csc_scaling, csc_width, csc_height, csc_spec,
                      enc_in_format, encoder_scaling, enc_width, enc_height, encoder_spec):
        options = typedict(self.encoding_options)
        self.assign_sq_options(options)
        min_w = 1
        min_h = 1
        max_w = 16384
        max_h = 16384
        if csc_spec:
            #TODO: no need to OR encoder mask if we are scaling...
            width_mask = csc_spec.width_mask & encoder_spec.width_mask
            height_mask = csc_spec.height_mask & encoder_spec.height_mask
            min_w = max(min_w, csc_spec.min_w)
            min_h = max(min_h, csc_spec.min_h)
            max_w = min(max_w, csc_spec.max_w)
            max_h = min(max_h, csc_spec.max_h)
            #csc speed is not very important compared to encoding speed,
            #so make sure it never degrades quality
            speed = options.get("speed", self._current_speed)
            quality = options.get("quality", self._current_quality)
            csc_speed = max(1, min(speed, 100-quality/2.0))
            csc_options = typedict({"speed" : csc_speed})
            csc_start = monotonic()
            csce = csc_spec.make_instance()
            csce.init_context(csc_width, csc_height, src_format,
                                   enc_width, enc_height, enc_in_format, csc_options)
            csc_end = monotonic()
            csclog("setup_pipeline: csc=%s, info=%s, setup took %.2fms",
                  csce, csce.get_info(), (csc_end-csc_start)*1000.0)
        else:
            csce = None
            #use the encoder's mask directly since that's all we have to worry about!
            width_mask = encoder_spec.width_mask
            height_mask = encoder_spec.height_mask
            #restrict limits:
            min_w = max(min_w, encoder_spec.min_w)
            min_h = max(min_h, encoder_spec.min_h)
            max_w = min(max_w, encoder_spec.max_w)
            max_h = min(max_h, encoder_spec.max_h)
            if encoder_scaling!=(1,1) and not encoder_spec.can_scale:
                videolog("scaling is now enabled, so skipping %s", encoder_spec)
                return False
        self._csc_encoder = csce
        enc_start = monotonic()
        #FIXME: filter dst_formats to only contain formats the encoder knows about?
        dst_formats = self.full_csc_modes.strtupleget(encoder_spec.encoding)
        ve = encoder_spec.make_instance()
        options.update(self.get_video_encoder_options(encoder_spec.encoding, width, height))
        if self.encoding=="grayscale":
            options["grayscale"] = True
        if encoder_scaling!=(1, 1):
            n, d = encoder_scaling
            options["scaling"] = encoder_scaling
            options["scaled-width"] = enc_width*n//d
            options["scaled-height"] = enc_height*n//d
        options["dst-formats"] = dst_formats

        ve.init_context(encoder_spec.encoding, enc_width, enc_height, enc_in_format, options)
        #record new actual limits:
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
                csce, ve, ve.get_info(), (enc_end-enc_start)*1000.0)
        scalinglog("setup_pipeline: scaling=%s, encoder_scaling=%s", scaling, encoder_scaling)
        return True

    def get_video_encoder_options(self, encoding, width, height):
        #tweaks for "real" video:
        opts = {"cuda-device-context" : self.cuda_device_context}
        if not self._fixed_quality and not self._fixed_speed and self._fixed_min_quality<50:
            #only allow bandwidth to drive video encoders
            #when we don't have strict quality or speed requirements:
            opts["bandwidth-limit"] = self.bandwidth_limit
        if self.content_type:
            content_type = self.content_type
        elif self.matches_video_subregion(width, height) and self.subregion_is_video() and (monotonic()-self.last_scroll_time)>5:
            content_type = "video"
        else:
            content_type = None
        if content_type:
            opts["content-type"] = content_type
            if content_type=="video":
                if B_FRAMES and (encoding in self.supports_video_b_frames):
                    opts["b-frames"] = True
        return opts


    def get_fail_cb(self, packet):
        coding = packet[6]
        if coding in self.common_video_encodings:
            return None
        return super().get_fail_cb(packet)


    def make_draw_packet(self, x, y, w, h, coding, data, outstride, client_options, options):
        #overriden so we can invalidate the scroll data:
        #log.error("make_draw_packet%s", (x, y, w, h, coding, "..", outstride, client_options)
        packet = super().make_draw_packet(x, y, w, h, coding, data, outstride, client_options, options)
        sd = self.scroll_data
        if sd and not options.get("scroll"):
            if client_options.get("scaled_size") or client_options.get("quality", 100)<20:
                #don't scroll very low quality content, better to refresh it
                scrolllog("low quality %s update, invalidating all scroll data (scaled_size=%s, quality=%s)",
                          coding, client_options.get("scaled_size"), client_options.get("quality", 100))
                self.do_free_scroll_data()
            else:
                sd.invalidate(x, y, w, h)
        return packet


    def free_scroll_data(self):
        self.call_in_encode_thread(False, self.do_free_scroll_data)

    def do_free_scroll_data(self):
        scrolllog("do_free_scroll_data()")
        sd = self.scroll_data
        if sd:
            self.scroll_data = None
            sd.free()

    def may_use_scrolling(self, image, options):
        scrolllog("may_use_scrolling(%s, %s) supports_scrolling=%s, has_pixels=%s, content_type=%s, non-video encodings=%s",
                  image, options, self.supports_scrolling, image.has_pixels, self.content_type, self.non_video_encodings)

        if WINDOW_FOCUS_VIDEO_ENCODER and self.has_focus:
            scrolllog("no scrolling: has focus")
            return False
        if self._mmap_size>0 and self.encoding!="scroll":
            scrolllog("no scrolling: using mmap")
            return False
        if not self.supports_scrolling:
            scrolllog("no scrolling: not supported")
            return False
        if options.get("auto_refresh"):
            scrolllog("no scrolling: auto-refresh")
            return False
        #don't download the pixels if we have a GPU buffer,
        #since that means we're likely to be able to compress on the GPU too with NVENC:
        if not image.has_pixels():
            return False
        if self.content_type.find("video")>=0 or not self.non_video_encodings:
            scrolllog("no scrolling: content is video")
            return False
        w = image.get_width()
        h = image.get_height()
        if w<MIN_SCROLL_IMAGE_SIZE or h<MIN_SCROLL_IMAGE_SIZE:
            scrolllog("no scrolling: image size %ix%i is too small, minimum is %ix%i",
                      w, h, MIN_SCROLL_IMAGE_SIZE, MIN_SCROLL_IMAGE_SIZE)
            return False
        scroll_data = self.scroll_data
        if self.b_frame_flush_timer and scroll_data:
            scrolllog("no scrolling: b_frame_flush_timer=%s", self.b_frame_flush_timer)
            self.do_free_scroll_data()
            return False
        speed = options.get("speed", self._current_speed)
        if speed>=50 or self.scroll_preference<100:
            now = monotonic()
            scroll_event_elapsed = now-self.last_scroll_event
            scroll_encode_elapsed = now-self.last_scroll_time
            #how long since we last successfully used scroll encoding,
            #or seen a scroll mouse wheel event:
            scroll_elapsed = min(scroll_event_elapsed, scroll_encode_elapsed)
            max_time = 1+min((100-speed)/10, self.scroll_preference/20)
            if scroll_elapsed>=max_time:
                scrolllog("no scrolling: elapsed=%.1f, max time=%.1f", scroll_elapsed, max_time)
                return False
        return self.do_scroll_encode(image, options, self.scroll_min_percent)

    def scroll_encode(self, coding, image, options):
        self.do_scroll_encode(image, options, 0)
        #do_scroll_encode() sends the packets
        #so there is nothing to return:
        return None

    def do_scroll_encode(self, image, options, min_percent=0):
        x = image.get_target_x()
        y = image.get_target_y()
        w = image.get_width()
        h = image.get_height()
        scroll_data = self.scroll_data
        if options.get("scroll") is True:
            scrolllog("no scrolling: detection has already been used on this image")
            return False
        if w>=32000 or h>=32000:
            scrolllog("no scrolling: the image is too large, %ix%i", w, h)
            return False
        try:
            start = monotonic()
            if not scroll_data:
                scroll_data = ScrollData()
                self.scroll_data = scroll_data
                scrolllog("new scroll data: %s", scroll_data)
            if not image.is_thread_safe():
                #what we really want is to check that the frame has been frozen,
                #so it doesn't get modified whilst we checksum or encode it,
                #the "thread_safe" flag gives us that for the X11 case in most cases,
                #(the other servers already copy the pixels from the "real" screen buffer)
                #TODO: use a separate flag? (ximage uses this flag to know if it is safe
                # to call image.free from another thread - which is theoretically more restrictive)
                newstride = roundup(image.get_width()*image.get_bytesperpixel(), 4)
                image.restride(newstride)
                stride = image.get_rowstride()
            bpp = image.get_bytesperpixel()
            pixels = image.get_pixels()
            if not pixels:
                return False
            stride = image.get_rowstride()
            scroll_data.update(pixels, x, y, w, h, stride, bpp)
            max_distance = min(1000, (100-min_percent)*h//100)
            scroll_data.calculate(max_distance)
            #marker telling us not to invalidate the scroll data from here on:
            options["scroll"] = True
            if min_percent>0:
                max_zones = 20
                scroll, count = scroll_data.get_best_match()
                end = monotonic()
                match_pct = int(100*count/h)
                scrolllog("best scroll guess took %ims, matches %i%% of %i lines: %s",
                          (end-start)*1000, match_pct, h, scroll)
            else:
                max_zones = 50
                match_pct = min_percent
            #if enough scrolling is detected, use scroll encoding for this frame:
            if match_pct>=min_percent:
                self.encode_scrolling(scroll_data, image, options, match_pct, max_zones)
                return True
        except Exception:
            scrolllog("do_scroll_encode(%s, %s)", image, options, exc_info=True)
            if not self.is_cancelled():
                scrolllog.error("Error during scrolling detection")
                scrolllog.error(" with image=%s, options=%s", image, options, exc_info=True)
            #make sure we start again from scratch next time:
            self.do_free_scroll_data()
        return False

    def encode_scrolling(self, scroll_data, image, options, match_pct, max_zones=20):
        #generate all the packets for this screen update
        #using 'scroll' encoding and picture encodings for the other regions
        start = monotonic()
        options.pop("av-sync", None)
        #tells make_data_packet not to invalidate the scroll data:
        ww, wh = self.window_dimensions
        scrolllog("encode_scrolling([], %s, %s, %i, %i) window-dimensions=%s",
                  image, options, match_pct, max_zones, (ww, wh))
        x = image.get_target_x()
        y = image.get_target_y()
        w = image.get_width()
        h = image.get_height()
        raw_scroll, non_scroll = {}, {0 : h}
        if x+w>ww or y+h>wh:
            #window may have been resized
            pass
        else:
            v = scroll_data.get_scroll_values()
            if v:
                raw_scroll, non_scroll = v
                if len(raw_scroll)>=max_zones or len(non_scroll)>=max_zones:
                    #avoid fragmentation, which is too costly
                    #(too many packets, too many loops through the encoder code)
                    scrolllog("too many items: %i scrolls, %i non-scrolls - sending just one image instead",
                              len(raw_scroll), len(non_scroll))
                    raw_scroll = {}
                    non_scroll = {0 : h}
        scrolllog(" will send scroll data=%s, non-scroll=%s", raw_scroll, non_scroll)
        flush = len(non_scroll)
        #convert to a screen rectangle list for the client:
        scrolls = []
        for scroll, line_defs in raw_scroll.items():
            if scroll==0:
                continue
            for line, count in line_defs.items():
                assert y+line+scroll>=0, "cannot scroll rectangle by %i lines from %i+%i" % (scroll, y, line)
                assert y+line+scroll<=wh, "cannot scroll rectangle %i high by %i lines from %i+%i (window height is %i)" % (count, scroll, y, line, wh)
                scrolls.append((x, y+line, w, count, 0, scroll))
        del raw_scroll
        #send the scrolls if we have any
        #(zero change scrolls have been removed - so maybe there are none)
        if scrolls:
            client_options = {}
            if flush>0:
                client_options["flush"] = flush
            coding = "scroll"
            end = monotonic()
            packet = self.make_draw_packet(x, y, w, h,
                                           coding, LargeStructure(coding, scrolls), 0, client_options, options)
            self.queue_damage_packet(packet, 0, 0, options)
            compresslog(COMPRESS_SCROLL_FMT,
                 (end-start)*1000.0, w, h, x, y, self.wid, coding,
                 len(scrolls), w*h*4/1024,
                 self._damage_packet_sequence, client_options, options)
        del scrolls
        #send the rest as rectangles:
        if non_scroll:
            #boost quality a bit, because lossless saves refreshing,
            #more so if we have a high match percentage (less to send):
            if self._fixed_quality<=0:
                quality = options.get("quality", self._current_quality)
                quality = min(100, quality + max(60, match_pct)//2)
                options["quality"] = quality
            nsstart = monotonic()
            client_options = options.copy()
            for sy, sh in non_scroll.items():
                substart = monotonic()
                sub = image.get_sub_image(0, sy, w, sh)
                encoding = self.get_best_nonvideo_encoding(w, sh, options)
                assert encoding, "no nonvideo encoding found for %ix%i screen update" % (w, sh)
                encode_fn = self._encoders[encoding]
                ret = encode_fn(encoding, sub, options)
                self.free_image_wrapper(sub)
                if not ret:
                    scrolllog("no result for %s encoding of %s with options %s", encoding, sub, options)
                    #cancelled?
                    return None
                coding, data, client_options, outw, outh, outstride, _ = ret
                assert data
                flush -= 1
                if flush>0:
                    client_options["flush"] = flush
                #if SAVE_TO_FILE:
                #    #hard-coded for BGRA!
                #    from xpra.os_util import memoryview_to_bytes
                #    from PIL import Image
                #    im = Image.frombuffer("RGBA", (w, sh), memoryview_to_bytes(sub.get_pixels()),
                #                          "raw", "BGRA", sub.get_rowstride(), 1)
                #    filename = "./scroll-%i-%i.png" % (self._sequence, len(non_scroll)-flush)
                #    im.save(filename, "png")
                #    log.info("saved scroll y=%i h=%i to %s", sy, sh, filename)
                packet = self.make_draw_packet(sub.get_target_x(), sub.get_target_y(), outw, outh,
                                               coding, data, outstride, client_options, options)
                self.queue_damage_packet(packet, 0, 0, options)
                psize = w*sh*4
                csize = len(data)
                compresslog(COMPRESS_FMT,
                     (monotonic()-substart)*1000.0, w, sh, x+0, y+sy, self.wid, coding,
                     100.0*csize/psize, psize/1024, csize/1024,
                     self._damage_packet_sequence, client_options, options)
            scrolllog("non-scroll encoding using %s (quality=%i, speed=%i) took %ims for %i rectangles",
                      encoding, self._current_quality, self._current_speed, (monotonic()-nsstart)*1000, len(non_scroll))
        else:
            scrolllog("no non_scroll areas")
        assert flush==0, "flush counter mismatch: %s" % flush
        self.last_scroll_time = monotonic()
        scrolllog("scroll encoding total time: %ims", (self.last_scroll_time-start)*1000)
        self.free_image_wrapper(image)


    def do_schedule_auto_refresh(self, encoding, data, region, client_options, options):
        #for scroll encoding, data is a LargeStructure wrapper:
        if encoding=="scroll" and hasattr(data, "data"):
            if not self.refresh_regions:
                return
            #check if any pending refreshes intersect the area containing the scroll data:
            if not any(region.intersects_rect(r) for r in self.refresh_regions):
                #nothing to do!
                return
            pixels_added = 0
            for x, y, w, h, dx, dy in data.data:
                #the region that moved
                src_rect = rectangle(x, y, w, h)
                for rect in self.refresh_regions:
                    inter = src_rect.intersection_rect(rect)
                    if inter:
                        dst_rect = rectangle(inter.x+dx, inter.y+dy, inter.width, inter.height)
                        pixels_added += self.add_refresh_region(dst_rect)
            if pixels_added:
                #if we end up with too many rectangles,
                #bail out and simplify:
                if len(self.refresh_regions)>=200:
                    self.refresh_regions = [merge_all(self.refresh_regions)]
                refreshlog("updated refresh regions with scroll data: %i pixels added", pixels_added)
                refreshlog(" refresh_regions=%s", self.refresh_regions)
            #we don't change any of the refresh scheduling
            #if there are non-scroll packets following this one, they will
            #and if not then we're OK anyway
            return
        super().do_schedule_auto_refresh(encoding, data, region, client_options, options)


    def video_fallback(self, image, options, warn=False):
        if warn and first_time("non-video-%i" % self.wid):
            videolog.warn("Warning: using non-video fallback encoding")
            videolog.warn(" for %s of window %s" % (image, self.wid))
        w = image.get_width()
        h = image.get_height()
        encoding = self.do_get_auto_encoding(w, h, options, None, self.non_video_encodings)
        if not encoding:
            return None
        encode_fn = self._encoders[encoding]
        return encode_fn(encoding, image, options)

    def video_encode(self, encoding, image, options : dict):
        try:
            return self.do_video_encode(encoding, image, options)
        finally:
            self.free_image_wrapper(image)

    def do_video_encode(self, encoding, image, options : dict):
        """
            This method is used by make_data_packet to encode frames using video encoders.
            Video encoders only deal with fixed dimensions,
            so we must clean and reinitialize the encoder if the window dimensions
            has changed.

            Runs in the 'encode' thread.
        """
        log("do_video_encode(%s, %s, %s)", encoding, image, options)
        x, y, w, h = image.get_geometry()[:4]
        src_format = image.get_pixel_format()
        stride = image.get_rowstride()
        if self.pixel_format!=src_format:
            if self.is_cancelled():
                return None
            videolog.warn("Warning: image pixel format unexpectedly changed from %s to %s",
                          self.pixel_format, src_format)
            self.pixel_format = src_format

        if SAVE_VIDEO_FRAMES:
            from xpra.os_util import memoryview_to_bytes
            from PIL import Image
            img_data = image.get_pixels()
            rgb_format = image.get_pixel_format() #ie: BGRA
            rgba_format = rgb_format.replace("BGRX", "BGRA")
            img = Image.frombuffer("RGBA", (w, h), memoryview_to_bytes(img_data), "raw", rgba_format, stride)
            kwargs = {}
            if SAVE_VIDEO_FRAMES=="jpeg":
                kwargs = {
                          "quality"     : 0,
                          "optimize"    : False,
                          }
            t = monotonic()
            tstr = time.strftime("%H-%M-%S", time.localtime(t))
            filename = "W%i-VDO-%s.%03i.%s" % (self.wid, tstr, (t*1000)%1000, SAVE_VIDEO_FRAMES)
            if SAVE_VIDEO_PATH:
                filename = os.path.join(SAVE_VIDEO_PATH, filename)
            videolog("do_video_encode: saving %4ix%-4i pixels, %7i bytes to %s", w, h, (stride*h), filename)
            img.save(filename, SAVE_VIDEO_FRAMES, **kwargs)

        if self.may_use_scrolling(image, options):
            #scroll encoding has dealt with this image
            return None

        if not self.common_video_encodings:
            #we have to send using a non-video encoding as that's all we have!
            return self.video_fallback(image, options)
        if self.image_depth not in (24, 30, 32):
            #this image depth is not supported for video
            return self.video_fallback(image, options)

        if self.encoding=="grayscale":
            from xpra.codecs.csc_libyuv.colorspace_converter import argb_to_gray    #@UnresolvedImport pylint: disable=import-outside-toplevel
            image = argb_to_gray(image)

        vh = self.video_helper
        if vh is None:
            return None         #shortcut when closing down
        if not self.check_pipeline(encoding, w, h, src_format):
            if self.is_cancelled():
                return None
            #just for diagnostics:
            supported_csc_modes = self.full_csc_modes.strtupleget(encoding)
            encoder_specs = vh.get_encoder_specs(encoding)
            encoder_types = []
            ecsc = []
            for csc in supported_csc_modes:
                if csc not in encoder_specs:
                    continue
                if csc not in ecsc:
                    ecsc.append(csc)
                for especs in encoder_specs.get(csc, []):
                    if especs.codec_type not in encoder_types:
                        encoder_types.append(especs.codec_type)
            videolog.error("Error: failed to setup a video pipeline for %s encoding with source format %s",
                           encoding, src_format)
            all_encs = set(es.codec_type for sublist in encoder_specs.values() for es in sublist)
            videolog.error(" all encoders: %s", csv(tuple(all_encs)))
            videolog.error(" supported CSC modes: %s", csv(supported_csc_modes))
            videolog.error(" supported encoders: %s", csv(encoder_types))
            videolog.error(" encoders CSC modes: %s", csv(ecsc))
            if FORCE_CSC:
                videolog.error(" forced csc mode: %s", FORCE_CSC_MODE)
            return self.video_fallback(image, options, warn=True)
        ve = self._video_encoder
        if not ve:
            return self.video_fallback(image, options, warn=True)
        if not ve.is_ready():
            log("video encoder %s is not ready yet, using temporary fallback", ve)
            return self.video_fallback(image, options, warn=False)

        #we're going to use the video encoder,
        #so make sure we don't time it out:
        self.cancel_video_encoder_timer()

        #dw and dh are the edges we don't handle here
        width = w & self.width_mask
        height = h & self.height_mask
        videolog("video_encode%s image size: %4ix%-4i, encoder/csc size: %4ix%-4i",
                 (encoding, image, options), w, h, width, height)

        csce, csc_image, csc, enc_width, enc_height = self.csc_image(image, width, height)

        start = monotonic()
        options.update(self.get_video_encoder_options(ve.get_encoding(), width, height))
        try:
            ret = ve.compress_image(csc_image, options)
        except Exception as e:
            videolog("%s.compress_image%s", ve, (csc_image, options), exc_info=True)
            if self.is_cancelled():
                return None
            videolog.error("Error: failed to encode %s frame", ve.get_encoding())
            videolog.error(" using %s video encoder:", ve.get_type())
            videolog.error(" %s", e)
            videolog.error(" source: %s", csc_image)
            videolog.error(" options:")
            print_nested_dict(options, prefix="   ", print_fn=videolog.error)
            videolog.error(" encoder:")
            print_nested_dict(ve.get_info(), prefix="   ", print_fn=videolog.error)
            if csce:
                videolog.error(" csc %s:", csce.get_type())
                print_nested_dict(csce.get_info(), prefix="   ", print_fn=videolog.error)
            return None
        finally:
            if image!=csc_image:
                self.free_image_wrapper(csc_image)
            del csc_image
        if ret is None:
            if not self.is_cancelled():
                videolog.error("Error: %s video compression failed", encoding)
            return None
        data, client_options = ret
        end = monotonic()

        #populate client options:
        frame = client_options.get("frame", 0)
        if frame<self.start_video_frame:
            #tell client not to bother updating the screen,
            #as it must have received a non-video frame already
            client_options["paint"] = False

        if frame==0 and SAVE_VIDEO_STREAMS:
            self.close_video_stream_file()
            elapsed = monotonic()-self.start_time
            stream_filename = "window-%i-%.1f-%s.%s" % (self.wid, elapsed, ve.get_type(), ve.get_encoding())
            if SAVE_VIDEO_PATH:
                stream_filename = os.path.join(SAVE_VIDEO_PATH, stream_filename)
            self.video_stream_file = open(stream_filename, "wb")
            log.info("saving new %s stream for window %i to %s", ve.get_encoding(), self.wid, stream_filename)
        if self.video_stream_file:
            self.video_stream_file.write(data)
            self.video_stream_file.flush()

        #tell the client about scaling (the size of the encoded picture):
        #(unless the video encoder has already done so):
        scaled_size = None
        if csce and ("scaled_size" not in client_options) and (enc_width!=width or enc_height!=height):
            scaled_size = enc_width, enc_height
            client_options["scaled_size"] = scaled_size

        if LOG_ENCODERS or compresslog.is_debug_enabled():
            client_options["encoder"] = ve.get_type()

        #deal with delayed b-frames:
        delayed = client_options.get("delayed", 0)
        self.cancel_video_encoder_flush()
        if delayed>0:
            self.schedule_video_encoder_flush(ve, csc, frame, x, y, scaled_size)
            if not data:
                if self.non_video_encodings and frame==0:
                    #first frame has not been sent yet,
                    #so send something as non-video
                    #and skip painting this video frame when it does come out:
                    self.start_video_frame = delayed
                    return self.video_fallback(image, options)
                return None
        else:
            #there are no delayed frames,
            #make sure we timeout the encoder if no new frames come through:
            self.schedule_video_encoder_timer()
        actual_encoding = ve.get_encoding()
        videolog("video_encode %s encoder: %4s %4ix%-4i result is %7i bytes, %6.1f MPixels/s, client options=%s",
                            ve.get_type(), actual_encoding, enc_width, enc_height, len(data or ""),
                            (enc_width*enc_height/(end-start+0.000001)/1024.0/1024.0), client_options)
        return actual_encoding, Compressed(actual_encoding, data), client_options, width, height, 0, 24

    def cancel_video_encoder_flush(self):
        self.cancel_video_encoder_flush_timer()
        self.b_frame_flush_data = None

    def cancel_video_encoder_flush_timer(self):
        bft = self.b_frame_flush_timer
        if bft:
            self.b_frame_flush_timer = None
            self.source_remove(bft)

    def schedule_video_encoder_flush(self, ve, csc, frame, x , y, scaled_size):
        flush_delay = max(150, min(500, int(self.batch_config.delay*10)))
        self.b_frame_flush_data = (ve, csc, frame, x, y, scaled_size)
        self.b_frame_flush_timer = self.timeout_add(flush_delay, self.flush_video_encoder)

    def flush_video_encoder_now(self):
        #this can be called before the timer is due
        self.cancel_video_encoder_flush_timer()
        self.flush_video_encoder()

    def flush_video_encoder(self):
        #this runs in the UI thread as scheduled by schedule_video_encoder_flush,
        #but we want to run from the encode thread to access the encoder:
        self.b_frame_flush_timer = None
        if self.b_frame_flush_data:
            self.call_in_encode_thread(True, self.do_flush_video_encoder)

    def do_flush_video_encoder(self):
        flush_data = self.b_frame_flush_data
        videolog("do_flush_video_encoder: %s", flush_data)
        if not flush_data:
            return
        ve, csc, frame, x, y, scaled_size = flush_data
        if self._video_encoder!=ve or ve.is_closed():
            return
        if frame==0 and ve.get_type()=="x264":
            #x264 has problems if we try to re-use a context after flushing the first IDR frame
            self.ve_clean(self._video_encoder)
            if self.non_video_encodings:
                log("do_flush_video_encoder() scheduling novideo refresh")
                self.idle_add(self.refresh, {"novideo" : True})
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
        if frame<self.start_video_frame:
            client_options["paint"] = False
        if scaled_size:
            client_options["scaled_size"] = scaled_size
        client_options["flush-encoder"] = True
        videolog("do_flush_video_encoder %s : (%s %s bytes, %s)",
                 flush_data, len(data or ()), type(data), client_options)
        #warning: 'options' will be missing the "window-size",
        #so we may end up not honouring gravity during window resizing:
        options = {}
        packet = self.make_draw_packet(x, y, w, h, encoding, Compressed(encoding, data), 0, client_options, options)
        self.queue_damage_packet(packet)
        #check for more delayed frames since we want to support multiple b-frames:
        if not self.b_frame_flush_timer and client_options.get("delayed", 0)>0:
            self.schedule_video_encoder_flush(ve, csc, frame, x, y, scaled_size)
        else:
            self.schedule_video_encoder_timer()


    def cancel_video_encoder_timer(self):
        vet = self.video_encoder_timer
        if vet:
            self.video_encoder_timer = None
            self.source_remove(vet)

    def schedule_video_encoder_timer(self):
        if not self.video_encoder_timer:
            vs = self.video_subregion
            if vs and vs.detection:
                timeout = VIDEO_TIMEOUT
            else:
                timeout = VIDEO_NODETECT_TIMEOUT
            if timeout>0:
                self.video_encoder_timer = self.timeout_add(timeout*1000, self.video_encoder_timeout)

    def video_encoder_timeout(self):
        videolog("video_encoder_timeout() will close video encoder=%s", self._video_encoder)
        self.video_encoder_timer = None
        self.video_context_clean()


    def csc_image(self, image, width, height):
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
            #no csc step!
            return None, image, image.get_pixel_format(), width, height

        start = monotonic()
        csc_image = csce.convert_image(image)
        end = monotonic()
        csclog("csc_image(%s, %s, %s) converted to %s in %.1fms, %6.1f MPixels/s",
                        image, width, height,
                        csc_image, (1000.0*end-1000.0*start), (width*height/(end-start+0.000001)/1024.0/1024.0))
        if not csc_image:
            raise Exception("csc_image: conversion of %s to %s failed" % (image, csce.get_dst_format()))
        assert csce.get_dst_format()==csc_image.get_pixel_format()
        return csce, csc_image, csce.get_dst_format(), csce.get_dst_width(), csce.get_dst_height()
