# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2014 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import os
from collections import deque

from xpra.log import Logger
log = Logger("window", "encoding")
refreshlog = Logger("window", "refresh")
compresslog = Logger("window", "compress")
scalinglog = Logger("scaling")


AUTO_REFRESH_ENCODING = os.environ.get("XPRA_AUTO_REFRESH_ENCODING", "")
AUTO_REFRESH_THRESHOLD = int(os.environ.get("XPRA_AUTO_REFRESH_THRESHOLD", 95))
AUTO_REFRESH_QUALITY = int(os.environ.get("XPRA_AUTO_REFRESH_QUALITY", 100))
AUTO_REFRESH_SPEED = int(os.environ.get("XPRA_AUTO_REFRESH_SPEED", 50))

MAX_PIXELS_PREFER_RGB = 4096

DELTA = os.environ.get("XPRA_DELTA", "1")=="1"
MAX_DELTA_SIZE = int(os.environ.get("XPRA_MAX_DELTA_SIZE", "10000"))
HAS_ALPHA = os.environ.get("XPRA_ALPHA", "1")=="1"
FORCE_BATCH = os.environ.get("XPRA_FORCE_BATCH", "0")=="1"
STRICT_MODE = os.environ.get("XPRA_ENCODING_STRICT_MODE", "0")=="1"


from xpra.util import updict
from xpra.server.window_stats import WindowPerformanceStatistics
from xpra.simple_stats import add_list_stats
from xpra.server.batch_delay_calculator import calculate_batch_delay, get_target_speed, get_target_quality
from xpra.server.stats.maths import time_weighted_average
from xpra.server.region import rectangle, add_rectangle, remove_rectangle
from xpra.codecs.xor.cyxor import xor_str
from xpra.server.picture_encode import webp_encode, rgb_encode, PIL_encode, mmap_encode, mmap_send
from xpra.codecs.loader import NEW_ENCODING_NAMES_TO_OLD, PREFERED_ENCODING_ORDER, get_codec
from xpra.codecs.codec_constants import LOSSY_PIXEL_FORMATS, get_PIL_encodings
from xpra.net import compression


class WindowSource(object):
    """
    We create a Window Source for each window we send pixels for.

    The UI thread calls 'damage' and we eventually
    call ServerSource.queue_damage to queue the damage compression,

    """

    _encoding_warnings = set()

    def __init__(self, idle_add, timeout_add, source_remove,
                    queue_size, queue_damage, queue_packet, statistics,
                    wid, window, batch_config, auto_refresh_delay,
                    video_helper,
                    server_core_encodings, server_encodings,
                    encoding, encodings, core_encodings, encoding_options, rgb_formats,
                    default_encoding_options,
                    mmap, mmap_size):
        #scheduling stuff (gobject wrapped):
        self.idle_add = idle_add
        self.timeout_add = timeout_add
        self.source_remove = source_remove

        # mmap:
        self._mmap = mmap
        self._mmap_size = mmap_size

        self.init_vars()

        self.queue_size   = queue_size                  #callback to get the size of the damage queue
        self.queue_damage = queue_damage                #callback to add damage data which is ready to compress to the damage processing queue
        self.queue_packet = queue_packet                #callback to add a network packet to the outgoing queue
        self.wid = wid
        self.global_statistics = statistics             #shared/global statistics from ServerSource
        self.statistics = WindowPerformanceStatistics()

        self.server_core_encodings = server_core_encodings
        self.server_encodings = server_encodings
        self.encoding = encoding                        #the current encoding
        self.encodings = encodings                      #all the encodings supported by the client
        self.core_encodings = core_encodings            #the core encodings supported by the client
        self.rgb_formats = rgb_formats                  #supported RGB formats (RGB, RGBA, ...) - used by mmap
        self.encoding_options = encoding_options        #extra options which may be specific to the encoder (ie: x264)
        self.rgb_zlib = compression.use_zlib and encoding_options.boolget("rgb_zlib", True)     #server and client support zlib pixel compression (not to be confused with 'rgb24zlib'...)
        self.rgb_lz4 = compression.use_lz4 and encoding_options.boolget("rgb_lz4", False)       #server and client support lz4 pixel compression
        self.rgb_lzo = compression.use_lzo and encoding_options.boolget("rgb_lzo", False)       #server and client support lzo pixel compression
        self.webp_leaks = encoding_options.boolget("webp_leaks", True)  #all clients leaked memory until this flag got added
        self.generic_encodings = encoding_options.boolget("generic")
        self.supports_transparency = HAS_ALPHA and encoding_options.boolget("transparency")
        self.full_frames_only = encoding_options.boolget("full_frames_only")
        ropts = set(("png", "webp", "rgb", "jpeg"))     #default encodings for auto-refresh
        if self.webp_leaks:
            ropts.remove("webp")                        #don't use webp if the client is going to leak with it!
        ropts = ropts.intersection(set(self.server_core_encodings)) #ensure the server has support for it
        ropts = ropts.intersection(set(self.core_encodings))        #ensure the client has support for it
        self.client_refresh_encodings = encoding_options.strlistget("auto_refresh_encodings", list(ropts))
        self.supports_delta = []
        if not window.is_tray():
            self.supports_delta = [x for x in encoding_options.strlistget("supports_delta", []) if x in ("png", "rgb24", "rgb32")]
        self.batch_config = batch_config
        #auto-refresh:
        self.auto_refresh_delay = auto_refresh_delay
        self.video_helper = video_helper
        if window.is_shadow():
            self.max_delta_size = -1

        self.is_OR = window.is_OR()
        self.is_tray = window.is_tray()
        self.has_alpha = window.has_alpha()
        self.window_dimensions = 0, 0
        self.fullscreen = window.get_property("fullscreen")
        self.scaling = None
        self.maximized = False          #set by the client!
        if "fullscreen" in window.get_dynamic_property_names():
            window.connect("notify::fullscreen", self._fullscreen_changed)

        #for deciding between small regions and full screen updates:
        self.max_small_regions = 40
        self.max_bytes_percent = 60
        self.small_packet_cost = 1024
        if mmap and mmap_size>0:
            #with mmap, we can move lots of data around easily
            #so favour large screen updates over small packets
            self.max_small_regions = 10
            self.max_bytes_percent = 25
            self.small_packet_cost = 4096

        # general encoding tunables (mostly used by video encoders):
        self._encoding_quality = deque(maxlen=100)   #keep track of the target encoding_quality: (event time, info, encoding speed)
        self._encoding_speed = deque(maxlen=100)     #keep track of the target encoding_speed: (event time, info, encoding speed)
        # they may have fixed values:
        self._fixed_quality = default_encoding_options.get("quality", 0)
        self._fixed_min_quality = default_encoding_options.get("min-quality", 0)
        self._fixed_speed = default_encoding_options.get("speed", 0)
        self._fixed_min_speed = default_encoding_options.get("min-speed", 0)
        #will be overriden by update_quality() and update_speed() called from update_encoding_selection()
        #just here for clarity:
        self._current_quality = 50
        self._current_speed = 50
        self._want_alpha = False
        self._lossless_threshold_base = 85
        self._lossless_threshold_pixel_boost = 20
        self._rgb_auto_threshold = MAX_PIXELS_PREFER_RGB

        self.init_encoders()
        self.update_encoding_selection(encoding)
        log("initial encoding for %s: %s", self.wid, self.encoding)

    def __repr__(self):
        return "WindowSource(%s : %s)" % (self.wid, self.window_dimensions)


    def init_encoders(self):
        self._encoders["rgb24"] = self.rgb_encode
        self._encoders["rgb32"] = self.rgb_encode
        for x in get_PIL_encodings(get_codec("PIL")):
            if x in self.server_core_encodings:
                self._encoders[x] = self.PIL_encode
        #prefer this one over PIL supplied version:
        if "webp" in self.server_core_encodings:
            self._encoders["webp"] = self.webp_encode
        if self._mmap and self._mmap_size>0:
            self._encoders["mmap"] = self.mmap_encode

    def init_vars(self):
        self.server_core_encodings = []
        self.server_encodings = []
        self.encoding = None
        self.encodings = []
        self.encoding_last_used = None
        self.auto_refresh_encodings = []
        self.core_encodings = []
        self.rgb_formats = []
        self.client_refresh_encodings = []
        self.encoding_options = {}
        self.rgb_zlib = False
        self.rgb_lz4 = False
        self.rgb_lzo = False
        self.generic_encodings = []
        self.supports_transparency = False
        self.full_frames_only = False
        self.supports_delta = []
        self.last_pixmap_data = None
        self.suspended = False
        self.strict = STRICT_MODE
        #
        self.auto_refresh_delay = 0
        self.video_helper = None
        self.refresh_event_time = 0
        self.refresh_timer = None
        self.refresh_regions = []
        self.timeout_timer = None
        self.expire_timer = None
        self.soft_timer = None
        self.soft_expired = 0
        self.max_soft_expired = 5
        self.min_delta_size = 512
        self.max_delta_size = MAX_DELTA_SIZE
        self.is_OR = False
        self.is_tray = False
        self.has_alpha = False
        self.window_dimensions = 0, 0
        self.fullscreen = False
        self.scaling = None
        self.maximized = False
        #
        self.max_small_regions = 0
        self.max_bytes_percent = 0
        self.small_packet_cost = 0
        #
        self._encoding_quality = []
        self._encoding_speed = []
        #
        self._fixed_quality = 0
        self._fixed_min_quality = 0
        self._fixed_speed = 0
        self._fixed_min_speed = 0
        #
        self._damage_delayed = None
        self._damage_delayed_expired = False
        self._sequence = 1
        self._last_sequence_queued = 0
        self._damage_cancelled = 0
        self._damage_packet_sequence = 1
        encoders = {}
        if self._mmap and self._mmap_size>0:
            #we must always be able to send mmap
            #so we can reclaim its space
            encoders["mmap"] = self.mmap_encode
        self._encoders = encoders

    def cleanup(self):
        self.cancel_damage()
        self.statistics.reset()
        log("encoding_totals for wid=%s with primary encoding=%s : %s", self.wid, self.encoding, self.statistics.encoding_totals)
        self.init_vars()
        self._damage_cancelled = float("inf")


    def get_info(self):
        #should get prefixed with "client[M].window[N]." by caller
        """
            Add window specific stats
        """
        info = {
                "dimensions"            : self.window_dimensions,
                "encoding"              : self.encoding,
                "encoding.mmap"         : bool(self._mmap) and (self._mmap_size>0),
                "encoding.last_used"    : self.encoding_last_used or "",
                "suspended"             : self.suspended or False
                }
        def up(prefix, d):
            updict(info, prefix, d)

        #heuristics
        up("encoding.lossless_threshold", {
                "base"                  : self._lossless_threshold_base,
                "pixel_boost"           : self._lossless_threshold_pixel_boost})
        info["encoding.rgb_threshold"] = self._rgb_auto_threshold
        try:
            #ie: get_strict_encoding -> "strict_encoding"
            info["encoding.selection"] = self.get_best_encoding.__name__.replace("get_", "")
        except:
            pass
        up("property",  self.get_property_info())
        up("batch",     self.batch_config.get_info())
        up("encoding",  self.get_quality_speed_info())
        info.update(self.statistics.get_info())
        return info

    def get_quality_speed_info(self):
        info = {}
        def add_last_rec_info(prefix, recs):
            #must make a list to work on (again!)
            l = list(recs)
            if len(l)>0:
                _, descr, _ = l[-1]
                for k,v in descr.items():
                    info[prefix+"."+k] = v
        quality_list = self._encoding_quality
        if quality_list:
            qp = "quality"
            add_list_stats(info, qp, [x for _, _, x in list(quality_list)])
            add_last_rec_info(qp, quality_list)
        speed_list = self._encoding_speed
        if speed_list:
            sp = "speed"
            add_list_stats(info, sp, [x for _, _, x in list(speed_list)])
            add_last_rec_info(sp, speed_list)
        return info

    def get_property_info(self):
        return {
                "scaling"               : self.scaling or (1, 1),
                "fullscreen"            : self.fullscreen or False,
                #speed / quality properties (not necessarily the same as the video encoder settings..):
                "min_speed"             : self._fixed_min_speed,
                "speed"                 : self._fixed_speed,
                "min_quality"           : self._fixed_min_quality,
                "quality"               : self._fixed_quality,
                }



    def suspend(self):
        self.cancel_damage()
        self.statistics.reset()
        self.suspended = True

    def resume(self, window):
        self.cancel_damage()
        self.statistics.reset()
        self.suspended = False
        self.refresh(window, {"quality" : 100})

    def refresh(self, window, options={}):
        w, h = window.get_dimensions()
        self.damage(window, 0, 0, w, h, options)


    def set_scaling(self, scaling):
        scalinglog("set_scaling(%s)", scaling)
        self.scaling = scaling
        self.reconfigure(True)

    def _fullscreen_changed(self, window, *args):
        self.fullscreen = window.get_property("fullscreen")
        log("window fullscreen state changed: %s", self.fullscreen)
        self.reconfigure(True)

    def set_client_properties(self, properties):
        #filter out stuff we don't care about
        #to see if there is anything to set at all,
        #and if not, don't bother doing the potentially expensive update_encoding_selection()
        for k in ("workspace", "screen"):
            if k in properties:
                del properties[k]
        if properties:
            self.do_set_client_properties(properties)

    def do_set_client_properties(self, properties):
        self.maximized = properties.boolget("maximized", False)
        self.client_refresh_encodings = properties.strlistget("encoding.auto_refresh_encodings", self.client_refresh_encodings)
        self.full_frames_only = properties.boolget("encoding.full_frames_only", self.full_frames_only)
        self.supports_transparency = HAS_ALPHA and properties.boolget("encoding.transparency", self.supports_transparency)
        self.encodings = properties.strlistget("encodings", self.encodings)
        self.core_encodings = properties.strlistget("encodings.core", self.core_encodings)
        rgb_formats = properties.strlistget("encodings.rgb_formats", self.rgb_formats)
        if not self.supports_transparency:
            #remove rgb formats with alpha
            rgb_formats = [x for x in rgb_formats if x.find("A")<0]
        self.rgb_formats = rgb_formats
        self.update_encoding_selection(self.encoding)

    def set_auto_refresh_delay(self, d):
        self.auto_refresh_delay = d

    def set_new_encoding(self, encoding, strict):
        """ Changes the encoder for the given 'window_ids',
            or for all windows if 'window_ids' is None.
        """
        if strict is not None:
            self.strict = strict or STRICT_MODE
        if self.encoding==encoding:
            return
        self.statistics.reset()
        self.last_pixmap_data = None
        self.update_encoding_selection(encoding)


    def update_encoding_selection(self, encoding=None):
        #now we have the real list of encodings we can use:
        #"rgb32" and "rgb24" encodings are both aliased to "rgb"
        common_encodings = [x for x in self._encoders.keys() if x in self.core_encodings]
        #"rgb" is a pseudo encoding and needs special code:
        if "rgb24" in  common_encodings or "rgb32" in common_encodings:
            common_encodings.append("rgb")
        if self.webp_leaks and "webp" in common_encodings:
            common_encodings.remove("webp")
        self.common_encodings = [x for x in PREFERED_ENCODING_ORDER if x in common_encodings]
        #ensure the encoding chosen is supported by this source:
        if encoding in self.common_encodings:
            self.encoding = encoding
        else:
            self.encoding = self.common_encodings[0]
        self.auto_refresh_encodings = [x for x in self.client_refresh_encodings if x in self.common_encodings]
        log("update_encoding_selection(%s) encoding=%s, common encodings=%s, auto_refresh_encodings=%s", encoding, self.encoding, self.common_encodings, self.auto_refresh_encodings)
        assert self.encoding is not None
        self.update_quality()
        self.update_speed()
        self.update_encoding_options()

    def update_encoding_options(self, force_reload=False):
        self._want_alpha = self.is_tray or (self.has_alpha and self.supports_transparency)
        self._lossless_threshold_base = min(95, 75+self._current_speed/5)
        self._lossless_threshold_pixel_boost = 20
        #calculate the threshold for using rgb
        #if speed is high, assume we have bandwidth to spare
        smult = max(0.25, (self._current_speed-50)/5.0)
        qmult = max(0, self._current_quality/20.0)
        self._rgb_auto_threshold = int(MAX_PIXELS_PREFER_RGB * smult * qmult * (1 + int(self.is_OR)*2))
        self.get_best_encoding = self.get_best_encoding_impl()
        log("update_encoding_options(%s) want_alpha=%s, lossless threshold: %s / %s, small_as_rgb=%s, get_best_encoding=%s",
                        force_reload, self._want_alpha, self._lossless_threshold_base, self._lossless_threshold_pixel_boost, self._rgb_auto_threshold, self.get_best_encoding)

    def get_best_encoding_impl(self):
        #choose which method to use for selecting an encoding
        #first the easy ones (when there is no choice):
        if self.encoding=="png/L":
            #(png/L would look awful if we mixed it with something else)
            return self.get_strict_encoding
        elif self.strict:
            #honour strict flag
            if self.encoding=="rgb":
                #choose between rgb32 and rgb24 already
                #as alpha support does not change without going through this method
                if self._want_alpha and "rgb32" in self.common_encodings:
                    return self.encoding_is_rgb32
                else:
                    assert "rgb24" in self.common_encodings
                    return self.encoding_is_rgb24
            return self.get_strict_encoding
        elif self._want_alpha:
            if self.encoding in ("rgb", "rgb32") and "rgb32" in self.common_encodings:
                return self.encoding_is_rgb32
            if self.encoding in ("png", "webp", "png/P"):
                #chosen encoding does alpha, stick to it:
                #(prevents alpha bleeding artifacts,
                # as different encoders may encode alpha differently)
                return self.get_strict_encoding
            #choose an alpha encoding and keep it?
            return self.get_transparent_encoding
        elif self.encoding=="rgb":
            #if we're here we don't need alpha, so try rgb24 first:
            if "rgb24" in self.common_encodings:
                return self.encoding_is_rgb24
            elif "rgb32" in self.common_encodings:
                return self.encoding_is_rgb32
        #stick to what is specified or use rgb for small regions:
        return self.get_current_or_rgb

    def encoding_is_rgb32(self, *args):
        return "rgb32"

    def encoding_is_rgb24(self, *args):
        return "rgb24"

    def get_strict_encoding(self, *args):
        return self.encoding

    def get_transparent_encoding(self, pixel_count, ww, wh, speed, quality, current_encoding):
        #small areas prefer rgb, also when high speed and high quality
        if "rgb32" in self.common_encodings and (pixel_count<self._rgb_auto_threshold or quality>=90 and speed>=90):
            return "rgb32"
        #choose webp for limited sizes:
        if "webp" in self.common_encodings:
            max_webp = 1024*1024*(200-quality)/100*speed/100
            if 16384<pixel_count<max_webp:
                return "webp"
        if "png" in self.common_encodings and quality>75:
            return "png"
        for x in ("rgb32", "webp", "rgb32"):
            if x in self.common_encodings:
                return x
        return self.common_encodings[0]

    def get_current_or_rgb(self, pixel_count, ww, wh, *args):
        if pixel_count<self._rgb_auto_threshold:
            return "rgb24"
        return self.encoding


    def unmap(self):
        self.cancel_damage()
        self.statistics.reset()


    def cancel_damage(self):
        """
        Use this method to cancel all currently pending and ongoing
        damage requests for a window.
        Damage methods will check this value via 'is_cancelled(sequence)'.
        """
        log("cancel_damage() wid=%s, dropping delayed region %s and all sequences up to %s", self.wid, self._damage_delayed, self._sequence)
        #for those in flight, being processed in separate threads, drop by sequence:
        self._damage_cancelled = self._sequence
        self.cancel_expire_timer()
        self.cancel_soft_timer()
        self.cancel_refresh_timer()
        self.cancel_timeout_timer()
        #if a region was delayed, we can just drop it now:
        self.refresh_regions = []
        self._damage_delayed = None
        self._damage_delayed_expired = False
        self.last_pixmap_data = None
        #make sure we don't account for those as they will get dropped
        #(generally before encoding - only one may still get encoded):
        for sequence in self.statistics.encoding_pending.keys():
            if self._damage_cancelled>=sequence:
                try:
                    del self.statistics.encoding_pending[sequence]
                except KeyError:
                    #may have been processed whilst we checked
                    pass

    def cancel_expire_timer(self):
        if self.expire_timer:
            self.source_remove(self.expire_timer)
            self.expire_timer = None

    def cancel_soft_timer(self):
        if self.soft_timer:
            self.source_remove(self.soft_timer)
            self.soft_timer = None

    def cancel_refresh_timer(self):
        if self.refresh_timer:
            self.source_remove(self.refresh_timer)
            self.refresh_timer = None
            self.refresh_event_time = 0

    def cancel_timeout_timer(self):
        if self.timeout_timer:
            self.source_remove(self.timeout_timer)
            self.timeout_timer = None


    def is_cancelled(self, sequence=None):
        """ See cancel_damage(wid) """
        return self._damage_cancelled>=(sequence or float("inf"))


    def calculate_batch_delay(self, has_focus, other_is_fullscreen, other_is_maximized):
        if not self.batch_config.locked:
            calculate_batch_delay(self.wid, self.window_dimensions, has_focus, other_is_fullscreen, other_is_maximized, self.is_OR, self.soft_expired, self.batch_config, self.global_statistics, self.statistics)

    def update_speed(self):
        if self.suspended or self._mmap:
            return
        speed = self._fixed_speed
        if speed<=0:
            #make a copy to work on (and discard "info")
            speed_data = [(event_time, speed) for event_time, _, speed in list(self._encoding_speed)]
            info, target_speed = get_target_speed(self.wid, self.window_dimensions, self.batch_config, self.global_statistics, self.statistics, self._fixed_min_speed, speed_data)
            speed_data.append((time.time(), target_speed))
            speed = max(self._fixed_min_speed, time_weighted_average(speed_data, min_offset=1, rpow=1.1))
            speed = min(99, speed)
        else:
            info = {}
            speed = min(100, speed)
        self._current_speed = int(speed)
        log("update_speed() info=%s, speed=%s", info, self._current_speed)
        self._encoding_speed.append((time.time(), info, self._current_speed))

    def set_min_speed(self, min_speed):
        if self._fixed_min_speed!=min_speed:
            self._fixed_min_speed = min_speed
            self.reconfigure()

    def set_speed(self, speed):
        if self._fixed_speed != speed:
            prev_speed = self._fixed_speed
            self._fixed_speed = speed
            #force a reload when switching to/from 100% speed:
            self.reconfigure(force_reload=(speed>99 and prev_speed<=99) or (speed<=99 and prev_speed>99))

    def get_speed(self, coding):
        return self._current_speed


    def update_quality(self):
        if self.suspended or self._mmap:
            return
        if self.encoding in ("rgb", "png", "png/P", "png/L"):
            #the user has selected an encoding which does not use quality
            #so skip the calculations!
            self._current_quality = 100
            return
        quality = self._fixed_quality
        if quality<=0:
            info, quality = get_target_quality(self.wid, self.window_dimensions, self.batch_config, self.global_statistics, self.statistics, self._fixed_min_quality)
            #make a copy to work on (and discard "info")
            ves_copy = [(event_time, speed) for event_time, _, speed in list(self._encoding_quality)]
            ves_copy.append((time.time(), quality))
            quality = max(self._fixed_min_quality, time_weighted_average(ves_copy, min_offset=0.1, rpow=1.2))
            quality = min(99, quality)
        else:
            info = {}
            quality = min(100, quality)
        self._current_quality = int(quality)
        log("update_quality() info=%s, quality=%s", info, self._current_quality)
        self._encoding_quality.append((time.time(), info, self._current_quality))

    def set_min_quality(self, min_quality):
        self._fixed_min_quality = min_quality
        self.update_quality()

    def set_quality(self, quality):
        if self._fixed_quality!=quality:
            self._fixed_quality = quality
            self._current_quality = quality
            self.reconfigure()

    def get_quality(self, encoding):
        #overriden in window video source
        return self._current_quality


    def reconfigure(self, force_reload=False):
        if self.batch_config.locked and not force_reload:
            return False
        self.update_quality()
        self.update_speed()
        self.update_encoding_options(force_reload)
        return True


    def damage(self, window, x, y, w, h, options={}):
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
        if self.suspended:
            return
        if w==0 or h==0:
            #we may fire damage ourselves,
            #in which case the dimensions may be zero (if so configured by the client)
            return
        now = time.time()
        if "auto_refresh" not in options:
            log("damage%s", (window, x, y, w, h, options))
            self.statistics.last_damage_events.append((now, x,y,w,h))
        self.global_statistics.damage_events_count += 1
        self.statistics.damage_events_count += 1
        self.statistics.last_damage_event_time = now
        ww, wh = window.get_dimensions()
        if self.window_dimensions != (ww, wh):
            self.statistics.last_resized = time.time()
            self.window_dimensions = ww, wh
        if self.full_frames_only:
            x, y, w, h = 0, 0, ww, wh

        if self._damage_delayed:
            #use existing delayed region:
            if not self.full_frames_only:
                regions = self._damage_delayed[2]
                region = rectangle(x, y, w, h)
                add_rectangle(regions, region)
            #merge/override options
            if options is not None:
                override = options.get("override_options", False)
                existing_options = self._damage_delayed[4]
                for k in options.keys():
                    if override or k not in existing_options:
                        existing_options[k] = options[k]
            log("damage(%s, %s, %s, %s, %s) wid=%s, using existing delayed %s regions created %.1fms ago",
                x, y, w, h, options, self.wid, self._damage_delayed[3], now-self._damage_delayed[0])
            return
        elif self.batch_config.delay < self.batch_config.min_delay and not self.batch_config.always:
            #work out if we have too many damage requests
            #or too many pixels in those requests
            #for the last time_unit, and if so we force batching on
            event_min_time = now-self.batch_config.time_unit
            all_pixels = [pixels for _,event_time,pixels in self.global_statistics.damage_last_events if event_time>event_min_time]
            eratio = float(len(all_pixels)) / self.batch_config.max_events
            pratio = float(sum(all_pixels)) / self.batch_config.max_pixels
            if eratio>1.0 or pratio>1.0:
                self.batch_config.delay = self.batch_config.min_delay * max(eratio, pratio)

        delay = options.get("delay", self.batch_config.delay)
        if now-self.statistics.last_resized<0.250:
            #recently resized, batch more
            delay = min(50, delay+25)
        qsize = self.queue_size()
        if qsize>4:
            #the queue is getting big, try to slow down progressively:
            delay = min(10, delay) * (qsize/4.0)
        delay = max(delay, options.get("min_delay", 0))
        delay = min(delay, options.get("max_delay", self.batch_config.max_delay))
        delay = int(delay)
        packets_backlog = self.statistics.get_packets_backlog()
        pixels_encoding_backlog, enc_backlog_count = self.statistics.get_pixels_encoding_backlog()
        #only send without batching when things are going well:
        # - no packets backlog from the client
        # - the amount of pixels waiting to be encoded is less than one full frame refresh
        # - no more than 10 regions waiting to be encoded
        if not self.must_batch(delay) and (packets_backlog==0 and pixels_encoding_backlog<=ww*wh and enc_backlog_count<=10):
            #send without batching:
            log("damage(%s, %s, %s, %s, %s) wid=%s, sending now with sequence %s", x, y, w, h, options, self.wid, self._sequence)
            actual_encoding = options.get("encoding")
            if actual_encoding is None:
                q = options.get("quality") or self._current_quality
                s = options.get("speed") or self._current_speed
                actual_encoding = self.get_best_encoding(w*h, ww, wh, s, q, self.encoding)
            if self.must_encode_full_frame(window, actual_encoding):
                x, y = 0, 0
                w, h = ww, wh
            self.batch_config.last_delays.append((now, delay))
            self.batch_config.last_actual_delays.append((now, delay))
            def damage_now():
                if self.is_cancelled():
                    return
                window.acknowledge_changes()
                self.process_damage_region(now, window, x, y, w, h, actual_encoding, options)
            self.idle_add(damage_now)
            return

        #create a new delayed region:
        regions = [rectangle(x, y, w, h)]
        self._damage_delayed_expired = False
        actual_encoding = options.get("encoding", self.encoding)
        self._damage_delayed = now, window, regions, actual_encoding, options or {}
        log("damage(%s, %s, %s, %s, %s) wid=%s, scheduling batching expiry for sequence %s in %.1f ms", x, y, w, h, options, self.wid, self._sequence, delay)
        self.batch_config.last_delays.append((now, delay))
        self.expire_timer = self.timeout_add(delay, self.expire_delayed_region, delay)

    def must_batch(self, delay):
        if FORCE_BATCH or self.batch_config.always or delay>self.batch_config.min_delay:
            return True
        try:
            t, _ = self.batch_config.last_delays[-5]
            #do batch if we got more than 5 damage events in the last 10 milliseconds:
            return time.time()-t<0.010
        except:
            #probably not enough events to grab -10
            return False


    def expire_delayed_region(self, delay):
        """ mark the region as expired so damage_packet_acked can send it later,
            and try to send it now.
        """
        self.expire_timer = None
        self._damage_delayed_expired = True
        self.may_send_delayed()
        if self._damage_delayed is None:
            #region has been sent
            return
        #the region has not been sent yet because we are waiting for damage ACKs from the client
        if self.soft_expired<self.max_soft_expired:
            #there aren't too many regions soft expired yet
            #so use the "soft timer":
            self.soft_expired += 1
            #we have already waited for "delay" to get here, wait more as we soft expire more regions:
            self.soft_timer = self.timeout_add(int(self.soft_expired*delay), self.delayed_region_soft_timeout)
        else:
            #NOTE: this should never happen...
            #the region should now get sent when we eventually receive the pending ACKs
            #but if somehow they go missing... clean it up from a timeout:
            delayed_region_time = self._damage_delayed[0]
            self.timeout_timer = self.timeout_add(self.batch_config.timeout_delay, self.delayed_region_timeout, delayed_region_time)

    def delayed_region_soft_timeout(self):
        self.soft_timer = None
        if self._damage_delayed is None:
            return
        damage_time = self._damage_delayed[0]
        now = time.time()
        actual_delay = int(1000.0*(now-damage_time))
        self.batch_config.last_actual_delays.append((now, actual_delay))
        self.do_send_delayed()
        return False

    def delayed_region_timeout(self, delayed_region_time):
        if self._damage_delayed is None:
            #delayed region got sent
            return False
        region_time = self._damage_delayed[0]
        if region_time!=delayed_region_time:
            #this is a different region
            return False
        #ouch: same region!
        window      = self._damage_delayed[1]
        options     = self._damage_delayed[4]
        elapsed = int(1000.0 * (time.time() - region_time))
        log.warn("delayed_region_timeout: region is %ims old, bad connection?", elapsed)
        #re-try:
        self._damage_delayed = None
        self.full_quality_refresh(window, options)
        return False

    def may_send_delayed(self):
        """ send the delayed region for processing if there is no client backlog """
        if not self._damage_delayed:
            log("window %s delayed region already sent", self.wid)
            return False
        damage_time = self._damage_delayed[0]
        packets_backlog = self.statistics.get_packets_backlog()
        now = time.time()
        actual_delay = int(1000.0 * (now-damage_time))
        if packets_backlog>0:
            if actual_delay<self.batch_config.max_delay:
                log("send_delayed for wid %s, delaying again because of backlog: %s packets, batch delay is %s, elapsed time is %.1f ms",
                        self.wid, packets_backlog, self.batch_config.delay, actual_delay)
                #this method will get fired again damage_packet_acked
                return False
            else:
                log.warn("send_delayed for wid %s, elapsed time %.1f is above limit of %.1f - sending now", self.wid, actual_delay, self.batch_config.max_delay)
        else:
            #if we're here, there is no packet backlog, and therefore
            #may_send_delayed() may not be called again by an ACK packet,
            #so we must either process the region now or set a timer to
            #check again later:
            def check_again(delay=actual_delay/10.0):
                delay = int(min(self.batch_config.max_delay, max(10, delay)))
                self.timeout_add(delay, self.may_send_delayed)
                return False
            if self.batch_config.locked and self.batch_config.delay>actual_delay:
                #ensure we honour the fixed delay
                #(as we may get called from a damage ack before we expire)
                return check_again(self.batch_config.delay-actual_delay)
            pixels_encoding_backlog, enc_backlog_count = self.statistics.get_pixels_encoding_backlog()
            ww, wh = self.window_dimensions
            if pixels_encoding_backlog>=(ww*wh):
                log("send_delayed for wid %s, delaying again because too many pixels are waiting to be encoded: %s", self.wid, ww*wh)
                return check_again()
            elif enc_backlog_count>10:
                log("send_delayed for wid %s, delaying again because too many damage regions are waiting to be encoded: %s", self.wid, enc_backlog_count)
                return check_again()
            #no backlog, so ok to send, clear soft-expired counter:
            self.soft_expired = 0
            log("send_delayed for wid %s, batch delay is %.1f, elapsed time is %.1f ms", self.wid, self.batch_config.delay, actual_delay)
        self.batch_config.last_actual_delays.append((now, actual_delay))
        self.do_send_delayed()
        return False

    def do_send_delayed(self):
        self.cancel_timeout_timer()
        self.cancel_soft_timer()
        delayed = self._damage_delayed
        if delayed:
            self._damage_delayed = None
            self.send_delayed_regions(*delayed)
        return False

    def send_delayed_regions(self, damage_time, window, regions, coding, options):
        """ Called by 'send_delayed' when we expire a delayed region,
            There may be many rectangles within this delayed region,
            so figure out if we want to send them all or if we
            just send one full window update instead.
        """
        # It's important to acknowledge changes *before* we extract them,
        # to avoid a race condition.
        window.acknowledge_changes()
        if not self.is_cancelled():
            self.do_send_delayed_regions(damage_time, window, regions, coding, options)

    def do_send_delayed_regions(self, damage_time, window, regions, coding, options, exclude_region=None, get_best_encoding=None):
        ww,wh = window.get_dimensions()
        speed = options.get("speed") or self._current_speed
        quality = options.get("quality") or self._current_quality
        get_best_encoding = get_best_encoding or self.get_best_encoding
        def get_encoding(pixel_count):
            return get_best_encoding(pixel_count, ww, wh, speed, quality, coding)

        def send_full_window_update():
            actual_encoding = get_encoding(ww*wh)
            log("send_delayed_regions: using full window update %sx%s with %s", ww, wh, actual_encoding)
            assert actual_encoding is not None
            self.process_damage_region(damage_time, window, 0, 0, ww, wh, actual_encoding, options)

        if exclude_region is None:
            if self.is_tray or self.full_frames_only:
                send_full_window_update()
                return

            if len(regions)>self.max_small_regions:
                #too many regions!
                send_full_window_update()
                return

        regions = list(set(regions))
        bytes_threshold = ww*wh*self.max_bytes_percent/100
        pixel_count = sum(rect.width*rect.height for rect in regions)
        bytes_cost = pixel_count+self.small_packet_cost*len(regions)
        log("send_delayed_regions: bytes_cost=%s, bytes_threshold=%s, pixel_count=%s", bytes_cost, bytes_threshold, pixel_count)
        if bytes_cost>=bytes_threshold:
            #too many bytes to send lots of small regions..
            if exclude_region is None:
                send_full_window_update()
                return
            #make regions out of the rest of the window area:
            non_exclude = rectangle(0, 0, ww, wh).substract_rect(exclude_region)
            #and keep those that have damage areas in them:
            regions = [x for x in non_exclude if len([y for y in regions if x.intersects_rect(y)])>0]
            #TODO: should verify that is still better than what we had before..

        elif len(regions)>1:
            #try to merge all the regions to see if we save anything:
            merged = regions[0].clone()
            for r in regions[1:]:
                merged.merge_rect(r)
            #remove the exclude region if needed:
            if exclude_region:
                merged_rects = merged.substract_rect(exclude_region)
            else:
                merged_rects = [merged]
            merged_pixel_count = sum([r.width*r.height for r in merged_rects])
            merged_bytes_cost = pixel_count+self.small_packet_cost*len(merged_rects)
            if merged_bytes_cost<bytes_cost or merged_pixel_count<pixel_count:
                #better, so replace with merged regions:
                regions = merged_rects

        #check to see if the total amount of pixels makes us use a fullscreen update instead:
        if len(regions)>1:
            pixel_count = sum(rect.width*rect.height for rect in regions)
            log("send_delayed_regions: %s regions with %s pixels (coding=%s)", len(regions), pixel_count, coding)
            actual_encoding = get_encoding(pixel_count)
            if self.must_encode_full_frame(window, actual_encoding):
                #use full screen dimensions:
                self.process_damage_region(damage_time, window, 0, 0, ww, wh, actual_encoding, options)
                return

        #we're processing a number of regions separately:
        for region in regions:
            actual_encoding = get_encoding(region.width*region.height)
            if self.must_encode_full_frame(window, actual_encoding):
                #we may have sent regions already - which is now wasted, oh well..
                self.process_damage_region(damage_time, window, 0, 0, ww, wh, actual_encoding, options)
                #we can stop here (full screen update will include the other regions)
                return
            self.process_damage_region(damage_time, window, region.x, region.y, region.width, region.height, actual_encoding, options)


    def must_encode_full_frame(self, window, encoding):
        #WindowVideoSource overrides this method
        return self.full_frames_only or self.is_tray


    def free_image_wrapper(self, image):
        """ when not running in the UI thread,
            call this method to free an image wrapper safely
        """
        if image.is_thread_safe():
            image.free()
        else:
            self.idle_add(image.free)


    def process_damage_region(self, damage_time, window, x, y, w, h, coding, options):
        """
            Called by 'damage' or 'send_delayed_regions' to process a damage region.

            Actual damage region processing:
            we extract the rgb data from the pixmap and place it on the damage queue,
            so the damage thread will call make_data_packet_cb which does the actual compression
            This runs in the UI thread.
        """
        if w==0 or h==0:
            return
        if not window.is_managed():
            log("the window %s is not composited!?", window)
            return
        self._sequence += 1
        sequence = self._sequence
        if self.is_cancelled(sequence):
            log("get_window_pixmap: dropping damage request with sequence=%s", sequence)
            return

        assert coding is not None
        rgb_request_time = time.time()
        image = window.get_image(x, y, w, h, logger=log)
        if image is None:
            log("get_window_pixmap: no pixel data for window %s, wid=%s", window, self.wid)
            return
        if self.is_cancelled(sequence):
            image.free()
            return

        now = time.time()
        log("process_damage_regions: wid=%s, adding %s pixel data to queue, elapsed time: %.1f ms, request time: %.1f ms",
                self.wid, coding, 1000*(now-damage_time), 1000*(now-rgb_request_time))
        self.statistics.encoding_pending[sequence] = (damage_time, w, h)
        self.queue_damage(self.make_data_packet_cb, window, damage_time, now, self.wid, image, coding, sequence, options)

    def make_data_packet_cb(self, window, damage_time, process_damage_time, wid, image, coding, sequence, options):
        """ This function is called from the damage data thread!
            Extra care must be taken to prevent access to X11 functions on window.
        """
        try:
            packet = self.make_data_packet(damage_time, process_damage_time, wid, image, coding, sequence, options)
        finally:
            self.free_image_wrapper(image)
            del image
            try:
                del self.statistics.encoding_pending[sequence]
            except KeyError:
                #may have been cancelled whilst we processed it
                pass
        #NOTE: we MUST send it (even if the window is cancelled by now..)
        #because the code may rely on the client having received this frame
        if not packet:
            return
        #queue packet for sending:
        self.queue_damage_packet(packet, damage_time, process_damage_time)

        if not self.can_refresh(window):
            return
        encoding = packet[6]
        if options.get("auto_refresh", False):
            refreshlog("auto-refresh %s packet sent", encoding)
            #don't trigger a loop:
            return
        #the actual encoding used may be different from the global one we specify
        x, y, w, h = packet[2:6]
        client_options = packet[10]     #info about this packet from the encoder
        actual_quality = client_options.get("quality", 0)
        if encoding.startswith("png") or encoding.startswith("rgb"):
            actual_quality = 100
        lossy_csc = client_options.get("csc") in LOSSY_PIXEL_FORMATS
        scaled = client_options.get("scaled_size") is not None
        region = rectangle(x, y, w, h)
        if actual_quality>=AUTO_REFRESH_THRESHOLD and not lossy_csc and not scaled:
            #this screen update is lossless or high quality
            if not self.refresh_regions:
                #nothing due for refresh, still nothing to do
                msg = "nothing to do"
            else:
                #refresh already due: substract this region from the list of regions:
                self.remove_refresh_region(region)
                if len(self.refresh_regions)==0:
                    msg = "covered all regions that needed a refresh, cancelling refresh"
                    self.cancel_refresh_timer()
                else:
                    msg = "removed rectangle from regions"
        else:
            #try to add the rectangle to the refresh list:
            if not self.add_refresh_region(window, region):
                msg = "list of refresh regions unchanged"
            else:
                #if we're here: the window is still valid and this was a lossy update,
                #of some form (lossy encoding with low enough quality, or using CSC subsampling, or using scaling)
                #so we need an auto-refresh (re-schedule it if one was due already)
                if self.refresh_event_time>0:
                    msg = "keeping existing timer"
                else:
                    msg = "scheduling refresh"
                    self.refresh_event_time = time.time()
                    sched_delay = int(max(50, self.auto_refresh_delay, self.batch_config.delay*4))
                    self.refresh_timer = self.timeout_add(sched_delay, self.schedule_auto_refresh, window, options)
        refreshlog("auto refresh: %5s screen update (quality=%3i), %s (region=%s, refresh regions=%s)", encoding, actual_quality, msg, region, self.refresh_regions)

    def remove_refresh_region(self, region):
        #removes the given region from the refresh list
        #(also overriden in window video source)
        remove_rectangle(self.refresh_regions, region)

    def add_refresh_region(self, window, region):
        #adds the given region to the refresh list
        #returns True if the list was modified
        #(overriden in window video source to exclude the video region)
        #Note: this does not run in the UI thread!
        return add_rectangle(self.refresh_regions, region)

    def can_refresh(self, window):
        #safe to call from any thread (does not call X11):
        if not window.is_managed():
            #window is gone
            return False
        if self.auto_refresh_delay<=0 or self.is_cancelled() or len(self.auto_refresh_encodings)==0 or self._mmap:
            #can happen during cleanup
            return False
        return True

    def schedule_auto_refresh(self, window, damage_options):
        """ Must be called from the UI thread:
            this makes it easier to prevent races
        """
        #timer is running now, clear so we don't try to cancel it somewhere else:
        self.refresh_timer = None
        #re-do some checks that may have changed:
        if not self.can_refresh(window):
            self.refresh_event_time = 0
            return
        ret = self.refresh_event_time
        if ret==0:
            return

        #decide if now is the right time, or if we delay some more
        #(the more pixels we have to refresh, the longer we wait)
        pixels = sum(r.width*r.height for r in self.refresh_regions)
        ww, wh = window.get_dimensions()
        pct = 100*pixels/(ww*wh)
        #target auto_refresh_delay, but double that if we have a full screen update:
        target_delay = max(50, self.auto_refresh_delay * pct / 50)
        elapsed = int(1000.0*(time.time()-ret))
        if elapsed>=(target_delay-20):
            #close enough to target, do it now:
            refreshlog("schedule_auto_refresh: elapsed time %i with target=%i, refreshing now", elapsed, target_delay)
            self.timer_full_refresh(window)
        else:
            #delay a bit more:
            delay = int(max(20, self.auto_refresh_delay, target_delay - elapsed))
            refreshlog("schedule_auto_refresh: rescheduling auto refresh timer with extra delay %i (%i%% of window, refresh delay=%i, target=%i, elapsed=%i)", delay, pct, self.auto_refresh_delay, target_delay, elapsed)
            self.refresh_timer = self.timeout_add(delay, self.timer_full_refresh, window)
        return False

    def timer_full_refresh(self, window):
        ret = self.refresh_event_time
        self.refresh_timer = None
        self.refresh_event_time = 0
        regions = self.refresh_regions
        self.refresh_regions = []
        if self.can_refresh(window) and regions:
            now = time.time()
            refreshlog("timer_full_refresh() after %ims, regions=%s", 1000.0*(time.time()-ret), regions)
            #choose an encoding:
            ww, wh = window.get_dimensions()
            encoding = self.auto_refresh_encodings[0]
            encodings = self.get_best_encoding(ww*wh, ww, wh, AUTO_REFRESH_SPEED, AUTO_REFRESH_QUALITY, encoding)
            refresh_encodings = [x for x in self.auto_refresh_encodings if x in encodings]
            if refresh_encodings:
                encoding = refresh_encodings[0]
            options = self.get_refresh_options()
            WindowSource.do_send_delayed_regions(self, now, window, regions, encoding, options, exclude_region=self.get_refresh_exclude())
        return False

    def get_refresh_exclude(self):
        #overriden in window video source to exclude the video subregion
        return None

    def full_quality_refresh(self, window, damage_options):
        #called on use request via xpra control,
        #or when we need to resend the window after a send timeout
        if not window.is_managed():
            #this window is no longer managed
            return
        if not self.auto_refresh_encodings or self.is_cancelled():
            #can happen during cleanup
            return
        refresh_regions = self.refresh_regions
        self.refresh_regions = []
        w, h = window.get_dimensions()
        log("full_quality_refresh() for %sx%s window with regions: %s", w, h, self.refresh_regions)
        new_options = damage_options.copy()
        encoding = self.auto_refresh_encodings[0]
        new_options.update(self.get_refresh_options())
        log("full_quality_refresh() using %s with options=%s", encoding, new_options)
        damage_time = time.time()
        self.send_delayed_regions(damage_time, window, refresh_regions, encoding, new_options)
        self.damage(window, 0, 0, w, h, options=new_options)

    def get_refresh_options(self):
        return {"optimize"      : False,
                "auto_refresh"  : True,     #not strictly an auto-refresh, just makes sure we won't trigger one
                "quality"       : AUTO_REFRESH_QUALITY,
                "speed"         : AUTO_REFRESH_SPEED}

    def queue_damage_packet(self, packet, damage_time, process_damage_time):
        """
            Adds the given packet to the packet_queue,
            (warning: this runs from the non-UI 'encode' thread)
            we also record a number of statistics:
            - damage packet queue size
            - number of pixels in damage packet queue
            - damage latency (via a callback once the packet is actually sent)
        """
        #packet = ["draw", wid, x, y, w, h, coding, data, self._damage_packet_sequence, rowstride, client_options]
        width = packet[4]
        height = packet[5]
        damage_packet_sequence = packet[8]
        actual_batch_delay = process_damage_time-damage_time
        def start_send(bytecount):
            now = time.time()
            self.statistics.damage_ack_pending[damage_packet_sequence] = [now, bytecount, 0, 0, width*height]
        def damage_packet_sent(bytecount):
            now = time.time()
            stats = self.statistics.damage_ack_pending.get(damage_packet_sequence)
            #if we timed it out, it may be gone already:
            if stats:
                stats[2] = now
                stats[3] = bytecount
                damage_out_latency = now-process_damage_time
                self.statistics.damage_out_latency.append((now, width*height, actual_batch_delay, damage_out_latency))
        now = time.time()
        damage_in_latency = now-process_damage_time
        self.statistics.damage_in_latency.append((now, width*height, actual_batch_delay, damage_in_latency))
        self.queue_packet(packet, self.wid, width*height, start_send, damage_packet_sent)

    def damage_packet_acked(self, damage_packet_sequence, width, height, decode_time):
        """
            The client is acknowledging a damage packet,
            we record the 'client decode time' (provided by the client itself)
            and the "client latency".
            If we were waiting for pending ACKs to send an expired damage packet,
            check for it.
            (warning: this runs from the non-UI network parse thread)
        """
        log("packet decoding sequence %s for window %s %sx%s took %.1fms", damage_packet_sequence, self.wid, width, height, decode_time/1000.0)
        if decode_time>0:
            self.statistics.client_decode_time.append((time.time(), width*height, decode_time))
        pending = self.statistics.damage_ack_pending.get(damage_packet_sequence)
        if pending is None:
            log("cannot find sent time for sequence %s", damage_packet_sequence)
            return
        del self.statistics.damage_ack_pending[damage_packet_sequence]
        if decode_time:
            start_send_at, start_bytes, end_send_at, end_bytes, pixels = pending
            bytecount = end_bytes-start_bytes
            #it is possible, though very unlikely,
            #that we get the ack before we've had a chance to call
            #damage_packet_sent, so we must validate the data:
            if bytecount>0 and end_send_at>0:
                self.global_statistics.record_latency(self.wid, decode_time, start_send_at, end_send_at, pixels, bytecount)
        else:
            #something failed client-side, so we can't rely on the delta being available
            self.last_pixmap_data = None
        if self._damage_delayed is not None and self._damage_delayed_expired:
            self.idle_add(self.may_send_delayed)
        if not self._damage_delayed:
            self.soft_expired = 0

    def make_data_packet(self, damage_time, process_damage_time, wid, image, coding, sequence, options):
        """
            Picture encoding - non-UI thread.
            Converts a damage item picked from the 'compression_work_queue'
            by the 'encode' thread and returns a packet
            ready for sending by the network layer.

            * 'mmap' will use 'mmap_send' + 'mmap_encode' - always if available, otherwise:
            * 'jpeg' and 'png' are handled by 'PIL_encode'.
            * 'webp' uses 'webp_encode'
            * 'h264' and 'vp8' use 'video_encode'
            * 'rgb24' and 'rgb32' use 'rgb_encode'
        """
        if self.is_cancelled(sequence) or self.suspended:
            log("make_data_packet: dropping data packet for window %s with sequence=%s", wid, sequence)
            return  None
        x, y, w, h, _ = image.get_geometry()

        #more useful is the actual number of bytes (assuming 32bpp)
        #since we generally don't send the padding with it:
        psize = w*h*4
        assert w>0 and h>0, "invalid dimensions: %sx%s" % (w, h)
        log("make_data_packet: image=%s, damage data: %s", image, (wid, x, y, w, h, coding))
        start = time.time()
        if self._mmap and self._mmap_size>0 and psize>256:
            mmap_data = mmap_send(self._mmap, self._mmap_size, image, self.rgb_formats, self.supports_transparency)
            if mmap_data:
                #success
                data, mmap_free_size, written = mmap_data
                self.global_statistics.mmap_bytes_sent += written
                self.global_statistics.mmap_free_size = mmap_free_size
                #hackish: pass data to mmap_encode using "options":
                coding = "mmap"         #changed encoding!
                options["mmap_data"] = data

        #if client supports delta pre-compression for this encoding, use it if we can:
        delta = -1
        store = -1
        if DELTA and not (self._mmap and self._mmap_size>0) and (coding in self.supports_delta) and self.min_delta_size<image.get_size()<self.max_delta_size:
            #we need to copy the pixels because some delta encodings
            #will modify the pixel array in-place!
            dpixels = image.get_pixels()[:]
            store = sequence
            lpd = self.last_pixmap_data
            if lpd is not None:
                lw, lh, lcoding, lsequence, ldata = lpd
                if lw==w and lh==h and lcoding==coding and len(ldata)==len(dpixels):
                    #xor with the last frame:
                    delta = lsequence
                    data = xor_str(dpixels, ldata)
                    image.set_pixels(data)

        #by default, don't set rowstride (the container format will take care of providing it):
        encoder = self._encoders.get(coding)
        if encoder is None:
            if self.is_cancelled(sequence):
                return None
            else:
                raise Exception("BUG: no encoder not found for %s" % coding)
        ret = encoder(coding, image, options)
        if ret is None:
            #something went wrong.. nothing we can do about it here!
            return  None

        coding, data, client_options, outw, outh, outstride, bpp = ret
        #check cancellation list again since the code above may take some time:
        #but always send mmap data so we can reclaim the space!
        if coding!="mmap" and (self.is_cancelled(sequence) or self.suspended):
            log("make_data_packet: dropping data packet for window %s with sequence=%s", wid, sequence)
            return  None
        #tell client about delta/store for this pixmap:
        if delta>=0:
            client_options["delta"] = delta
        csize = len(data)
        if store>0:
            if delta>0 and csize>=psize/3:
                #compressed size is more than 33% of the original
                #maybe delta is not helping us, so clear it:
                self.last_pixmap_data = None
                #TODO: could tell the clients they can clear it too
                #(add a new client capability and send it a zero store value)
            else:
                self.last_pixmap_data = w, h, coding, store, dpixels
                client_options["store"] = store
        encoding = coding
        if not self.generic_encodings:
            #old clients use non-generic encoding names:
            encoding = NEW_ENCODING_NAMES_TO_OLD.get(coding, coding)
        #actual network packet:
        packet = ("draw", wid, x, y, outw, outh, encoding, data, self._damage_packet_sequence, outstride, client_options)
        end = time.time()
        compresslog("compress: %5.1fms for %4ix%-4i pixels using %5s with ratio %5.1f%% (%5iKB to %5iKB), delta=%i, client_options=%s",
                 (end-start)*1000.0, w, h, coding, 100.0*csize/psize, psize/1024, csize/1024, delta, client_options)
        self.global_statistics.packet_count += 1
        self.statistics.packet_count += 1
        self._damage_packet_sequence += 1
        self.statistics.encoding_stats.append((coding, w*h, bpp, len(data), end-start))
        #record number of frames and pixels:
        totals = self.statistics.encoding_totals.setdefault(coding, [0, 0])
        totals[0] = totals[0] + 1
        totals[1] = totals[1] + w*h
        self._last_sequence_queued = sequence
        self.encoding_last_used = coding
        #log("make_data_packet: returning packet=%s", packet[:7]+[".."]+packet[8:])
        return packet


    def webp_encode(self, coding, image, options):
        q = options.get("quality") or self.get_quality(coding)
        s = options.get("speed") or self.get_speed(coding)
        return webp_encode(coding, image, self.rgb_formats, self.supports_transparency, q, s, options)

    def rgb_encode(self, coding, image, options):
        s = options.get("speed") or self._current_speed
        return rgb_encode(coding, image, self.rgb_formats, self.supports_transparency, s,
                          self.rgb_zlib, self.rgb_lz4, self.rgb_lzo)

    def PIL_encode(self, coding, image, options):
        #for more information on pixel formats supported by PIL / Pillow, see:
        #https://github.com/python-imaging/Pillow/blob/master/libImaging/Unpack.c
        assert coding in self.server_core_encodings
        q = options.get("quality") or self.get_quality(coding)
        s = options.get("speed") or self.get_speed(coding)
        return PIL_encode(coding, image, q, s, self.supports_transparency)

    def mmap_encode(self, coding, image, options):
        return mmap_encode(coding, image, options)
