# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2013-2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import math

from xpra.util import MutableInteger
from xpra.server.window.region import rectangle, add_rectangle, remove_rectangle, merge_all    #@UnresolvedImport
from xpra.log import Logger

sslog = Logger("regiondetect")
refreshlog = Logger("regionrefresh")

MIN_EVENTS = 20
MIN_W = 128
MIN_H = 96


class VideoSubregion(object):

    def __init__(self, timeout_add, source_remove, refresh_cb, auto_refresh_delay):
        self.timeout_add = timeout_add
        self.source_remove = source_remove
        self.refresh_cb = refresh_cb        #usage: refresh_cb(window, regions)
        self.auto_refresh_delay = auto_refresh_delay
        self.init_vars()

    def init_vars(self):
        self.enabled = True
        self.detection = True
        self.rectangle = None
        self.counter = 0
        self.set_at = 0
        self.time = 0
        self.refresh_timer = None
        self.refresh_regions = []
        #keep track of how much extra we batch non-video regions (milliseconds):
        self.non_waited = 0
        self.non_max_wait = 150

    def reset(self):
        self.cancel_refresh_timer()
        self.init_vars()

    def cleanup(self):
        self.reset()


    def __repr__(self):
        return "VideoSubregion(%s)" % self.get_info()


    def set_enabled(self, enabled):
        self.enabled = enabled
        if not enabled:
            self.novideoregion("disabled")

    def set_detection(self, detection):
        self.detection = detection

    def set_region(self, x, y, w, h):
        sslog("set_region%s", (x, y, w, h))
        if self.detection:
            sslog("video region detection is on - the given region may or may not stick")
        self.rectangle = rectangle(x, y, w, h)


    def set_auto_refresh_delay(self, d):
        refreshlog("subregion auto-refresh delay: %s", d)
        self.auto_refresh_delay = d

    def cancel_refresh_timer(self):
        rt = self.refresh_timer
        refreshlog("cancel_refresh_timer() timer=%s", rt)
        if rt:
            self.source_remove(rt)
            self.refresh_timer = None
            self.refresh_regions = []

    def get_info(self):
        r = self.rectangle
        info = {"enabled"   : self.enabled,
                "detection" : self.detection,
                "counter"   : self.counter,
                }
        if r is None:
            return info
        info.update({"x"            : r.x,
                     "y"            : r.y,
                     "width"        : r.width,
                     "height"       : r.height,
                     "rectangle"    : (r.x, r.y, r.width, r.height),
                     "set_at"       : self.set_at,
                     "time"         : int(self.time),
                     "non_waited"   : self.non_waited,
                     "non_max_wait" : self.non_max_wait})
        rr = list(self.refresh_regions)
        if rr:
            for i, r in enumerate(rr):
                info["refresh_region[%s]" % i] = (r.x, r.y, r.width, r.height)
        return info


    def remove_refresh_region(self, region):
        remove_rectangle(self.refresh_regions, region)
        refreshlog("remove_refresh_region(%s) updated refresh regions=%s", region, self.refresh_regions)


    def add_video_refresh(self, window, region):
        #called by add_refresh_region if the video region got painted on
        #Note: this does not run in the UI thread!
        rect = self.rectangle
        if not rect:
            return
        refreshlog("add_video_refresh(%s, %s) rectangle=%s", window, region, rect)
        #something in the video region is still refreshing,
        #so we re-schedule the subregion refresh:
        self.cancel_refresh_timer()
        #add the new region to what we already have:
        add_rectangle(self.refresh_regions, region)
        #do refresh any regions which are now outside the current video region:
        #(this can happen when the region moves or changes size)
        non_video = []
        for r in self.refresh_regions:
            if not rect.contains_rect(r):
                non_video += r.substract_rect(rect)
        delay = max(150, self.auto_refresh_delay)
        if non_video:
            #refresh via timeout_add so this will run in the UI thread:
            self.timeout_add(delay, self.refresh_cb, window, non_video)
            #only keep the regions still in the video region:
            inrect = [rect.intersection_rect(r) for r in self.refresh_regions]
            self.refresh_regions = [r for r in inrect if r is not None]
        #re-schedule the video region refresh (if we have regions to fresh):
        if self.refresh_regions:
            def refresh():
                #runs via timeout_add, safe to call UI!
                self.refresh_timer = None
                regions = self.refresh_regions
                self.refresh_regions = []
                #it probably makes sense to refresh the whole thing:
                #(the window source code doesn't know about the video region,
                # and would decide to do many overlapping refreshes)
                if len(regions)>=2 and rect:
                    regions = [rect]
                refreshlog("refresh() calling %s with regions=%s", self.refresh_cb, regions)
                self.refresh_cb(window, regions)
            self.refresh_timer = self.timeout_add(delay, refresh)


    def novideoregion(self, msg="", *args):
        sslog("novideoregion: "+msg, *args)
        self.rectangle = None
        self.set_at = 0
        self.counter = 0

    def identify_video_subregion(self, ww, wh, damage_events_count, last_damage_events, starting_at=0):
        if not self.detection:
            return
        if not self.enabled:
            #could have been disabled since we started this method!
            self.novideoregion("disabled")
        sslog("%s.identify_video_subregion(..)", self)
        sslog("identify_video_subregion(%s, %s, %s, %s)", ww, wh, damage_events_count, last_damage_events)

        def setnewregion(rect, msg="", *args):
            if rect.x<=0 and rect.y<=0 and rect.width>=ww and rect.height>=wh:
                #same size as the window, don't use a region!
                self.novideoregion("region is full window")
                return
            sslog("setting new region %s: "+msg, rect, *args)
            self.set_at = damage_events_count
            self.counter = damage_events_count
            if not self.enabled:
                #could have been disabled since we started this method!
                self.novideoregion("disabled")
            if not self.detection:
                return
            self.rectangle = rect

        if damage_events_count < self.set_at:
            #stats got reset
            self.video_subregion_set_at = 0
        #validate against window dimensions:
        rect = self.rectangle
        if rect and (rect.width>ww or rect.height>wh):
            #region is now bigger than the window!
            return self.novideoregion("window is now smaller than current region")
        #arbitrary minimum size for regions we will look at:
        #(we don't want video regions smaller than this - too much effort for little gain)
        if ww<MIN_W or wh<MIN_H:
            return self.novideoregion("window is too small: %sx%s", MIN_W, MIN_H)

        def update_markers():
            self.counter = damage_events_count
            self.time = time.time()

        def few_damage_events(event_types, event_count):
            elapsed = time.time()-self.time
            #how many damage events occurred since we chose this region:
            event_count = max(0, damage_events_count - self.set_at)
            #make the timeout longer when the region has worked longer:
            slow_region_timeout = 2 + math.log(2+event_count, 1.5)
            if rect and elapsed>=slow_region_timeout:
                update_markers()
                return self.novideoregion("too much time has passed (%is for %s %s events)", elapsed, event_types, event_count)
            sslog("identify video: waiting for more %s damage events (%s) counters: %s / %s", event_types, event_count, self.counter, damage_events_count)

        if self.counter+10>damage_events_count:
            #less than 10 events since last time we called update_markers:
            event_count = damage_events_count-self.counter
            few_damage_events("total", event_count)
            return

        #create a list (copy) to work on:
        lde = [x for x in list(last_damage_events) if x[0]>=starting_at]
        dc = len(lde)
        if dc<=MIN_EVENTS:
            return self.novideoregion("not enough damage events yet (%s)", dc)
        #structures for counting areas and sizes:
        wc = {}
        hc = {}
        dec = {}
        #count how many times we see each area, each width/height and where:
        for _,x,y,w,h in lde:
            r = rectangle(x,y,w,h)
            dec.setdefault(r, MutableInteger()).increase()
            if w>=MIN_W:
                wc.setdefault(w, dict()).setdefault(x, set()).add(r)
            if h>=MIN_H:
                hc.setdefault(h, dict()).setdefault(y, set()).add(r)

        def score_region(info, region, ignore_size=0):
            #check if the region given is a good candidate, and if so we use it
            #clamp it:
            width = min(ww, region.width)
            height = min(wh, region.height)
            if width<MIN_W or height<MIN_H:
                #too small, ignore it:
                return 0
            #and make sure this does not end up much bigger than needed:
            insize = width*height
            if ww*wh<insize:
                return 0
            #count how many pixels are in or out if this region
            incount, outcount = 0, 0
            for r, count in dec.items():
                inregion = r.intersection_rect(region)
                if inregion:
                    incount += inregion.width*inregion.height*int(count)
                outregions = r.substract_rect(region)
                for x in outregions:
                    if ignore_size>0 and x.width*x.height<ignore_size:
                        #skip small region outside rectangle
                        continue
                    outcount += x.width*x.height*int(count)
            total = incount+outcount
            assert total>0
            inpct = 100*incount/total
            outpct = 100*outcount/total
            #devaluate by taking into account the number of pixels in the area
            #so that a large video region only wins if it really
            #has a larger proportion of the pixels
            #(offset the "insize" to even things out a bit:
            # if we have a series of vertical or horizontal bands that we merge,
            # we would otherwise end up excluding the ones on the edge
            # if they ever happen to have a slightly lower hit count)
            score = inpct * ww*wh*2 / (ww*wh + insize)
            sslog("testing %12s video region %34s: %3i%% in, %3i%% out, %3i%% of window, score=%2i",
                  info, region, inpct, outpct, 100*width*height/ww/wh, score)
            return score

        update_markers()

        #see if we can keep the region we already have (if any):
        cur_score = 0
        if rect:
            cur_score = score_region("current", rect)
            if cur_score>=125:
                sslog("keeping existing video region %s with score %s", rect, cur_score)
                return

        scores = {None : 0}

        #split the regions we really care about (enough pixels, big enough):
        damage_count = {}
        min_count = max(2, len(lde)/40)
        for r, count in dec.items():
            #ignore small regions:
            if count>min_count and r.width>=MIN_W and r.height>=MIN_H:
                damage_count[r] = count
        c = sum([int(x) for x in damage_count.values()])
        most_damaged = -1
        most_pct = 0
        if c>0:
            most_damaged = int(sorted(damage_count.values())[-1])
            most_pct = 100*most_damaged/c
            sslog("identify video: most=%s%% damage count=%s", most_pct, damage_count)
            #is there a region that stands out?
            #try to use the region which is responsible for most of the large damage requests:
            most_damaged_regions = [r for r,v in damage_count.items() if v==most_damaged]
            if len(most_damaged_regions)==1:
                r = most_damaged_regions[0]
                score = score_region("most-damaged", r)
                sslog("identify video: score most damaged area %s=%s%%", r, score)
                if score>120:
                    setnewregion(r, "%s%% of large damage requests, score=%s", most_pct, score)
                    return
                elif score>=100:
                    scores[r] = score

        #try harder: try combining regions with the same width or height:
        #(some video players update the video region in bands)
        for w, d in wc.items():
            for x,regions in d.items():
                if len(regions)>=2:
                    #merge regions of width w at x
                    min_count = max(2, len(regions)/25)
                    keep = [r for r in regions if int(dec.get(r, 0))>=min_count]
                    sslog("vertical regions of width %i at %i with at least %i hits: %s", w, x, min_count, keep)
                    if keep:
                        merged = merge_all(keep)
                        scores[merged] = score_region("vertical", merged, 48*48)
        for h, d in hc.items():
            for y,regions in d.items():
                if len(regions)>=2:
                    #merge regions of height h at y
                    min_count = max(2, len(regions)/25)
                    keep = [r for r in regions if int(dec.get(r, 0))>=min_count]
                    sslog("horizontal regions of height %i at %i with at least %i hits: %s", h, y, min_count, keep)
                    if keep:
                        merged = merge_all(keep)
                        scores[merged] = score_region("horizontal", merged, 48*48)

        sslog("merged regions scores: %s", scores)
        highscore = max(scores.values())
        #a score of 100 is neutral
        if highscore>=120:
            region = [r for r,s in scores.items() if s==highscore][0]
            return setnewregion(region, "very high score: %s", highscore)

        #retry existing region, tolerate lower score:
        if cur_score>=90:
            sslog("keeping existing video region %s with score %s", rect, cur_score)
            return

        if highscore>=100:
            region = [r for r,s in scores.items() if s==highscore][0]
            return setnewregion(region, "high score: %s", highscore)

        #FIXME: re-add some scrolling detection

        #try harder still: try combining all the regions we haven't discarded
        #(flash player with firefox and youtube does stupid unnecessary repaints)
        if len(damage_count)>=2:
            merged = merge_all(damage_count.keys())
            score = score_region("merged", merged)
            if score>=110:
                return setnewregion(merged, "merged all regions, score=%s", score, 48*48)

        self.novideoregion("failed to identify a video region")
