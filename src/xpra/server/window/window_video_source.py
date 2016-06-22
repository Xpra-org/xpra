# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2013-2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time
import operator

from xpra.net.compression import Compressed
from xpra.codecs.codec_constants import get_subsampling_divs, \
                                        TransientCodecException, RGB_FORMATS, PIXEL_SUBSAMPLING, LOSSY_PIXEL_FORMATS
from xpra.server.window.window_source import WindowSource, STRICT_MODE, AUTO_REFRESH_SPEED, AUTO_REFRESH_QUALITY
from xpra.server.window.region import merge_all            #@UnresolvedImport
from xpra.server.window.video_subregion import VideoSubregion
from xpra.codecs.loader import PREFERED_ENCODING_ORDER, EDGE_ENCODING_ORDER
from xpra.util import parse_scaling_value, engs
from xpra.log import Logger

log = Logger("encoding")
csclog = Logger("csc")
scorelog = Logger("score")
scalinglog = Logger("scaling")
sublog = Logger("subregion")
videolog = Logger("video")
avsynclog = Logger("av-sync")


def envint(name, d):
    try:
        return int(os.environ.get(name, d))
    except:
        return d

MAX_NONVIDEO_PIXELS = envint("XPRA_MAX_NONVIDEO_PIXELS", 1024*4)

FORCE_CSC_MODE = os.environ.get("XPRA_FORCE_CSC_MODE", "")   #ie: "YUV444P"
if FORCE_CSC_MODE and FORCE_CSC_MODE not in RGB_FORMATS and FORCE_CSC_MODE not in PIXEL_SUBSAMPLING:
    log.warn("ignoring invalid CSC mode specified: %s", FORCE_CSC_MODE)
    FORCE_CSC_MODE = ""
FORCE_CSC = bool(FORCE_CSC_MODE) or  os.environ.get("XPRA_FORCE_CSC", "0")=="1"
SCALING = os.environ.get("XPRA_SCALING", "1")=="1"
SCALING_HARDCODED = parse_scaling_value(os.environ.get("XPRA_SCALING_HARDCODED", ""))

VIDEO_SUBREGION = os.environ.get("XPRA_VIDEO_SUBREGION", "1")=="1"
B_FRAMES = os.environ.get("XPRA_B_FRAMES", "1")=="1"
VIDEO_SKIP_EDGE = os.environ.get("XPRA_VIDEO_SKIP_EDGE", "0")=="1"


class WindowVideoSource(WindowSource):
    """
        A WindowSource that handles video codecs.
    """

    def __init__(self, *args):
        #this will call init_vars():
        WindowSource.__init__(self, *args)
        self.supports_video_scaling = self.encoding_options.boolget("video_scaling", False)
        self.supports_video_b_frames = self.encoding_options.strlistget("video_b_frames", [])
        self.supports_video_subregion = VIDEO_SUBREGION

    def init_encoders(self):
        WindowSource.init_encoders(self)
        #for 0.12 onwards: per encoding lists:
        self.full_csc_modes = {}
        self.parse_csc_modes(self.encoding_options.dictget("full_csc_modes", default_value=None))

        self.video_encodings = self.video_helper.get_encodings()
        for x in self.video_encodings:
            if x in self.server_core_encodings:
                self._encoders[x] = self.video_encode
        #these are used for non-video areas, ensure "jpeg" is used if available
        #as we may be dealing with large areas still, and we want speed:
        nv_common = (set(self.server_core_encodings) & set(self.core_encodings)) - set(self.video_encodings)
        self.non_video_encodings = [x for x in PREFERED_ENCODING_ORDER if x in nv_common]

        #those two instances should only ever be modified or accessed from the encode thread:
        self._csc_encoder = None
        self._video_encoder = None
        self._last_pipeline_check = 0

    def __repr__(self):
        return "WindowVideoSource(%s : %s)" % (self.wid, self.window_dimensions)

    def init_vars(self):
        WindowSource.init_vars(self)
        self.video_subregion = VideoSubregion(self.timeout_add, self.source_remove, self.refresh_subregion, self.auto_refresh_delay)

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
        self.last_pipeline_scores = []
        self.last_pipeline_time = 0

        self.supports_video_scaling = False
        self.supports_video_subregion = False

        self.full_csc_modes = {}                            #for 0.12 onwards: per encoding lists
        self.video_encodings = []
        self.non_video_encodings = []
        self.edge_encoding = None
        self.b_frame_flush_timer = None

    def set_auto_refresh_delay(self, d):
        WindowSource.set_auto_refresh_delay(self, d)
        r = self.video_subregion
        if r:
            r.set_auto_refresh_delay(d)

    def calculate_batch_delay(self, has_focus, other_is_fullscreen, other_is_maximized):
        WindowSource.calculate_batch_delay(self, has_focus, other_is_fullscreen, other_is_maximized)
        vsr = self.video_subregion
        bc = self.batch_config
        if not bc.locked and vsr:
            #we have a video subregion, update its refresh delay
            r = vsr.rectangle
            if r:
                ww, wh = self.window_dimensions
                pct = (100*r.width*r.height)/(ww*wh)
                d = 2 * int(max(100, self.auto_refresh_delay * max(50, pct) / 50, bc.delay*4))
                vsr.set_auto_refresh_delay(d)

    def update_av_sync_frame_delay(self):
        self.av_sync_frame_delay = 0
        ve = self._video_encoder
        if ve:
            d = ve.get_info().get("delayed", 0)
            self.av_sync_frame_delay += 40 * d
            avsynclog("update_av_sync_frame_delay() video encoder=%s, delayed frames=%i, frame delay=%i", ve, d, self.av_sync_frame_delay)
        self.set_av_sync_delay()


    def get_client_info(self):
        info = {
            "supports_video_scaling"    : self.supports_video_scaling,
            "supports_video_subregion"  : self.supports_video_subregion,
            }
        for enc, csc_modes in (self.full_csc_modes or {}).items():
            info["csc_modes.%s" % enc] = csc_modes
        return info

    def get_property_info(self):
        i = WindowSource.get_property_info(self)
        i.update({
                "scaling.control"       : self.scaling_control,
                "scaling"               : self.scaling or (1, 1),
                })
        return i

    def get_info(self):
        info = WindowSource.get_info(self)
        sr = self.video_subregion
        if sr:
            info["video_subregion"] = sr.get_info()
        info["scaling"] = self.actual_scaling
        def addcinfo(prefix, x):
            if not x:
                return
            try:
                i = x.get_info()
                i[""] = x.get_type()
                info[prefix] = i
            except:
                log.error("Error collecting codec information from %s", x, exc_info=True)
        addcinfo("csc", self._csc_encoder)
        addcinfo("encoder", self._video_encoder)
        info.setdefault("encodings", {}).update({
                                                 "non-video"    : self.non_video_encodings,
                                                 "edge"         : self.edge_encoding or "",
                                                 })
        einfo = {"pipeline_param" : self.get_pipeline_info()}
        if self._last_pipeline_check>0:
            einfo["pipeline_last_check"] = int(1000*(time.time()-self._last_pipeline_check))
        lps = self.last_pipeline_scores
        if lps:
            popts = einfo.setdefault("pipeline_option", {})
            for i, lp in enumerate(lps):
                popts[i] = self.get_pipeline_score_info(*lp)
        info.setdefault("encoding", {}).update(einfo)
        return info

    def get_pipeline_info(self):
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
            except:
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


    def cleanup(self):
        WindowSource.cleanup(self)
        self.cleanup_codecs()

    def cleanup_codecs(self):
        """ Video encoders (x264, nvenc and vpx) and their csc helpers
            require us to run cleanup code to free the memory they use.
            We have to do this from the encode thread to be safe.
            (the encoder and csc module may be in use by that thread)
        """
        if self._csc_encoder:
            self.csc_encoder_clean()
        if self._video_encoder:
            self.video_encoder_clean()

    def csc_encoder_clean(self):
        """ Calls self._csc_encoder.clean() from the encode thread """
        csce = self._csc_encoder
        if csce:
            self._csc_encoder = None
            self.call_in_encode_thread(False, csce.clean)

    def video_encoder_clean(self):
        """ Calls self._video_encoder.clean() from the encode thread """
        ve = self._video_encoder
        if ve:
            self._video_encoder = None
            self.call_in_encode_thread(False, ve.clean)


    def parse_csc_modes(self, full_csc_modes):
        #only override if values are specified:
        csclog("parse_csc_modes(%s) current value=%s", full_csc_modes, self.full_csc_modes)
        if full_csc_modes is not None and type(full_csc_modes)==dict:
            self.full_csc_modes = full_csc_modes


    def set_new_encoding(self, encoding, strict=None):
        if self.encoding!=encoding:
            #ensure we re-init the codecs asap:
            self.cleanup_codecs()
        WindowSource.set_new_encoding(self, encoding, strict)

    def update_encoding_selection(self, encoding=None, exclude=[]):
        #override so we don't use encodings that don't have valid csc modes:
        log("update_encoding_selection(%s, %s)", encoding, exclude)
        for x in self.video_encodings:
            if x not in self.core_encodings:
                exclude.append(x)
                continue
            csc_modes = self.full_csc_modes.get(x)
            csclog("full_csc_modes[%s]=%s", x, csc_modes)
            if not csc_modes or x not in self.core_encodings:
                exclude.append(x)
                csclog.warn("client does not support any csc modes with %s", x)
        WindowSource.update_encoding_selection(self, encoding, exclude)

    def do_set_client_properties(self, properties):
        #client may restrict csc modes for specific windows
        self.parse_csc_modes(properties.dictget("encoding.full_csc_modes", default_value=None))
        self.supports_video_scaling = properties.boolget("encoding.video_scaling", self.supports_video_scaling)
        self.supports_video_subregion = properties.boolget("encoding.video_subregion", self.supports_video_subregion)
        self.scaling_control = max(0, min(100, properties.intget("scaling.control", self.scaling_control)))
        WindowSource.do_set_client_properties(self, properties)
        #encodings may have changed, so redo this:
        nv_common = (set(self.server_core_encodings) & set(self.core_encodings)) - set(self.video_encodings)
        self.non_video_encodings = [x for x in PREFERED_ENCODING_ORDER if x in nv_common]
        try:
            self.edge_encoding = [x for x in EDGE_ENCODING_ORDER if x in self.non_video_encodings][0]
        except:
            self.edge_encoding = None
        log("do_set_client_properties(%s) full_csc_modes=%s, video_scaling=%s, video_subregion=%s, non_video_encodings=%s, edge_encoding=%s, scaling_control=%s",
            properties, self.full_csc_modes, self.supports_video_scaling, self.supports_video_subregion, self.non_video_encodings, self.edge_encoding, self.scaling_control)

    def get_best_encoding_impl_default(self):
        return self.get_best_encoding_video


    def get_best_encoding_video(self, pixel_count, ww, wh, speed, quality, current_encoding):
        """
            decide whether we send a full window update using the video encoder,
            or if a separate small region(s) is a better choice
        """
        def nonvideo(q=quality):
            s = max(0, min(100, speed))
            q = max(0, min(100, q))
            return self.get_best_nonvideo_encoding(pixel_count, ww, wh, s, q, self.non_video_encodings[0], self.non_video_encodings)

        def lossless(reason):
            log("get_best_encoding_video(..) temporarily switching to lossless mode for %8i pixels: %s", pixel_count, reason)
            s = max(0, min(100, speed))
            q = 100
            return self.get_best_nonvideo_encoding(pixel_count, ww, wh, s, q, self.non_video_encodings[0], self.non_video_encodings)

        if len(self.non_video_encodings)==0:
            return current_encoding

        sr = self.video_subregion.rectangle

        rgbmax = self._rgb_auto_threshold
        if sr:
            rgbmax = min(rgbmax, sr.width*sr.height//2)
        if pixel_count<=rgbmax:
            return lossless("low pixel count")

        if current_encoding not in self.video_encodings:
            #not doing video, bail out:
            return nonvideo()

        #ensure the dimensions we use for decision making are the ones actually used:
        cww = ww & self.width_mask
        cwh = wh & self.height_mask

        if cww*cwh<=MAX_NONVIDEO_PIXELS:
            #window is too small!
            return nonvideo()

        if cww<self.min_w or cww>self.max_w or cwh<self.min_h or cwh>self.max_h:
            #video encoder cannot handle this size!
            #(maybe this should be an 'assert' statement here?)
            return nonvideo()

        now = time.time()
        if now-self.statistics.last_resized<0.350:
            #window has just been resized, may still resize
            return nonvideo(q=quality-30)

        lde = list(self.statistics.last_damage_events)
        lim = now-2
        pixels_last_2secs = sum(w*h for when,_,_,w,h in lde if when>lim)
        if pixels_last_2secs<5*cww*cwh:
            #less than 5 full window pixels in last 2 seconds
            return nonvideo()

        if self._current_quality!=quality or self._current_speed!=speed:
            #quality or speed override, best not to force video encoder re-init
            return nonvideo()

        if sr and ((sr.width&self.width_mask)!=cww or (sr.height&self.height_mask)!=cwh):
            #we have a video region, and this is not it, so don't use video
            #raise the quality as the areas around video tend to not be graphics
            return nonvideo(q=quality+30)

        #calculate the threshold for using video vs small regions:
        factors = (max(1, (speed-75)/5.0),                      #speed multiplier
                   1 + int(self.is_OR or self.is_tray)*2,       #OR windows tend to be static
                   max(1, 10-self._sequence),                   #gradual discount the first 9 frames, as the window may be temporary
                   1.0 / (int(bool(self._video_encoder)) + 1)   #if we have a video encoder already, make it more likely we'll use it:
                   )
        max_nvp = int(reduce(operator.mul, factors, MAX_NONVIDEO_PIXELS))
        if pixel_count<=max_nvp:
            #below threshold
            return nonvideo()

        if cww<self.min_w or cww>self.max_w or cwh<self.min_h or cwh>self.max_h:
            #failsafe:
            return nonvideo()
        return current_encoding

    def get_best_nonvideo_encoding(self, pixel_count, ww, wh, speed, quality, current_encoding, options=[]):
        #if we're here, then the window has no alpha (or the client cannot handle alpha)
        #and we can ignore the current encoding
        options = options or self.non_video_encodings
        if pixel_count<self._rgb_auto_threshold:
            #high speed and high quality, rgb is still good
            if "rgb24" in options:
                return "rgb24"
            if "rgb32" in options:
                return "rgb32"
        #use sliding scale for lossless threshold
        #(high speed favours switching to lossy sooner)
        #take into account how many pixels need to be encoder:
        #more pixels means we switch to lossless more easily
        lossless_q = min(100, self._lossless_threshold_base + self._lossless_threshold_pixel_boost * pixel_count / (ww*wh))
        if quality<lossless_q:
            #lossy options:
            if "jpeg" in options:
                #assume that we have "turbojpeg",
                #which beats everything in terms of efficiency for lossy compression:
                return "jpeg"
            #avoid large areas (too slow), especially at low speed and high quality:
            if "webp" in options and pixel_count>16384:
                max_webp = 1024*1024 * (200-quality)/100 * speed/100
                if speed>30 and pixel_count<max_webp:
                    return "webp"
        else:
            #lossless options:
            #webp: don't enable it for "true" lossless (q>99) unless speed is high enough
            #because webp forces speed=100 for true lossless mode
            #also avoid very small and very large areas (both slow)
            if "webp" in options and (quality<100 or speed>=50) and pixel_count>16384:
                max_webp = 1024*1024 * (200-quality)/100 * speed/100
                if pixel_count<max_webp:
                    return "webp"
            if speed>75:
                if "rgb24" in options:
                    return "rgb24"
                if "rgb32" in options:
                    return "rgb32"
            if "png" in options:
                return "png"
        #we failed to find a good match, default to the first of the options..
        if options:
            return options[0]
        return None #can happen during cleanup!


    def unmap(self):
        WindowSource.cancel_damage(self)
        self.cleanup_codecs()

    def cancel_damage(self):
        self.video_subregion.cancel_refresh_timer()
        WindowSource.cancel_damage(self)
        #we must clean the video encoder to ensure
        #we will resend a key frame because we may be missing a frame
        self.cleanup_codecs()


    def full_quality_refresh(self, damage_options={}):
        #override so we can:
        if self.video_subregion.detection:
            #reset the video region on full quality refresh
            self.video_subregion.reset()
        else:
            #keep the region, but cancel the refresh:
            self.video_subregion.cancel_refresh_timer()
        #refresh the whole window in one go:
        damage_options["novideo"] = True
        WindowSource.full_quality_refresh(self, damage_options)


    def must_batch(self, delay):
        #force batching when using video region
        #because the video region code is in the send_delayed path
        return self.video_subregion.rectangle is not None or WindowSource.must_batch(self, delay)


    def get_speed(self, encoding):
        s = WindowSource.get_speed(self, encoding)
        #give a boost if we have a video region and this is not video:
        if self.video_subregion.rectangle and encoding not in self.video_encodings:
            s += 25
        return min(100, s)

    def get_quality(self, encoding):
        q = WindowSource.get_quality(self, encoding)
        #give a boost if we have a video region and this is not video:
        if self.video_subregion.rectangle and encoding not in self.video_encodings:
            q += 40
        return q


    def client_decode_error(self, error, message):
        #maybe the stream is now corrupted..
        self.cleanup_codecs()
        WindowSource.client_decode_error(self, error, message)


    def get_refresh_exclude(self):
        #exclude video region (if any) from lossless refresh:
        return self.video_subregion.rectangle

    def refresh_subregion(self, regions):
        #callback from video subregion to trigger a refresh of some areas
        sublog("refresh_subregion(%s, %s)", regions)
        if not regions or not self.can_refresh():
            return
        now = time.time()
        encoding = self.auto_refresh_encodings[0]
        options = self.get_refresh_options()
        WindowSource.do_send_delayed_regions(self, now, regions, encoding, options, get_best_encoding=self.get_refresh_subregion_encoding)

    def get_refresh_subregion_encoding(self, *args):
        ww, wh = self.window_dimensions
        w, h = ww, wh
        vr = self.video_subregion.rectangle
        #could have been cleared by another thread:
        if vr:
            w, h = vr.width, vr.height
        return self.get_best_nonvideo_encoding(ww*wh, w, h, AUTO_REFRESH_SPEED, AUTO_REFRESH_QUALITY, self.auto_refresh_encodings[0], self.auto_refresh_encodings)

    def remove_refresh_region(self, region):
        #override so we can update the subregion timers / regions tracking:
        WindowSource.remove_refresh_region(self, region)
        self.video_subregion.remove_refresh_region(region)

    def add_refresh_region(self, region):
        #Note: this does not run in the UI thread!
        #returns the number of pixels in the region update
        #don't refresh the video region as part of normal refresh,
        #use subregion refresh for that
        vr = self.video_subregion.rectangle
        if vr is None:
            #no video region, normal code path:
            return WindowSource.add_refresh_region(self, region)
        if vr.contains_rect(region):
            #all of it is in the video region:
            self.video_subregion.add_video_refresh(region)
            return 0
        ir = vr.intersection_rect(region)
        if ir is None:
            #region is outside video region, normal code path:
            return WindowSource.add_refresh_region(self, region)
        #add intersection (rectangle in video region) to video refresh:
        self.video_subregion.add_video_refresh(ir)
        #add any rectangles not in the video region
        #(if any: keep track if we actually added anything)
        pixels_modified = 0
        for r in region.substract_rect(vr):
            pixels_modified += WindowSource.add_refresh_region(self, r)
        return pixels_modified


    def do_send_delayed_regions(self, damage_time, regions, coding, options):
        """
            Overriden here so we can try to intercept the video_subregion if one exists.
        """
        #overrides the default method for finding the encoding of a region
        #so we can ensure we don't use the video encoder when we don't want to:
        def send_nonvideo(regions=regions, encoding=coding, exclude_region=None, get_best_encoding=self.get_best_nonvideo_encoding):
            WindowSource.do_send_delayed_regions(self, damage_time, regions, encoding, options, exclude_region=exclude_region, get_best_encoding=get_best_encoding)

        if self.is_tray:
            sublog("BUG? video for tray - don't use video region!")
            return send_nonvideo(encoding=None)

        if coding not in self.video_encodings:
            sublog("not a video encoding")
            #keep current encoding selection function
            return send_nonvideo(get_best_encoding=self.get_best_encoding)

        if options.get("novideo"):
            sublog("video disabled in options")
            return send_nonvideo(encoding=None)

        vr = self.video_subregion.rectangle
        if not vr or not self.video_subregion.enabled:
            sublog("no video region, we may use the video encoder for something else")
            WindowSource.do_send_delayed_regions(self, damage_time, regions, coding, options)
            return
        assert not self.full_frames_only

        actual_vr = None
        if vr in regions:
            #found the video region the easy way: exact match in list
            actual_vr = vr
        else:
            #find how many pixels are within the region (roughly):
            #find all unique regions that intersect with it:
            inter = [x for x in (vr.intersection_rect(r) for r in regions) if x is not None]
            if len(inter)>0:
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
                same_d = [r for r in regions if r.width==vr.width and r.height==vr.height]
                if len(same_d)==1:
                    #probably right..
                    actual_vr = same_d[0]
                elif len(same_d)>1:
                    #find one that shares at least one coordinate:
                    same_c = [r for r in same_d if r.x==vr.x or r.y==vr.y]
                    if len(same_c)==1:
                        actual_vr = same_c[0]

        if actual_vr is None:
            sublog("send_delayed_regions: video region %s not found in: %s", vr, regions)
        else:
            #found the video region:
            #send this using the video encoder:
            video_options = options.copy()
            video_options["av-sync"] = True
            self.process_damage_region(damage_time, actual_vr.x, actual_vr.y, actual_vr.width, actual_vr.height, coding, video_options, 0)

            #now substract this region from the rest:
            trimmed = []
            for r in regions:
                trimmed += r.substract_rect(actual_vr)
            if not trimmed:
                sublog("send_delayed_regions: nothing left after removing video region %s", actual_vr)
                return
            sublog("send_delayed_regions: substracted %s from %s gives us %s", actual_vr, regions, trimmed)
            regions = trimmed

        #merge existing damage delayed region if there is one:
        #(this codepath can fire from a video region refresh callback)
        dr = self._damage_delayed
        if dr:
            regions = dr[2] + regions
            damage_time = min(damage_time, dr[0])
            self._damage_delayed = None
            self.cancel_expire_timer()
        #decide if we want to send the rest now or delay some more,
        #only delay once the video encoder has dealt with a few frames:
        event_count = max(0, self.statistics.damage_events_count - self.video_subregion.set_at)
        if event_count<100:
            delay = 0
        else:
            #non-video is delayed at least 50ms, 4 times the batch delay, but no more than non_max_wait:
            elapsed = int(1000.0*(time.time()-damage_time))
            delay = max(self.batch_config.delay*4, 50)
            delay = min(delay, self.video_subregion.non_max_wait-elapsed)
        if delay<=25:
            send_nonvideo(regions=regions, encoding=None)
        else:
            self._damage_delayed = damage_time, regions, coding, options or {}
            sublog("send_delayed_regions: delaying non video regions %s some more by %ims", regions, delay)
            self.expire_timer = self.timeout_add(int(delay), self.expire_delayed_region, delay)


    def process_damage_region(self, damage_time, x, y, w, h, coding, options, flush=None):
        #now figure out if we need to send edges separately:
        if coding in self.video_encodings:
            dw = w - (w & self.width_mask)
            dh = h - (h & self.height_mask)
        else:
            dw, dh = 0, 0
        if self.edge_encoding and not VIDEO_SKIP_EDGE:
            if dw>0:
                WindowSource.process_damage_region(self, damage_time, x+w-dw, y, dw, h, self.edge_encoding, options, flush=1+int(dh>0))
            if dh>0:
                WindowSource.process_damage_region(self, damage_time, x, y+h-dh, x+w, dh, self.edge_encoding, options, flush=1)
        WindowSource.process_damage_region(self, damage_time, x, y, w-dw, h-dh, coding, options, flush=flush)


    def must_encode_full_frame(self, encoding):
        return self.full_frames_only or (encoding in self.video_encodings) or not self.non_video_encodings


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
        WindowSource.update_encoding_options(self, force_reload)
        log("update_encoding_options(%s) supports_video_subregion=%s, csc_encoder=%s, video_encoder=%s", force_reload, self.supports_video_subregion, self._csc_encoder, self._video_encoder)
        if self.supports_video_subregion:
            if self.encoding in self.video_encodings and not self.full_frames_only and not STRICT_MODE and len(self.non_video_encodings)>0 and not (self._mmap and self._mmap_size>0):
                ww, wh = self.window_dimensions
                self.video_subregion.identify_video_subregion(ww, wh, self.statistics.damage_events_count, self.statistics.last_damage_events, self.statistics.last_resized)
            else:
                #FIXME: small race if a refresh timer is due when we change encoding - meh
                self.video_subregion.reset()

            if self.video_subregion.rectangle:
                #when we have a video region, lower the lossless threshold
                #especially for small regions
                self._lossless_threshold_base = min(80, 10+self._current_speed//5)
                self._lossless_threshold_pixel_boost = 90-self._current_speed//5

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
        elapsed = time.time()-self._last_pipeline_check
        if not force_reload and elapsed<0.75:
            scorelog("cannot score: only %ims since last check", 1000*elapsed)
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
        encoding = self.encoding
        if encoding not in self.video_encodings:
            return checknovideo("non-video encoding: %s", encoding)
        if self._sequence<2 or self._damage_cancelled>=float("inf"):
            #too early, or too late!
            return checknovideo("sequence=%s (cancelled=%s)", self._sequence, self._damage_cancelled)
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
            return checknovideo("out of bounds: %sx%s (min %sx%s, max %sx%s)", w, h, self.min_w, self.min_h, self.max_w, self.max_h)
        if time.time()-self.statistics.last_resized<0.500:
            return checknovideo("resized just %.1f seconds ago", time.time()-self.statistics.last_resized)

        #must copy reference to those objects because of threading races:
        ve = self._video_encoder
        csce = self._csc_encoder
        if ve is not None and ve.is_closed():
            scorelog("cannot score: video encoder is closed or closing")
            return
        if csce is not None and csce.is_closed():
            scorelog("cannot score: csc is closed or closing")
            return

        scores = self.get_video_pipeline_options(encoding, w, h, self.pixel_format, force_reload)
        if len(scores)==0:
            scorelog("check_pipeline_score(%s) no pipeline options found!", force_reload)
            return

        scorelog("check_pipeline_score(%s) best=%s", force_reload, scores[0])
        _, _, _, csc_width, csc_height, csc_spec, enc_in_format, _, enc_width, enc_height, encoder_spec = scores[0]
        if csce:
            if csc_spec is None:
                scorelog("check_pipeline_score(%s) csc is no longer needed: %s", force_reload, scores[0])
                self.csc_encoder_clean()
            elif csce.get_dst_format()!=enc_in_format:
                scorelog("check_pipeline_score(%s) change of csc output format from %s to %s", force_reload, csce.get_dst_format(), enc_in_format)
                self.csc_encoder_clean()
            elif csce.get_src_width()!=csc_width or csce.get_src_height()!=csc_height:
                scorelog("check_pipeline_score(%s) change of csc input dimensions from %ix%i to %ix%i", force_reload, csce.get_src_width(), csce.get_src_height(), csc_width, csc_height)
                self.csc_encoder_clean()
        if ve is None:
            pass    #nothing to check or clean
        elif ve.get_src_format()!=enc_in_format:
            scorelog("check_pipeline_score(%s) change of video input format from %s to %s", force_reload, ve.get_src_format(), enc_in_format)
            self.video_encoder_clean()
        elif ve.get_width()!=enc_width or ve.get_height()!=enc_height:
            scorelog("check_pipeline_score(%s) change of video input dimensions from %ix%i to %ix%i", force_reload, ve.get_width(), ve.get_height(), enc_width, enc_height)
            self.video_encoder_clean()
        elif type(ve)!=encoder_spec.codec_class:
            scorelog("check_pipeline_score(%s) found a better video encoder class than %s: %s", force_reload, type(ve), scores[0])
            self.video_encoder_clean()
        self._last_pipeline_check = time.time()


    def get_video_pipeline_options(self, encoding, width, height, src_format, force_refresh=False):
        """
            Given a picture format (width, height and src pixel format),
            we find all the pipeline options that will allow us to compress
            it using the given encoding.
            First, we try with direct encoders (for those that support the
            source pixel format natively), then we try all the combinations
            using csc encoders to convert to an intermediary format.
            Each solution is rated and we return all of them in descending
            score (best solution comes first).
            Because this function is expensive to call, we cache the results.
            This allows it to run more often from the timer thread.

            Can be called from any thread.
        """
        if not force_refresh and (time.time()-self.last_pipeline_time<1) and self.last_pipeline_params and self.last_pipeline_params==(encoding, width, height, src_format):
            #keep existing scores
            scorelog("get_video_pipeline_options%s using cached values from %ims ago", (encoding, width, height, src_format, force_refresh), 1000.0*(time.time()-self.last_pipeline_time))
            return self.last_pipeline_scores

        vh = self.video_helper
        if vh is None:
            return []       #closing down

        #these are the CSC modes the client can handle for this encoding:
        #we must check that the output csc mode for each encoder is one of those
        supported_csc_modes = self.full_csc_modes.get(encoding)
        if not supported_csc_modes:
            scorelog("get_video_pipeline_options: no supported csc modes for %s", encoding)
            return []
        encoder_specs = vh.get_encoder_specs(encoding)
        if not encoder_specs:
            scorelog("get_video_pipeline_options: no encoder specs for %s", encoding)
            return []
        scorelog("get_video_pipeline_options%s speed: %s (min %s), quality: %s (min %s)", (encoding, width, height, src_format), self._current_speed, self._fixed_min_speed, int(self._current_quality), self._fixed_min_quality)
        scores = []
        def add_scores(info, csc_spec, enc_in_format):
            scorelog("add_scores(%s, %s, %s)", info, csc_spec, enc_in_format)
            #find encoders that take 'enc_in_format' as input:
            colorspace_specs = encoder_specs.get(enc_in_format)
            if not colorspace_specs:
                scorelog("add_scores: no matching colorspace specs for %s", enc_in_format)
                return
            #log("%s encoding from %s: %s", info, pixel_format, colorspace_specs)
            for encoder_spec in colorspace_specs:
                #ensure that the output of the encoder can be processed by the client:
                matches = set(encoder_spec.output_colorspaces) & set(supported_csc_modes)
                if not matches:
                    scorelog("add_scores: no matches for %s (%s and %s)", encoder_spec, encoder_spec.output_colorspaces, supported_csc_modes)
                    continue
                scaling = self.calculate_scaling(width, height, encoder_spec.max_w, encoder_spec.max_h)
                score_data = self.get_score(enc_in_format, csc_spec, encoder_spec, width, height, scaling)
                if score_data:
                    scores.append(score_data)
        if not FORCE_CSC or src_format==FORCE_CSC_MODE:
            add_scores("direct (no csc)", None, src_format)

        #now add those that require a csc step:
        csc_specs = vh.get_csc_specs(src_format)
        if csc_specs:
            #log("%s can also be converted to %s using %s", pixel_format, [x[0] for x in csc_specs], set(x[1] for x in csc_specs))
            #we have csc module(s) that can get us from pixel_format to out_csc:
            for out_csc, l in csc_specs.items():
                actual_csc = self.csc_equiv(out_csc)
                if not bool(FORCE_CSC_MODE) or FORCE_CSC_MODE==out_csc:
                    for csc_spec in l:
                        add_scores("via %s (%s)" % (out_csc, actual_csc), csc_spec, out_csc)
        s = sorted(scores, key=lambda x : -x[0])
        scorelog("get_video_pipeline_options%s scores=%s", (encoding, width, height, src_format), s)
        self.last_pipeline_params = (encoding, width, height, src_format)
        self.last_pipeline_scores = s
        self.last_pipeline_time = time.time()
        return s

    def csc_equiv(self, csc_mode):
        #in some places, we want to check against the subsampling used
        #and not the colorspace itself.
        #and NV12 uses the same subsampling as YUV420P...
        return {"NV12" : "YUV420P",
                "BGRX" : "YUV444P"}.get(csc_mode, csc_mode)


    def get_quality_score(self, csc_format, csc_spec, encoder_spec, scaling):
        quality = encoder_spec.quality
        if csc_format in ("YUV420P", "YUV422P", "YUV444P"):
            #account for subsampling: reduces quality
            y,u,v = get_subsampling_divs(csc_format)
            div = 0.5   #any colourspace convertion will lose at least some quality (due to rounding)
            for div_x, div_y in (y, u, v):
                div += (div_x+div_y)/2.0/3.0
            quality = quality / div

        if csc_spec:
            #csc_spec.quality is the upper limit (up to 100):
            quality += csc_spec.quality
            quality /= 2.0

        if scaling==(1, 1) and csc_format not in ("YUV420P", "YUV422P") and self._current_quality==100 and encoder_spec.has_lossless_mode:
            #we want lossless!
            qscore = quality + 80
        else:
            #how far are we from the current quality heuristics?
            qscore = 100-abs(self._current_quality - quality)
            mq = self._fixed_min_quality
            if mq>=0:
                #if the encoder quality is lower or close to min_quality
                #then it isn't very suitable:
                mqs = max(0, quality - mq)*100/max(1, 100-mq)
                qscore = (qscore + mqs)//2
            #when downscaling, YUV420P should always win:
            if csc_format=="YUV420P" and scaling!=(1, 1):
                qscore *= 2.0
        return int(qscore)

    def get_speed_score(self, csc_format, csc_spec, encoder_spec, scaling):
        #score based on speed:
        speed = encoder_spec.speed
        if csc_spec:
            #when subsampling, add the speed gains to the video encoder
            #which now has less work to do:
            mult = 1.0
            if csc_format and csc_format in ("YUV420P", "YUV422P", "YUV444P"):
                #account for subsampling: increases encoding speed
                y,u,v = get_subsampling_divs(csc_format)
                mult = 0.0
                for div_x, div_y in (y, u, v):
                    mult += (div_x+div_y)/2.0/3.0
            #average and add 0.25 for the extra cost of doing the csc step:
            speed = (encoder_spec.speed * mult + csc_spec.speed) / 2.25

        #the lower the current speed
        #the more we need a fast encoder/csc to cancel it out:
        sscore = max(0, (100.0-self._current_speed) * speed/100.0)
        ms = self._fixed_min_speed
        if ms>=0:
            #if the encoder speed is lower or close to min_speed
            #then it isn't very suitable:
            mss = max(0, speed - ms)*100/max(1, 100-ms)
            sscore = (sscore + mss)/2.0
        #then always favour fast encoders:
        sscore += speed
        sscore /= 2
        return int(sscore)

    def get_score(self, enc_in_format, csc_spec, encoder_spec, width, height, scaling):
        """
            Given an optional csc step (csc_format and csc_spec), and
            and a required encoding step (encoder_spec and width/height),
            we calculate a score of how well this matches our requirements:
            * our quality target (as per get_currend_quality)
            * our speed target (as per _current_speed)
            * how expensive it would be to switch to this pipeline option
            Note: we know the current pipeline settings, so the "switching
            cost" will be lower for pipelines that share components with the
            current one.

            Can be called from any thread.
        """
        def clamp(v):
            return max(0, min(100, v))
        qscore = clamp(self.get_quality_score(enc_in_format, csc_spec, encoder_spec, scaling))
        sscore = clamp(self.get_speed_score(enc_in_format, csc_spec, encoder_spec, scaling))

        #runtime codec adjustements:
        runtime_score = 100
        #score for "edge resistance" via setup cost:
        ecsc_score = 100

        csc_width = 0
        csc_height = 0
        if csc_spec:
            #OR the masks so we have a chance of making it work
            width_mask = csc_spec.width_mask & encoder_spec.width_mask
            height_mask = csc_spec.height_mask & encoder_spec.height_mask
            csc_width = width & width_mask
            csc_height = height & height_mask
            if enc_in_format=="RGB":
                #converting to "RGB" is often a waste of CPU
                #(can only get selected because the csc step will do scaling,
                # but even then, the YUV subsampling are better options)
                ecsc_score = 1
            elif self._csc_encoder is None or self._csc_encoder.get_dst_format()!=enc_in_format or \
               type(self._csc_encoder)!=csc_spec.codec_class or \
               self._csc_encoder.get_src_width()!=csc_width or self._csc_encoder.get_src_height()!=csc_height:
                #if we have to change csc, account for new csc setup cost:
                ecsc_score = max(0, 80 - csc_spec.setup_cost*80.0/100.0)
            else:
                ecsc_score = 80
            ecsc_score += csc_spec.score_boost
            runtime_score *= csc_spec.get_runtime_factor()

            csc_scaling = scaling
            encoder_scaling = (1, 1)
            if scaling!=(1,1) and not csc_spec.can_scale:
                #csc cannot take care of scaling, so encoder will have to:
                encoder_scaling = scaling
                csc_scaling = (1, 1)
            if scaling!=(1, 1):
                #if we are (down)scaling, we should prefer lossy pixel formats:
                v = LOSSY_PIXEL_FORMATS.get(enc_in_format, 1)
                qscore *= (v/2)
            enc_width, enc_height = self.get_encoder_dimensions(csc_spec, encoder_spec, csc_width, csc_height, scaling)
        else:
            #not using csc at all!
            ecsc_score = 100
            width_mask = encoder_spec.width_mask
            height_mask = encoder_spec.height_mask
            enc_width = width & width_mask
            enc_height = height & height_mask
            csc_scaling = None
            encoder_scaling = scaling

        if encoder_scaling!=(1,1) and not encoder_spec.can_scale:
            #we need the encoder to scale but it cannot do it, fail it:
            scorelog("scaling (%s) not supported by %s", encoder_scaling, encoder_spec)
            return None

        ee_score = 100
        ve = self._video_encoder
        if ve is None or ve.get_type()!=encoder_spec.codec_type or \
           ve.get_src_format()!=enc_in_format or \
           ve.get_width()!=enc_width or ve.get_height()!=enc_height:
            #account for new encoder setup cost:
            ee_score = 100 - encoder_spec.setup_cost
            ee_score += encoder_spec.score_boost
        #edge resistance score: average of csc and encoder score:
        er_score = (ecsc_score + ee_score) / 2.0
        score = int((qscore+sscore+er_score)*runtime_score/100.0/3.0)
        scorelog("get_score(%-7s, %-24r, %-24r, %5i, %5i) quality: %2i, speed: %2i, setup: %2i runtime: %2i scaling: %s / %s, encoder dimensions=%sx%s, score=%2i",
                 enc_in_format, csc_spec, encoder_spec, width, height,
                 qscore, sscore, er_score, runtime_score, scaling, encoder_scaling, enc_width, enc_height, score)
        return score, scaling, csc_scaling, csc_width, csc_height, csc_spec, enc_in_format, encoder_scaling, enc_width, enc_height, encoder_spec

    def get_encoder_dimensions(self, csc_spec, encoder_spec, width, height, scaling=(1,1)):
        """
            Given a csc and encoder specs and dimensions, we calculate
            the dimensions that we would use as output.
            Taking into account:
            * applications can require scaling (see "scaling" attribute)
            * we scale fullscreen and maximize windows when at high speed
              and low quality.
            * we do not bother scaling small dimensions
            * the encoder may not support all dimensions
              (see width and height masks)
        """
        v, u = scaling
        enc_width = int(width * v / u) & encoder_spec.width_mask
        enc_height = int(height * v / u) & encoder_spec.height_mask
        return enc_width, enc_height

    def calculate_scaling(self, width, height, max_w=4096, max_h=4096):
        q = self._current_quality
        s = self._current_speed
        actual_scaling = self.scaling
        def get_min_required_scaling():
            if width<=max_w and height<=max_h:
                return (1, 1)       #no problem
            #most encoders can't deal with that!
            TRY_SCALE = ((2, 3), (1, 2), (1, 3), (1, 4), (1, 8), (1, 10))
            for op, d in TRY_SCALE:
                if width*op/d<=max_w and height*op/d<=max_h:
                    return (op, d)
            raise Exception("BUG: failed to find a scaling value for window size %sx%s", width, height)
        if not SCALING or not self.supports_video_scaling:
            #not supported by client or disabled by env
            #FIXME: what to do if width>max_w or height>max_h?
            actual_scaling = 1, 1
        elif self.scaling_control==0:
            #only enable if we have to:
            actual_scaling = get_min_required_scaling()
        elif SCALING_HARDCODED:
            actual_scaling = tuple(SCALING_HARDCODED)
            scalinglog("using hardcoded scaling: %s", actual_scaling)
        elif actual_scaling is None and (width>max_w or height>max_h):
            #most encoders can't deal with that!
            actual_scaling = get_min_required_scaling()
        elif actual_scaling is None and not self.is_shadow and self.statistics.damage_events_count>50 and (time.time()-self.statistics.last_resized)>0.5:
            #no scaling window attribute defined, so use heuristics to enable:
            #full frames per second (measured in pixels vs window size):
            ffps = 0
            stime = time.time()-5           #only look at the last 5 seconds max
            lde = [x for x in list(self.statistics.last_damage_events) if x[0]>stime]
            if len(lde)>10:
                #the first event's first element is the oldest event time:
                otime = lde[0][0]
                pixels = sum(w*h for _,_,_,w,h in lde)
                ffps = int(pixels/(width*height)/(time.time() - otime))

            #edge resistance for changing the current scaling value:
            er = 0
            if self.actual_scaling!=(1, 1):
                #if we are currently downscaling, stick with it a bit longer:
                #more so if we are downscaling a lot (1/3 -> er=1.5 + ..)
                #and yet even more if scaling_control is high (scaling_control=100 -> er= .. + 1)
                er = (0.5 * self.actual_scaling[1] / self.actual_scaling[0]) + self.scaling_control/100.0
            qs = s>(q-er*10) and q<(70+er*15)
            #scalinglog("calculate_scaling: er=%.1f, qs=%s, ffps=%s", er, qs, ffps)

            if self.fullscreen and (qs or ffps>=max(2, 10-er*3)):
                actual_scaling = 1,3
            elif self.maximized and (qs or ffps>=max(2, 10-er*3)):
                actual_scaling = 1,2
            elif width*height>=(2560-er*768)*1600 and (qs or ffps>=max(4, 25-er*5)):
                actual_scaling = 1,3
            elif width*height>=(1920-er*384)*1200 and (qs or ffps>=max(5, 30-er*10)):
                actual_scaling = 2,3
            elif width*height>=(1200-er*256)*1024 and (qs or ffps>=max(10, 50-er*15)):
                actual_scaling = 2,3
            if actual_scaling:
                scalinglog("calculate_scaling enabled by heuristics er=%.1f, qs=%s, ffps=%s", er, qs, ffps)
        if actual_scaling is None:
            actual_scaling = 1, 1
        v, u = actual_scaling
        if v/u>1.0:
            #never upscale before encoding!
            actual_scaling = 1, 1
        elif float(v)/float(u)<0.1:
            #don't downscale more than 10 times! (for each dimension - that's 100 times!)
            actual_scaling = 1, 10
        scalinglog("calculate_scaling%s=%s (q=%s, s=%s, scaling_control=%s)", (width, height, max_w, max_h), actual_scaling, q, s, self.scaling_control)
        return actual_scaling


    def check_pipeline(self, encoding, width, height, src_format):
        """
            Checks that the current pipeline is still valid
            for the given input. If not, close it and make a new one.

            Runs in the 'encode' thread.
        """
        if self.do_check_pipeline(encoding, width, height, src_format):
            return True  #OK!

        videolog("check_pipeline%s setting up a new pipeline as check failed", (encoding, width, height, src_format))
        #cleanup existing one if needed:
        csce = self._csc_encoder
        if csce:
            self._csc_encoder = None
            csce.clean()
        ve = self._video_encoder
        if ve:
            self._video_encoder = None
            ve.clean()
        #and make a new one:
        scores = self.get_video_pipeline_options(encoding, width, height, src_format)
        return self.setup_pipeline(scores, width, height, src_format)

    def do_check_pipeline(self, encoding, width, height, src_format):
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
            return False

        if csce:
            csc_width = width & self.width_mask
            csc_height = height & self.height_mask
            if csce.get_src_format()!=src_format:
                videolog("do_check_pipeline csc: switching source format from %s to %s",
                                    csce.get_src_format(), src_format)
                return False
            elif csce.get_src_width()!=csc_width or csce.get_src_height()!=csc_height:
                videolog("do_check_pipeline csc: window dimensions have changed from %sx%s to %sx%s, csc info=%s",
                                    csce.get_src_width(), csce.get_src_height(), csc_width, csc_height, csce.get_info())
                return False
            elif csce.get_dst_format()!=ve.get_src_format():
                videolog.warn("do_check_pipeline csc: intermediate format mismatch: %s vs %s, csc info=%s",
                                    csce.get_dst_format(), ve.get_src_format(), csce.get_info())
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

        if ve.get_encoding()!=encoding:
            videolog("do_check_pipeline video: invalid encoding %s, expected %s",
                                            ve.get_encoding(), encoding)
            return False
        elif ve.get_width()!=encoder_src_width or ve.get_height()!=encoder_src_height:
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
        start = time.time()
        if len(scores)==0:
            log.error("Error: no video pipeline options found for %s at %ix%i", src_format, width, height)
            return False
        videolog("setup_pipeline%s", (scores, width, height, src_format))
        for option in scores:
            try:
                videolog("setup_pipeline: trying %s", option)
                if self.setup_pipeline_option(width, height, src_format, *option):
                    #success!
                    return True
                else:
                    #skip cleanup below
                    continue
            except TransientCodecException as e:
                videolog.warn("setup_pipeline failed for %s: %s", option, e)
            except:
                videolog.warn("setup_pipeline failed for %s", option, exc_info=True)
            #we're here because an exception occurred, cleanup before trying again:
            csce = self._csc_encoder
            if csce:
                self._csc_encoder = None
                csce.clean()
            ve = self._video_encoder
            if ve:
                self._video_encoder = None
                ve.clean()
        end = time.time()
        videolog("setup_pipeline(..) failed! took %.2fms", (end-start)*1000.0)
        videolog.error("Error: failed to setup a video pipeline for %s at %ix%i", src_format, width, height)
        videolog.error(" tried the following option%s", engs(scores))
        for option in scores:
            videolog.error(" %s", option)
        return False

    def setup_pipeline_option(self, width, height, src_format,
                      _score, scaling, _csc_scaling, csc_width, csc_height, csc_spec,
                      enc_in_format, encoder_scaling, enc_width, enc_height, encoder_spec):
        speed = self._current_speed
        quality = self._current_quality
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
            csc_speed = min(speed, 100-quality/2.0)
            csc_start = time.time()
            csce = csc_spec.make_instance()
            csce.init_context(csc_width, csc_height, src_format,
                                   enc_width, enc_height, enc_in_format, csc_speed)
            csc_end = time.time()
            videolog("setup_pipeline: csc=%s, info=%s, setup took %.2fms",
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
        enc_start = time.time()
        #FIXME: filter dst_formats to only contain formats the encoder knows about?
        dst_formats = self.full_csc_modes.get(encoder_spec.encoding)
        ve = encoder_spec.make_instance()
        options = self.encoding_options.copy()
        if encoder_spec.encoding in self.supports_video_b_frames and B_FRAMES:
            options["b-frames"] = True
        ve.init_context(enc_width, enc_height, enc_in_format, dst_formats, encoder_spec.encoding, quality, speed, encoder_scaling, options)
        #record new actual limits:
        self.actual_scaling = scaling
        self.width_mask = width_mask
        self.height_mask = height_mask
        self.min_w = min_w
        self.min_h = min_h
        self.max_w = max_w
        self.max_h = max_h
        enc_end = time.time()
        self._video_encoder = ve
        videolog("setup_pipeline: csc=%s, video encoder=%s, info: %s, setup took %.2fms",
                csce, ve, ve.get_info(), (enc_end-enc_start)*1000.0)
        scalinglog("setup_pipeline: scaling=%s, encoder_scaling=%s", scaling, encoder_scaling)
        return  True


    def video_fallback(self, image, options):
        #find one that is not video:
        fallback_encodings = [x for x in PREFERED_ENCODING_ORDER if (x in self.non_video_encodings and x in self._encoders and x!="mmap")]
        if not fallback_encodings:
            log.error("no non-video fallback encodings are available!")
            return None
        fallback_encoding = fallback_encodings[0]
        encode_fn = self._encoders[fallback_encoding]
        return encode_fn(fallback_encoding, image, options)

    def video_encode(self, encoding, image, options):
        """
            This method is used by make_data_packet to encode frames using video encoders.
            Video encoders only deal with fixed dimensions,
            so we must clean and reinitialize the encoder if the window dimensions
            has changed.

            Runs in the 'encode' thread.
        """
        x, y, w, h = image.get_geometry()[:4]
        assert self.supports_video_subregion or (x==0 and y==0), "invalid position: %s,%s" % (x,y)
        src_format = image.get_pixel_format()
        if self.pixel_format!=src_format:
            videolog.warn("image pixel format changed from %s to %s", self.pixel_format, src_format)
            self.pixel_format = src_format

        def video_fallback():
            videolog.warn("using non-video fallback encoding")
            return self.video_fallback(image, options)

        vh = self.video_helper
        if vh is None:
            return None         #shortcut when closing down
        if not self.check_pipeline(encoding, w, h, src_format):
            #just for diagnostics:
            supported_csc_modes = self.full_csc_modes.get(encoding, [])
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
            videolog.error("Error: failed to setup a video pipeline for %s encoding with source format %s", encoding, src_format)
            videolog.error(" all encoders: %s", ", ".join(list(set([es.codec_type for sublist in encoder_specs.values() for es in sublist]))))
            videolog.error(" supported CSC modes: %s", ", ".join(supported_csc_modes))
            videolog.error(" supported encoders: %s", ", ".join(encoder_types))
            videolog.error(" encoders CSC modes: %s", ", ".join(ecsc))
            if FORCE_CSC:
                log.error(" forced csc mode: %s", FORCE_CSC_MODE)
            return video_fallback()
        ve = self._video_encoder
        if not ve:
            return video_fallback()

        #dw and dh are the edges we don't handle here
        width = w & self.width_mask
        height = h & self.height_mask
        videolog("video_encode%s image size: %sx%s, encoder/csc size: %sx%s", (encoding, image, options), w, h, width, height)

        csc_image, csc, enc_width, enc_height = self.csc_image(image, width, height)

        start = time.time()
        quality = max(0, min(100, self._current_quality))
        speed = max(0, min(100, self._current_speed))
        ret = ve.compress_image(csc_image, quality, speed, options)
        if ret is None:
            videolog.error("video_encode: ouch, %s compression failed", encoding)
            return None
        data, client_options = ret
        end = time.time()

        self.free_image_wrapper(csc_image)
        del csc_image

        if self.b_frame_flush_timer:
            self.source_remove(self.b_frame_flush_timer)
            self.b_frame_flush_timer = None
        delayed = client_options.get("delayed")
        if delayed is not None:
            last_frame = client_options.get("frame")
            flush_delay = max(100, min(500, int(self.batch_config.delay*10)))
            videolog("schedule video_encoder_flush for encoder %s, last frame=%i, client_options=%s, flush delay=%i", ve, last_frame, client_options, flush_delay)
            self.b_frame_flush_timer = self.timeout_add(flush_delay, self.flush_video_encoder, ve, csc, last_frame, x, y)
            if data is None:
                return None

        #tell the client which colour subsampling we used:
        #(note: see csc_equiv!)
        client_options["csc"] = self.csc_equiv(csc)
        #tell the client about scaling (the size of the encoded picture):
        #(unless the video encoder has already done so):
        if self._csc_encoder and ("scaled_size" not in client_options) and (enc_width!=width or enc_height!=height):
            client_options["scaled_size"] = enc_width, enc_height
        videolog("video_encode %s encoder: %s %sx%s result is %s bytes (%.1f MPixels/s), client options=%s",
                            ve.get_type(), encoding, enc_width, enc_height, len(data), (enc_width*enc_height/(end-start+0.000001)/1024.0/1024.0), client_options)
        return ve.get_encoding(), Compressed(encoding, data), client_options, width, height, 0, 24

    def flush_video_encoder(self, ve, csc, frame, x, y):
        #this runs in the UI thread..
        #but we want to run from the encode thread to access the encoder:
        self.b_frame_flush_timer = None
        if self._video_encoder!=ve:
            return
        self.call_in_encode_thread(True, self.do_flush_video_encoder, ve, csc, frame, x, y)

    def do_flush_video_encoder(self, ve, csc, frame, x, y):
        videolog("do_flush_video_encoder%s", (ve, csc, frame, x, y))
        if self._video_encoder!=ve:
            return
        if frame==0:
            #x264 has problems if we try to re-use a context after flushing the first IDR frame
            self._video_encoder = None
            ve.clean()
            self.idle_add(self.full_quality_refresh)
            return
        v = ve.flush(frame)
        if not v:
            videolog("do_flush_video_encoder%s=%s", (ve, frame, x, y), v)
            return
        data, client_options = v
        client_options["csc"] = self.csc_equiv(csc)
        videolog("do_flush_video_encoder%s=(%s %s bytes, %s)", (ve, frame, x, y), len(data or ()), type(data), client_options)
        if data:
            w = ve.get_width()
            h = ve.get_height()
            encoding = ve.get_encoding()
            packet = self.make_draw_packet(x, y, w, h, encoding, Compressed(encoding, data), 0, client_options)
            self.queue_damage_packet(packet)
        #add check for delayed frames again if we support multiple b-frames


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
            return image, image.get_pixel_format(), width, height

        start = time.time()
        csc_image = csce.convert_image(image)
        end = time.time()
        #the image comes from the UI server, free it in the UI thread:
        self.idle_add(image.free)
        videolog("csc_image(%s, %s, %s) converted to %s in %.1fms (%.1f MPixels/s)",
                        image, width, height,
                        csc_image, (1000.0*end-1000.0*start), (width*height/(end-start+0.000001)/1024.0/1024.0))
        if not csc_image:
            raise Exception("csc_image: conversion of %s to %s failed" % (image, csce.get_dst_format()))
        assert csce.get_dst_format()==csc_image.get_pixel_format()
        return csc_image, csce.get_dst_format(), csce.get_dst_width(), csce.get_dst_height()
