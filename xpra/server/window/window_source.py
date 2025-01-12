# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2023 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import hashlib
import threading
from math import sqrt, ceil
from collections import deque
from time import monotonic
from typing import Callable, Dict, List, Tuple, Iterable, ContextManager, Any, Optional

from xpra.os_util import bytestostr, POSIX, OSX, DummyContextManager
from xpra.util import envint, envbool, csv, typedict, first_time, decode_str, repr_ellipsized
from xpra.common import MAX_WINDOW_SIZE, WINDOW_DECODE_SKIPPED, WINDOW_DECODE_ERROR, WINDOW_NOT_FOUND
from xpra.server.window.windowicon_source import WindowIconSource
from xpra.server.window.window_stats import WindowPerformanceStatistics
from xpra.server.window.batch_delay_calculator import calculate_batch_delay, get_target_speed, get_target_quality
from xpra.server.cystats import time_weighted_average, logp #@UnresolvedImport
from xpra.server.source.source_stats import GlobalPerformanceStatistics
from xpra.rectangle import rectangle, add_rectangle, remove_rectangle, merge_all   #@UnresolvedImport
from xpra.simple_stats import get_list_stats
from xpra.codecs.rgb_transform import rgb_reformat
from xpra.codecs.loader import get_codec
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.codecs.codec_constants import preforder, LOSSY_PIXEL_FORMATS, PREFERRED_REFRESH_ENCODING_ORDER
from xpra.net.compression import use, Compressed
from xpra.log import Logger

log = Logger("window", "encoding")
refreshlog = Logger("window", "refresh")
compresslog = Logger("window", "compress")
damagelog = Logger("window", "damage")
scalinglog = Logger("scaling")
iconlog = Logger("icon")
avsynclog = Logger("av-sync")
statslog = Logger("stats")
bandwidthlog = Logger("bandwidth")


UI_THREAD_CHECK : bool = envbool("XPRA_UI_THREAD_CHECK", True)

TRUE_LOSSLESS : bool = envbool("XPRA_TRUE_LOSSLESS", False)
LOG_ENCODERS : bool = envbool("XPRA_LOG_ENCODERS", False)

AUTO_REFRESH : bool = envbool("XPRA_AUTO_REFRESH", True)
AUTO_REFRESH_QUALITY : int = envint("XPRA_AUTO_REFRESH_QUALITY", 100)
AUTO_REFRESH_SPEED : int = envint("XPRA_AUTO_REFRESH_SPEED", 50)

INITIAL_QUALITY : int = envint("XPRA_INITIAL_QUALITY", 65)
INITIAL_SPEED : int = envint("XPRA_INITIAL_SPEED", 40)
TEXT_QUALITY = envint("XPRA_TEXT_QUALITY", 100)

LOCKED_BATCH_DELAY : int = envint("XPRA_LOCKED_BATCH_DELAY", 1000)

MAX_PIXELS_PREFER_RGB : int = envint("XPRA_MAX_PIXELS_PREFER_RGB", 4096)
WEBP_EFFICIENCY_CUTOFF : int = envint("XPRA_WEBP_EFFICIENCY_CUTOFF", 512*1024)

MIN_WINDOW_REGION_SIZE : int = envint("XPRA_MIN_WINDOW_REGION_SIZE", 1024)
MAX_SOFT_EXPIRED : int = envint("XPRA_MAX_SOFT_EXPIRED", 5)
ACK_JITTER : int = envint("XPRA_ACK_JITTER", 100)
ACK_TOLERANCE : int = envint("XPRA_ACK_TOLERANCE", 250)
SLOW_SEND_THRESHOLD : int = envint("XPRA_SLOW_SEND_THRESHOLD", 20*1000*1000)
FRAME_OVERHEAD : int = envint("XPRA_FRAME_OVERHEAD", 1)

HAS_ALPHA : bool = envbool("XPRA_ALPHA", True)
BROWSER_ALPHA_FIX : bool = envbool("XPRA_BROWSER_ALPHA_FIX", True)
FORCE_BATCH : int = envint("XPRA_FORCE_BATCH", True)
STRICT_MODE : bool = envbool("XPRA_ENCODING_STRICT_MODE", False)
MAX_QUALITY : int = envint("XPRA_ENCODING_MAX_QUALITY", 100)
MAX_SPEED : int = envint("XPRA_ENCODING_MAX_SPEED", 100)
assert MAX_QUALITY>0 and MAX_SPEED>0

MERGE_REGIONS : bool = envbool("XPRA_MERGE_REGIONS", True)
DOWNSCALE : bool = envbool("XPRA_DOWNSCALE", True)
DOWNSCALE_THRESHOLD : int = envint("XPRA_DOWNSCALE_THRESHOLD", 20)
INTEGRITY_HASH : int = envint("XPRA_INTEGRITY_HASH", False)
MAX_SYNC_BUFFER_SIZE : int = envint("XPRA_MAX_SYNC_BUFFER_SIZE", 256)*1024*1024        #256MB
AV_SYNC_RATE_CHANGE : int = envint("XPRA_AV_SYNC_RATE_CHANGE", 20)
AV_SYNC_TIME_CHANGE : int = envint("XPRA_AV_SYNC_TIME_CHANGE", 500)
SEND_TIMESTAMPS : bool = envbool("XPRA_SEND_TIMESTAMPS", False)
DAMAGE_STATISTICS : bool = envbool("XPRA_DAMAGE_STATISTICS", False)

SCROLL_ALL : bool = envbool("XPRA_SCROLL_ALL", True)
FORCE_PILLOW : bool = envbool("XPRA_FORCE_PILLOW", False)
HARDCODED_ENCODING : str = os.environ.get("XPRA_HARDCODED_ENCODING", "")

INFINITY = float("inf")
def get_env_encodings(etype:str, valid_options:Iterable[str]=()) -> Tuple[str,...]:
    v = os.environ.get(f"XPRA_{etype}_ENCODINGS")
    encodings = tuple(valid_options)
    if v:
        options = v.split(",")
        encodings = tuple(x for x in options if x in valid_options)
    log("%s encodings: %s", etype, encodings)
    return encodings
TRANSPARENCY_ENCODINGS = get_env_encodings("TRANSPARENCY", ("webp", "png", "rgb32", "jpega"))
if TRUE_LOSSLESS:
    LOSSLESS_ENCODINGS = ("rgb", "png", "png/P", "png/L", "webp", "avif")
else:
    LOSSLESS_ENCODINGS = ("rgb", "png", "png/P", "png/L", "webp", "avif", "jpeg", "jpega")
LOSSLESS_ENCODINGS = get_env_encodings("LOSSLESS", LOSSLESS_ENCODINGS)
REFRESH_ENCODINGS = get_env_encodings("REFRESH", LOSSLESS_ENCODINGS)

LOSSLESS_WINDOW_TYPES = set(os.environ.get("XPRA_LOSSLESS_WINDOW_TYPES",
                                       "DOCK,TOOLBAR,MENU,UTILITY,DROPDOWN_MENU,POPUP_MENU,TOOLTIP,NOTIFICATION,COMBO,DND").split(","))


COMPRESS_FMT_PREFIX : str = "compress: %5.1fms for %4ix%-4i pixels at %4i,%-4i for wid=%-5i using %9s"
COMPRESS_FMT_SUFFIX : str = ", sequence %5i, client_options=%-50s, options=%s"
COMPRESS_FMT        : str = COMPRESS_FMT_PREFIX+" with ratio %5.1f%%  (%5iKB to %5iKB)"+COMPRESS_FMT_SUFFIX


ui_context : ContextManager = DummyContextManager()
if POSIX and not OSX and not envbool("XPRA_NOX11", False) and os.environ.get("GDK_BACKEND", "x11") == "x11":
    from xpra.gtk_common.error import xlog
    ui_context = xlog


class DelayedRegions:
    def __init__(self, damage_time:float, regions:List[rectangle], encoding:str, options:Optional[Dict]):
        self.expired : bool = False
        self.damage_time : float = damage_time
        self.regions = regions
        self.encoding : str = encoding
        self.options : Dict = options or {}

    def __repr__(self):
        return "DelayedRegion(time=%i, expired=%s, encoding=%s, regions=%s, options=%s)" % (
            self.damage_time, self.expired, self.encoding, repr_ellipsized(self.regions), self.options
            )


def capr(v) -> int:
    return min(100, max(0, int(v)))


def get_encoder_type(encoder) -> str:
    if not encoder:
        return "none"
    mod = getattr(encoder, "__module__")    #ie: 'xpra.codecs.pillow.encoder'
    if not mod:
        return "none"
    if mod.endswith(".encoder"):
        mod = mod[:-len(".encoder")]    #ie: 'xpra.codecs.pillow'
        mod = mod.split(".")[-1]        #ie: 'pillow'
    return mod


class WindowSource(WindowIconSource):
    """
    We create a Window Source for each window we send pixels for.

    The UI thread calls 'damage' for screen updates,
    we eventually call 'ClientConnection.call_in_encode_thread' to queue the damage compression,
    the function can then submit the packet using the 'queue_damage_packet' callback.

    (also by 'send_window_icon' and clipboard packets)
    """
    def __init__(self,
                    idle_add:Callable, timeout_add:Callable, source_remove:Callable,
                    ww:int, wh:int,
                    record_congestion_event:Callable, queue_size:Callable, call_in_encode_thread:Callable, queue_packet:Callable,
                    statistics,
                    wid:int, window, batch_config, auto_refresh_delay:int,
                    av_sync:bool, av_sync_delay:int,
                    video_helper,
                    cuda_device_context,
                    server_core_encodings:Tuple[str,...], server_encodings:Tuple[str,...],
                    encoding:str, encodings:Tuple[str,...], core_encodings:Tuple[str,...], window_icon_encodings:Tuple[str,...],
                    encoding_options:typedict, icons_encoding_options:typedict,
                    rgb_formats:Tuple[str,...],
                    default_encoding_options,
                    mmap, mmap_size:int, bandwidth_limit:int, jitter:int):
        super().__init__(window_icon_encodings, icons_encoding_options)
        self.idle_add = idle_add
        self.timeout_add = timeout_add
        self.source_remove = source_remove
        # mmap:
        self._mmap = mmap
        self._mmap_size = mmap_size

        self.init_vars()

        self.start_time = monotonic()
        self.ui_thread = threading.current_thread()

        self.record_congestion_event = record_congestion_event  #callback for send latency problems
        self.queue_size   = queue_size                  #callback to get the size of the damage queue
        self.call_in_encode_thread = call_in_encode_thread  #callback to add damage data which is ready to compress to the damage processing queue
        self.queue_packet = queue_packet                #callback to add a network packet to the outgoing queue
        self.wid : int = wid
        self.window = window                            #only to be used from the UI thread!
        self.global_statistics : GlobalPerformanceStatistics = statistics             #shared/global statistics from ClientConnection
        self.statistics : WindowPerformanceStatistics = WindowPerformanceStatistics()
        self.av_sync : bool = av_sync                          #flag: enabled or not?
        self.av_sync_delay = av_sync_delay              #the av-sync delay we actually use
        self.av_sync_delay_target = av_sync_delay       #the av-sync delay we want at this point in time (can vary quickly)
        self.av_sync_delay_base = av_sync_delay         #the total av-sync delay we are trying to achieve (including video encoder delay)
        self.av_sync_frame_delay : int = 0                    #how long frames spend in the video encoder
        self.av_sync_timer : int = 0
        self.encode_queue : List[Tuple] = []
        self.encode_queue_max_size : int = 10
        self.last_scroll_event : float = 0

        self.server_core_encodings = server_core_encodings
        self.server_encodings = server_encodings
        self.encoding = encoding                        #the current encoding
        self.encodings = encodings                      #all the encodings supported by the client
        self.core_encodings = core_encodings            #the core encodings supported by the client
        self.picture_encodings = ()                     #non-video only
        self.rgb_formats = rgb_formats                  #supported RGB formats (RGB, RGBA, ...) - used by mmap
        self.encoding_options = encoding_options        #extra options which may be specific to the encoder (ie: x264)
        self.rgb_lz4 : bool = use("lz4") and encoding_options.boolget("rgb_lz4", False)       #server and client support lz4 pixel compression
        self.client_render_size = encoding_options.get("render-size")
        self.client_bit_depth : int = encoding_options.intget("bit-depth", 24)
        self.supports_transparency : bool = HAS_ALPHA and encoding_options.boolget("transparency")
        self.full_frames_only : bool = self.is_tray or encoding_options.boolget("full_frames_only")
        self.client_refresh_encodings : Tuple[str, ...] = encoding_options.strtupleget("auto_refresh_encodings")
        self.max_soft_expired : int = max(0, min(100, encoding_options.intget("max-soft-expired", MAX_SOFT_EXPIRED)))
        self.send_timetamps : bool = encoding_options.boolget("send-timestamps", SEND_TIMESTAMPS)
        self.send_window_size : bool = encoding_options.boolget("send-window-size", False)
        self.decoder_speed = typedict(self.encoding_options.dictget("decoder-speed") or {})
        self.batch_config = batch_config
        #auto-refresh:
        self.auto_refresh_delay = auto_refresh_delay
        self.base_auto_refresh_delay = auto_refresh_delay
        self.last_auto_refresh_message = None
        self.video_helper = video_helper
        self.cuda_device_context = cuda_device_context

        self.is_idle : bool = False
        self.is_OR : bool = window.is_OR()
        self.is_tray : bool = window.is_tray()
        self.is_shadow : bool = window.is_shadow()
        self.has_alpha : bool = HAS_ALPHA and window.has_alpha()
        self.window_dimensions = ww, wh
        #where the window is mapped on the client:
        self.mapped_at = None
        self.fullscreen : bool = not self.is_tray and window.get("fullscreen")
        if default_encoding_options.get("scaling.control") is None:
            self.scaling_control = None     #means "auto"
        else:
            #ClientConnection sets defaults with the client's scaling.control value
            self.scaling_control = default_encoding_options.intget("scaling.control", 1)
        self.scaling = None
        self.maximized : bool = False          #set by the client!
        self.iconic : bool = False
        self.window_signal_handlers = []
        #watch for changes to properties that are used to derive the content-type:
        self.content_type : str = window.get("content-type", "")
        if "content-type" in window.get_dynamic_property_names():
            sid = window.connect("notify::content-type", self.content_type_changed)
            self.window_signal_handlers.append(sid)
        if "iconic" in window.get_dynamic_property_names():
            self.iconic = window.get_property("iconic")
            sid = window.connect("notify::iconic", self._iconic_changed)
            self.window_signal_handlers.append(sid)
        if "fullscreen" in window.get_dynamic_property_names():
            sid = window.connect("notify::fullscreen", self._fullscreen_changed)
            self.window_signal_handlers.append(sid)
        if "children" in window.get_internal_property_names():
            #we just copy the value to an attribute of window-source,
            #so that we can access it from any thread
            def children_updated(*_args):
                self.children = window.get_property("children")
            sid = window.connect("notify::children", children_updated)
            self.window_signal_handlers.append(sid)
            children_updated()
        else:
            self.children = None

        self.bandwidth_limit = bandwidth_limit
        self.jitter = jitter

        self.pixel_format = None                            #ie: BGRX
        self.image_depth : int = window.get_property("depth")

        # general encoding tunables (mostly used by video encoders):
        #keep track of the target encoding_quality: (event time, info, encoding speed):
        self._encoding_quality : deque[Tuple[float,int]] = deque(maxlen=100)
        self._encoding_quality_info : Dict[str,Any] = {}
        #keep track of the target encoding_speed: (event time, info, encoding speed):
        self._encoding_speed : deque[Tuple[float,int]] = deque(maxlen=100)
        self._encoding_speed_info : Dict[str,Any] = {}
        # they may have fixed values:
        deo = typedict(default_encoding_options)
        self._fixed_quality = deo.intget("quality", -1)
        self._fixed_min_quality = capr(deo.intget("min-quality", 0))
        self._fixed_max_quality = capr(deo.intget("max-quality", MAX_QUALITY))
        self._fixed_speed = deo.intget("speed", -1)
        self._fixed_min_speed = capr(deo.intget("min-speed", 0))
        self._fixed_max_speed = capr(deo.intget("max-speed", MAX_SPEED))
        self._encoding_hint : str = ""
        self._quality_hint = self.window.get("quality", -1)
        dyn_props = window.get_dynamic_property_names()
        if "quality" in dyn_props:
            sid = window.connect("notify::quality", self.quality_changed)
            self.window_signal_handlers.append(sid)
        self._speed_hint = self.window.get("speed", -1)
        if "speed" in dyn_props:
            sid = window.connect("notify::speed", self.speed_changed)
            self.window_signal_handlers.append(sid)
        if "encoding" in dyn_props:
            sid = window.connect("notify::encoding", self.encoding_changed)
            self.window_signal_handlers.append(sid)
        self.window_type = set()
        if "window-type" in dyn_props:
            self.window_type = set(self.window.get_property("window-type"))
            sid = window.connect("notify::window-type", self.window_type_changed)
            self.window_signal_handlers.append(sid)
        self._opaque_region = self.window.get("opaque-region", ())
        if "opaque-region" in dyn_props:
            sid = window.connect("notify::opaque-region", self.window_opaque_region_changed)
            self.window_signal_handlers.append(sid)

        if self.has_alpha and BROWSER_ALPHA_FIX and not self.is_OR:
            #remove alpha from 'NORMAL' browser windows
            #of a size greater than 200x200:
            if self.content_type.find("browser")>=0 and "NORMAL" in self.window_type and ww>=200 and wh>=200:
                self.has_alpha = False

        #will be overridden by update_quality() and update_speed() called from update_encoding_selection()
        #just here for clarity:
        nobwl = (self.bandwidth_limit or 0)<=0
        if self._quality_hint>=0:
            self._current_quality = capr(self._quality_hint)
        elif self._fixed_quality>0:
            self._current_quality = capr(self._fixed_quality)
        else:
            self._current_quality = capr(encoding_options.intget("initial_quality", INITIAL_QUALITY*(1+int(nobwl))))
        if self._speed_hint>=0:
            self._current_speed = capr(self._speed_hint)
        elif self._fixed_speed>0:
            self._current_speed = capr(self._fixed_speed)
        else:
            self._current_speed = capr(encoding_options.intget("initial_speed", INITIAL_SPEED*(1+int(nobwl))))
        self._want_alpha : bool = False
        self._lossless_threshold_base : int = 85
        self._lossless_threshold_pixel_boost : int = 20
        self._rgb_auto_threshold : int = MAX_PIXELS_PREFER_RGB

        log("initial encoding for %s: %s", self.wid, self.encoding)
        #ready to service:
        self._damage_cancelled = 0

    def __repr__(self) -> str:
        return f"WindowSource({self.wid} : {self.window_dimensions})"

    def ui_thread_check(self) -> None:
        if not UI_THREAD_CHECK:
            return
        ct = threading.current_thread()
        if ct != self.ui_thread:
            raise RuntimeError(f"called from {ct.name!r} instead of UI thread {self.ui_thread}")


    def insert_encoder(self, encoder_name:str, encoding:str, encode_fn:Callable) -> None:
        log(f"insert_encoder({encoder_name}, {encoding}, {encode_fn})")
        self._all_encoders.setdefault(encoding, []).insert(0, encode_fn)
        self._encoders[encoding] = encode_fn

    def append_encoder(self, encoding:str, encode_fn:Callable) -> None:
        log("append_encoder(%s, %s)", encoding, encode_fn)
        self._all_encoders.setdefault(encoding, []).append(encode_fn)
        if encoding not in self._encoders:
            self._encoders[encoding] = encode_fn

    def init_encoders(self) -> None:
        self.do_init_encoders()
        self.parse_csc_modes(self.encoding_options.dictget("full_csc_modes", default=None))
        self.update_encoding_selection(self.encoding, init=True)

    def do_init_encoders(self) -> None:
        self._all_encoders : Dict[str,List[Callable]] = {}
        self._encoders : Dict[str,Callable] = {}
        picture_encodings = set()
        def add(encoder_name:str):
            encoder = get_codec(encoder_name)
            if not encoder:
                return None
            for encoding in encoder.get_encodings():
                if encoding in self.server_core_encodings:
                    self.insert_encoder(encoder_name, encoding, encoder.encode)
            picture_encodings.update(encoder.get_encodings())
            return encoder
        rgb = add("enc_rgb")
        if not rgb:
            log.warn("Warning: plain rgb encoder is missing!")
        #we need pillow for scaling and grayscale:
        pillow = add("enc_pillow")
        if self._mmap_size>0:
            try:
                from xpra.net.mmap_pipe import mmap_write
            except ImportError:
                if first_time("mmap_write missing"):
                    log.warn("Warning: cannot use mmap, no write method support")
            else:
                self.mmap_write = mmap_write
                self.insert_encoder("mmap", "mmap", self.mmap_encode)
        if (not FORCE_PILLOW or not pillow) and self.image_depth != 30:
            #prefer these native encoders over the Pillow version:
            add("enc_spng")
            add("enc_webp")
            add("enc_jpeg")
            add("enc_avif")
            #prefer nvjpeg over all the other jpeg encoders:
            log("init_encoders() cuda_device_context=%s", self.cuda_device_context)
            if self.cuda_device_context:
                add("enc_nvjpeg")
        self.picture_encodings = tuple(picture_encodings)
        self.parse_csc_modes(self.encoding_options.dictget("full_csc_modes", default=None))
        self.update_encoding_selection(self.encoding, init=True)


    def init_vars(self) -> None:
        self.server_core_encodings = ()
        self.server_encodings = ()
        self.encoding = ""
        self.encodings = ()
        self.encoding_last_used : str = ""
        self.auto_refresh_encodings = ()
        self.core_encodings = ()
        self.rgb_formats = ()
        self.full_csc_modes = typedict()
        self.client_refresh_encodings = ()
        self.encoding_options = {}
        self.rgb_lz4 = False
        self.supports_transparency = False
        self.full_frames_only = False
        self.suspended : bool = False
        self.strict = STRICT_MODE
        self.decoder_speed = typedict()
        self.mmap_write = None
        #
        self.decode_error_refresh_timer : int = 0
        self.may_send_timer : int = 0
        self.auto_refresh_delay = 0
        self.base_auto_refresh_delay = 0
        self.min_auto_refresh_delay = 50
        self.video_helper = None
        self.refresh_quality = AUTO_REFRESH_QUALITY
        self.refresh_speed = AUTO_REFRESH_SPEED
        self.refresh_event_time : float = 0.0
        self.refresh_target_time : float = 0.0
        self.refresh_timer : int = 0
        self.refresh_regions : List[rectangle] = []
        self.timeout_timer : int = 0
        self.expire_timer : int = 0
        self.soft_timer : int = 0
        self.soft_expired : int = 0
        self.max_soft_expired = MAX_SOFT_EXPIRED
        self.is_OR = False
        self.is_tray = False
        self.is_shadow = False
        self.has_alpha = False
        self.window_dimensions = 0, 0
        self.fullscreen = False
        self.scaling_control = None
        self.scaling = None
        self.maximized = False
        self.bandwidth_limit = 0
        #for deciding between small regions and full screen updates:
        self.max_small_regions : int = 40
        self.max_bytes_percent : int = 60
        self.small_packet_cost : int = 1024
        #
        self._encoding_quality = deque()
        self._encoding_quality_info = {}
        self._encoding_speed = deque()
        self._encoding_speed_info = {}
        #
        self._fixed_quality = -1
        self._fixed_min_quality = 0
        self._fixed_max_quality = MAX_QUALITY
        self._fixed_speed = -1
        self._fixed_min_speed = 0
        self._fixed_max_speed = MAX_SPEED
        #
        self._damage_delayed = None
        self._sequence : int = 1
        self._damage_cancelled = INFINITY
        self._damage_packet_sequence : int = 1

    def cleanup(self) -> None:
        self.cancel_damage(INFINITY)
        log("encoding_totals for wid=%s with primary encoding=%s : %s",
            self.wid, self.encoding, self.statistics.encoding_totals)
        self.init_vars()
        self._mmap_size = 0
        self.batch_config.cleanup()
        #we can only clear the encoders after clearing the whole encoding queue:
        #(because mmap cannot be cancelled once queued for encoding)
        self.call_in_encode_thread(False, self.encode_ended)

    def encode_ended(self) -> None:
        log("encode_ended()")
        self._encoders = {}
        self.idle_add(self.ui_cleanup)

    def ui_cleanup(self) -> None:
        log("ui_cleanup: will disconnect %s", self.window_signal_handlers)
        for sid in self.window_signal_handlers:
            self.window.disconnect(sid)
        self.window_signal_handlers = []
        self.window = None
        self.batch_config = None
        self.get_best_encoding : Callable = self.encoding_is_rgb32
        self.statistics = None
        self.global_statistics = None


    def get_info(self) -> Dict[str,Any]:
        #should get prefixed with "client[M].window[N]." by caller
        """
            Add window specific stats
        """
        info = self.statistics.get_info()
        info.update(super().get_info())
        einfo = info.setdefault("encoding", {})     #defined in statistics.get_info()
        einfo.update(self.get_quality_speed_info())
        einfo.update({
                      ""                    : self.encoding,
                      "lossless_threshold"  : {
                                               "base"           : self._lossless_threshold_base,
                                               "pixel_boost"    : self._lossless_threshold_pixel_boost
                                               },
                      })
        try:
            #ie: get_strict_encoding -> "strict_encoding"
            einfo["selection"] = self.get_best_encoding.__name__.replace("get_", "")
        except AttributeError:
            pass

        #"encodings" info:
        esinfo : Dict[str,Any] = {
                  ""                : self.encodings,
                  "core"            : self.core_encodings,
                  "auto-refresh"    : self.client_refresh_encodings,
                  "csc_modes"       : dict(self.full_csc_modes or {}),
                  "decoder-speed"   : dict(self.decoder_speed),
                  }
        larm = self.last_auto_refresh_message
        if larm:
            esinfo.update({"auto-refresh"    : {
                "quality"       : self.refresh_quality,
                "speed"         : self.refresh_speed,
                "min-delay"     : self.min_auto_refresh_delay,
                "delay"         : self.auto_refresh_delay,
                "base-delay"    : self.base_auto_refresh_delay,
                "last-event"    : {
                    "elapsed"    : int(1000*(monotonic()-larm[0])),
                    "message"    : larm[1],
                    }
                }
            })

        #remove large default dict:
        info.update({
                "idle"                  : self.is_idle,
                "dimensions"            : self.window_dimensions,
                "suspended"             : self.suspended or False,
                "bandwidth-limit"       : self.bandwidth_limit,
                "av-sync"               : {
                                           "enabled"    : self.av_sync,
                                           "current"    : self.av_sync_delay,
                                           "target"     : self.av_sync_delay_target
                                           },
                "encodings"             : esinfo,
                "rgb_threshold"         : self._rgb_auto_threshold,
                "mmap"                  : self._mmap_size>0,
                "last_used"             : self.encoding_last_used or "",
                "full-frames-only"      : self.full_frames_only,
                "supports-transparency" : self.supports_transparency,
                "property"              : self.get_property_info(),
                "content-type"          : self.content_type or "",
                "batch"                 : self.batch_config.get_info(),
                "soft-timeout"          : {
                                           "expired"        : self.soft_expired,
                                           "max"            : self.max_soft_expired,
                                           },
                "send-timetamps"        : self.send_timetamps,
                "send-window-size"      : self.send_window_size,
                "rgb_formats"           : self.rgb_formats,
                "bit-depth"             : {
                    "source"                : self.image_depth,
                    "client"                : self.client_bit_depth,
                    },
                })
        ma = self.mapped_at
        if ma:
            info["mapped-at"] = ma
        crs = self.client_render_size
        if crs:
            info["render-size"] = crs
        info["damage.fps"] = int(self.get_damage_fps())
        if self.pixel_format:
            info["pixel-format"] = self.pixel_format
        cdd = self.cuda_device_context
        if cdd:
            info["cuda-device"] = cdd.get_info()
        return info

    def get_damage_fps(self) -> int:
        now = monotonic()
        cutoff = now-5
        lde = tuple(x[0] for x in tuple(self.statistics.last_damage_events) if x[0]>=cutoff)
        fps = 0
        if len(lde)>=2:
            elapsed = now-min(lde)
            if elapsed>0:
                fps = round(len(lde) / elapsed)
        return fps

    def get_quality_speed_info(self) -> Dict[str,Any]:
        info = {}
        def add_list_info(prefix, v, vinfo):
            if not v:
                return
            l = tuple(v)
            if not l:
                li = {}
            else:
                li = get_list_stats(x for _, x in l)
            li.update(vinfo)
            info[prefix] = li
        add_list_info("quality", self._encoding_quality, self._encoding_quality_info)
        add_list_info("speed", self._encoding_speed, self._encoding_speed_info)
        return info

    def get_property_info(self) -> Dict[str,Any]:
        return {
                "fullscreen"            : self.fullscreen or False,
                #speed / quality properties (not necessarily the same as the video encoder settings..):
                "encoding-hint"         : self._encoding_hint or "",
                "speed" : {
                    "min"               : self._fixed_min_speed,
                    "max"               : self._fixed_max_speed,
                    "fixed"             : self._fixed_speed,
                    "cur"               : self._current_speed,
                    "hint"              : self._speed_hint,
                    "refresh"           : self.refresh_speed,
                    },
                "quality" : {
                    "min"               : self._fixed_min_quality,
                    "max"               : self._fixed_max_quality,
                    "fixed"             : self._fixed_quality,
                    "cur"               : self._current_quality,
                    "hint"              : self._quality_hint,
                    "refresh"           : self.refresh_quality,
                    },
                }


    def go_idle(self) -> None:
        self.is_idle = True
        self.lock_batch_delay(LOCKED_BATCH_DELAY)

    def no_idle(self) -> None:
        self.is_idle = False
        self.unlock_batch_delay()

    def lock_batch_delay(self, delay) -> None:
        """ use a fixed delay until unlock_batch_delay is called """
        if not self.batch_config.locked:
            self.batch_config.locked = True
            self.batch_config.saved = self.batch_config.delay
        self.batch_config.delay = max(delay, self.batch_config.delay)

    def unlock_batch_delay(self) -> None:
        if self.iconic or not self.batch_config.locked:
            return
        self.batch_config.locked = False
        self.batch_config.delay = self.batch_config.saved

    def record_scroll_event(self) -> None:
        self.last_scroll_event = monotonic()

    def suspend(self) -> None:
        self.cancel_damage()
        self.statistics.reset()
        self.suspended = True

    def resume(self) -> None:
        self.ui_thread_check()
        self.cancel_damage()
        self.statistics.reset()
        self.suspended = False
        self.refresh({"quality" : 100})
        if not self.is_OR and not self.is_tray and "icons" in self.window.get_property_names():
            self.send_window_icon()

    def refresh(self, options=None) -> None:
        self.ui_thread_check()
        w, h = self.window_dimensions
        self.damage(0, 0, w, h, options)


    def set_scaling(self, scaling) -> None:
        scalinglog("set_scaling(%s)", scaling)
        self.scaling = scaling
        self.reconfigure(True)

    def set_scaling_control(self, scaling_control) -> None:
        scalinglog("set_scaling_control(%s)", scaling_control)
        if scaling_control is None:
            self.scaling_control = None
        else:
            self.scaling_control = max(0, min(100, scaling_control))
        self.reconfigure(True)

    def _fullscreen_changed(self, _window, *_args) -> bool:
        self.fullscreen = self.window.get_property("fullscreen")
        log("window fullscreen state changed: %s", self.fullscreen)
        self.reconfigure(True)
        return True

    def _iconic_changed(self, _window, *_args) -> bool:
        self.iconic = self.window.get_property("iconic")
        if self.iconic:
            self.go_idle()
        else:
            self.no_idle()
        return True

    def content_type_changed(self, window, *args) -> bool:
        self.content_type = window.get("content-type", "")
        log("content_type_changed(%s, %s) content-type=%s", window, args, self.content_type)
        self.reconfigure(True)
        return True

    def quality_changed(self, window, *args) -> bool:
        self._quality_hint = window.get("quality", -1)
        log("quality_changed(%s, %s) quality=%s", window, args, self._quality_hint)
        return True

    def speed_changed(self, window, *args) -> bool:
        self._speed_hint = window.get("speed", -1)
        log("speed_changed(%s, %s) speed=%s", window, args, self._speed_hint)
        return True

    def encoding_changed(self, window, *args) -> bool:
        v = window.get("encoding", None)
        if v and v not in self._encoders:
            log.warn("Warning: invalid encoding hint '%s'", v)
            log.warn(" this encoding is not supported")
            v = ""
        self._encoding_hint = v
        self.assign_encoding_getter()
        log("encoding_changed(%s, %s) encoding-hint=%s, selection=%s",
            window, args, self._encoding_hint, self.get_best_encoding)
        return True

    def window_type_changed(self, window, *args) -> bool:
        self.window_type = set(window.get_property("window-type"))
        log("window_type_changed(window, %s) window_type=%s", window, args, self.window_type)
        self.assign_encoding_getter()
        return True

    def window_opaque_region_changed(self, window, *args) -> bool:
        self._opaque_region = window.get_property("opaque-region") or ()
        log("window_opaque_region_changed(%s, %s) opaque-region=%s", window, args, self._opaque_region)
        self.update_encoding_options()
        return True

    def set_client_properties(self, properties : typedict) -> None:
        #filter out stuff we don't care about
        #to see if there is anything to set at all,
        #and if not, don't bother doing the potentially expensive update_encoding_selection()
        for k in ("workspace", "screen"):
            properties.pop(k, None)
            #for legacy packet encoders:
            properties.pop(k.encode("latin1"), None)
        if properties:
            self.do_set_client_properties(properties)

    def do_set_client_properties(self, properties : typedict) -> None:
        self.maximized = properties.boolget("maximized", False)
        self.client_render_size = properties.intpair("encoding.render-size")
        self.client_bit_depth = properties.intget("bit-depth", self.client_bit_depth)
        self.client_refresh_encodings = properties.strtupleget("encoding.auto_refresh_encodings", self.client_refresh_encodings)
        self.full_frames_only = self.is_tray or properties.boolget("encoding.full_frames_only", self.full_frames_only)
        self.supports_transparency = HAS_ALPHA and properties.boolget("encoding.transparency", self.supports_transparency)
        self.encodings = properties.strtupleget("encodings", self.encodings)
        self.core_encodings = properties.strtupleget("encodings.core", self.core_encodings)
        self.decoder_speed = typedict(properties.dictget("decoder-speed", self.decoder_speed))
        rgb_formats = properties.strtupleget("encodings.rgb_formats", self.rgb_formats)
        if not self.supports_transparency:
            #remove rgb formats with alpha
            rgb_formats = tuple(x for x in rgb_formats if x.find("A")<0)
        self.rgb_formats = rgb_formats
        self.send_window_size = properties.boolget("encoding.send-window-size", self.send_window_size)
        self.parse_csc_modes(properties.dictget("encoding.full_csc_modes", default=None))
        #select the defaults encoders:
        #(in case pillow was selected previously and the client side scaling changed)
        for encoding, encoders in self._all_encoders.items():
            self._encoders[encoding] = encoders[0]
        self.update_encoding_selection(self.encoding)


    def parse_csc_modes(self, full_csc_modes) -> None:
        #only override if values are specified:
        log("parse_csc_modes(%s) current value=%s", full_csc_modes, self.full_csc_modes)
        if full_csc_modes is not None and isinstance(full_csc_modes, dict):
            self.full_csc_modes = typedict()
            #workaround for older packet encoders: (strings vs bytes nonsense)
            for enc, csc_formats in full_csc_modes.items():
                self.full_csc_modes[bytestostr(enc)] = tuple(bytestostr(v) for v in csc_formats)


    def set_auto_refresh_delay(self, d:int) -> None:
        self.auto_refresh_delay = d
        self.update_refresh_attributes()

    def set_av_sync(self, av_sync:int) -> None:
        self.av_sync = av_sync

    def set_av_sync_delay(self, new_delay:int) -> None:
        self.av_sync_delay_base = new_delay

    def may_update_av_sync_delay(self) -> None:
        #set the target then schedule a timer to gradually
        #get the actual value "av_sync_delay" moved towards it
        self.av_sync_delay_target = max(0, self.av_sync_delay_base - self.av_sync_frame_delay)
        avsynclog("may_update_av_sync_delay() target=%s from base=%s, frame-delay=%s",
                  self.av_sync_delay_target, self.av_sync_delay_base, self.av_sync_frame_delay)
        self.schedule_av_sync_update()

    def schedule_av_sync_update(self, delay:int=0) -> None:
        avsynclog("schedule_av_sync_update(%i) wid=%i, delay=%i, target=%i, timer=%s",
                  delay, self.wid, self.av_sync_delay, self.av_sync_delay_target, self.av_sync_timer)
        if self.av_sync_timer:
            return
        if not self.av_sync:
            self.av_sync_delay = 0
            return
        if self.av_sync_delay==self.av_sync_delay_target:
            return  #already up to date
        if self.av_sync_timer:
            return  #already scheduled
        self.av_sync_timer = self.timeout_add(delay, self.update_av_sync_delay)

    def update_av_sync_delay(self) -> None:
        self.av_sync_timer = 0
        delta = self.av_sync_delay_target-self.av_sync_delay
        if delta==0:
            return
        #limit the rate of change:
        rdelta = min(AV_SYNC_RATE_CHANGE, max(-AV_SYNC_RATE_CHANGE, delta))
        avsynclog("update_av_sync_delay() wid=%i, current=%s, target=%s, adding %s (capped to +-%s from %s)",
                  self.wid, self.av_sync_delay, self.av_sync_delay_target, rdelta, AV_SYNC_RATE_CHANGE, delta)
        self.av_sync_delay += rdelta
        if self.av_sync_delay!=self.av_sync_delay_target:
            self.schedule_av_sync_update(AV_SYNC_TIME_CHANGE)


    def set_new_encoding(self, encoding:str, strict:bool) -> None:
        if strict is not None or STRICT_MODE:
            self.strict = strict or STRICT_MODE
        if self.encoding==encoding:
            return
        self.statistics.reset()
        self.update_encoding_selection(encoding)


    def update_encoding_selection(self, encoding=None, exclude=(), init:bool=False) -> None:
        #now we have the real list of encodings we can use:
        #"rgb32" and "rgb24" encodings are both aliased to "rgb"
        if self._mmap_size>0 and self.encoding!="grayscale":
            self.auto_refresh_encodings = ()
            self.encoding = "mmap"
            self.encodings = ("mmap", )
            self.common_encodings = ("mmap", )
            self.get_best_encoding = self.encoding_is_mmap
            return
        common_encodings = [x for x in self._encoders if x in self.core_encodings and x not in exclude]
        self.common_encodings = preforder(common_encodings)
        if not self.common_encodings:
            raise ValueError("no common encodings found (server: %s vs client: %s, excluding: %s)" % (
                csv(self._encoders.keys()), csv(self.core_encodings), csv(exclude)))
        #ensure the encoding chosen is supported by this source:
        if (encoding in self.common_encodings or encoding in ("stream", "auto", "grayscale")) and len(self.common_encodings)>1:
            self.encoding = encoding
        else:
            self.encoding = self.common_encodings[0]
        log("ws.update_encoding_selection(%s, %s, %s) encoding=%s, common encodings=%s",
            encoding, exclude, init, self.encoding, self.common_encodings)
        assert self.encoding is not None
        #auto-refresh:
        if self.client_refresh_encodings:
            #client supplied list, honour it:
            ropts = set(self.client_refresh_encodings)
        else:
            #sane defaults:
            ropts = set(REFRESH_ENCODINGS)  #default encodings for auto-refresh
        if (self.refresh_quality<100 or not TRUE_LOSSLESS) and self.image_depth>16:
            ropts.add("jpeg")
            ropts.add("jpega")
        are : Tuple[str,...] = ()
        if self.supports_transparency:
            are = tuple(x for x in self.common_encodings if x in ropts and x in TRANSPARENCY_ENCODINGS)
        if not are:
            are = tuple(x for x in self.common_encodings if x in ropts) or self.common_encodings
        self.auto_refresh_encodings = tuple(x for x in PREFERRED_REFRESH_ENCODING_ORDER if x in are)
        if not self.auto_refresh_encodings:
            self.auto_refresh_encodings = preforder(are)
        log("update_encoding_selection: client refresh encodings=%s, auto_refresh_encodings=%s",
            self.client_refresh_encodings, self.auto_refresh_encodings)
        self.update_quality()
        self.update_speed()
        self.update_encoding_options()
        self.update_refresh_attributes()

    def update_encoding_options(self, force_reload:bool=False) -> None:
        cv = self.global_statistics.congestion_value
        self._want_alpha = self.is_tray or (self.has_alpha and self.supports_transparency)
        ww, wh = self.window_dimensions
        opr = self._opaque_region
        for coords in opr:
            r = rectangle(*coords)
            if r.contains(0, 0, ww, wh):
                #window is fully opaque
                self._want_alpha = False
                break
        self._lossless_threshold_base = max(0, min(90, 60+self._current_speed//5 + int(cv*100) - int(self.is_shadow)*20))
        self._lossless_threshold_pixel_boost = max(5, 20-self._current_speed//5)
        #calculate the threshold for using rgb
        #if speed is high, assume we have bandwidth to spare
        smult = max(0.25, (self._current_speed-50)/5.0)
        qmult = max(0.0, self._current_quality/20.0)
        pcmult = min(20.0, 0.5+self.statistics.packet_count)/20.0
        max_rgb_threshold = 16*1024
        min_rgb_threshold = 2048
        if cv>0.1:
            max_rgb_threshold = int(32*1024/(1+cv))
            min_rgb_threshold = 1024
        bwl = self.bandwidth_limit
        if bwl:
            max_rgb_threshold = min(max_rgb_threshold, max(bwl//1000, 1024))
        weight = 1 + int(self.is_OR or self.is_tray or self.is_shadow)*2
        v = int(MAX_PIXELS_PREFER_RGB * pcmult * smult * qmult * weight)
        crs = self.client_render_size
        if crs and DOWNSCALE and (crs[0]<ww or crs[1]<wh):
            #client will downscale, best to avoid sending rgb,
            #so we can more easily downscale at this end:
            max_rgb_threshold = 1024
        self._rgb_auto_threshold = min(max_rgb_threshold, max(min_rgb_threshold, v))
        #for deciding between small regions and full screen updates:
        self.max_small_regions = 40
        self.max_bytes_percent = 60
        self.small_packet_cost = 1024
        if self._mmap_size>0:
            #with mmap, we can move lots of data around easily
            #so favour large screen updates over small packets
            self.max_small_regions = 10
            self.max_bytes_percent = 25
            self.small_packet_cost = 4096
        elif self.content_type=="desktop":
            #in desktop mode, many areas will be updating
            #so favour large screen updates
            self.max_small_regions = 20
            self.max_bytes_percent = 40
        self.assign_encoding_getter()
        log("update_encoding_options(%s) wid=%i, want_alpha=%s, speed=%i, quality=%i",
                        force_reload, self.wid, self._want_alpha, self._current_speed, self._current_quality)
        log("lossless threshold: %s / %s, rgb auto threshold=%i (min=%i, max=%i)",
                        self._lossless_threshold_base, self._lossless_threshold_pixel_boost,
                        self._rgb_auto_threshold, min_rgb_threshold, max_rgb_threshold)
        log("bandwidth-limit=%i, get_best_encoding=%s", bwl, self.get_best_encoding)

    def assign_encoding_getter(self) -> None:
        self.get_best_encoding = self.get_best_encoding_impl()

    def get_best_encoding_impl(self) -> Callable:
        if HARDCODED_ENCODING:
            return self.hardcoded_encoding
        if self._encoding_hint and self._encoding_hint in self._encoders:
            return self.encoding_is_hint
        #choose which method to use for selecting an encoding
        #first the easy ones (when there is no choice):
        if self._mmap_size>0 and self.encoding!="grayscale":
            return self.encoding_is_mmap
        if self.encoding=="png/L":
            #(png/L would look awful if we mixed it with something else)
            return self.encoding_is_pngL
        if self.image_depth==8 or self.encoding=="png/P":
            #limited options:
            if self.encoding=="grayscale":
                assert "png/L" in self.common_encodings
                return self.encoding_is_pngL
            assert "png/P" in self.common_encodings
            return self.encoding_is_pngP
        if self.strict and self.encoding not in ("auto", "stream"):
            #honour strict flag
            if self.encoding=="rgb":
                #choose between rgb32 and rgb24 already
                #as alpha support does not change without going through this method
                if self._want_alpha and "rgb32" in self.common_encodings:
                    return self.encoding_is_rgb32
                assert "rgb24" in self.common_encodings
                return self.encoding_is_rgb24
            return self.get_strict_encoding
        if self._want_alpha or self.is_tray:
            if self.encoding in ("rgb", "rgb32") and "rgb32" in self.common_encodings:
                return self.encoding_is_rgb32
            if self.encoding in ("png", "png/P", "png/L"):
                #chosen encoding does alpha, stick to it:
                #(prevents alpha bleeding artifacts,
                # as different encoders may encode alpha differently)
                return self.get_strict_encoding
            if self.encoding=="grayscale":
                return self.encoding_is_grayscale
            #choose an alpha encoding and keep it?
            return self.get_transparent_encoding
        if self.encoding=="rgb":
            #if we're here we don't need alpha, so try rgb24 first:
            if "rgb24" in self.common_encodings:
                return self.encoding_is_rgb24
            if "rgb32" in self.common_encodings:
                return self.encoding_is_rgb32
        return self.get_best_encoding_impl_default()

    def get_best_encoding_impl_default(self) -> Callable:
        #stick to what is specified or use rgb for small regions:
        if self.encoding in ("auto", "stream"):
            return self.get_auto_encoding
        if self.encoding=="grayscale":
            return self.encoding_is_grayscale
        return self.get_current_or_rgb

    @staticmethod
    def hardcoded_encoding(*_args) -> str:
        return HARDCODED_ENCODING

    def encoding_is_hint(self, *_args) -> str:
        return self._encoding_hint

    @staticmethod
    def encoding_is_mmap(*_args) -> str:
        return "mmap"

    @staticmethod
    def encoding_is_pngL(*_args) -> str:
        return "png/L"

    @staticmethod
    def encoding_is_pngP(*_args) -> str:
        return "png/P"

    @staticmethod
    def encoding_is_rgb32(*_args) -> str:
        return "rgb32"

    @staticmethod
    def encoding_is_rgb24(*_args) -> str:
        return "rgb24"

    def get_strict_encoding(self, *_args) -> str:
        return self.encoding

    def encoding_is_grayscale(self, *args) -> str:
        e = self.get_auto_encoding(*args)  #pylint: disable=no-value-for-parameter
        if e.startswith("rgb") or e.startswith("png"):
            return "png/L"
        return e

    def get_transparent_encoding(self, w:int, h:int, options, current_encoding:str) -> str:
        #small areas prefer rgb, also when high speed and high quality
        if current_encoding in TRANSPARENCY_ENCODINGS:
            return current_encoding
        pixel_count = w*h
        depth = self.image_depth
        co = tuple(e for e in self.common_encodings if e in TRANSPARENCY_ENCODINGS)
        if not co and current_encoding:
            return current_encoding
        quality = options.get("quality", self._current_quality)
        lossy = quality<100
        if "rgb32" in co and (
                (pixel_count<self._rgb_auto_threshold) or
                #the only encoding that can preserve higher bit depth at present:
                (not lossy and depth>24 and self.client_bit_depth>24)
            ):
            return "rgb32"
        grayscale = self.encoding=="grayscale"
        webp = "webp" in co and 16383>=w>=2 and 16383>=h>=2 and not grayscale
        if webp and depth in (24, 32) and w*h<=WEBP_EFFICIENCY_CUTOFF:
            return "webp"
        if "jpega" in co and w>=2 and h>=2 and (lossy or not TRUE_LOSSLESS):
            return "jpega"
        if webp:
            return "webp"
        for e in ("png", "rgb32"):
            if e in co:
                return e
        #so we don't have an encoding that does transparency... any will do:
        return self.get_auto_encoding(w, h, options, current_encoding)

    def get_auto_encoding(self, w, h, options, current_encoding=None) -> str:
        return self.do_get_auto_encoding(w, h, options, current_encoding, self.common_encodings)

    def do_get_auto_encoding(self, w, h, options, current_encoding, encoding_options) -> str:
        co = encoding_options
        if not co:
            raise ValueError("no options to choose from")
        depth = self.image_depth
        grayscale = self.encoding=="grayscale"
        alpha = self._want_alpha or self.is_tray
        quality = options.get("quality", 0)
        if self._lossless_threshold_base<quality<100 and self._fixed_quality<=0:
            quality = self._fixed_max_quality
        if w*h<self._rgb_auto_threshold and not grayscale:
            if depth>24 and self.client_bit_depth>24 and "rgb32" in co:
                return "rgb32"
            if "rgb24" in co:
                return "rgb24"
        jpeg = "jpeg" in co and w>=2 and h>=2
        jpega = "jpega" in co and w>=2 and h>=2
        webp = "webp" in co and 16383>=w>=2 and 16383>=h>=2 and not grayscale
        avif = "avif" in co
        lossy = quality<100
        if depth in (24, 32) and (jpeg or jpega or webp or avif):
            if webp and (not lossy or w*h<=WEBP_EFFICIENCY_CUTOFF):
                return "webp"
            if lossy or not TRUE_LOSSLESS:
                if jpeg and not alpha:
                    return "jpeg"
                if jpega and alpha:
                    return "jpega"
            if webp:
                return "webp"
            if avif:
                return "avif"
        elif depth>24 and "rgb32" in co and self.client_bit_depth>24 and self.client_bit_depth!=32:
            #the only encoding that can do higher bit depth at present
            #(typically r210 which is actually rgb30+2)
            return "rgb32"
        if "png" in co and (not lossy or depth<=16):
            return "png"
        if jpeg:
            return "jpeg"
        if avif:
            return "avif"
        if current_encoding in co:
            return current_encoding
        try:
            return next(x for x in co if x!="rgb")
        except StopIteration:
            return co[0]

    def get_current_or_rgb(self, pixel_count, *_args) -> str:
        if pixel_count<self._rgb_auto_threshold:
            if self.image_depth<=24:
                return "rgb24"
            return "rgb32"
        return self.encoding


    def map(self, mapped_at) -> None:
        self.mapped_at = mapped_at
        self.no_idle()

    def unmap(self) -> None:
        self.cancel_damage()
        self.statistics.reset()
        self.go_idle()


    def cancel_damage(self, limit=0.0) -> None:
        """
        Use this method to cancel all currently pending and ongoing
        damage requests for a window.
        Damage methods will check this value via 'is_cancelled(sequence)'.
        """
        damagelog("cancel_damage(%s) wid=%s, dropping delayed region %s, %s queued encodes, and all sequences up to %s",
                  limit, self.wid, self._damage_delayed, len(self.encode_queue), self._sequence)
        #for those in flight, being processed in separate threads, drop by sequence:
        self._damage_cancelled = limit or self._sequence
        self.cancel_expire_timer()
        self.cancel_may_send_timer()
        self.cancel_soft_timer()
        self.cancel_refresh_timer()
        self.cancel_timeout_timer()
        self.cancel_av_sync_timer()
        self.cancel_decode_error_refresh_timer()
        #if a region was delayed, we can just drop it now:
        self.refresh_regions = []
        self._damage_delayed = None
        #make sure we don't account for those as they will get dropped
        #(generally before encoding - only one may still get encoded):
        for sequence in tuple(self.statistics.encoding_pending.keys()):
            if self._damage_cancelled>=sequence:
                self.statistics.encoding_pending.pop(sequence, None)

    def cancel_expire_timer(self) -> None:
        et = self.expire_timer
        if et:
            self.expire_timer = 0
            self.source_remove(et)

    def cancel_may_send_timer(self) -> None:
        mst = self.may_send_timer
        if mst:
            self.may_send_timer = 0
            self.source_remove(mst)

    def cancel_soft_timer(self) -> None:
        st = self.soft_timer
        if st:
            self.soft_timer = 0
            self.source_remove(st)

    def cancel_refresh_timer(self) -> None:
        rt = self.refresh_timer
        if rt:
            self.refresh_timer = 0
            self.source_remove(rt)
            self.refresh_event_time = 0
            self.refresh_target_time = 0

    def cancel_timeout_timer(self) -> None:
        tt = self.timeout_timer
        if tt:
            self.timeout_timer = 0
            self.source_remove(tt)

    def cancel_av_sync_timer(self) -> None:
        avst = self.av_sync_timer
        if avst:
            self.av_sync_timer = 0
            self.source_remove(avst)


    def is_cancelled(self, sequence=INFINITY) -> bool:
        """ See cancel_damage(wid) """
        return self._damage_cancelled>=sequence


    def calculate_batch_delay(self, has_focus, other_is_fullscreen, other_is_maximized) -> None:
        bc = self.batch_config
        if bc.locked:
            return
        if self._mmap_size>0:
            #mmap is so fast that we don't need to use the batch delay:
            bc.delay = bc.min_delay
            return
        #calculations take time (CPU), see if we can just skip it this time around:
        now = monotonic()
        lr = self.statistics.last_recalculate
        elapsed = now-lr
        statslog("calculate_batch_delay for wid=%i current batch delay=%i, last update %.1f seconds ago",
                 self.wid, bc.delay, elapsed)
        if bc.delay<=2*bc.start_delay and lr>0 and elapsed<60 and self.get_packets_backlog()==0:
            #delay is low-ish, figure out if we should bother updating it
            lde = tuple(self.statistics.last_damage_events)
            if not lde:
                return      #things must have got reset anyway
            since_last = tuple((pixels, compressed_size) for t, _, pixels, _, compressed_size, _
                               in tuple(self.statistics.encoding_stats) if t>=lr)
            if len(since_last)<=5:
                statslog("calculate_batch_delay for wid=%i, skipping - only %i events since the last update",
                         self.wid, len(since_last))
                return
            pixel_count = sum(v[0] for v in since_last)
            ww, wh = self.window_dimensions
            if pixel_count<=ww*wh:
                statslog("calculate_batch_delay for wid=%i, skipping - only %i pixels updated since the last update",
                         self.wid, pixel_count)
                return
            if self._mmap_size<=0:
                statslog("calculate_batch_delay for wid=%i, %i pixels updated since the last update",
                         self.wid, pixel_count)
                #if pixel_count<8*ww*wh:
                nbytes = sum(v[1] for v in since_last)
                #less than 16KB/s since last time? (or <=64KB)
                max_bytes = max(4, int(elapsed))*16*1024
                if nbytes<=max_bytes:
                    statslog("calculate_batch_delay for wid=%i, skipping - only %i bytes sent since the last update",
                             self.wid, nbytes)
                    return
                statslog("calculate_batch_delay for wid=%i, %i bytes sent since the last update", self.wid, nbytes)
        calculate_batch_delay(self.wid, self.window_dimensions, has_focus,
                              other_is_fullscreen, other_is_maximized,
                              self.is_OR, self.soft_expired, bc,
                              self.global_statistics, self.statistics, self.bandwidth_limit, self.jitter)
        #update the normalized value:
        ww, wh = self.window_dimensions
        bc.delay_per_megapixel = int(bc.delay*1000000//max(1, (ww*wh)))
        self.statistics.last_recalculate = now
        self.update_av_sync_frame_delay()

    def update_av_sync_frame_delay(self) -> None:
        self.av_sync_frame_delay = 0
        self.may_update_av_sync_delay()

    def update_speed(self) -> None:
        if self.is_cancelled():
            return
        statslog("update_speed() suspended=%s, mmap=%s, current=%i, hint=%i, fixed=%i, encoding=%s, sequence=%i",
                 self.suspended, self._mmap_size>0,
                 self._current_speed, self._speed_hint, self._fixed_speed,
                 self.encoding, self._sequence)
        if self.suspended:
            self._encoding_speed_info = {"suspended" : True}
            return
        if self._mmap_size>0:
            self._encoding_speed_info = {"mmap" : True}
            return
        speed = self._speed_hint
        if speed>=0:
            self._current_speed = capr(speed)
            self._encoding_speed_info = {"hint" : True}
            return
        speed = self._fixed_speed
        if speed>=0:
            self._current_speed = capr(speed)
            self._encoding_speed_info = {"fixed" : True}
            return
        if self._sequence<10:
            self._encoding_speed_info = {"pending" : True}
            return
        now = monotonic()
        #make a copy to work on:
        speed_data = list(self._encoding_speed)
        info, target, max_speed = get_target_speed(self.window_dimensions, self.batch_config,
                                                   self.global_statistics, self.statistics,
                                                   self.bandwidth_limit, self._fixed_min_speed, speed_data)
        speed_data.append((monotonic(), target))
        speed = int(time_weighted_average(speed_data, min_offset=1, rpow=1.1))
        speed = max(0, self._fixed_min_speed, speed)
        speed = int(min(self._fixed_max_speed, speed))
        self._current_speed = speed
        statslog("update_speed() speed=%2i (target=%2i, max=%2i) for wid=%i, info=%s",
                 speed, target, max_speed, self.wid, info)
        self._encoding_speed_info = info
        self._encoding_speed.append((monotonic(), speed))
        ww, wh = self.window_dimensions
        self.global_statistics.speed.append((now, ww*wh, speed))

    def set_min_speed(self, min_speed:int) -> None:
        min_speed = capr(min_speed)
        if self._fixed_min_speed!=min_speed:
            if min_speed>0:
                self._fixed_speed = 0
            self._fixed_min_speed = min_speed
            self.reconfigure(True)

    def set_max_speed(self, max_speed:int) -> None:
        max_speed = capr(max_speed)
        if self._fixed_max_speed!=max_speed:
            self._fixed_max_speed = max_speed
            self.reconfigure(True)

    def set_speed(self, speed:int) -> None:
        speed = capr(speed)
        if self._fixed_speed!=speed:
            self._fixed_speed = speed
            self._current_speed = speed
            self.reconfigure(True)


    def update_quality(self) -> None:
        if self.is_cancelled():
            return
        statslog("update_quality() suspended=%s, mmap_size=%s, current=%i, hint=%i, fixed=%i, encoding=%s, sequence=%i",
                 self.suspended, self._mmap_size,
                 self._current_quality, self._quality_hint, self._fixed_quality,
                 self.encoding, self._sequence)
        if self.suspended:
            self._encoding_quality_info = {"suspended" : True}
            return
        if self._mmap_size>0:
            self._encoding_quality_info = {"mmap" : True}
            return
        quality = self._quality_hint
        if quality>=0:
            self._current_quality = capr(quality)
            self._encoding_quality_info = {"hint" : True}
            return
        quality = self._fixed_quality
        if quality>=0:
            self._current_quality = capr(quality)
            self._encoding_quality_info = {"fixed" : True}
            return
        if self.encoding in LOSSLESS_ENCODINGS:
            #the user has selected an encoding which does not use quality
            #so skip the calculations!
            self._encoding_quality_info = {"lossless" : self.encoding}
            self._current_quality = 100
            return
        if self._sequence<10:
            self._encoding_quality_info = {"pending" : True}
            return
        if self.window_type.intersection(LOSSLESS_WINDOW_TYPES):
            self._encoding_quality_info = {"lossless-window-type" : self.window_type}
            self._current_quality = 100
            return
        now = monotonic()
        info, target = get_target_quality(self.window_dimensions, self.batch_config,
                                          self.global_statistics, self.statistics,
                                          self.bandwidth_limit, self._fixed_min_quality, self._fixed_min_speed)
        #make a copy to work on:
        ves_copy = list(self._encoding_quality)
        ves_copy.append((now, target))
        quality = int(time_weighted_average(ves_copy, min_offset=0.1, rpow=1.2))
        quality = max(0, self._fixed_min_quality, quality)
        quality = int(min(self._fixed_max_quality, quality))
        self._current_quality = quality
        statslog("update_quality() quality=%2i (target=%2i) for wid=%i, info=%s", quality, target, self.wid, info)
        self._encoding_quality_info = info
        self._encoding_quality.append((now, quality))
        ww, wh = self.window_dimensions
        self.global_statistics.quality.append((now, ww*wh, quality))

    def set_min_quality(self, min_quality:int) -> None:
        min_quality = capr(min_quality)
        if self._fixed_min_quality!=min_quality:
            if min_quality>0:
                self._fixed_quality = 0
            self._fixed_min_quality = min_quality
            self.update_quality()
            self.reconfigure(True)

    def set_max_quality(self, max_quality:int) -> None:
        max_quality = capr(max_quality)
        if self._fixed_max_quality!=max_quality:
            self._fixed_max_quality = max_quality
            self.update_quality()
            self.reconfigure(True)

    def set_quality(self, quality:int) -> None:
        quality = capr(quality)
        if self._fixed_quality!=quality:
            self._fixed_quality = quality
            self._current_quality = self._fixed_quality
            self.reconfigure(True)


    def update_refresh_attributes(self) -> None:
        if self._mmap_size>0:
            #not used since mmap is lossless
            return
        if self.auto_refresh_delay==0:
            self.base_auto_refresh_delay = 0
            return
        ww, wh = self.window_dimensions
        cv = self.global_statistics.congestion_value
        #try to take into account:
        # - window size: bigger windows are more costly, refresh more slowly
        # - when quality is low, we can refresh more slowly
        # - when speed is low, we can also refresh slowly
        # - delay a lot more when we have bandwidth issues
        sizef = sqrt(ww*wh/(1000*1000))      #more than 1 megapixel -> delay more
        qf = (150-self._current_quality)/100.0
        sf = (150-self._current_speed)/100.0
        cf = (100+cv*500)/100.0    #high congestion value -> very high delay
        #bandwidth limit is used to set a minimum on the delay
        min_delay = int(max(100*cf, self.auto_refresh_delay, 50 * sizef, self.batch_config.delay*4))
        bwl = self.bandwidth_limit or 0
        if bwl>0:
            #1Mbps -> 1s, 10Mbps -> 0.1s
            min_delay = max(min_delay, 1000*1000*1000//bwl)
        max_delay = int(1000*cf)
        raw_delay = int(sizef * qf * sf * cf)
        if self.content_type.find("text")>=0:
            raw_delay = raw_delay*2//3
        elif self.content_type=="video":
            raw_delay = raw_delay*3//2
        delay = max(min_delay, min(max_delay, raw_delay))
        refreshlog("update_refresh_attributes() wid=%i, sizef=%.2f, content-type=%s, qf=%.2f, sf=%.2f, cf=%.2f, batch delay=%i, bandwidth-limit=%s, min-delay=%i, max-delay=%i, delay=%i",
                   self.wid, sizef, self.content_type, qf, sf, cf, self.batch_config.delay, bwl, min_delay, max_delay, delay)
        self.do_set_auto_refresh_delay(min_delay, delay)
        rs = AUTO_REFRESH_SPEED
        rq = AUTO_REFRESH_QUALITY
        bits_per_pixel = bwl/(1+ww*wh)
        if self._current_quality<70 and (cv>0.1 or (bwl>0 and bits_per_pixel<1)):
            #when bandwidth is scarce, don't use lossless refresh,
            #switch to almost-lossless:
            rs = AUTO_REFRESH_SPEED//2
            rq = 100-cv*10
            if bwl>0:
                rq -= sqrt(1000*1000//bwl)
            rs = min(50, max(0, rs))
            rq = min(99, max(80, int(rq), self._current_quality+30))
        refreshlog("update_refresh_attributes() wid=%i, refresh quality=%i%%, refresh speed=%i%%, for cv=%.2f, bwl=%i",
                   self.wid, rq, rs, cv, bwl)
        self.refresh_quality = rq
        self.refresh_speed = rs

    def do_set_auto_refresh_delay(self, min_delay:int, delay:int) -> None:
        refreshlog("do_set_auto_refresh_delay%s", (min_delay, delay))
        self.min_auto_refresh_delay = int(min_delay)
        self.base_auto_refresh_delay = int(delay)


    def reconfigure(self, force_reload=False) -> None:
        self.update_quality()
        self.update_speed()
        self.update_encoding_options(force_reload)
        self.update_refresh_attributes()


    def damage(self, x : int, y : int, w : int, h : int, options=None) -> None:
        """ decide what to do with the damage area:
            * send it now (if not congested)
            * add it to an existing delayed region
            * create a new delayed region if we find the client needs it
            Also takes care of updating the batch-delay in case of congestion.
            The options dict is currently used for carrying the
            "quality" and "override_options" values, and potentially others.
            When damage requests are delayed and bundled together,
            specify an option of "override_options"=True to
            force the current options to override the old ones,
            otherwise they are only merged.
        """
        self.ui_thread_check()
        if self.suspended:
            return
        if w==0 or h==0:
            damagelog("damage%-24s ignored zero size", (x, y, w, h, options))
            #we may fire damage ourselves,
            #in which case the dimensions may be zero (if so configured by the client)
            return
        now = monotonic()
        if options is None:
            options = {}
        if options.pop("damage", False):
            damagelog("damage%s wid=%i", (x, y, w, h, options), self.wid)
            self.statistics.last_damage_events.append((now, x,y,w,h))
            self.global_statistics.damage_events_count += 1
            self.statistics.damage_events_count += 1
        ww, wh = self.may_update_window_dimensions()
        if ww==0 or wh==0:
            damagelog("damage%s window size %ix%i ignored", (x, y, w, h, options), ww, wh)
            return
        if ww>MAX_WINDOW_SIZE or wh>MAX_WINDOW_SIZE:
            if first_time(f"window-oversize-{self.wid}"):
                damagelog("")
                damagelog.warn("Warning: invalid window dimensions %ix%i for window %i", ww, wh, self.wid)
                damagelog.warn(" window updates will be dropped until this is corrected")
            else:
                damagelog("ignoring damage for window %i size %ix%i", self.wid, ww, wh)
            return
        if self.full_frames_only:
            x, y, w, h = 0, 0, ww, wh
        self.do_damage(ww, wh, x, y, w, h, options)
        self.statistics.last_damage_event_time = now

    def do_damage(self, ww : int, wh : int, x : int, y : int, w : int, h : int, options) -> None:
        now = monotonic()
        if self.refresh_timer and options.get("quality", self._current_quality)<self.refresh_quality:
            rr = tuple(self.refresh_regions)
            if rr:
                #does this screen update intersect with
                #the areas that are due to be refreshed?
                overlap = sum(rect.width*rect.height for rect in rr)
                if overlap>0:
                    pct = int(min(100, 100*overlap//(ww*wh)) * (1+self.global_statistics.congestion_value))
                    sched_delay = max(self.min_auto_refresh_delay, int(self.base_auto_refresh_delay * pct // 100))
                    self.refresh_target_time = max(self.refresh_target_time, now + sched_delay/1000.0)

        delayed = self._damage_delayed
        if delayed:
            #use existing delayed region:
            regions = delayed.regions
            if self.full_frames_only or len(regions) >= self.max_small_regions:
                delayed.regions = regions = [rectangle(0, 0, ww, wh)]
            else:
                region = rectangle(x, y, w, h)
                add_rectangle(regions, region)
            #merge/override options
            if options is not None:
                override = options.get("override_options", False)
                existing_options = delayed.options
                for k in options.keys():
                    if k=="override_options":
                        continue
                    if override or k not in existing_options:
                        existing_options[k] = options[k]
            damagelog("do_damage%-24s wid=%s, using existing %i delayed regions created %ims ago",
                (x, y, w, h, options), self.wid, len(regions), 1000*(now-delayed.damage_time))
            if not self.expire_timer and not self.soft_timer and self.soft_expired==0:
                log.error("Error: bug, found a delayed region without a timer!")
                self.expire_timer = self.timeout_add(0, self.expire_delayed_region, now)
            return

        #create a new delayed region:
        regions = [rectangle(x, y, w, h)]
        delay = options.get("delay", self.batch_config.delay)
        resize_elapsed = int(1000*(now-self.statistics.last_resized))
        if resize_elapsed<500:
            try:
                #batch more when recently resized,
                #but only if this is not the first recent resize event:
                if now-self.statistics.resize_events[-2]<1:
                    delay += (500-resize_elapsed)//2
            except IndexError:
                pass
        gs = self.global_statistics
        congestion_elapsed = -1
        if gs:
            congestion_elapsed = int(1000*(now-gs.last_congestion_time))
            if congestion_elapsed<1000:
                delay += (1000-congestion_elapsed)//4
        #raise min_delay with qsize:
        min_delay = max(0, self.batch_config.min_delay * max(2, self.queue_size())//2 - FRAME_OVERHEAD)
        delay = max(delay, options.get("min_delay", min_delay))
        delay = min(delay, options.get("max_delay", self.batch_config.max_delay))
        delay = int(delay)
        elapsed = int(1000*(now-self.batch_config.last_event))
        #discount the elapsed time since the last event:
        target_delay = delay
        delay = max(0, delay-elapsed)
        actual_encoding = options.get("encoding", self.encoding)
        self._damage_delayed = DelayedRegions(now, regions, actual_encoding, options)
        expire_delay = min(self.batch_config.expire_delay, delay)
        #weighted average with the last delays:
        #(so when we end up delaying a lot for some reason,
        # then we don't expire the next one quickly after)
        inc = 0
        try:
            for v in (self.batch_config.last_actual_delay, self.batch_config.last_delay):
                if v is None:
                    continue
                when, d = v
                delta = now-when
                if d>expire_delay and delta<5:
                    weight = (5-delta)/10
                    inc = max(inc, int((d-expire_delay)*weight))
            expire_delay += inc
        except IndexError:
            pass
        lad = (now, delay)
        self.batch_config.last_delays.append(lad)
        self.batch_config.last_delay = lad
        damagelog("do_damage%-24s wid=%s, scheduling batching expiry for sequence %4i in %3i ms",
                  (x, y, w, h, options), self.wid, self._sequence, expire_delay)
        damagelog(" delay=%i, elapsed=%i, resize_elapsed=%i, congestion_elapsed=%i, batch=%i, min=%i, inc=%i",
                  delay, elapsed, resize_elapsed, congestion_elapsed, self.batch_config.delay, min_delay, inc)
        due = now+expire_delay/1000.0
        self.expire_timer = self.timeout_add(expire_delay, self.expire_delayed_region, due, target_delay)

    def may_update_window_dimensions(self) -> Tuple[int,int]:
        ww, wh = self.window.get_dimensions()
        if self.window_dimensions != (ww, wh):
            self.update_window_dimensions(ww, wh)
        return ww, wh

    def update_window_dimensions(self, ww, wh):
        now = monotonic()
        self.statistics.last_resized = now
        self.statistics.resize_events.append(now)
        log("window dimensions changed from %s to %s", self.window_dimensions, (ww, wh))
        self.window_dimensions = ww, wh
        self.encode_queue_max_size = max(2, min(30, MAX_SYNC_BUFFER_SIZE//(ww*wh*4)))


    def get_packets_backlog(self) -> int:
        s = self.statistics
        gs = self.global_statistics
        if not s or not gs:
            return 0
        latency_tolerance_pct = int(min(self._damage_packet_sequence, 10) *
                                    min(monotonic()-gs.last_congestion_time, 10))
        latency = s.target_latency + ACK_JITTER/1000*(1+latency_tolerance_pct/100)
        #log("get_packets_backlog() latency=%s (target=%i, tolerance=%i)",
        #         1000*latency, 1000*s.target_latency, latency_tolerance_pct)
        return s.get_late_acks(latency)

    def expire_delayed_region(self, due=0, target_delay=100) -> bool:
        """ mark the region as expired so damage_packet_acked can send it later,
            and try to send it now.
        """
        self.expire_timer = 0
        delayed = self._damage_delayed
        if not delayed:
            damagelog("expire_delayed_region() already processed")
            #region has been sent
            return False
        if self.soft_timer:
            #a soft timer will take care of it soon
            damagelog("expire_delayed_region() soft timer will take care of it")
            return False
        damagelog("expire_delayed_region(%i, %i) delayed region=%s", due, target_delay, delayed)
        delayed.expired = True
        self.cancel_may_send_timer()
        self.may_send_delayed()
        if not self._damage_delayed:
            #got sent
            return False
        now = monotonic()
        if now<due:
            damagelog("expire_delayed_region(%i, %i) due in %i ms",
                      due, target_delay, 1000*(due-now))
            #not due yet, don't allow soft expiry, just try again later:
            delay = int(1000*(due-now))
            expire_delay = max(self.batch_config.min_delay, min(self.batch_config.expire_delay, delay))
            self.expire_timer = self.timeout_add(expire_delay, self.expire_delayed_region, due)
            return False
        #the region has not been sent yet because we are waiting for damage ACKs from the client
        max_soft_expired = min(1+self.statistics.damage_events_count//2, self.max_soft_expired)
        if self.soft_expired<max_soft_expired:
            damagelog("expire_delayed_region: soft expired %i (max %i)", self.soft_expired, max_soft_expired)
            #there aren't too many regions soft expired yet
            #so use the "soft timer":
            self.soft_expired += 1
            # we have already waited for "expire delay" to get here,
            # wait gradually longer as we soft-expire more regions:
            soft_delay = self.soft_expired*target_delay
            self.soft_timer = self.timeout_add(soft_delay, self.delayed_region_soft_timeout)
        else:
            damagelog("expire_delayed_region: soft expire limit reached: %i", max_soft_expired)
            if max_soft_expired==self.max_soft_expired:
                #only record this congestion if this is a new event,
                #otherwise we end up perpetuating it
                #because congestion events lower the latency tolerance
                #which makes us more sensitive to packets backlog
                celapsed = monotonic()-self.global_statistics.last_congestion_time
                if celapsed<10:
                    late_pct = 2*100*self.soft_expired
                    delay = now-due
                    self.networksend_congestion_event(f"soft-expire limit: {delay}ms,"+
                                                      f" {self.soft_expired}/{self.max_soft_expired}",
                                                      late_pct)
            #NOTE: this should never happen...
            #the region should now get sent when we eventually receive the pending ACKs
            #but if somehow they go missing... clean it up from a timeout:
            if not self.timeout_timer:
                delayed_region_time = delayed.damage_time
                self.timeout_timer = self.timeout_add(self.batch_config.timeout_delay,
                                                      self.delayed_region_timeout, delayed_region_time)
        return False

    def delayed_region_soft_timeout(self) -> bool:
        self.soft_timer = 0
        log("delayed_region_soft_timeout() soft_expired=%i, max_soft_expired=%i",
                 self.soft_expired, self.max_soft_expired)
        self.do_send_delayed()
        return False

    def delayed_region_timeout(self, delayed_region_time) -> bool:
        self.timeout_timer = 0
        delayed = self._damage_delayed
        if delayed is None:
            #delayed region got sent
            return False
        region_time = delayed.damage_time
        if region_time!=delayed_region_time:
            #this is a different region
            return False
        #ouch: same region!
        now = monotonic()
        options = delayed.options
        elapsed = int(1000 * (now - region_time))
        log.warn("Warning: delayed region timeout")
        log.warn(" region is %i seconds old, will retry - bad connection?", elapsed//1000)
        self._log_late_acks(log.warn)
        #re-try: cancel anything pending and do a full quality refresh
        self.cancel_damage()
        self.cancel_expire_timer()
        self.cancel_refresh_timer()
        self.cancel_soft_timer()
        self._damage_delayed = None
        self.full_quality_refresh(options)
        return False

    def _log_late_acks(self, log_fn : Callable) -> None:
        dap = dict(self.statistics.damage_ack_pending)
        if dap:
            now = monotonic()
            log_fn(" %i late responses:", len(dap))
            for seq in sorted(dap.keys()):
                ack_data = dap[seq]
                if ack_data[3]==0:
                    log_fn(" %6i %-5s: queued but not sent yet", seq, ack_data[1])
                else:
                    log_fn(" %6i %-5s: %3is", seq, ack_data[1], now-ack_data[3])


    def _may_send_delayed(self) -> None:
        #this method is called from the timer,
        #we know we can clear it (and no need to cancel it):
        self.may_send_timer = 0
        self.may_send_delayed()

    def may_send_delayed(self) -> None:
        """ send the delayed region for processing if the time is right """
        dd = self._damage_delayed
        if not dd:
            log("window %s delayed region already sent", self.wid)
            return
        if not dd.expired:
            #we must wait for expire_delayed_region()
            return
        damage_time = dd.damage_time
        packets_backlog = self.get_packets_backlog()
        now = monotonic()
        actual_delay = int(1000 * (now-damage_time))
        if packets_backlog>0:
            if actual_delay>self.batch_config.timeout_delay:
                log("send_delayed for wid %s, elapsed time %ims is above limit of %.1f",
                    self.wid, actual_delay, self.batch_config.timeout_delay)
                key = f"timeout-damage-delay:{self.wid}-{damage_time}"
                if first_time(key):
                    log.warn("Warning: timeout on screen updates for window %i,", self.wid)
                    log.warn(" already delayed for more than %i seconds", actual_delay//1000)
                self.statistics.reset_backlog()
                return
            log("send_delayed for wid %s, sequence %i, delaying again because of backlog:",
                self.wid, self._sequence)
            log(" batch delay is %i, elapsed time is %ims", self.batch_config.delay, actual_delay)
            if actual_delay>=1000:
                self._log_late_acks(log)
            else:
                log(" %s packets", packets_backlog)
            #this method will fire again from damage_packet_acked
            return
        #if we're here, there is no packet backlog, but there may be damage acks pending or a bandwidth limit to honour,
        #if there are acks pending, may_send_delayed() should be called again from damage_packet_acked,
        #if not, we must either process the region now or set a timer to check again later
        def check_again(delay=actual_delay/10.0):
            #schedules a call to check again:
            delay = int(min(self.batch_config.max_delay, max(10.0, delay)))
            self.may_send_timer = self.timeout_add(delay, self._may_send_delayed)
        #locked means a fixed delay we try to honour,
        #this code ensures that we don't fire too early if called from damage_packet_acked
        if self.batch_config.locked:
            if self.batch_config.delay>actual_delay:
                #ensure we honour the fixed delay
                #(as we may get called from a damage ack before we expire)
                check_again(self.batch_config.delay-actual_delay)
            else:
                self.do_send_delayed()
            return
        bwl = self.bandwidth_limit
        if bwl>0:
            used = self.statistics.get_bitrate()
            bandwidthlog("may_send_delayed() wid=%3i : bandwidth limit=%i, used=%i : %i%%",
                         self.wid, bwl, used, 100*used//bwl)
            if used>=bwl:
                check_again(50)
                return
        pixels_encoding_backlog, enc_backlog_count = self.statistics.get_pixels_encoding_backlog()
        ww, wh = self.window_dimensions
        if pixels_encoding_backlog>=(ww*wh):
            log("send_delayed for wid %s, delaying again because too many pixels are waiting to be encoded: %s",
                self.wid, pixels_encoding_backlog)
            if self.statistics.get_acks_pending()==0:
                check_again()
            return
        if enc_backlog_count>10:
            log("send_delayed for wid %s, delaying again because too many damage regions are waiting to be encoded: %s",
                self.wid, enc_backlog_count)
            if self.statistics.get_acks_pending()==0:
                check_again()
            return
        #no backlog, so ok to send, clear soft-expired counter:
        self.soft_expired = 0
        log("send_delayed for wid %s, batch delay is %ims, elapsed time is %ims",
            self.wid, self.batch_config.delay, actual_delay)
        self.do_send_delayed()

    def do_send_delayed(self) -> None:
        self.cancel_timeout_timer()
        self.cancel_soft_timer()
        delayed = self._damage_delayed
        if not delayed:
            return
        self._damage_delayed = None
        damagelog("do_send_delayed() damage delayed=%s", delayed)
        now = monotonic()
        actual_delay = int(1000 * (now-delayed.damage_time))
        lad = (now, actual_delay)
        self.batch_config.last_actual_delays.append(lad)
        self.batch_config.last_actual_delay = lad
        self.batch_config.last_delays.append(lad)
        self.batch_config.last_delay = lad
        self.send_delayed_regions(delayed)

    def send_delayed_regions(self, delayed_regions : DelayedRegions) -> None:
        """ Called by 'send_delayed' when we expire a delayed region,
            There may be many rectangles within this delayed region,
            so figure out if we want to send them all or if we
            just send one full window update instead.
        """
        # It's important to acknowledge changes *before* we extract them,
        # to avoid a race condition.
        self.ui_thread_check()
        if not self.window.is_managed():
            return
        self.window.acknowledge_changes()
        self.batch_config.last_event = monotonic()
        if not self.is_cancelled():
            dr = delayed_regions
            self.send_regions(dr.damage_time, dr.regions, dr.encoding, dr.options)

    def send_regions(self, damage_time, regions, coding : str, options) -> None:
        #window video source overrides this method
        #in order to filter out the video region
        self.do_send_regions(damage_time, regions, coding, options)

    def do_send_regions(self, damage_time, regions, coding : str, options,
                        exclude_region=None, get_best_encoding:Callable=None) -> None:
        ww,wh = self.window_dimensions
        options = self.assign_sq_options(options)
        get_best_encoding = get_best_encoding or self.get_best_encoding
        def get_encoding(w, h):
            return get_best_encoding(w, h, options, coding)

        def send_full_window_update(cause):
            actual_encoding = get_encoding(ww, wh)
            log("send_delayed_regions: using full window update %sx%s as %5s: %s, from %s",
                ww, wh, actual_encoding, cause, get_best_encoding)
            if not actual_encoding:
                raise RuntimeError(f"no encoding for {ww}x{wh} full screen update")
            self.process_damage_region(damage_time, 0, 0, ww, wh, actual_encoding, options)

        if exclude_region is None:
            if self.full_frames_only or self.encoding=="stream":
                send_full_window_update("full-frames-only set")
                return

            if len(regions)>self.max_small_regions:
                #too many regions!
                send_full_window_update(f"too many regions: {len(regions)}")
                return
            if ww*wh<=MIN_WINDOW_REGION_SIZE:
                #size is too small to bother with regions:
                send_full_window_update(f"small window: {ww}x{wh}")
                return
            regions = tuple(set(regions))
        else:
            non_ex = set()
            for r in regions:
                for v in r.subtract_rect(exclude_region):
                    non_ex.add(v)
            regions = tuple(non_ex)

        if MERGE_REGIONS and len(regions)>1:
            merge_threshold = ww*wh*self.max_bytes_percent//100
            pixel_count = sum(rect.width*rect.height for rect in regions)
            packet_cost = pixel_count+self.small_packet_cost*len(regions)
            log("send_delayed_regions: packet_cost=%s, merge_threshold=%s, pixel_count=%s",
                packet_cost, merge_threshold, pixel_count)
            if packet_cost>=merge_threshold and exclude_region is None:
                send_full_window_update(f"bytes cost ({packet_cost}) too high (max {merge_threshold})")
                return
            #try to merge all the regions to see if we save anything:
            merged = merge_all(regions)
            if exclude_region:
                merged_rects = merged.subtract_rect(exclude_region)
                merged_pixel_count = sum(r.width*r.height for r in merged_rects)
            else:
                merged_rects = (merged,)
                merged_pixel_count = merged.width*merged.height
            merged_packet_cost = merged_pixel_count+self.small_packet_cost*len(merged_rects)
            log("send_delayed_regions: merged=%s, merged_bytes_cost=%s, bytes_cost=%s, merged_pixel_count=%s, pixel_count=%s",
                     merged_rects, merged_packet_cost, packet_cost, merged_pixel_count, pixel_count)
            if self._mmap_size>0 or merged_packet_cost<packet_cost or merged_pixel_count<pixel_count:
                #better, so replace with merged regions:
                regions = merged_rects

        if not regions:
            #nothing left after removing the exclude region
            return
        if len(regions)==1:
            merged = regions[0]
            #if we end up with just one region covering almost the entire window,
            #refresh the whole window (ie: when the video encoder mask rounded the dimensions down)
            if merged.x<=1 and merged.y<=1 and abs(ww-merged.width)<2 and abs(wh-merged.height)<2:
                send_full_window_update("merged region covers almost the whole window")
                return

        #figure out which encoding will get used,
        #and shortcut out if this needs to be a full window update:
        i_reg_enc = []
        for i,region in enumerate(regions):
            actual_encoding = get_encoding(region.width, region.height)
            if self.must_encode_full_frame(actual_encoding):
                log("send_delayed_regions: using full frame for %s encoding of %ix%i",
                    actual_encoding, region.width, region.height)
                self.process_damage_region(damage_time, 0, 0, ww, wh, actual_encoding, options)
                #we can stop here (full screen update will include the other regions)
                return
            i_reg_enc.append((i, region, actual_encoding))

        #reversed so that i=0 is last for flushing
        log("send_delayed_regions: queuing %i regions", len(i_reg_enc))
        encodings = []
        for i, region, actual_encoding in reversed(i_reg_enc):
            if not self.process_damage_region(damage_time, region.x, region.y, region.width, region.height,
                                              actual_encoding, options, flush=i):
                log("failed on %i: %s", i, region)
            encodings.append(actual_encoding)
        log("send_delayed_regions: queued %i regions for encoding using %s", len(i_reg_enc), encodings)


    def assign_sq_options(self, options, speed_pct : int=100, quality_pct : int=100) -> Dict[str,Any]:
        packets_backlog = None
        speed = options.get("speed", 0)
        if speed==0:
            if self._fixed_speed>0:
                speed = self._fixed_speed
            else:
                speed = self._current_speed
                packets_backlog = self.get_packets_backlog()
                speed = (speed - packets_backlog*20) * speed_pct // 100
                speed = min(self._fixed_max_speed, max(1, self._fixed_min_speed, speed))
        quality = options.get("quality", 0)
        if quality==0:
            if self._fixed_quality>0:
                quality = self._fixed_quality
            else:
                text_hint = self.content_type.find("text") >= 0
                quality = TEXT_QUALITY if text_hint else self._current_quality
                if packets_backlog is None:
                    packets_backlog = self.get_packets_backlog()
                now = monotonic()
                if not packets_backlog:
                    #if we haven't sent any packets for a while,
                    #chances are that we can raise the quality,
                    #at least for the first packet:
                    elapsed = now-self.statistics.last_packet_time
                    quality += int(elapsed*25)
                scaling_discount = 0
                if "scaled-width" in options or "scaled-height" in options:
                    scaling_discount = 20
                quality = (quality - packets_backlog*20 - scaling_discount) * quality_pct // 100
                quality = min(self._fixed_max_quality, max(1, self._fixed_min_quality, quality))
        eoptions = dict(options)
        eoptions.update({
            "quality"   : quality,
            "speed"     : speed,
            "rgb_formats"   : self.rgb_formats,
            "lz4"       : self.rgb_lz4,
            })
        if self.encoding=="grayscale":
            eoptions["grayscale"] = True
        if not self.supports_transparency:
            eoptions["alpha"] = False
        if self.content_type:
            eoptions["content-type"] = self.content_type
        return eoptions


    def must_encode_full_frame(self, _encoding : str) -> bool:
        #WindowVideoSource overrides this method
        return self.full_frames_only


    def free_image_wrapper(self, image : ImageWrapper) -> None:
        """ when not running in the UI thread,
            call this method to free an image wrapper safely
        """
        #log("free_image_wrapper(%s) thread_safe=%s", image, image.is_thread_safe())
        if image.is_thread_safe():
            image.free()
        else:
            def do_free_image():
                with ui_context:
                    image.free()
            self.idle_add(do_free_image)


    def get_damage_image(self, x:int, y:int, w:int, h:int) -> Optional[ImageWrapper]:
        self.ui_thread_check()
        def nodata(msg, *args) -> Optional[ImageWrapper]:
            log("get_damage_image: "+msg, *args)
            return None
        if not self.window.is_managed():
            return nodata("the window %s is not managed", self.window)
        ww, wh = self.may_update_window_dimensions()
        if x+w<0 or y+h<0:
            return nodata(f"dropped, window is offscreen at {x},{y}")
        if x+w>ww or y+h>wh:
            #window is now smaller than the region we're trying to request
            w = ww-x
            h = wh-y
        if w<=0 or h<=0:
            return nodata(f"dropped, invalid dimensions {w},{h}")
        self._sequence += 1
        sequence = self._sequence
        if self.is_cancelled(sequence):
            return nodata("sequence %s is cancelled", sequence)
        image = self.window.get_image(x, y, w, h)
        if image is None:
            return nodata("no pixel data for window %s, wid=%s", self.window, self.wid)
        #image may have been clipped to the new window size during resize:
        w = image.get_width()
        h = image.get_height()
        if w==0 or h==0:
            return nodata("invalid dimensions: %ix%i", w, h)
        if self.is_cancelled(sequence):
            self.free_image_wrapper(image)
            return nodata("sequence %i is cancelled", sequence)
        pixel_format = image.get_pixel_format()
        image_depth = image.get_depth()
        if image_depth==32 and pixel_format.find("A")>=0:
            alpha = self.has_alpha
            opr = self._opaque_region
            if alpha and opr:
                for coords in opr:
                    r = rectangle(*coords)
                    if r.contains(x, y, w, h):
                        alpha = False
                        break
            if not alpha:
                pixel_format = pixel_format.replace("A", "X")   #ie: BGRA -> BGRX
                image.set_pixel_format(pixel_format)
                image_depth = 24
                log("removed alpha from image metadata: %s", pixel_format)
        self.image_depth = image_depth
        self.pixel_format = pixel_format
        return image

    def process_damage_region(self, damage_time, x : int, y : int, w : int, h : int, coding : str, options, flush=None) -> bool:
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
        assert coding is not None
        rgb_request_time = monotonic()
        image = self.get_damage_image(x, y, w, h)
        if image is None:
            return False
        log("get_damage_image%s took %ims", (x, y, w, h), 1000*(monotonic()-rgb_request_time))
        sequence = self._sequence

        if self.send_window_size:
            options["window-size"] = self.window_dimensions
        resize = self.scaled_size(image)
        if resize:
            sw, sh = resize
            options["scaled-width"] = sw
            options["scaled-height"] = sh

        now = monotonic()
        item = (w, h, damage_time, now, image, coding, sequence, options, flush)
        self.call_in_encode_thread(True, self.make_data_packet_cb, *item)
        log("process_damage_region: wid=%i, sequence=%i, adding pixel data to encode queue (%4ix%-4i - %5s), elapsed time: %3.1f ms, request time: %3.1f ms",
                self.wid, sequence, w, h, coding, 1000*(now-damage_time), 1000*(now-rgb_request_time))
        return True

    def scaled_size(self, image : ImageWrapper) -> Optional[Tuple[int,int]]:
        crs = self.client_render_size
        if not crs or not DOWNSCALE:
            return None
        w, h = image.get_width(), image.get_height()
        ww, wh = self.window_dimensions
        crsw, crsh = crs
        #resize if the render size is smaller
        if ww-crsw>DOWNSCALE_THRESHOLD and wh-crsh>DOWNSCALE_THRESHOLD:
            #keep the same proportions:
            return w*crsw//ww, h*crsh//wh
        return None


    def make_data_packet_cb(self, w : int, h : int, damage_time, process_damage_time,
                            image : ImageWrapper, coding : str, sequence : int, options, flush) -> None:
        """ This function is called from the damage data thread!
            Extra care must be taken to prevent access to X11 functions on window.
        """
        self.statistics.encoding_pending[sequence] = (damage_time, w, h)
        try:
            packet = self.make_data_packet(damage_time, process_damage_time, image, coding, sequence, options, flush)
        except Exception:
            log("make_data_packet%s", (damage_time, process_damage_time, image, coding, sequence, options, flush),
                exc_info=True)
            if not self.is_cancelled(sequence):
                log.error("Error: failed to create data packet", exc_info=True)
            packet = None
        finally:
            self.free_image_wrapper(image)
            del image
            #may have been cancelled whilst we processed it:
            self.statistics.encoding_pending.pop(sequence, None)
        #NOTE: we MUST send it (even if the window is cancelled by now..)
        #because the code may rely on the client having received this frame
        if not packet:
            return
        #queue packet for sending:
        self.queue_damage_packet(packet, damage_time, process_damage_time, options)


    def schedule_auto_refresh(self, packet : Tuple, options) -> None:
        if not self.can_refresh():
            self.cancel_refresh_timer()
            return
        encoding = packet[6]
        data = packet[7]
        region = rectangle(*packet[2:6])    #x,y,w,h
        client_options = packet[10]     #info about this packet from the encoder
        self.do_schedule_auto_refresh(encoding, data, region, client_options, options)

    def do_schedule_auto_refresh(self, encoding : str, data, region, client_options, options) -> None:
        assert data
        if self.encoding=="stream":
            #streaming mode doesn't use refresh
            return
        if encoding.startswith("png"):
            actual_quality = 100
            lossy = self.image_depth>32 or self.image_depth==30
        elif encoding.startswith("rgb") or encoding=="mmap":
            actual_quality = 100
            lossy = False
        else:
            actual_quality = client_options.get("quality", 0)
            lossy = (
                actual_quality<self.refresh_quality or
                client_options.get("csc") in LOSSY_PIXEL_FORMATS or
                client_options.get("scaled_size") is not None
                )
            if encoding=="jpeg" and TRUE_LOSSLESS:
                lossy = True
        refresh_exclude = self.get_refresh_exclude()  #pylint: disable=assignment-from-none
        now = monotonic()
        def rec(msg):
            self.last_auto_refresh_message = now, msg
            refreshlog("auto refresh: %5s screen update (actual quality=%3i, lossy=%5s),"
                       " %s (region=%s, refresh regions=%s, exclude=%s)",
                       encoding, actual_quality, lossy, msg,
                       region, self.refresh_regions, refresh_exclude)
        if not lossy or options.get("auto_refresh", False):
            #subtract this region from the list of refresh regions:
            #(window video source may remove it from the video subregion)
            self.remove_refresh_region(region)
            if not self.refresh_timer:
                #nothing due for refresh, still nothing to do
                return rec("lossless - nothing to do")
            if not self.refresh_regions:
                self.cancel_refresh_timer()
                return rec("covered all regions that needed a refresh, cancelling refresh timer")
            return rec("removed rectangle from regions, keeping existing refresh timer")
        #if we're here: the window is still valid and this was a lossy update,
        #of some form (lossy encoding with low enough quality, or using CSC subsampling, or using scaling)
        #so we probably need an auto-refresh (re-schedule it if one was due already)
        #try to add the rectangle to the refresh list:
        ww, wh = self.window_dimensions
        if ww<=0 or wh<=0:
            self.cancel_refresh_timer()
            return rec("cancelling refresh - window cleaned up?")
        #we may have modified some pixels that were already due to be refreshed,
        #or added new ones to the list:
        window_pixcount = ww*wh
        region_pixcount = region.width*region.height
        if refresh_exclude:
            #there's a video region to exclude
            #(it is handled separately with its own timer)
            window_pixcount -= refresh_exclude.width*refresh_exclude.height
            region_excluded = region.intersection_rect(refresh_exclude)
            if region_excluded:
                region_pixcount -= region_excluded.width*region_excluded.height
        added_pixcount = self.add_refresh_region(region)
        if window_pixcount<=0:
            #if everything was excluded window_pixcount can be 0
            pct = 100
        else:
            pct = 100*region_pixcount//window_pixcount
        if pct==100:
            #everything was updated, start again as new:
            self.cancel_refresh_timer()
        if not self.refresh_timer:
            #timer was not due yet, or we've just updated everything
            if region_pixcount<=0 or not self.refresh_regions:
                return rec("nothing to refresh")
            self.refresh_event_time = now
            #slow down refresh when there is congestion:
            mult = sqrt(pct * (1+self.global_statistics.congestion_value))//10
            sched_delay = max(
                self.batch_config.delay*5,
                self.min_auto_refresh_delay,
                int(self.base_auto_refresh_delay * mult),
                )
            self.refresh_target_time = now + sched_delay/1000.0
            self.refresh_timer = self.timeout_add(sched_delay, self.refresh_timer_function, options)
            return rec(f"scheduling refresh in {sched_delay}ms (pct={pct}, batch={self.batch_config.delay})")
        #some of those rectangles may overlap,
        #so the value may be greater than the size of the window:
        due_pixcount = sum(rect.width*rect.height for rect in self.refresh_regions)
        #a refresh is already due
        if added_pixcount>=due_pixcount//2:
            #we have more than doubled the number of pixels to refresh
            #use the total due
            pct = 100*due_pixcount//window_pixcount
        #don't use sqrt() on pct,
        #so this will not move it forwards for small updates following bigger ones:
        sched_delay = max(
            self.batch_config.delay*5,
            self.min_auto_refresh_delay,
            int(self.base_auto_refresh_delay * pct // 100),
            )
        max_time = self.refresh_event_time + 5*self.base_auto_refresh_delay
        target_time = self.refresh_target_time
        self.refresh_target_time = min(max_time, max(target_time, now + sched_delay/1000.0))
        added_ms = int(1000*(self.refresh_target_time-target_time))
        due_ms = int(1000*(self.refresh_target_time-now))
        if self.refresh_target_time==target_time:
            return rec(f"unchanged refresh: due in {due_ms}ms, pct={pct}")
        rec("re-scheduling refresh: due in %ims, %ims added - sched_delay=%s, pct=%i, batch=%i)" % (
            due_ms, added_ms, sched_delay, pct, self.batch_config.delay))

    def remove_refresh_region(self, region) -> None:
        #removes the given region from the refresh list
        #(also overridden in window video source)
        remove_rectangle(self.refresh_regions, region)

    def add_refresh_region(self, region) -> int:
        #adds the given region to the refresh list
        #returns the number of pixels in the region update
        #(overridden in window video source to exclude the video region)
        #Note: this does not run in the UI thread!
        return add_rectangle(self.refresh_regions, region)

    def can_refresh(self) -> bool:
        if not AUTO_REFRESH:
            return False
        w = self.window
        #safe to call from any thread (does not call X11):
        if not w or not w.is_managed():
            #window is gone
            return False
        if self.auto_refresh_delay<=0 or self.is_cancelled() or not self.auto_refresh_encodings:
            #can happen during cleanup
            return False
        return True

    def refresh_timer_function(self, damage_options) -> bool:
        """ Must be called from the UI thread:
            this makes it easier to prevent races,
            and we're also allowed to use the window object.
            And for that reason, it may re-schedule itself safely here too.
            We figure out if now is the right time to do the refresh,
            and if not re-schedule.
        """
        self.refresh_timer = 0
        # timer is running now, clear it so that we don't try to cancel it somewhere else:
        # re-do some checks that may have changed:
        if not self.can_refresh():
            self.refresh_event_time = 0
            return False
        ret = self.refresh_event_time
        if ret==0:
            return False
        delta = self.refresh_target_time - monotonic()
        if delta<0.050:
            #this is about right (due already or due shortly)
            self.timer_full_refresh()
            return False
        #re-schedule ourselves:
        self.refresh_timer = self.timeout_add(int(delta*1000), self.refresh_timer_function, damage_options)
        refreshlog("refresh_timer_function: rescheduling auto refresh timer with extra delay %ims", int(1000*delta))
        return False

    def timer_full_refresh(self) -> bool:
        #copy event time and list of regions (which may get modified by another thread)
        ret = self.refresh_event_time
        self.refresh_event_time = 0
        regions = self.refresh_regions
        self.refresh_regions = []
        if self.can_refresh() and regions and ret>0:
            now = monotonic()
            options = self.get_refresh_options()
            refresh_exclude = self.get_refresh_exclude()    #pylint: disable=assignment-from-none
            refreshlog("timer_full_refresh() after %ims, auto_refresh_encodings=%s, options=%s, regions=%s, refresh_exclude=%s",
                       1000.0*(monotonic()-ret), self.auto_refresh_encodings, options, regions, refresh_exclude)
            self.do_send_regions(now, regions, self.auto_refresh_encodings[0], options,
                                 exclude_region=refresh_exclude, get_best_encoding=self.get_refresh_encoding)
        return False

    def get_refresh_encoding(self, w : int, h : int, options, coding : str) -> str:
        refresh_encodings = self.auto_refresh_encodings
        encoding = self.do_get_auto_encoding(w, h, options,
                                             refresh_encodings[0], refresh_encodings)
        refreshlog("get_refresh_encoding(%i, %i, %s, %s)=%s", w, h, options, coding, encoding)
        return encoding

    def get_refresh_exclude(self):
        #overridden in window video source to exclude the video subregion
        return None

    def full_quality_refresh(self, damage_options) -> None:
        #can be called from:
        # * xpra control channel
        # * send timeout
        # * client decoding error
        if not self.window or not self.window.is_managed():
            #this window is no longer managed
            return
        if not self.auto_refresh_encodings or self.is_cancelled():
            #can happen during cleanup
            return
        refresh_regions = self.refresh_regions
        #since we're going to refresh the whole window,
        #we don't need to track what needs refreshing:
        self.refresh_regions = []
        w, h = self.window_dimensions
        refreshlog("full_quality_refresh() for %sx%s window with pending refresh regions: %s", w, h, refresh_regions)
        new_options = damage_options.copy()
        encoding = self.auto_refresh_encodings[0]
        new_options.update(self.get_refresh_options())
        refreshlog("full_quality_refresh() using %s with options=%s", encoding, new_options)
        #just refresh the whole window:
        regions = [rectangle(0, 0, w, h)]
        now = monotonic()
        damage = DelayedRegions(now, regions, encoding, new_options)
        self.send_delayed_regions(damage)

    def get_refresh_options(self) -> Dict[str,Any]:
        return {
                "optimize"      : False,
                "auto_refresh"  : True,     #not strictly an auto-refresh, just makes sure we won't trigger one
                "quality"       : self.refresh_quality,
                "speed"         : self.refresh_speed,
                }

    def queue_damage_packet(self, packet, damage_time:float=0, process_damage_time:float=0, options=None) -> None:
        """
            Adds the given packet to the packet_queue,
            (warning: this runs from the non-UI 'encode' thread)
            we also record a number of statistics:
            - damage packet queue size
            - number of pixels in damage packet queue
            - damage latency (via a callback once the packet is actually sent)
        """
        #packet = ["draw", wid, x, y, w, h, coding, data, self._damage_packet_sequence, rowstride, client_options]
        width = int(packet[4])
        height = int(packet[5])
        coding, data, damage_packet_sequence, _, client_options = packet[6:11]
        ldata = len(data)
        actual_batch_delay = process_damage_time-damage_time
        ack_pending = [0, coding, 0, 0, 0, width*height, client_options, damage_time]
        statistics = self.statistics
        statistics.damage_ack_pending[damage_packet_sequence] = ack_pending
        def start_send(bytecount:int):
            ack_pending[0] = monotonic()
            ack_pending[2] = bytecount
        def damage_packet_sent(bytecount:int):
            now = monotonic()
            ack_pending[3] = now
            ack_pending[4] = bytecount
            if process_damage_time>0:
                statistics.damage_out_latency.append((now, width*height, actual_batch_delay, now-process_damage_time))
            elapsed_ms = int((now-ack_pending[0])*1000)
            #only record slow send as congestion events
            #if the bandwidth limit is already below the threshold:
            if ldata>1024 and self.bandwidth_limit<SLOW_SEND_THRESHOLD:
                #if this packet completed late, record congestion send speed:
                max_send_delay = 5 + self.estimate_send_delay(ldata)
                if elapsed_ms>max_send_delay:
                    late_pct = round(elapsed_ms*100/max_send_delay)-100
                    send_speed = int(ldata*8*1000/elapsed_ms)
                    self.networksend_congestion_event("slow send", late_pct, send_speed)
            self.schedule_auto_refresh(packet, options or {})
        if process_damage_time>0:
            now = monotonic()
            damage_in_latency = now-process_damage_time
            statistics.damage_in_latency.append((now, width*height, actual_batch_delay, damage_in_latency))
        #log.info("queuing %s packet with fail_cb=%s", coding, fail_cb)
        self.statistics.last_packet_time = monotonic()
        self.queue_packet(packet, self.wid, width*height, start_send, damage_packet_sent,
                          self.get_fail_cb(packet), client_options.get("flush", 0))

    def networksend_congestion_event(self, source, late_pct:int, cur_send_speed:int=0) -> None:
        gs = self.global_statistics
        if not gs:
            return
        #calculate the send speed for the packet we just sent:
        now = monotonic()
        send_speed = cur_send_speed
        avg_send_speed = 0
        if len(gs.bytes_sent)>=5:
            #find a sample more than a second old
            #(hopefully before the congestion started)
            stime1 = svalue1 = svalue2 = 0
            i = 1
            while i<4:
                stime1, svalue1 = gs.bytes_sent[-i]
                i += 1
                if now-stime1>1:
                    break
            #find a sample more than 4 seconds earlier,
            #with at least 64KB sent in between:
            t = 0
            while i<len(gs.bytes_sent):
                stime2, svalue2 = gs.bytes_sent[-i]
                t = stime1-stime2
                if t>10:
                    #too far back, not enough data sent in 10 seconds
                    break
                if t>=4 and (svalue1-svalue2)>=65536:
                    break
                i += 1
            if 4<=t<=10:
                #calculate the send speed over that interval:
                bcount = svalue1-svalue2
                avg_send_speed = int(bcount*8//t)
                if cur_send_speed:
                    #weighted average,
                    #when we're very late, the value is much more likely to be correct
                    send_speed = (avg_send_speed*100 + cur_send_speed*late_pct)//2//(100+late_pct)
                else:
                    send_speed = avg_send_speed
        bandwidthlog("networksend_congestion_event(%s, %i, %i) %iKbps (average=%iKbps) for wid=%i",
                     source, late_pct, cur_send_speed, send_speed//1024, avg_send_speed//1024, self.wid)
        rtt = self.refresh_target_time
        if rtt:
            #a refresh now would really hurt us!
            self.refresh_target_time = max(rtt, now+2)
        self.record_congestion_event(source, late_pct, send_speed)


    def get_fail_cb(self, packet : Tuple) -> Callable:
        def resend():
            log("paint packet failure, resending")
            x, y, width, height = packet[2:6]
            damage_packet_sequence : int = packet[8]
            self.damage_packet_acked(damage_packet_sequence, width, height, 0, "")
            self.idle_add(self.damage, x, y, width, height)
        return resend

    def estimate_send_delay(self, bytecount : int) -> int:
        #how long it should take to send this packet (in milliseconds)
        #based on the bandwidth available (if we know it):
        bl = self.bandwidth_limit
        if bl>0:
            #estimate based on current bandwidth limit:
            return 1000*bytecount*8//max(200000, bl)
        return int(10*logp(bytecount/1024.0))


    def damage_packet_acked(self, damage_packet_sequence, width, height, decode_time, message) -> None:
        """
            The client is acknowledging a damage packet,
            we record the 'client decode time' (provided by the client itself)
            and the "client latency".
            If we were waiting for pending ACKs to send an expired damage packet,
            check for it.
            (warning: this runs from the non-UI network parse thread,
            don't access the window from here!)
        """
        statslog("packet decoding sequence %s for window %s: %sx%s took %.1fms",
                      damage_packet_sequence, self.wid, width, height, decode_time/1000.0)
        if decode_time>0:
            self.statistics.client_decode_time.append((monotonic(), width*height, decode_time))
        elif decode_time==WINDOW_DECODE_SKIPPED:
            log(f"client skipped decoding sequence {damage_packet_sequence} for window {self.wid}")
        elif decode_time==WINDOW_NOT_FOUND:
            log.warn("Warning: client cannot find window %i", self.wid)
        elif decode_time==WINDOW_DECODE_ERROR:
            self.client_decode_error(decode_time, message)
        pending = self.statistics.damage_ack_pending.pop(damage_packet_sequence, None)
        if pending is None:
            log("cannot find sent time for sequence %s", damage_packet_sequence)
            return
        gs = self.global_statistics
        start_send_at, _, start_bytes, end_send_at, end_bytes, pixels, client_options, damage_time = pending
        bytecount = end_bytes-start_bytes
        #it is possible though unlikely
        #that we get the ack before we've had a chance to call
        #damage_packet_sent, so we must validate the data:
        if bytecount>0 and end_send_at>0:
            now = monotonic()
            if decode_time>0:
                latency = int(1000*(now-damage_time))
                self.global_statistics.record_latency(self.wid, damage_packet_sequence, decode_time,
                                                      start_send_at, end_send_at, pixels, bytecount, latency)
            #we can ignore some packets:
            # * the first frame (frame=0) of video encoders can take longer to decode
            #   as we have to create a decoder context
            frame_no = client_options.get("frame", None)
            # when flushing a screen update as multiple packets (network layer aggregation),
            # we could ignore all but the last one (flush=0):
            #flush = client_options.get("flush", 0)
            if frame_no!=0:
                netlatency = int(1000*gs.min_client_latency*(100+ACK_JITTER)//100)
                sendlatency = min(200, self.estimate_send_delay(bytecount))
                #decode = pixels//100000         #0.1MPixel/s: 2160p -> 8MPixels, 80ms budget
                live_time = int(1000*(now-self.statistics.init_time))
                ack_tolerance = self.jitter + ACK_TOLERANCE + max(0, 200-live_time//10)
                latency = netlatency + sendlatency + decode_time + ack_tolerance
                #late_by and latency are in ms, timestamps are in seconds:
                actual = int(1000*(now-start_send_at))
                late_by = actual-latency
                if late_by>0 and (live_time>=1000 or pixels>=4096):
                    actual_send_latency = actual-netlatency-decode_time
                    late_pct = actual_send_latency*100//(1+sendlatency)
                    if pixels<=4096 or actual_send_latency<=0:
                        #small packets can really skew things, don't bother
                        #(this also filters out scroll packets which are tiny)
                        send_speed = 0
                    else:
                        send_speed = bytecount*8*1000//actual_send_latency
                    #statslog("send latency: expected up to %3i, got %3i, %6iKB sent in %3i ms: %5iKbps",
                    #    latency, actual, bytecount//1024, actual_send_latency, send_speed//1024)
                    self.networksend_congestion_event("late-ack for sequence %6i: late by %3ims, target latency=%3i (%s)" %
                                                       (damage_packet_sequence, late_by, latency, (netlatency, sendlatency, decode_time, ack_tolerance)),
                                                       late_pct, send_speed)
        damage_delayed = self._damage_delayed
        if not damage_delayed:
            self.soft_expired = 0
        elif damage_delayed.expired:
            def call_may_send_delayed():
                log("call_may_send_delayed()")
                self.cancel_may_send_timer()
                self.may_send_delayed()
            #this function is called from the network thread,
            #call via idle_add to prevent race conditions:
            log("ack with expired delayed region: %s", damage_delayed)
            self.idle_add(call_may_send_delayed)

    def client_decode_error(self, error, message) -> None:
        #don't print error code -1, which is just a generic code for error
        emsg = {-1 : ""}.get(error, error)
        def s(v):
            return decode_str(v or b"")
        if emsg:
            emsg = " "+s(emsg).replace("\n", "").replace("\r", "")
        log.warn("Warning: client decoding error:")
        if message or emsg:
            log.warn(" %s%s", s(message), emsg)
        else:
            log.warn(" unknown cause")
        self.global_statistics.decode_errors += 1
        if self.window:
            delay = min(1000, 250+self.global_statistics.decode_errors*100)
            self.decode_error_refresh_timer = self.timeout_add(delay, self.decode_error_refresh)

    def decode_error_refresh(self) -> None:
        self.decode_error_refresh_timer = 0
        self.full_quality_refresh({})

    def cancel_decode_error_refresh_timer(self) -> None:
        dert : int = self.decode_error_refresh_timer
        if dert:
            self.decode_error_refresh_timer = 0
            self.source_remove(dert)


    def may_use_scrolling(self, _image, _options) -> bool:
        #overridden in video source
        return False


    def make_data_packet(self, damage_time, process_damage_time,
                         image : ImageWrapper, coding : str, sequence : int, options, flush) -> Optional[Tuple]:
        """
            Picture encoding - non-UI thread.
            Converts a damage item picked from the 'compression_work_queue'
            by the 'encode' thread and returns a packet
            ready for sending by the network layer.
            The actual encoding method used is: self._encoders[coding], ie:
            * 'mmap' will use 'mmap_encode'
            * 'webp' uses 'webp_encode'
            * 'rgb24' and 'rgb32' use 'rgb_encode'
            * etc..
        """
        def nodata(msg, *args) -> None:
            log("make_data_packet: no data for window %s with sequence=%s: "+msg, self.wid, sequence, *args)
            self.free_image_wrapper(image)
        if self.is_cancelled(sequence):
            return nodata("cancelled")
        if self.suspended:
            return nodata("suspended")
        start = monotonic()
        if SCROLL_ALL and self.may_use_scrolling(image, options):
            return nodata("used scrolling instead")
        end = monotonic()
        log("scroll detection took %ims", 1000*(end-start))
        x = image.get_target_x()
        y = image.get_target_y()
        w = image.get_width()
        h = image.get_height()
        if w<=0 or h<=0:
            raise RuntimeError(f"invalid dimensions: {w}x{h}")

        #more useful is the actual number of bytes (assuming 32bpp)
        #since we generally don't send the padding with it:
        psize = w*h*4
        log("make_data_packet: image=%s, damage data: %s", image, (self.wid, x, y, w, h, coding))
        start = monotonic()

        if self.cuda_device_context:
            options["cuda-device-context"] = self.cuda_device_context
        #by default, don't set rowstride (the container format will take care of providing it):
        encoder = self._encoders.get(coding)
        if encoder is None:
            if self.is_cancelled(sequence):
                return nodata("cancelled")
            raise RuntimeError(f"BUG: no encoder found for {coding!r} with options={options}")
        ret = encoder(coding, image, options)
        if not ret:
            return nodata("no data from encoder %s for %s",
                          get_encoder_type(encoder), (coding, image, options))

        coding, data, client_options, outw, outh, outstride, bpp = ret
        #check for cancellation again since the code above may take some time to encode:
        #but never cancel mmap after encoding because we need to reclaim the space
        #by getting the client to move the mmap received pointer
        if coding!="mmap":
            if self.is_cancelled(sequence):
                return nodata("cancelled after encoding")
            if self.suspended:
                return nodata("suspended after encoding")
        csize = len(data)
        if INTEGRITY_HASH and coding!="mmap":
            #could be a compressed wrapper or just raw bytes:
            try:
                v = data.data
            except AttributeError:
                v = data
            chksum = hashlib.sha256(v).hexdigest()
            client_options["z.sha256"] = chksum
            client_options["z.len"] = len(data)
            log("added len and hash of compressed data integrity %19s: %8i / %s", type(v), len(v), chksum)
        if (LOG_ENCODERS or compresslog.is_debug_enabled()) and "encoder" not in client_options:
            if encoder==self.mmap_encode:  #pylint: disable=comparison-with-callable
                mod = "mmap_encode"
            else:
                mod = get_encoder_type(encoder)
            if mod:
                client_options["encoder"] = mod
        #actual network packet:
        client_options["flush"] = flush or 0
        if self.send_timetamps:
            client_options["ts"] = image.get_timestamp()
        end = monotonic()
        if DAMAGE_STATISTICS:
            client_options['damage_time'] = int(damage_time * 1000)
            client_options['process_damage_time'] = int(process_damage_time * 1000)
            client_options['damage_packet_time'] = int(end * 1000)
        compresslog(COMPRESS_FMT,
                 (end-start)*1000.0, outw, outh, x, y, self.wid, coding,
                 100.0*csize/psize, ceil(psize/1024), ceil(csize/1024),
                 self._damage_packet_sequence, client_options, options)
        self.statistics.encoding_stats.append((end, coding, w*h, bpp, csize, end-start))
        return self.make_draw_packet(x, y, outw, outh, coding, data, outstride, client_options, options)

    def make_draw_packet(self, x : int, y : int, outw : int, outh : int,
                         coding : str, data, outstride : int, client_options, options) -> Tuple:
        if not isinstance(coding, str):
            raise RuntimeError(f"invalid type for encoding: {coding} ({type(coding)})")
        for v in (x, y, outw, outh, outstride):
            if not isinstance(v, int):
                raise RuntimeError(f"expected int, found {v} ({type(v)})")
        if self.send_window_size:
            ws = options.get("window-size")
            if ws:
                client_options["window-size"] = ws
        packet = ("draw", self.wid, x, y, outw, outh, coding, data,
                  self._damage_packet_sequence, outstride, client_options)
        self.global_statistics.packet_count += 1
        self.statistics.packet_count += 1
        self._damage_packet_sequence += 1
        #record number of frames and pixels:
        totals = self.statistics.encoding_totals.setdefault(coding, [0, 0])
        totals[0] = totals[0] + 1
        totals[1] = totals[1] + outw*outh
        self.encoding_last_used = coding
        #log("make_data_packet: returning packet=%s", packet[:7]+[".."]+packet[8:])
        return packet


    def direct_queue_draw(self, coding:str, data:bytes, client_info:Dict) -> None:
        #this is a frame from a compressed stream,
        #send it to all the window sources for this window:
        cdata = Compressed(coding, data)
        options : Dict[str,Any] = {}
        x = y = 0
        w, h = self.window_dimensions
        outstride = 0
        damage_time = process_damage_time = monotonic()
        log(f"direct_queue_draw({coding}, {len(data)} bytes, {client_info})")
        packet = self.make_draw_packet(x, y, w, h, coding, cdata, outstride, client_info, options)
        self.queue_damage_packet(packet, damage_time, process_damage_time, options)


    def mmap_encode(self, coding : str, image : ImageWrapper, _options) -> Tuple:
        assert coding=="mmap"
        assert self._mmap and self._mmap_size>0
        #prepare the pixels in a format accepted by the client:
        pf = image.get_pixel_format()
        if pf not in self.rgb_formats:
            if not rgb_reformat(image, self.rgb_formats, self.supports_transparency):
                warning_key = f"mmap_send({pf})"
                if first_time(warning_key):
                    log.warn(f"Warning: cannot use mmap to send {pf}")
                return ()
            pf = image.get_pixel_format()
        #write to mmap area:
        data = image.get_pixels()
        if not data:
            raise RuntimeError(f"failed to get pixels from {image}")
        mmap_data, mmap_free_size = self.mmap_write(self._mmap, self._mmap_size, data)
        #elapsed = monotonic()-start+0.000000001 #make sure never zero!
        #log("%s MBytes/s - %s bytes written to mmap in %.1f ms", int(len(data)/elapsed/1024/1024),
        #    len(data), 1000*elapsed)
        if mmap_data is None:
            return ()
        self.global_statistics.mmap_bytes_sent += len(data)
        self.global_statistics.mmap_free_size = mmap_free_size
        #the data we send is the index within the mmap area:
        return (
            "mmap", mmap_data, {"rgb_format" : pf},
            image.get_width(), image.get_height(), image.get_rowstride(), len(pf)*8,
            )
