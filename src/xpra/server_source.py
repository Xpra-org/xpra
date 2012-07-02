# coding=utf8 
# This file is part of Parti.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


import gtk.gdk
gtk.gdk.threads_init()

import gobject
try:
    from StringIO import StringIO   #@UnusedImport
except:
    from io import StringIO         #@UnresolvedImport @Reimport
import time
import ctypes
from threading import Thread, Lock
try:
    from queue import Queue         #@UnresolvedImport @UnusedImport (python3)
except:
    from Queue import Queue         #@Reimport
from collections import deque
from math import log as mathlog
def logp2(x):
    return mathlog(1+max(1, x), 2)
def logp10(x):
    return mathlog(9+max(1, x), 10)

#it would be nice to be able to get rid of those 2 imports here:
from wimpiggy.window import OverrideRedirectWindowModel
from wimpiggy.lowlevel import get_rectangle_from_region   #@UnresolvedImport

from wimpiggy.log import Logger
log = Logger()

from xpra.deque import maxdeque
from xpra.protocol import Compressible
from xpra.scripts.main import ENCODINGS


def get_rgb_rawdata(damage_time, wid, pixmap, x, y, width, height, encoding, sequence, options):
    start = time.time()
    pixmap_w, pixmap_h = pixmap.get_size()
    # Just in case we somehow end up with damage larger than the pixmap,
    # we don't want to start requesting random chunks of memory (this
    # could happen if a window is resized but we don't throw away our
    # existing damage map):
    assert x >= 0
    assert y >= 0
    if x + width > pixmap_w:
        width = pixmap_w - x
    if y + height > pixmap_h:
        height = pixmap_h - y
    if width <= 0 or height <= 0:
        return None
    pixbuf = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, False, 8, width, height)
    pixbuf.get_from_drawable(pixmap, pixmap.get_colormap(), x, y, 0, 0, width, height)
    log("get_rgb_rawdata(..) pixbuf.get_from_drawable took %s ms", int(1000*(time.time()-start)))
    raw_data = pixbuf.get_pixels()
    rowstride = pixbuf.get_rowstride()
    return (damage_time, wid, x, y, width, height, encoding, raw_data, rowstride, sequence, options)

def dec1(x):
    #for pretty debug output of decimals:
    return int(10.0*x)/10.0


class DamageBatchConfig(object):
    """
    Encapsulate all the damage batching configuration into one object.
    """
    ENABLED = True
    ALWAYS = False
    MAX_EVENTS = 80                     #maximum number of damage events
    MAX_PIXELS = 1024*1024*MAX_EVENTS   #small screen at MAX_EVENTS frames
    TIME_UNIT = 1                       #per second
    MIN_DELAY = 5
    MAX_DELAY = 15000
    RECALCULATE_DELAY = 0.04           #re-compute delay 25 times per second at most
    def __init__(self):
        self.enabled = self.ENABLED
        self.always = self.ALWAYS
        self.max_events = self.MAX_EVENTS
        self.max_pixels = self.MAX_PIXELS
        self.time_unit = self.TIME_UNIT
        self.min_delay = self.MIN_DELAY
        self.max_delay = self.MAX_DELAY
        self.delay = self.MIN_DELAY
        self.recalculate_delay = self.RECALCULATE_DELAY
        self.last_delays = maxdeque(64)
        self.last_updated = 0
        self.encoding = None

    def clone(self):
        c = DamageBatchConfig()
        for x in ["enabled", "always", "min_delay", "max_delay", "delay", "last_delays"]:
            setattr(c, x, getattr(self, x))
        return c

class ServerSource(object):
    """
    Strategy: if we have ordinary packets to send, send those.
    When we don't, then send window updates (expired ones first).
    The UI thread adds damage requests to a queue - see damage()
    """

    def __init__(self, protocol, batch_config, encoding, mmap, mmap_size):
        self._ordinary_packets = []
        self._protocol = protocol
        self._encoding = encoding
        self._damage_cancelled = {}
        self._damage_last_events = {}
        self._damage_delayed = {}
        self._damage_stats = {}
        self.client_decode_time = {}
        # for managing sequence numbers:
        self._sequence = 1                      #increase with every Region
        self._damage_packet_sequence = 1        #increase with every packet send
        self._damage_packet_sizes = maxdeque(100)
        self._damage_latency = maxdeque(100)
        self._client_latency = maxdeque(100)
        self.last_client_packet_sequence = -1   #the last damage_packet_sequence the client echoed back to us
        self.last_client_delta = None           #last delta between our damage_packet_sequence and last_client_packet_sequence
        self.default_batch_config = batch_config
        self.batch_configs = {}
        # mmap:
        self._mmap = mmap
        self._mmap_size = mmap_size
        self._mmap_bytes_sent = 0
        protocol.source = self
        self._damage_data_queue = Queue()
        self._damage_data_queue_sizes = maxdeque(100)
        self._damage_packet_queue = deque()
        self._damage_packet_queue_sizes = maxdeque(100)
        self._damage_packet_queue_pixels = maxdeque(100)

        self._closed = False
        self._video_encoder_cleanup = {}
        self._video_encoder_lock = Lock()

        def start_daemon_thread(target, name):
            t = Thread(target=target)
            t.name = name
            t.daemon = True
            t.start()
            return t
        self._datapacket_thread = start_daemon_thread(self.data_to_packet, "data_to_packet")

    def close(self):
        self._closed = True
        self._damage_data_queue.put(None, block=False)
        self.video_encoder_cleanup()

    def video_encoder_cleanup(self):
        try:
            self._video_encoder_lock.acquire()
            for wid,cb in self._video_encoder_cleanup.items():
                try:
                    log("calling %s for wid=%s", cb, wid)
                    cb()
                except:
                    log.error("error on close callback %s", cb, exc_info=True)
            self._video_encoder_cleanup = {}
        finally:
            self._video_encoder_lock.release()

    def next_packet(self):
        packet, cb, have_more = None, None, False
        if not self._closed:
            if self._ordinary_packets:
                packet = self._ordinary_packets.pop(0)
            elif len(self._damage_packet_queue)>0:
                packet, _, cb = self._damage_packet_queue.popleft()
            have_more = packet is not None and (bool(self._ordinary_packets) or len(self._damage_packet_queue)>0)
        return packet, cb, have_more

    def queue_ordinary_packet(self, packet):
        assert self._protocol
        self._ordinary_packets.append(packet)
        self._protocol.source_has_more()

    def set_new_encoding(self, encoding, window_ids):
        self.video_encoder_cleanup()
        if window_ids:
            for wid in window_ids:
                batch = self.get_batch_config(wid, False)
                if batch and batch.encoding==encoding:
                    continue
                self.clear_stats(wid)
                batch.encoding = encoding
        else:
            for wid, batch in self.batch_configs.items():
                if batch.encoding==encoding:
                    continue
                self.clear_stats(wid)
                batch.encoding = encoding
        if not window_ids or self._encoding is None:
            self._encoding = encoding

    def cancel_damage(self, wid):
        #if delayed, we can just drop it now
        if wid in self._damage_delayed:
            log("cancel_damage: %s, removed batched region", wid)
            del self._damage_delayed[wid]
        #for those being processed in separate threads, drop by sequence:
        log("cancel_damage: %s, dropping all damage up to and including sequence=%s", wid, self._sequence)
        self._damage_cancelled[wid] = self._sequence
        #clear it eventually - it should be used within mere seconds
        def clear_cancel(sequence):
            if self._damage_cancelled.get(wid, 0)==sequence:
                del self._damage_cancelled[wid]
        gobject.timeout_add(30*1000, clear_cancel, self._sequence)

    def clear_stats(self, wid):
        log("clearing stats for window %s", wid)
        for d in [self._damage_last_events, self.client_decode_time, self.batch_configs, self._damage_stats]:
            if wid in d:
                del d[wid]

    def remove_window(self, wid):
        self.cancel_damage(wid)
        self.clear_stats(wid)
        try:
            self._video_encoder_lock.acquire()
            encoder_cleanup = self._video_encoder_cleanup.get(wid)
            if encoder_cleanup:
                encoder_cleanup()
                del self._video_encoder_cleanup[wid]
        finally:
            self._video_encoder_lock.release()

    def get_batch_config(self, wid, create=True):
        batch = self.batch_configs.get(wid)
        if not batch and create:
            batch = self.default_batch_config.clone()
            self.batch_configs[wid] = batch
        return batch

    def calculate_batch_delay(self, wid, window, batch):
        def update_batch_delay(reason, factor=1):
            current_delay = batch.delay
            target_delay = max(batch.min_delay, min(batch.max_delay, current_delay*factor))
            if len(batch.last_delays)==0:
                return
            #get the weighted average:
            now = time.time()
            tv, tw = 0.0, 0.0
            for when, delay in batch.last_delays:
                #newer matter more:
                w = 1.0/(1.0+(now-when)**2)
                tv += delay*w
                tw += w
            avg = tv / tw
            #favour our new value (absolute boost)
            #and more so if the factor is not close to 1.0
            #(and more so if the factor is >1.0)
            w = 16+tw*((factor-1)+3*abs(factor-1))
            tw += w
            tv += target_delay*w
            decimal_delays = [dec1(x) for _,x in batch.last_delays]
            batch.delay = max(batch.min_delay, min(batch.max_delay, tv / tw))
            batch.last_updated = time.time()
            log("update_batch_delay: wid=%s, factor=%s, delay min=%s, avg=%s, max=%s, cur=%s, w. average=%s, target=%s, wgt=%s, tot wgt=%s (%s%%), new delay=%s -- %s",
                        wid, dec1(factor), min(decimal_delays), dec1(sum(decimal_delays)/len(decimal_delays)), max(decimal_delays),
                        dec1(current_delay), dec1(avg), dec1(target_delay), dec1(w), dec1(tw), dec1(100*w/tw), dec1(batch.delay), reason)

        now = time.time()
        if batch.last_updated>0 and (batch.last_updated+batch.recalculate_delay*16)<now:
            #we haven't been called for a while
            #slash the delay accordingly
            elapsed = now-batch.last_updated
            n_skipped_calcs = elapsed / batch.recalculate_delay
            new_delay = max(batch.min_delay, min(batch.max_delay, batch.delay / logp2(n_skipped_calcs)))
            log("update_batch_delay: wid=%s, skipped %s times (%s ms), slashing delay by %s, was %s, now %s",
                        wid, dec1(n_skipped_calcs), dec1(1000*elapsed), dec1(logp2(n_skipped_calcs)), dec1(batch.delay), dec1(new_delay))
            batch.delay = new_delay
            batch.last_updated = now
            return

        #calculate average and recent latency:
        avg_latency = 0.1   #assume 100ms
        recent_latency = 0.1
        if len(self._client_latency)>0:
            tv, tw = 0.0, 0.0
            rv, rw = 0.0, 0.0
            for when, latency in self._client_latency:
                #newer matter more:
                w = 1.0/(1.0+(now-when)**2)
                tv += latency*w
                tw += w
                if when>(now-1.0):
                    rv += latency*w
                    rw += w
            avg = tv / tw
            if rv>0:
                #found some recent values, average them:
                recent_latency = rv/rw
            else:
                recent_latency = avg
            ms_latency_values = [dec1(1000*x) for _,x in self._client_latency]
            log("update_batch_delay: latency min=%s, avg=%s, max=%s, weighted average=%s, recent_latency=%s",
                    min(ms_latency_values), dec1(sum(ms_latency_values)/len(ms_latency_values)), max(ms_latency_values),
                    dec1(1000*avg), dec1(1000*recent_latency))
            avg_latency = avg

        #always record a new last_delta:
        last_delta = self.last_client_delta
        pixels_backlog, packets_backlog = 0, 0
        ack_pending = self._damage_stats.get(wid)
        #may be empty on startup
        if ack_pending:
            #latency adjusted (remove packets which may not have had enough time to do the roundtrip):
            sent_before = now-avg_latency
            pixels_backlog, packets_backlog = 0, 0
            for sent_at, pixels in ack_pending.values():
                if sent_at>sent_before:
                    continue
                packets_backlog += 1
                pixels_backlog += pixels
        self.last_client_delta = packets_backlog, pixels_backlog
        #from here on, we can return from this method, having made a decision

        ww, wh = self.get_window_dimensions(window)
        low_limit = ww*wh
        if self._mmap and self._mmap_size>0:
            #mmap can accumulate much more as it is much faster
            low_limit *= 4

        #start with the negative tests:
        if recent_latency>(0.005+1.05*avg_latency):
            #never allow the delay to go down when latency is going up
            factor = logp2(recent_latency/avg_latency)
            return update_batch_delay("recent latency is %s%% above average (%s vs %s)" %
                              (dec1(100*((recent_latency/avg_latency)-1)), dec1(1000*recent_latency), dec1(1000*avg_latency)), factor)

        def queue_inspect(qsizes, qsize):
            #inspect a queue size history: figure out if things are better or worse than before
            if qsize==0:
                return  "OK (empty)", 1.0
            factor = logp10(qsize)
            last_10 = list(qsizes)[-10:]
            if max(last_10)==qsize:
                #it's the worst it's been recently, ouch increase faster
                return "%s worst of %s" % (qsize, last_10), factor+0.2
            elif min(last_10)==qsize:
                #it's the best it's been recently, leave it alone
                return "%s best of %s" % (qsize, last_10), 1.0
            elif len(last_10)>4 and last_10[-1]>qsize and last_10[-2]>qsize:
                return "%s improving: %s" % (qsize, last_10), (factor+2)/3.0
            else:
                return "last_10=%s, min=%s, max=%s, current=%s" % (last_10, min(last_10), max(last_10), qsize), factor

        dp_qsize = len(self._damage_packet_queue)
        if dp_qsize>2:
            #there are a few packets waiting for the network layer
            pixels_in_packet_queue = sum([pixels for _,pixels,_ in list(self._damage_packet_queue)])
            msg, factor = queue_inspect(self._damage_packet_queue_pixels, dp_qsize)
            return update_batch_delay("damage packet queue overflow: %s (%s packets and %s pixels)" % (msg, dp_qsize, pixels_in_packet_queue), factor)

        dd_qsize = self._damage_data_queue.qsize()
        if dd_qsize>2:
            #contains pixmaps before they get converted to a packet that goes to the damage_packet_queue
            msg, factor = queue_inspect(self._damage_data_queue_sizes, dd_qsize)
            return update_batch_delay("damage data queue overflow: %s" % msg, factor)

        if not last_delta:
            #happens first time around
            return

        if ack_pending is None or len(ack_pending)==0:
            return update_batch_delay("client is fully up to date: no damage ACKs pending", 0.5)

        if pixels_backlog==0 and packets_backlog==0 and avg_latency<0.2 and len(ack_pending)<5:
            factor = 0.6+len(ack_pending)/10.0
            return update_batch_delay("client is up to date: only %s packets pending, within average latency bounds of %s ms" % (len(ack_pending), dec1(1000*avg_latency)), factor)

        #diff the backlogs since last time:
        last_packets_backlog, last_pixels_backlog = last_delta
        packets_diff = packets_backlog-last_packets_backlog
        pixels_diff = pixels_backlog-last_pixels_backlog

        if packets_diff<0 and pixels_diff<0 and pixels_backlog<(low_limit*4):
            #things are getting better somewhat
            factor = 0.6+0.4*pixels_backlog/(low_limit*4)
            return update_batch_delay("client is catching up: down from %s to %s packets in queue, %s to %s pixels due" % (last_packets_backlog, packets_backlog, last_pixels_backlog, pixels_backlog), factor)

        if pixels_backlog<=low_limit and packets_backlog<5:
            factor = 0.75+0.25*pixels_backlog/low_limit
            return update_batch_delay("client is only %s pixels and only %s packets behind" % (pixels_backlog, packets_backlog), factor)
        factor = min(1.5, logp2(pixels_backlog/low_limit))
        if packets_diff>0:
            factor += 0.25
        return update_batch_delay("client is %s pixels behind!" % pixels_backlog, factor)

    def get_encoding(self, wid):
        batch = self.get_batch_config(wid, False)
        if batch:
            return batch.encoding or self._encoding
        return self._encoding

    def is_cancelled(self, wid, sequence):
        return sequence>0 and self._damage_cancelled.get(wid, 0)>=sequence

    def get_window_pixmap(self, wid, window, sequence):
        # It's important to acknowledge changes *before* we extract them,
        # to avoid a race condition.
        window.acknowledge_changes()
        if self.is_cancelled(wid, sequence):
            log("get_window_pixmap: dropping damage request with sequence=%s", sequence)
            return  None
        pixmap = window.get_property("client-contents")
        if pixmap is None and not self.is_cancelled(wid, sequence):
            log.error("get_window_pixmap: wtf, pixmap is None for window %s, wid=%s", window, wid)
        return pixmap

    def get_window_dimensions(self, window):
        is_or = isinstance(window, OverrideRedirectWindowModel)
        try:
            if is_or:
                (_, _, ww, wh) = window.get_property("geometry")
            else:
                ww, wh = window.get_property("actual-size")
        except KeyError:
            ww, wh = 512, 512
        return ww,wh

    def damage(self, wid, window, x, y, w, h, options=None):
        """ decide what to do with the damage area:
            * send it now (if not congested or batch.enabled is off)
            * add it to an existing delayed region
            * create a new delayed region if we find the client needs it
            Also takes care of adjusting the batch-delay in case
            of congestion.
            The options dict is currently used for carrying the
            "jpegquality" value, it could also be used for other purposes.
            Be aware though that when multiple
            damage requests are delayed and bundled together,
            the options may get quashed! So, specify a "batching"=False
            option to ensure no batching will occur for this request.
        """
        now = time.time()
        batch = self.get_batch_config(wid)
        coding = self.get_encoding(wid)
        if coding in ["x264", "vpx"]:
            w,h = self.get_window_dimensions(window)
            x,y = 0,0
        def damage_now(reason):
            self._sequence += 1
            log("damage(%s, %s, %s, %s, %s) %s, sending now with sequence %s", wid, x, y, w, h, reason, self._sequence)
            pixmap = self.get_window_pixmap(wid, window, self._sequence)
            if pixmap:
                self._process_damage_region(now, pixmap, wid, x, y, w, h, coding, self._sequence, options)
                batch.last_delays.append((now, 0))
                batch.last_updated = time.time()
        #record this damage event in the damage_last_events queue:
        now = time.time()
        last_events = self._damage_last_events.setdefault(wid, maxdeque(100))
        last_events.append((now, w*h))

        if not batch.enabled:
            return damage_now("batching disabled")
        if options and options.get("batching", True) is False:
            return damage_now("batching option is off")

        if batch.last_updated+batch.recalculate_delay<now:
            self.calculate_batch_delay(wid, window, batch)

        delayed = self._damage_delayed.get(wid)
        if delayed:
            region = delayed[3]
            region.union_with_rect(gtk.gdk.Rectangle(x, y, w, h))
            log("damage(%s, %s, %s, %s, %s) using existing delayed region: %s", wid, x, y, w, h, delayed)
            return

        event_min_time = now-batch.time_unit
        all_pixels = [pixels for event_time,pixels in last_events if event_time>event_min_time]
        beyond_limit = len(all_pixels)>batch.max_events or sum(all_pixels)>batch.max_pixels
        if not beyond_limit and not batch.always and batch.delay<=batch.min_delay:
            return damage_now("delay (%s) is at the minimum threshold (%s): %s pixels (%s items) in the last %s ms" %
                              (batch.delay, batch.min_delay, sum(all_pixels), len(all_pixels), dec1(1000*batch.time_unit)))

        #create a new delayed region:
        region = gtk.gdk.Region()
        region.union_with_rect(gtk.gdk.Rectangle(x, y, w, h))
        self._sequence += 1
        self._damage_delayed[wid] = (now, wid, window, region, coding, self._sequence, options)
        def send_delayed():
            """ move the delayed rectangles to the expired list """
            delayed = self._damage_delayed.get(wid)
            if delayed:
                damage_time = delayed[0]
                log("send_delayed for wid %s, batch delay is %s, elapsed time is %s ms", wid, batch.delay, dec1(1000*(time.time()-damage_time)))
                del self._damage_delayed[wid]
                self.send_delayed_regions(*delayed)
                log("moving region %s to expired list", delayed)
            else:
                log("window %s already removed from delayed list?", wid)
            return False
        log("damage(%s, %s, %s, %s, %s) scheduling batching expiry for sequence %s in %s ms", wid, x, y, w, h, self._sequence, dec1(batch.delay))
        batch.last_delays.append((now, batch.delay))
        gobject.timeout_add(int(batch.delay), send_delayed)

    def send_delayed_regions(self, damage_time, wid, window, damage, coding, sequence, options):
        log("send_delayed_regions: processing sequence=%s", sequence)
        if self.is_cancelled(wid, sequence):
            log("send_delayed_regions: dropping request with sequence=%s", sequence)
            return
        regions = []
        ww,wh = self.get_window_dimensions(window)
        def send_full_screen_update():
            log("send_delayed_regions: using full screen update")
            pixmap = self.get_window_pixmap(wid, window, sequence)
            if pixmap:
                self._process_damage_region(damage_time, pixmap, wid, 0, 0, ww, wh, coding, sequence, options)

        try:
            count_threshold = 60
            pixels_threshold = ww*wh*9/10
            packet_cost = 1024
            if self._mmap and self._mmap_size>0:
                #with mmap, we can move lots of data around easily
                #so favour large screen updates over many small packets
                pixels_threshold = ww*wh/2
                packet_cost = 4096
            pixel_count = 0
            while not damage.empty():
                try:
                    if self.is_cancelled(wid, sequence):
                        return
                    (x, y, w, h) = get_rectangle_from_region(damage)
                    pixel_count += w*h
                    #favor full screen updates over many regions:
                    if len(regions)>count_threshold or pixel_count+packet_cost*len(regions)>=pixels_threshold:
                        send_full_screen_update()
                        return
                    regions.append((x, y, w, h))
                    rect = gtk.gdk.Rectangle(x, y, w, h)
                    damage.subtract(gtk.gdk.region_rectangle(rect))
                except ValueError:
                    log.error("send_delayed_regions: damage is empty: %s", damage)
                    break
            log("send_delayed_regions: to regions: %s items, %s pixels", len(regions), pixel_count)
        except Exception, e:
            log.error("send_delayed_regions: error processing region %s: %s", damage, e)
            return
        pixmap = self.get_window_pixmap(wid, window, sequence)
        if pixmap is None:
            return
        log("send_delayed_regions: pixmap size=%s, window size=%s", pixmap.get_size(), (ww, wh))
        for region in regions:
            x, y, w, h = region
            if self.is_cancelled(wid, sequence):
                return
            self._process_damage_region(damage_time, pixmap, wid, x, y, w, h, coding, sequence, options)

    def _process_damage_region(self, damage_time, pixmap, wid, x, y, w, h, coding, sequence, options):
        data = get_rgb_rawdata(damage_time, wid, pixmap, x, y, w, h, coding, sequence, options)
        if data:
            log("process_damage_regions: adding pixel data %s to queue, elapsed time=%s, queue size=%s", data[:6], dec1(1000*(time.time()-damage_time)), self._damage_data_queue.qsize())
            self._damage_data_queue_sizes.append(self._damage_data_queue.qsize())
            self._damage_data_queue.put(data)

    def data_to_packet(self):
        while not self._closed:
            item = self._damage_data_queue.get(True)
            if item is None:
                return              #empty marker
            try:
                #damage_time, wid, x, y, width, height, encoding, raw_data, rowstride, sequence, options = item
                damage_time = item[0]
                log("data_to_packet: elapsed time before encoding=%s, size=%s", int(1000*(time.time()-damage_time)), len(self._damage_packet_queue))
                packet = self.make_data_packet(*item)
                if packet:
                    self.queue_damage_packet(packet, damage_time)
            except Exception, e:
                log.error("error processing damage data: %s", e, exc_info=True)
    
    def queue_damage_packet(self, packet, damage_time):
        log("queue_damage_packet: damage elapsed time=%s ms, size=%s", dec1(1000*(time.time()-damage_time)), len(self._damage_packet_queue))
        width = packet[4]
        height = packet[5]
        def damage_packet_sent():
            #packet = ["draw", wid, x, y, w, h, coding, data, self._damage_packet_sequence, rowstride]
            wid = packet[1]
            packet_sequence = packet[8]
            now = time.time()
            damage_latency = now-damage_time
            self._damage_latency.append(damage_latency)
            ack_pending = self._damage_stats.setdefault(wid, {})
            ack_pending[packet_sequence] = now, width*height
            log("damage_packet_sent: took %s ms for %s pixels of packet_sequence %s", dec1(1000*damage_latency), width*height, packet_sequence)
        self._damage_packet_queue.append((packet, width*height, damage_packet_sent))
        self._damage_packet_queue_sizes.append(len(self._damage_packet_queue))
        self._damage_packet_queue_pixels.append(sum([pixels for _,pixels,_ in list(self._damage_packet_queue)]))
        self._protocol.source_has_more()

    def client_ack_damage(self, packet_sequence, wid, width, height, decode_time):
        log("packet decoding for window %s %sx%s took %s µs", wid, width, height, decode_time)
        self.last_client_packet_sequence = packet_sequence
        client_decode_list = self.client_decode_time.setdefault(wid, maxdeque(maxlen=20))
        client_decode_list.append((time.time(), width*height, decode_time))
        ack_pending = self._damage_stats.get(wid)
        if not ack_pending:
            log("cannot find damage_pending list for window %s - already removed?", wid)
            return
        pending = ack_pending.get(packet_sequence)
        if pending is None:
            log.error("cannot find sent time for sequence %s", packet_sequence)
            return
        del ack_pending[packet_sequence]
        sent_at, pixels = pending
        now = time.time()
        diff = now-sent_at
        log("client_ack_damage: took %s ms round trip, %s for decoding of %s pixels, %s for network", dec1(diff*1000), dec1(decode_time/1000), pixels, dec1((diff*1000*1000-decode_time)/1000))
        self._client_latency.append((now, diff))

    def make_data_packet(self, damage_time, wid, x, y, w, h, coding, data, rowstride, sequence, options):
        if self.is_cancelled(wid, sequence):
            log("make_data_packet: dropping data packet for window %s with sequence=%s", wid, sequence)
            return  None
        log("make_data_packet: damage data: %s", (wid, x, y, w, h, coding))
        start = time.time()
        #send via mmap?
        if self._mmap and self._mmap_size>0 and len(data)>256:
            mmap_data = self._mmap_send(data)
            end = time.time()
            log("%s MBytes/s - %s bytes written to mmap in %s ms", int(len(data)/(end-start)/1024/1024), len(data), dec1(1000*(end-start)))
            if mmap_data is not None:
                self._mmap_bytes_sent += len(data)
                coding = "mmap"
                data = mmap_data
        #encode to jpeg/png:
        if coding in ["jpeg", "png"]:
            assert coding in ENCODINGS
            import Image
            im = Image.fromstring("RGB", (w, h), data, "raw", "RGB", rowstride)
            buf = StringIO()
            if coding=="jpeg":
                q = 50
                if options:
                    q = options.get("jpegquality", 50)
                q = min(99, max(1, q))
                log("sending with jpeg quality %s", q)
                im.save(buf, "JPEG", quality=q)
            else:
                log("sending as %s", coding)
                im.save(buf, coding.upper())
            data = buf.getvalue()
            buf.close()
        elif coding=="x264":
            assert coding in ENCODINGS
            #x264 needs sizes divisible by 2:
            w = w & 0xFFFE
            h = h & 0xFFFE
            from xpra.x264.codec import ENCODERS as x264_encoders, Encoder as x264Encoder   #@UnresolvedImport
            data = self.video_encode(x264_encoders, x264Encoder, wid, x, y, w, h, coding, data, rowstride)
        elif coding=="vpx":
            assert coding in ENCODINGS
            from xpra.vpx.codec import ENCODERS as vpx_encoders, Encoder as vpxEncoder      #@UnresolvedImport
            data = self.video_encode(vpx_encoders, vpxEncoder, wid, x, y, w, h, coding, data, rowstride)
        elif coding=="rgb24":
            data = Compressible(coding, data)
        elif coding=="mmap":
            pass
        else:
            raise Exception("invalid encoding: %s" % coding)

        #check cancellation list again since the code above may take some time:
        #but always send mmap data so we can reclaim the space!
        if coding!="mmap" and sequence>=0 and self.is_cancelled(wid, sequence):
            log("make_data_packet: dropping data packet for window %s with sequence=%s", wid, sequence)
            return  None
        #actual network packet:
        packet = ["draw", wid, x, y, w, h, coding, data, self._damage_packet_sequence, rowstride]
        end = time.time()
        self._damage_packet_sequence += 1
        self._damage_packet_sizes.append((wid, w*h, end-start))
        return packet

    def video_encode(self, encoders, factory, wid, x, y, w, h, coding, data, rowstride):
        assert coding in ENCODINGS
        assert x==0 and y==0, "invalid position: %sx%s" % (x,y)
        #time_before = time.clock()
        try:
            self._video_encoder_lock.acquire()
            encoder = encoders.get(wid)
            if encoder and (encoder.get_width()!=w or encoder.get_height()!=h):
                log("%s: window dimensions have changed from %s to %s", (coding, encoder.get_width(), encoder.get_height()), (w, h))
                encoder.clean()
                encoder.init(w, h)
            if encoder is None:
                #we could have an old encoder if we were using a different encoding
                #if so, clean it up:
                old_encoder_cb = self._video_encoder_cleanup.get(wid)
                if old_encoder_cb:
                    old_encoder_cb()
                    del self._video_encoder_cleanup[wid]
                log("%s: new encoder", coding)
                encoder = factory()
                encoder.init(w, h)
                encoders[wid] = encoder
                def close_encoder():
                    log("close_encoder: %s for wid=%s" % (coding, wid))
                    encoder.clean()
                    del encoders[wid]
                self._video_encoder_cleanup[wid] = close_encoder
            log("%s: compress_image(%s bytes, %s)", coding, len(data), rowstride)
            err, _, data = encoder.compress_image(data, rowstride)
            if err!=0:
                log.error("%s: ouch, compression error %s", coding, err)
                return None
            return data
        finally:
            self._video_encoder_lock.release()

    def _mmap_send(self, data):
        #This is best explained using diagrams:
        #mmap_area=[&S&E-------------data-------------]
        #The first pair of 4 bytes are occupied by:
        #S=data_start index is only updated by the client and tells us where it has read up to
        #E=data_end index is only updated here and marks where we have written up to (matches current seek)
        # '-' denotes unused/available space
        # '+' is for data we have written
        # '*' is for data we have just written in this call
        # E and S show the location pointed to by data_start/data_end
        data_start = ctypes.c_uint.from_buffer(self._mmap, 0)
        data_end = ctypes.c_uint.from_buffer(self._mmap, 4)
        start = max(8, data_start.value)
        end = max(8, data_end.value)
        if end<start:
            #we have wrapped around but the client hasn't yet:
            #[++++++++E--------------------S+++++]
            #so there is one chunk available (from E to S):
            available = start-end
            chunk = available
        else:
            #we have not wrapped around yet, or the client has wrapped around too:
            #[------------S++++++++++++E---------]
            #so there are two chunks available (from E to the end, from the start to S):
            chunk = self._mmap_size-end
            available = chunk+(start-8)
        l = len(data)
        if l>=available:
            log.warn("mmap area full: we need more than %s but only %s left! ouch!", l, available)
            return None
        if l<chunk:
            """ data fits in the first chunk """
            #ie: initially:
            #[----------------------------------]
            #[*********E------------------------]
            #or if data already existed:
            #[+++++++++E------------------------]
            #[+++++++++**********E--------------]
            self._mmap.seek(end)
            self._mmap.write(data)
            data = [(end, l)]
            data_end.value = end+l
        else:
            """ data does not fit in first chunk alone """
            if available>=(self._mmap_size/2) and available>=(l*3) and l<(start-8):
                """ still plenty of free space, don't wrap around: just start again """
                #[------------------S+++++++++E------]
                #[*******E----------S+++++++++-------]
                self._mmap.seek(8)
                self._mmap.write(data)
                data = [(8, l)]
                data_end.value = 8+l
            else:
                """ split in 2 chunks: wrap around the end of the mmap buffer """
                #[------------------S+++++++++E------]
                #[******E-----------S+++++++++*******]
                self._mmap.seek(end)
                self._mmap.write(data[:chunk])
                self._mmap.seek(8)
                self._mmap.write(data[chunk:])
                l2 = l-chunk
                data = [(end, chunk), (8, l2)]
                data_end.value = 8+l2
        log("sending damage with mmap: %s", data)
        return data
