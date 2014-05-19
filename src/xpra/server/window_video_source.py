# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2013, 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time
import math
import operator
from threading import Lock

from xpra.util import AtomicInteger
from xpra.net.protocol import Compressed
from xpra.codecs.codec_constants import get_avutil_enum_from_colorspace, get_subsampling_divs, get_default_csc_modes, \
                                        TransientCodecException, RGB_FORMATS, PIXEL_SUBSAMPLING, LOSSY_PIXEL_FORMATS
from xpra.server.window_source import WindowSource, MAX_PIXELS_PREFER_RGB
from xpra.gtk_common.region import rectangle, merge_all
from xpra.codecs.loader import PREFERED_ENCODING_ORDER
from xpra.log import Logger

log = Logger("video", "encoding")
scorelog = Logger("score")
sublog = Logger("subregion")


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
def parse_scaling_value(v):
    if not v:
        return None
    values = v.split(":", 1)
    values = [int(x) for x in values]
    for x in values:
        assert x>0, "invalid scaling value %s" % x
    if len(values)==1:
        return 1, values[0]
    assert values[0]<=values[1], "cannot upscale"
    return values[0], values[1]
SCALING_HARDCODED = parse_scaling_value(os.environ.get("XPRA_SCALING_HARDCODED", ""))


class WindowVideoSource(WindowSource):
    """
        A WindowSource that handles video codecs.
    """

    def __init__(self, *args):
        #this will call init_vars():
        WindowSource.__init__(self, *args)
        #client uses uses_swscale (has extra limits on sizes)
        self.uses_swscale = self.encoding_options.get("uses_swscale", True)
        self.uses_csc_atoms = self.encoding_options.get("csc_atoms", False)
        self.supports_video_scaling = self.encoding_options.get("video_scaling", False)
        self.supports_video_reinit = self.encoding_options.get("video_reinit", False)
        self.supports_video_subregion = self.encoding_options.get("video_subregion", False)

    def init_encoders(self):
        WindowSource.init_encoders(self)
        self.csc_modes = get_default_csc_modes(self.encoding_client_options)       #for pre 0.12 clients: just one list of modes for all encodings..
        self.full_csc_modes = {}                            #for 0.12 onwards: per encoding lists
        self.parse_csc_modes(self.encoding_options.get("csc_modes"), self.encoding_options.get("full_csc_modes"))

        self.video_encodings = self.video_helper.get_encodings()
        for x in self.video_encodings:
            if x in self.server_core_encodings:
                self._encoders[x] = self.video_encode
        #these are used for non-video areas, ensure "jpeg" is used if available
        #as we may be dealing with large areas still, and we want speed:
        nv_common = (set(self.server_core_encodings) & set(self.core_encodings)) - set(self.video_encodings)
        self.non_video_encodings = [x for x in PREFERED_ENCODING_ORDER if x in nv_common]

        self._csc_encoder = None
        self._video_encoder = None
        self._lock = Lock()               #to ensure we serialize access to the encoder and its internals

    def __repr__(self):
        return "WindowVideoSource(%s : %s)" % (self.wid, self.window_dimensions)

    def init_vars(self):
        WindowSource.init_vars(self)
        self.video_subregion = None
        self.video_subregion_counter = 0
        self.video_subregion_set_at = 0
        self.video_subregion_time = 0
        #keep track of how much extra we batch non-video regions (milliseconds):
        self.video_subregion_non_waited = 0
        self.video_subregion_non_max_wait = 150

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

        self.uses_swscale = False
        self.uses_csc_atoms = False
        self.supports_video_scaling = False
        self.supports_video_reinit = False
        self.supports_video_subregion = False

        self.csc_modes = []
        self.full_csc_modes = {}                            #for 0.12 onwards: per encoding lists
        self.video_encodings = []
        self.non_video_encodings = []


    def parse_csc_modes(self, csc_modes, full_csc_modes):
        #only override if values are specified:
        if csc_modes is not None and type(csc_modes) in (list, tuple):
            self.csc_modes = csc_modes
        if full_csc_modes is not None and type(full_csc_modes)==dict:
            self.full_csc_modes = full_csc_modes


    def add_stats(self, info, suffix=""):
        WindowSource.add_stats(self, info, suffix)
        prefix = "window[%s]." % self.wid
        info[prefix+"client.csc_modes"] = self.csc_modes
        if self.full_csc_modes is not None:
            for enc, csc_modes in self.full_csc_modes.items():
                info[prefix+"client.csc_modes.%s" % enc] = csc_modes
        info[prefix+"client.uses_swscale"] = self.uses_swscale
        info[prefix+"client.uses_csc_atoms"] = self.uses_csc_atoms
        info[prefix+"client.supports_video_scaling"] = self.supports_video_scaling
        info[prefix+"client.supports_video_reinit"] = self.supports_video_reinit
        info[prefix+"client.supports_video_subregion"] = self.supports_video_subregion
        sr = self.video_subregion
        if sr:
            info[prefix+"video_subregion"] = sr.x, sr.y, sr.width, sr.height
        info[prefix+"scaling"] = self.actual_scaling
        csce = self._csc_encoder
        if csce:
            info[prefix+"csc"+suffix] = csce.get_type()
            ci = csce.get_info()
            for k,v in ci.items():
                info[prefix+"csc."+k+suffix] = v
        ve = self._video_encoder
        if ve:
            info[prefix+"encoder"+suffix] = ve.get_type()
            vi = ve.get_info()
            for k,v in vi.items():
                info[prefix+"encoder."+k+suffix] = v
        lp = self.last_pipeline_params
        if lp:
            encoding, width, height, src_format = lp
            info[prefix+"encoding.pipeline_param.encoding"+suffix] = encoding
            info[prefix+"encoding.pipeline_param.dimensions"+suffix] = width, height
            info[prefix+"encoding.pipeline_param.src_format"+suffix] = src_format
        lps = self.last_pipeline_scores
        if lps:
            i = 0
            for score, csc_spec, enc_in_format, encoder_spec in lps:
                info[prefix+("encoding.pipeline_option[%s].score" % i)+suffix] = score
                info[prefix+("encoding.pipeline_option[%s].csc" % i)+suffix] = repr(csc_spec)
                info[prefix+("encoding.pipeline_option[%s].format" % i)+suffix] = str(enc_in_format)
                info[prefix+("encoding.pipeline_option[%s].encoder" % i)+suffix] = repr(encoder_spec)
                i += 1

    def cleanup(self):
        WindowSource.cleanup(self)
        self.cleanup_codecs()

    def cleanup_codecs(self):
        """ Video encoders (x264, nvenc and vpx) and their csc helpers
            require us to run cleanup code to free the memory they use.
            But some cleanups may be slow, so run them in a worker thread.
        """
        if self._csc_encoder is None and self._video_encoder is None:
            return
        try:
            self._lock.acquire()
            self.do_csc_encoder_cleanup()
            self.do_video_encoder_cleanup()
        finally:
            self._lock.release()

    def do_csc_encoder_cleanup(self):
        #MUST be called with video lock held!
        if self._csc_encoder is None:
            return
        self._csc_encoder.clean()
        self._csc_encoder = None

    def do_video_encoder_cleanup(self):
        #MUST be called with video lock held!
        if self._video_encoder is None:
            return
        self._video_encoder.clean()
        self._video_encoder = None

    def set_new_encoding(self, encoding):
        if self.encoding!=encoding:
            #ensure we re-init the codecs asap:
            self.cleanup_codecs()
        WindowSource.set_new_encoding(self, encoding)

    def set_client_properties(self, properties):
        #client may restrict csc modes for specific windows
        self.parse_csc_modes(properties.get("encoding.csc_modes"), properties.get("encoding.full_csc_modes"))
        self.supports_video_scaling = properties.get("encoding.video_scaling", self.supports_video_scaling)
        self.supports_video_subregion = properties.get("encoding.video_subregion", self.supports_video_subregion)
        self.uses_swscale = properties.get("encoding.uses_swscale", self.uses_swscale)
        WindowSource.set_client_properties(self, properties)
        #encodings may have changed, so redo this:
        nv_common = (set(self.server_core_encodings) & set(self.core_encodings)) - set(self.video_encodings)
        self.non_video_encodings = [x for x in PREFERED_ENCODING_ORDER if x in nv_common]
        log("set_client_properties(%s) csc_modes=%s, full_csc_modes=%s, video_scaling=%s, video_subregion=%s, uses_swscale=%s, non_video_encodings=%s", properties, self.csc_modes, self.full_csc_modes, self.supports_video_scaling, self.supports_video_subregion, self.uses_swscale, self.non_video_encodings)

    def unmap(self):
        WindowSource.cancel_damage(self)
        self.cleanup_codecs()

    def cancel_damage(self):
        WindowSource.cancel_damage(self)
        if self._last_sequence_queued<self._sequence:
            #we must clean the video encoder to ensure
            #we will resend a key frame because it looks like we will
            #drop a frame which is being processed
            self.cleanup_codecs()

    def must_batch(self, delay):
        #force batching when using video region
        #because the video region code is in the send_delayed path
        return (self.video_subregion is not None) or WindowSource.must_batch(self, delay)


    def identify_video_subregion(self):
        if self.statistics.damage_events_count < self.video_subregion_set_at:
            #stats got reset
            self.video_subregion_set_at = 0
        if self.encoding not in self.video_encodings:
            sublog("identify video: not using a video mode! (%s)", self.encoding)
            self.video_subregion = None
            return
        if self.full_frames_only:
            sublog("identify video: full frames only!")
            self.video_subregion = None
            return
        ww, wh = self.window_dimensions
        #validate against window dimensions:
        if self.video_subregion and (self.video_subregion.width>ww or self.video_subregion.height>wh):
            #region is now bigger than the window!
            self.video_subregion = None

        #arbitrary minimum size for regions we will look at:
        #(we don't want video regions smaller than this - too much effort for little gain)
        min_w = max(256, ww/4)
        min_h = max(192, wh/4)
        if ww<min_w or wh<min_h:
            sublog("identify video: window is too small")
            self.video_subregion = None
            return

        def update_markers():
            self.video_subregion_counter = self.statistics.damage_events_count
            self.video_subregion_time = time.time()

        def few_damage_events(event_types, event_count):
            elapsed = time.time()-self.video_subregion_time
            #how many damage events occurred since we chose this region:
            event_count = max(0, self.statistics.damage_events_count - self.video_subregion_set_at)
            #make the timeout longer when the region has worked longer:
            slow_region_timeout = 10 + math.log(2+event_count, 1.5)
            if self.video_subregion is not None and elapsed>=slow_region_timeout:
                sublog("identify video: too much time has passed (%is for %s %s events), clearing region", elapsed, event_types, event_count)
                update_markers()
                self.video_subregion_set_at = 0
                self.video_subregion = None
                return
            sublog("identify video: waiting for more damage events (%s)", self.statistics.damage_events_count)

        if self.video_subregion_counter+10>self.statistics.damage_events_count:
            #less than 20 events since last time we called update_markers:
            event_count = self.statistics.damage_events_count-self.video_subregion_counter
            few_damage_events("total", event_count)
            return
        update_markers()

        #create a list (copy) to work on:
        lde = list(self.statistics.last_damage_events)
        dc = len(lde)
        if dc<20:
            sublog("identify video: not enough damage events yet (%s)", dc)
            self.video_subregion_set_at = 0
            self.video_subregion = None
            return
        #count how many times we see each area, and keep track of those we ignore:
        damage_count = {}
        ignored_count = {}
        c = 0
        for _,x,y,w,h in lde:
            #ignore small regions:
            if w>=min_w and h>=min_h:
                damage_count.setdefault((x,y,w,h), AtomicInteger()).increase()
                c += 1
            else:
                ignored_count.setdefault((x,y,w,h), AtomicInteger()).increase()
        #ignore low counts, add them to ignored dict:
        min_count = max(2, len(lde)/40)
        low_count = dict((region, count) for (region, count) in damage_count.items() if int(count)<=min_count)
        ignored_count.update(low_count)
        damage_count = dict((region, count) for (region, count) in damage_count.items() if region not in low_count)
        if len(damage_count)==0:
            few_damage_events("large", 0)
            return
        most_damaged = int(sorted(damage_count.values())[-1])
        most_pct = 100*most_damaged/c
        sublog("identify video: most=%s%% damage count=%s", most_pct, damage_count)

        def select_most_damaged():
            #use the region responsible for most of the large damage requests:
            most_damaged_regions = [k for k,v in damage_count.items() if v==most_damaged]
            rect = rectangle(*most_damaged_regions[0])
            if rect.width>=ww or rect.height>=wh:
                sublog("most damaged region is the whole window!")
                self.video_subregion = None
                return
            self.video_subregion = rect
            self.video_subregion_set_at = self.statistics.damage_events_count
            sublog("identified video region (%s%% of large damage requests): %s", most_pct, self.video_subregion)

        #ignore current subregion, 80% is high enough:
        if most_damaged>c*80/100:
            select_most_damaged()
            return

        #see if we can keep the region we have (if any):
        if self.video_subregion:
            #percentage of window area it occupies:
            vs_pct = 100*(self.video_subregion.width*self.video_subregion.height)/(ww*wh)
            pixels_contained = sum(((w*h) for _,x,y,w,h in lde if self.video_subregion.contains(x,y,w,h)))
            pixels_not = sum(((w*h) for _,x,y,w,h in lde if not self.video_subregion.contains(x,y,w,h)))
            pixels_total = pixels_not + pixels_contained
            if pixels_total>0:
                #proportion of damage pixels contained within the region:
                pix_pct = 100*pixels_contained/pixels_total
                #how many damage events occurred since we chose this region:
                event_count = max(0, self.statistics.damage_events_count - self.video_subregion_set_at)
                #high ratio of damage events to window area at first,
                #but lower it as we get more events that match
                #(edge resistance of sorts: prevents outliers from making us drop the region
                # if we know it has worked well in the past)
                ratio = 3.0 - 2.0/max(1, event_count)
                if pix_pct>=min(75, vs_pct*ratio):
                    sublog("keeping existing video region (%s%% of window area %sx%s, %s%% of damage pixels): %s", vs_pct, ww, wh, pix_pct, self.video_subregion)
                    return

        #try again with 50% threshold:
        if most_damaged>c*50/100:
            select_most_damaged()
            return

        #group by size:
        size_count = {}
        for region, count in damage_count.items():
            _, _, w, h = region
            size_count.setdefault((w,h), AtomicInteger(0)).increase(int(count))
        #try by size alone:
        most_common_size = int(sorted(size_count.values())[-1])
        if most_common_size>=c*60/100:
            mcw, mch = [k for k,v in size_count.items() if v==most_common_size][0]
            #now this will match more than one area..
            #so find a recent one:
            for _,x,y,w,h in reversed(lde):
                if w>=ww or h>=wh:
                    continue
                if w==mcw and h==mch:
                    #recent and matching size, assume this is the one
                    self.video_subregion_set_at = self.statistics.damage_events_count
                    self.video_subregion = rectangle(x, y, w, h)
                    sublog("identified video region by size (%sx%s), using recent match: %s", mcw, mch, self.video_subregion)
                    return

        #try harder: try combining all the regions we haven't discarded
        #(flash player with firefox and youtube does stupid unnecessary repaints)
        if len(damage_count)>=2:
            merged = merge_all(damage_count.keys())
            #clamp it:
            merged.width = min(ww, merged.width)
            merged.height = min(wh, merged.height)
            #and make sure this does not end up much bigger than needed:
            merged_pixels = merged.width*merged.height
            unmerged_pixels = sum((int(w*h) for _,_,w,h in damage_count.keys()))
            if merged_pixels<ww*wh*70/100 and unmerged_pixels*140/100<merged_pixels and (merged.width<ww or merged.height<wh):
                self.video_subregion_set_at = self.statistics.damage_events_count
                self.video_subregion = merged
                sublog("identified merged video region: %s", self.video_subregion)
                return

        sublog("failed to identify a video region")
        self.video_subregion = None


    def do_send_delayed_regions(self, damage_time, window, regions, coding, options):
        """
            Overriden here so we can try to intercept the video_subregion if one exists.
        """
        #overrides the default method for finding the encoding of a region
        #so we can ensure we don't use the video encoder when we don't want to:

        def nonvideo(regions=regions, encoding=coding, exclude_region=None):
            WindowSource.do_send_delayed_regions(self, damage_time, window, regions, encoding, options, exclude_region=exclude_region, fallback=self.non_video_encodings)

        if self.is_tray:
            sublog("BUG? video for tray - don't use video region!")
            return nonvideo(encoding=None)

        if coding not in self.video_encodings:
            sublog("not a video encoding")
            return nonvideo()

        vr = self.video_subregion
        if vr is None:
            sublog("no video region, we may use the video encoder for something else")
            WindowSource.do_send_delayed_regions(self, damage_time, window, regions, coding, options)
            return
        assert not self.full_frames_only

        actual_vr = None
        if vr in regions:
            #found the video region the easy way: exact match in list
            actual_vr = vr
        else:
            #find how many pixels are within the region (roughly):
            #find all unique regions that intersect with it:
            inter = (vr.intersection_rect(r) for r in regions)
            inter = [x for x in inter if x is not None]
            if len(inter)>0:
                #merge all regions into one:
                in_region = None
                for i in inter:
                    if i is None:
                        continue
                    if in_region is None:
                        in_region = i
                    else:
                        in_region.merge_rect(i)
                if in_region:
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
            sublog("send_delayed_regions: video region %s not found in: %s (using non video encoding)", vr, regions)
            return nonvideo(encoding=None)

        #found the video region:
        #send this straight away using the video encoder:
        self.process_damage_region(damage_time, window, actual_vr.x, actual_vr.y, actual_vr.width, actual_vr.height, coding, options)

        #now substract this region from the rest:
        trimmed = []
        for r in regions:
            trimmed += r.substract_rect(actual_vr)
        if len(trimmed)==0:
            sublog("send_delayed_regions: nothing left after removing video region %s", actual_vr)
            return
        sublog("send_delayed_regions: substracted %s from %s gives us %s", actual_vr, regions, trimmed)

        #decide if we want to send the rest now or delay some more:
        event_count = max(0, self.statistics.damage_events_count - self.video_subregion_set_at)
        #only delay once the video encoder has deal with a few frames:
        if event_count>100:
            elapsed = int(1000.0*(time.time()-damage_time)) + self.video_subregion_non_waited
            if elapsed>=self.video_subregion_non_max_wait:
                #send now, reset delay:
                sublog("send_delayed_regions: non video regions have waited %sms already, sending", elapsed)
                self.video_subregion_non_waited = 0
            else:
                #delay further: just create new delayed region:
                sublog("send_delayed_regions: delaying non video regions some more")
                self._damage_delayed = time.time(), window, trimmed, coding, options
                delay = self.video_subregion_non_max_wait-elapsed
                self.expire_timer = self.timeout_add(int(delay), self.expire_delayed_region, delay)
                return
        nonvideo(regions=trimmed, encoding=None, exclude_region=actual_vr)


    def process_damage_region(self, damage_time, window, x, y, w, h, coding, options):
        WindowSource.process_damage_region(self, damage_time, window, x, y, w, h, coding, options)
        #now figure out if we need to send edges separately:
        dw = w - (w & self.width_mask)
        dh = h - (h & self.height_mask)
        if coding in self.video_encodings and (dw>0 or dh>0):
            #no point in using get_best_encoding here, rgb24 wins
            #(as long as the mask is small - and it is)
            if dw>0:
                WindowSource.process_damage_region(self, damage_time, window, x+w-dw, y, dw, h, "rgb24", options)
            if dh>0:
                WindowSource.process_damage_region(self, damage_time, window, x, y+h-dh, x+w, dh, "rgb24", options)


    def must_encode_full_frame(self, window, encoding):
        return WindowSource.must_encode_full_frame(self, window, encoding) or (encoding in self.video_encodings)


    def get_encoding_options(self, batching, pixel_count, ww, wh, speed, quality, current_encoding):
        """
            decide whether we send a full window update using the video encoder,
            or if a separate small region(s) is a better choice
        """
        def nonvideo(s=speed, q=quality):
            s = max(0, min(100, s))
            q = max(0, min(100, q))
            return WindowSource.get_encoding_options(self, batching, pixel_count, ww, wh, s, q, current_encoding)

        if current_encoding not in self.video_encodings:
            #not doing video, bail out:
            return nonvideo()

        if ww*wh<=MAX_NONVIDEO_PIXELS:
            #window is too small!
            return nonvideo()

        if ww<self.min_w or ww>self.max_w or wh<self.min_h or wh>self.max_h:
            #video encoder cannot handle this size!
            #(maybe this should be an 'assert' statement here?)
            return nonvideo()

        if time.time()-self.statistics.last_resized<0.150:
            #window has just been resized, may still resize
            return nonvideo(q=quality-30)

        if self.get_current_quality()!=quality or self.get_current_speed()!=speed:
            #quality or speed override, best not to force video encoder re-init
            return nonvideo()

        def lossless(reason):
            log("get_encoding_options(..) temporarily switching to lossless mode for %8i pixels: %s", pixel_count, reason)
            return nonvideo(q=100)

        #if speed is high, assume we have bandwidth to spare
        smult = max(1, (speed-75)/5.0)
        if pixel_count<=MAX_PIXELS_PREFER_RGB * smult:
            return lossless("low pixel count")

        if self.video_subregion and (self.video_subregion.width!=ww or self.video_subregion.height!=wh):
            #we have a video region, and this is not it, so don't use video
            #raise the quality as the areas around video tend to not be graphics
            return nonvideo(q=quality+30)

        #calculate the threshold for using video vs small regions:
        factors = (smult,                                       #speed multiplier
                   1 + int(self.is_OR)*2,                       #OR windows tend to be static
                   max(1, 10-self._sequence),                   #gradual discount the first 9 frames, as the window may be temporary
                   1 + int(batching)*2,                         #if we're not batching, allow more pixels
                   1.0 / (int(bool(self._video_encoder)) + 1)   #if we have a video encoder already, make it more likely we'll use it:
                   )
        max_nvp = int(reduce(operator.mul, factors, MAX_NONVIDEO_PIXELS))
        if pixel_count<=max_nvp:
            #below threshold
            return nonvideo()

        #ensure the dimensions we use for decision making are the ones actually used:
        ww = ww & self.width_mask
        wh = wh & self.height_mask
        if ww<self.min_w or ww>self.max_w or wh<self.min_h or wh>self.max_h:
            #failsafe:
            return nonvideo()
        return [current_encoding]

    def do_get_best_encoding(self, options, current_encoding, fallback):
        #video encodings: always pick from the ordered list of options
        #rather than sticking with the current encoding:
        return self.pick_encoding(options, fallback)


    def reconfigure(self, force_reload=False):
        """
            This is called when we want to force a full re-init (force_reload=True)
            or from the timer that allows to tune the quality and speed.
            (this tuning is done in WindowSource.reconfigure)
            Here we re-evaluate if the pipeline we are currently using
            is really the best one, and if not we switch to the best one.
            This uses get_video_pipeline_options() to get a list of pipeline
            options with a score for each.
        """
        log("reconfigure(%s) csc_encoder=%s, video_encoder=%s", force_reload, self._csc_encoder, self._video_encoder)
        WindowSource.reconfigure(self, force_reload)
        if self.supports_video_subregion:
            self.identify_video_subregion()
        if not self._video_encoder:
            return
        try:
            self._lock.acquire()
            ve = self._video_encoder
            if not ve or ve.is_closed():
                #could have been freed since we got the lock!
                return
            if force_reload:
                if self._csc_encoder:
                    self.do_csc_encoder_cleanup()
                self.do_video_encoder_cleanup()
                return

            pixel_format = None
            if self._csc_encoder:
                pixel_format = self._csc_encoder.get_src_format()
            else:
                pixel_format = ve.get_src_format()
            width = ve.get_width()
            height = ve.get_height()
            quality = self.get_current_quality()
            speed = self.get_current_speed()

            scores = self.get_video_pipeline_options(ve.get_encoding(), width, height, pixel_format)
            if len(scores)==0:
                log("reconfigure(%s) no pipeline options found!")
                return

            log("reconfigure(%s) best=%s", force_reload, scores[0])
            _, csc_spec, enc_in_format, encoder_spec = scores[0]
            if self._csc_encoder:
                if csc_spec is None or \
                   type(self._csc_encoder)!=csc_spec.codec_class or \
                   self._csc_encoder.get_dst_format()!=enc_in_format:
                    log("reconfigure(%s) found better csc encoder: %s", force_reload, scores[0])
                    self.do_csc_encoder_cleanup()
            if type(self._video_encoder)!=encoder_spec.codec_class or \
               self._video_encoder.get_src_format()!=enc_in_format:
                log("reconfigure(%s) found better video encoder: %s", force_reload, scores[0])
                self.do_video_encoder_cleanup()

            if self._video_encoder is None:
                self.setup_pipeline(scores, width, height, pixel_format)

            if self._video_encoder:
                self._video_encoder.set_encoding_speed(speed)
                self._video_encoder.set_encoding_quality(quality)
        finally:
            self._lock.release()


    def get_video_pipeline_options(self, encoding, width, height, src_format):
        """
            Given a picture format (width, height and src pixel format),
            we find all the pipeline options that will allow us to compress
            it using the given encoding.
            First, we try with direct encoders (for those that support the
            source pixel format natively), then we try all the combinations
            using csc encoders to convert to an intermediary format.
            Each solution is rated and we return all of them in descending
            score (best solution comes first).
        """
        scores = []
        #these are the CSC modes the client can handle for this encoding:
        #we must check that the output csc mode for each encoder is one of those
        supported_csc_modes = self.full_csc_modes.get(encoding, self.csc_modes)
        if len(supported_csc_modes)==0:
            return scores
        encoder_specs = self.video_helper.get_encoder_specs(encoding)
        if len(encoder_specs)==0:
            return scores
        scorelog("get_video_pipeline_options%s speed: %s (min %s), quality: %s (min %s)", (encoding, width, height, src_format), int(self.get_current_speed()), self.get_min_speed(), int(self.get_current_quality()), self.get_min_quality())
        def add_scores(info, csc_spec, enc_in_format):
            #find encoders that take 'enc_in_format' as input:
            colorspace_specs = encoder_specs.get(enc_in_format)
            if not colorspace_specs:
                return
            #log("%s encoding from %s: %s", info, pixel_format, colorspace_specs)
            for encoder_spec in colorspace_specs:
                #ensure that the output of the encoder can be processed by the client:
                matches = set(encoder_spec.output_colorspaces) & set(supported_csc_modes)
                if len(matches)==0:
                    continue
                score = self.get_score(enc_in_format, csc_spec, encoder_spec, width, height)
                if score>=0:
                    item = score, csc_spec, enc_in_format, encoder_spec
                    scores.append(item)
        if not FORCE_CSC or src_format==FORCE_CSC_MODE:
            add_scores("direct (no csc)", None, src_format)

        #now add those that require a csc step:
        csc_specs = self.video_helper.get_csc_specs(src_format)
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
        return s

    def csc_equiv(self, csc_mode):
        #in some places, we want to check against the subsampling used
        #and not the colorspace itself.
        #and NV12 uses the same subsampling as YUV420P...
        return {"NV12" : "YUV420P",
                "BGRX" : "YUV444P"}.get(csc_mode, csc_mode)


    def get_quality_score(self, csc_format, csc_spec, encoder_spec):
        quality = encoder_spec.quality
        if csc_format and csc_format in ("YUV420P", "YUV422P", "YUV444P"):
            #account for subsampling (reduces quality):
            y,u,v = get_subsampling_divs(csc_format)
            div = 0.5   #any colourspace convertion will lose at least some quality (due to rounding)
            for div_x, div_y in (y, u, v):
                div += (div_x+div_y)/2.0/3.0
            quality = quality / div

        if csc_spec:
            #csc_spec.quality is the upper limit (up to 100):
            quality += csc_spec.quality
            quality /= 2.0

        #the lower the current quality
        #the more we need an HQ encoder/csc to improve things:
        qscore = max(0, (100.0-self.get_current_quality()) * quality/100.0)
        mq = self.get_min_quality()
        if mq>=0:
            #if the encoder quality is lower or close to min_quality
            #then it isn't very suitable:
            mqs = max(0, quality - mq)*100/max(1, 100-mq)
            qscore = (qscore + mqs)/2.0
        return qscore

    def get_speed_score(self, csc_spec, encoder_spec):
        #score based on speed:
        speed = encoder_spec.speed
        if csc_spec:
            #average and add 0.25 for the extra cost
            speed += csc_spec.speed
            speed /= 2.25
        #the lower the current speed
        #the more we need a fast encoder/csc to cancel it out:
        sscore = max(0, (100.0-self.get_current_speed()) * speed/100.0)
        ms = self.get_min_speed()
        if ms>=0:
            #if the encoder speed is lower or close to min_speed
            #then it isn't very suitable:
            mss = max(0, speed - ms)*100/max(1, 100-ms)
            sscore = (sscore + mss)/2.0
        #then always favour fast encoders:
        sscore += speed
        sscore /= 2
        return sscore

    def get_score(self, csc_format, csc_spec, encoder_spec, width, height):
        """
            Given an optional csc step (csc_format and csc_spec), and
            and a required encoding step (encoder_spec and width/height),
            we calculate a score of how well this matches our requirements:
            * our quality target (as per get_currend_quality)
            * our speed target (as per get_current_speed)
            * how expensive it would be to switch to this pipeline option
            Note: we know the current pipeline settings, so the "switching
            cost" will be lower for pipelines that share components with the
            current one.
        """
        if self._video_encoder is not None and not self.supports_video_reinit \
            and self._video_encoder.get_encoding()==encoder_spec.encoding \
            and self._video_encoder.get_type()!=encoder_spec.codec_type:
            #client does not support video decoder reinit,
            #so we cannot swap for another encoder of the same type
            #(which would generate a new stream)
            scorelog("encoding (%s vs %s) or type (%s vs %s) mismatch, without support for reinit",
                     self._video_encoder.get_encoding(), encoder_spec.encoding, self._video_encoder.get_type(), encoder_spec.codec_type)
            return -1
        def clamp(v):
            return max(0, min(100, v))
        qscore = clamp(self.get_quality_score(csc_format, csc_spec, encoder_spec))
        sscore = clamp(self.get_speed_score(csc_spec, encoder_spec))

        scaling = self.calculate_scaling(width, height, encoder_spec.max_w, encoder_spec.max_h)
        #runtime codec adjustements:
        runtime_score = 100
        #score for "edge resistance" via setup cost:
        ecsc_score = 100
        if csc_spec:
            #OR the masks so we have a chance of making it work
            width_mask = csc_spec.width_mask & encoder_spec.width_mask
            height_mask = csc_spec.height_mask & encoder_spec.height_mask
            csc_width = width & width_mask
            csc_height = height & height_mask
            if csc_format=="RGB":
                #converting to "RGB" is often a waste of CPU
                #(can only get selected because the csc step will do scaling,
                # but even then, the YUV subsampling are better options)
                ecsc_score = 1
            elif self._csc_encoder is None or self._csc_encoder.get_dst_format()!=csc_format or \
               type(self._csc_encoder)!=csc_spec.codec_class or \
               self._csc_encoder.get_src_width()!=csc_width or self._csc_encoder.get_src_height()!=csc_height:
                #if we have to change csc, account for new csc setup cost:
                ecsc_score = max(0, 80 - csc_spec.setup_cost*80.0/100.0)
            else:
                ecsc_score = 80
            ecsc_score += csc_spec.score_boost
            runtime_score *= csc_spec.get_runtime_factor()

            encoder_scaling = (1, 1)
            if scaling!=(1,1) and not csc_spec.can_scale:
                #csc cannot take care of scaling, so encoder will have to:
                encoder_scaling = scaling
                scaling = (1, 1)
            if scaling!=(1, 1):
                #if we are (down)scaling, we should prefer lossy pixel formats:
                v = LOSSY_PIXEL_FORMATS.get(csc_format, 1)
                qscore *= (v/2)
            enc_width, enc_height = self.get_encoder_dimensions(csc_spec, encoder_spec, csc_width, csc_height, scaling)
        else:
            #not using csc at all!
            ecsc_score = 100
            width_mask = encoder_spec.width_mask
            height_mask = encoder_spec.height_mask
            enc_width = width & width_mask
            enc_height = height & height_mask
            encoder_scaling = scaling

        if encoder_scaling!=(1,1) and not encoder_spec.can_scale:
            #we need the encoder to scale but it cannot do it, fail it:
            scorelog("scaling not supported (%s)", encoder_scaling)
            return -1

        ee_score = 100
        if self._video_encoder is None or self._video_encoder.get_type()!=encoder_spec.codec_type or \
           self._video_encoder.get_src_format()!=csc_format or \
           self._video_encoder.get_width()!=enc_width or self._video_encoder.get_height()!=enc_height:
            #account for new encoder setup cost:
            ee_score = 100 - encoder_spec.setup_cost
            ee_score += encoder_spec.score_boost
        #edge resistance score: average of csc and encoder score:
        er_score = (ecsc_score + ee_score) / 2.0
        score = int((qscore+sscore+er_score)*runtime_score/100.0/3.0)
        scorelog("get_score(%-7s, %-24r, %-24r, %5i, %5i) quality: %2i, speed: %2i, setup: %2i runtime: %2i scaling: %s / %s, score=%2i",
                 csc_format, csc_spec, encoder_spec, width, height,
                 qscore, sscore, er_score, runtime_score, scaling, encoder_scaling, score)
        return score

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
        actual_scaling = self.scaling
        if not SCALING or not self.supports_video_scaling:
            #not supported by client or disabled by env:
            actual_scaling = 1, 1
        elif SCALING_HARDCODED:
            actual_scaling = tuple(SCALING_HARDCODED)
            log("using hardcoded scaling: %s", actual_scaling)
        elif actual_scaling is None:
            #no scaling window attribute defined, so use heuristics to enable:
            q = self.get_current_quality()
            s = self.get_current_speed()
            qs = s>q and q<80
            #full frames per second:
            ffps = 0
            lde = list(self.statistics.last_damage_events)
            if len(lde)>10:
                #the first event's first element is the oldest event time:
                otime = lde[0][0]
                pixels = sum(w*h for _,_,_,w,h in lde)
                ffps = int(pixels/(width*height)/(time.time() - otime))

            if width>max_w or height>max_h:
                #most encoders can't deal with that!
                d = 2
                while width/d>max_w or height/d>max_h:
                    d += 1
                actual_scaling = 1,d
            elif self.fullscreen and (qs or ffps>=10):
                actual_scaling = 1,3
            elif self.maximized and (qs or ffps>=10):
                actual_scaling = 1,2
            elif width*height>=2048*1200 and (q<80 or ffps>=25):
                actual_scaling = 1,3
            elif width*height>=1024*1024 and (q<80 or ffps>=30):
                actual_scaling = 2,3
        if actual_scaling is None:
            actual_scaling = 1, 1
        v, u = actual_scaling
        if v/u>1.0:
            #never upscale before encoding!
            actual_scaling = 1, 1
        elif float(v)/float(u)<0.1:
            #don't downscale more than 10 times! (for each dimension - that's 100 times!)
            actual_scaling = 1, 10
        return actual_scaling


    def check_pipeline(self, encoding, width, height, src_format):
        """
            Checks that the current pipeline is still valid
            for the given input. If not, close it and make a new one.
        """
        #must be called with video lock held!
        if self.do_check_pipeline(encoding, width, height, src_format):
            return True  #OK!

        #cleanup existing one if needed:
        if self._csc_encoder:
            self.do_csc_encoder_cleanup()
        if self._video_encoder:
            self.do_video_encoder_cleanup()
        #and make a new one:
        self.last_pipeline_params = encoding, width, height, src_format
        self.last_pipeline_scores = self.get_video_pipeline_options(encoding, width, height, src_format)
        return self.setup_pipeline(self.last_pipeline_scores, width, height, src_format)

    def do_check_pipeline(self, encoding, width, height, src_format):
        """
            Checks that the current pipeline is still valid
            for the given input. If not, close it and make a new one.
        """
        #must be called with video lock held!
        if self._video_encoder is None:
            return False

        if self._csc_encoder:
            csc_width = width & self.width_mask
            csc_height = height & self.height_mask
            if self._csc_encoder.get_src_format()!=src_format:
                log("check_pipeline csc: switching source format from %s to %s",
                                            self._csc_encoder.get_src_format(), src_format)
                return False
            elif self._csc_encoder.get_src_width()!=csc_width or self._csc_encoder.get_src_height()!=csc_height:
                log("check_pipeline csc: window dimensions have changed from %sx%s to %sx%s, csc info=%s",
                                            self._csc_encoder.get_src_width(), self._csc_encoder.get_src_height(), csc_width, csc_height, self._csc_encoder.get_info())
                return False
            elif self._csc_encoder.get_dst_format()!=self._video_encoder.get_src_format():
                log.warn("check_pipeline csc: intermediate format mismatch: %s vs %s, csc info=%s",
                                            self._csc_encoder.get_dst_format(), self._video_encoder.get_src_format(), self._csc_encoder.get_info())
                return False

            #encoder will take its input from csc:
            encoder_src_width = self._csc_encoder.get_dst_width()
            encoder_src_height = self._csc_encoder.get_dst_height()
        else:
            #direct to video encoder without csc:
            encoder_src_width = width & self.width_mask
            encoder_src_height = height & self.height_mask

            if self._video_encoder.get_src_format()!=src_format:
                log("check_pipeline video: invalid source format %s, expected %s",
                                                self._video_encoder.get_src_format(), src_format)
                return False

        if self._video_encoder.get_encoding()!=encoding:
            log("check_pipeline video: invalid encoding %s, expected %s",
                                            self._video_encoder.get_encoding(), encoding)
            return False
        elif self._video_encoder.get_width()!=encoder_src_width or self._video_encoder.get_height()!=encoder_src_height:
            log("check_pipeline video: window dimensions have changed from %sx%s to %sx%s",
                                            self._video_encoder.get_width(), self._video_encoder.get_height(), encoder_src_width, encoder_src_height)
            return False
        return True


    def setup_pipeline(self, scores, width, height, src_format):
        """
            Given a list of pipeline options ordered by their score
            and an input format (width, height and source pixel format),
            we try to create a working pipeline, trying each option
            until one succeeds.
        """
        assert width>0 and height>0, "invalid dimensions: %sx%s" % (width, height)
        start = time.time()
        log("setup_pipeline%s", (scores, width, height, src_format))
        for option in scores:
            try:
                _, csc_spec, enc_in_format, encoder_spec = option
                log("setup_pipeline: trying %s", option)
                if csc_spec and not csc_spec.can_scale:
                    #the csc module cannot scale, disable it:
                    scaling = (1, 1)
                else:
                    scaling = self.calculate_scaling(width, height, encoder_spec.max_w, encoder_spec.max_h)
                encoder_scaling = scaling
                speed = self.get_current_speed()
                quality = self.get_current_quality()
                min_w = 1
                min_h = 1
                max_w = 16384
                max_h = 16384
                if csc_spec:
                    #TODO: no need to OR encoder mask if we are scaling...
                    self.width_mask = csc_spec.width_mask & encoder_spec.width_mask
                    self.height_mask = csc_spec.height_mask & encoder_spec.height_mask
                    min_w = max(min_w, csc_spec.min_w)
                    min_h = max(min_h, csc_spec.min_h)
                    max_w = min(max_w, csc_spec.max_w)
                    max_h = min(max_h, csc_spec.max_h)
                    csc_width = width & self.width_mask
                    csc_height = height & self.height_mask
                    enc_width, enc_height = self.get_encoder_dimensions(csc_spec, encoder_spec, csc_width, csc_height, scaling)
                    encoder_scaling = (1, 1)
                    #csc speed is not very important compared to encoding speed,
                    #so make sure it never degrades quality
                    csc_speed = min(speed, 100-quality/2.0)
                    csc_start = time.time()
                    self._csc_encoder = csc_spec.make_instance()
                    self._csc_encoder.init_context(csc_width, csc_height, src_format,
                                                          enc_width, enc_height, enc_in_format, csc_speed)
                    csc_end = time.time()
                    log("setup_pipeline: csc=%s, info=%s, setup took %.2fms",
                          self._csc_encoder, self._csc_encoder.get_info(), (csc_end-csc_start)*1000.0)
                else:
                    #use the encoder's mask directly since that's all we have to worry about!
                    self.width_mask = encoder_spec.width_mask
                    self.height_mask = encoder_spec.height_mask
                    #restrict limits:
                    min_w = max(min_w, encoder_spec.min_w)
                    min_h = max(min_h, encoder_spec.min_h)
                    max_w = min(max_w, encoder_spec.max_w)
                    max_h = min(max_h, encoder_spec.max_h)
                    enc_width = width & self.width_mask
                    enc_height = height & self.height_mask
                    if encoder_scaling!=(1,1) and not encoder_spec.can_scale:
                        log("scaling is now enabled, so skipping %s", encoder_spec)
                        continue
                if width<=0 or height<=0:
                    #log.warn("skipping invalid dimensions..")
                    continue
                enc_start = time.time()
                #FIXME: filter dst_formats to only contain formats the encoder knows about?
                dst_formats = self.full_csc_modes.get(encoder_spec.encoding, self.csc_modes)
                self._video_encoder = encoder_spec.make_instance()
                self._video_encoder.init_context(enc_width, enc_height, enc_in_format, dst_formats, encoder_spec.encoding, quality, speed, encoder_scaling, self.encoding_options)
                #record new actual limits:
                self.actual_scaling = scaling
                self.min_w = min_w
                self.min_h = min_h
                self.max_w = max_w
                self.max_h = max_h
                enc_end = time.time()
                log("setup_pipeline: video encoder=%s, info: %s, setup took %.2fms",
                        self._video_encoder, self._video_encoder.get_info(), (enc_end-enc_start)*1000.0)
                return  True
            except TransientCodecException, e:
                log.warn("setup_pipeline failed for %s: %s", option, e)
                self.cleanup_codecs()
            except:
                log.warn("setup_pipeline failed for %s", option, exc_info=True)
                self.cleanup_codecs()
        end = time.time()
        log("setup_pipeline(..) failed! took %.2fms", (end-start)*1000.0)
        return False


    def video_encode(self, encoding, image, options):
        """
            This method is used by make_data_packet to encode frames using video encoders.
            Video encoders only deal with fixed dimensions,
            so we must clean and reinitialize the encoder if the window dimensions
            has changed.
            Since this runs in the non-UI thread 'data_to_packet', we must
            use the '_lock' to prevent races.
        """
        log("video_encode%s", (encoding, image, options))
        x, y, w, h = image.get_geometry()[:4]
        assert self.supports_video_subregion or (x==0 and y==0), "invalid position: %s,%s" % (x,y)
        src_format = image.get_pixel_format()
        try:
            self._lock.acquire()
            if not self.check_pipeline(encoding, w, h, src_format):
                #find one that is not video:
                fallback_encodings = set(self._encoders.keys) - set(self.video_encodings) - set(["mmap"])
                log.error("BUG: failed to setup a video pipeline for %s encoding with source format %s, will fallback to: %s", encoding, src_format, fallback_encodings)
                assert len(fallback_encodings)>0
                fallback_encoding = [x for x in PREFERED_ENCODING_ORDER if x in fallback_encodings][0]
                return self._encoders[fallback_encoding](fallback_encoding, image, options)

            #dw and dh are the edges we don't handle here
            width = w & self.width_mask
            height = h & self.height_mask
            log("video_encode%s wxh=%s-%s, widthxheight=%sx%s", (encoding, image, options), w, h, width, height)

            csc_image, csc, enc_width, enc_height = self.csc_image(image, width, height)

            start = time.time()
            ret = self._video_encoder.compress_image(csc_image, options)
            if ret is None:
                log.error("video_encode: ouch, %s compression failed", encoding)
                return None
            data, client_options = ret
            end = time.time()

            self.free_image_wrapper(csc_image)
            del csc_image

            if self.encoding_client_options:
                #tell the client which colour subsampling we used:
                #(note: see csc_equiv!)
                if self.uses_csc_atoms:
                    client_options["csc"] = self.csc_equiv(csc)
                else:
                    #ugly hack: expose internal ffmpeg/libav constant
                    #for old versions without the "csc_atoms" feature:
                    client_options["csc_pixel_format"] = get_avutil_enum_from_colorspace(csc)
                #tell the client about scaling (the size of the encoded picture):
                #(unless the video encoder has already done so):
                if self._csc_encoder and ("scaled_size" not in client_options) and (enc_width!=width or enc_height!=height):
                    client_options["scaled_size"] = enc_width, enc_height
            log("video_encode encoder: %s %sx%s result is %s bytes (%.1f MPixels/s), client options=%s",
                                encoding, enc_width, enc_height, len(data), (enc_width*enc_height/(end-start+0.000001)/1024.0/1024.0), client_options)
            return self._video_encoder.get_encoding(), Compressed(encoding, data), client_options, width, height, 0, 24
        finally:
            self._lock.release()

    def csc_image(self, image, width, height):
        """
            Takes a source image and converts it
            using the current csc_encoder.
            If there are no csc_encoders (because the video
            encoder can process the source format directly)
            then the image is returned unchanged.
        """
        if self._csc_encoder is None:
            #no csc step!
            return image, image.get_pixel_format(), width, height

        start = time.time()
        csc_image = self._csc_encoder.convert_image(image)
        end = time.time()
        #the image comes from the UI server, free it in the UI thread:
        self.idle_add(image.free)
        log("csc_image(%s, %s, %s) converted to %s in %.1fms (%.1f MPixels/s)",
                        image, width, height,
                        csc_image, (1000.0*end-1000.0*start), (width*height/(end-start+0.000001)/1024.0/1024.0))
        if not csc_image:
            raise Exception("csc_image: conversion of %s to %s failed" % (image, self._csc_encoder.get_dst_format()))
        assert self._csc_encoder.get_dst_format()==csc_image.get_pixel_format()
        return csc_image, self._csc_encoder.get_dst_format(), self._csc_encoder.get_dst_width(), self._csc_encoder.get_dst_height()
