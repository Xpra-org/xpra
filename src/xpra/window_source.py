# coding=utf8
# This file is part of Parti.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
MAX_NONVIDEO_PIXELS = 512
try:
    MAX_NONVIDEO_PIXELS = int(os.environ.get("XPRA_MAX_NONVIDEO_PIXELS", 2048))
except:
    pass

#how many historical records to keep
#for the various statistics we collect:
#(cannot be lower than DamageBatchConfig.MAX_EVENTS)
NRECS = 100


import gtk.gdk
gtk.gdk.threads_init()

import gobject
try:
    from StringIO import StringIO   #@UnusedImport
except:
    from io import StringIO         #@UnresolvedImport @Reimport
import time
import ctypes
from threading import Lock

#it would be nice to be able to get rid of this import here:
from wimpiggy.lowlevel import get_rectangle_from_region   #@UnresolvedImport

from wimpiggy.log import Logger
log = Logger()

from xpra.deque import maxdeque
from xpra.protocol import zlib_compress, Compressed
from xpra.scripts.main import ENCODINGS
from xpra.pixbuf_to_rgb import get_rgb_rawdata
from xpra.maths import dec1, add_list_stats, add_weighted_list_stats, calculate_time_weighted_average
from xpra.batch_delay_calculator import calculate_batch_delay


class DamageBatchConfig(object):
    """
    Encapsulate all the damage batching configuration into one object.
    """
    ENABLED = True
    ALWAYS = False
    MAX_EVENTS = min(50, NRECS)         #maximum number of damage events
    MAX_PIXELS = 1024*1024*MAX_EVENTS   #small screen at MAX_EVENTS frames
    TIME_UNIT = 1                       #per second
    MIN_DELAY = 5
    START_DELAY = 100
    MAX_DELAY = 15000
    RECALCULATE_DELAY = 0.04            #re-compute delay 25 times per second at most
                                        #(this theoretical limit is never achieved since calculations take time + scheduling also does)
    def __init__(self):
        self.enabled = self.ENABLED
        self.always = self.ALWAYS
        self.max_events = self.MAX_EVENTS
        self.max_pixels = self.MAX_PIXELS
        self.time_unit = self.TIME_UNIT
        self.min_delay = self.MIN_DELAY
        self.max_delay = self.MAX_DELAY
        self.delay = self.START_DELAY
        self.recalculate_delay = self.RECALCULATE_DELAY
        self.last_delays = maxdeque(64)
        self.last_updated = 0
        self.wid = 0

    def clone(self):
        c = DamageBatchConfig()
        for x in ["enabled", "always", "max_events", "max_pixels", "time_unit",
                  "min_delay", "max_delay", "delay", "last_delays"]:
            setattr(c, x, getattr(self, x))
        return c


class WindowPerformanceStatistics(object):
    """
    Statistics which belong to a specific WindowSource
    """
    def __init__(self):
        self.reset()

    def reset(self):
        self.client_decode_time = maxdeque(NRECS)       #records how long it took the client to decode frames:
                                                        #(ack_time, no of pixels, decoding_time*1000*1000)
        self.encoding_stats = maxdeque(NRECS)           #encoding: (coding, pixels, compressed_size, encoding_time)
        # statistics:
        self.damage_in_latency = maxdeque(NRECS)        #records how long it took for a damage request to be sent
                                                        #last NRECS: (sent_time, no of pixels, actual batch delay, damage_latency)
        self.damage_out_latency = maxdeque(NRECS)       #records how long it took for a damage request to be processed
                                                        #last NRECS: (processed_time, no of pixels, actual batch delay, damage_latency)
        self.damage_send_speed = maxdeque(NRECS)        #how long it took to send damage packets (this is not a sustained speed)
                                                        #last NRECS: (sent_time, no_of_pixels, elapsed_time)
        self.damage_ack_pending = {}                    #records when damage packets are sent
                                                        #so we can calculate the "client_latency" when the client sends
                                                        #the corresponding ack ("damage-sequence" packet - see "client_ack_damage")
        self.last_client_delta = None                   #records how far behind the client was last time we checked

    def add_stats(self, info, suffix=""):
        #encoding stats:
        if len(self.encoding_stats)>0:
            estats = list(self.encoding_stats)
            encodings_used = [x[0] for x in estats]
            def add_compression_stats(enc_stats, suffix):
                comp_ratios_pct = []
                comp_times_ns = []
                total_pixels = 0
                total_time = 0.0
                for _, pixels, compressed_size, compression_time in enc_stats:
                    if compressed_size>0 and pixels>0:
                        osize = pixels*3
                        comp_ratios_pct.append((100.0*compressed_size/osize, pixels))
                        comp_times_ns.append((1000.0*1000*1000*compression_time/pixels, pixels))
                        total_pixels += pixels
                        total_time += compression_time
                add_weighted_list_stats(info, "compression_ratio_pct"+suffix, comp_ratios_pct)
                add_weighted_list_stats(info, "compression_pixels_per_ns"+suffix, comp_times_ns)
                info["pixels_encoded_per_second"+suffix] = int(total_pixels / total_time)
            add_compression_stats(estats, suffix=suffix)
            for encoding in encodings_used:
                enc_stats = [x for x in estats if x[0]==encoding]
                add_compression_stats(enc_stats, suffix="%s[%s]" % (suffix, encoding))

        latencies = [x*1000 for _, _, _, x in list(self.damage_in_latency)]
        add_list_stats(info, "damage_in_latency",  latencies)
        latencies = [x*1000 for _, _, _, x in list(self.damage_out_latency)]
        add_list_stats(info, "damage_out_latency",  latencies)

    def get_backlog(self, latency):
        packets_backlog, pixels_backlog, bytes_backlog = 0, 0, 0
        if len(self.damage_ack_pending)>0:
            sent_before = time.time()-latency
            for start_send_at, start_bytes, end_send_at, end_bytes, pixels in list(self.damage_ack_pending.values()):
                if end_send_at==0 or start_send_at>sent_before:
                    continue
                packets_backlog += 1
                pixels_backlog += pixels
                bytes_backlog += (end_bytes - start_bytes)
        return packets_backlog, pixels_backlog, bytes_backlog


class WindowSource(object):
    """
    We create a Window Source for each window we send pixels for.

    The UI thread calls 'damage' and we eventually
    call ServerSource.queue_damage to queue the damage compression,

    """

    def __init__(self, queue_damage, queue_packet, statistics,
                    wid, batch_config,
                    encoding, encodings,
                    encoding_client_options, supports_rgb24zlib,
                    mmap, mmap_size):
        self.queue_damage = queue_damage                #callback to add damage data which is ready to compress to the damage processing queue
        self.queue_packet = queue_packet                #callback to add a network packet to the outgoing queue
        self.wid = wid
        self.global_statistics = statistics             #shared/global statistics from ServerSource
        self.statistics = WindowPerformanceStatistics()
        self.encoding = encoding                        #the current encoding
        self.encodings = encodings                      #all the encodings supported by the client
        self.encoding_client_options = encoding_client_options #does the client support encoding options?
        self.supports_rgb24zlib = supports_rgb24zlib    #supports rgb24 compression outside network layer (unwrapped)
        self.batch_config = batch_config
        # mmap:
        self._mmap = mmap
        self._mmap_size = mmap_size
        if self._mmap and self._mmap_size>0:
            self._mmap_data_start = ctypes.c_uint.from_buffer(self._mmap, 0)
            self._mmap_data_end = ctypes.c_uint.from_buffer(self._mmap, 4)

        # video codecs:
        self._video_encoder = None
        self._video_encoder_lock = Lock()               #to ensure we serialize access to the encoder and its internals
        self._video_encoder_quality = maxdeque(NRECS)   #keep track of the target encoding_quality: (event time, encoding speed)
        self._video_encoder_speed = maxdeque(NRECS)     #keep track of the target encoding_speed: (event time, encoding speed)
        # for managing/cancelling damage requests:
        self._damage_delayed = None                     #may store a delayed region when batching in progress
        self._sequence = 1                              #increase with every region we process or delay
        self._damage_cancelled = 0                      #stores the highest _sequence cancelled
        self._damage_packet_sequence = 1                #increase with every damage packet created

    def cleanup(self):
        self.cancel_damage()

    def video_encoder_cleanup(self):
        """ Video encoders (x264 and vpx) require us to run
            cleanup code to free the memory they use.
        """
        try:
            self._video_encoder_lock.acquire()
            if self._video_encoder:
                self._video_encoder.clean()
                self._video_encoder = None
                self._video_encoder_speed = maxdeque(NRECS)
                self._video_encoder_quality = maxdeque(NRECS)
        finally:
            self._video_encoder_lock.release()

    def set_new_encoding(self, encoding):
        """ Changes the encoder for the given 'window_ids',
            or for all windows if 'window_ids' is None.
        """
        if self.encoding==encoding:
            return
        self.video_encoder_cleanup()
        self.encoding = encoding
        self.statistics.reset()

    def cancel_damage(self):
        """
        Use this method to cancel all currently pending and ongoing
        damage requests for a window.
        Damage methods will check this value via 'is_cancelled(sequence)'.
        """
        log("cancel_damage() wid=%s, dropping delayed region %s and all sequences up to %s", self.wid, self._damage_delayed, self._sequence)
        #we must clean the video encoder to ensure
        #we will resend key frames
        self.video_encoder_cleanup()
        #if a region was delayed, we can just drop it now:
        self._damage_delayed = None
        #for those in flight, being processed in separate threads, drop by sequence:
        self._damage_cancelled = self._sequence

    def is_cancelled(self, sequence):
        """ See cancel_damage(wid) """
        return sequence>=0 and self._damage_cancelled>=sequence

    def add_stats(self, info, suffix=""):
        """
            Add window specific stats
        """
        suffix += "[%s]" % self.wid
        info["encoding"+suffix] = self.encoding
        self.statistics.add_stats(info, suffix)
        #batch stats:
        if len(self.batch_config.last_delays)>0:
            batch_delays = [x for _,x in self.batch_config.last_delays]
            add_list_stats(info, "batch_delay"+suffix, batch_delays)
        if self._video_encoder is not None:
            quality_list = [x for _, x in self._video_encoder_quality]
            add_list_stats(info, self._video_encoder.get_type()+"_quality"+suffix, quality_list, show_percentile=False)
            speed_list = [x for _, x in self._video_encoder_speed]
            add_list_stats(info, self._video_encoder.get_type()+"_speed"+suffix, speed_list, show_percentile=False)


    def may_calculate_batch_delay(self, window):
        """
            Call this method whenever a batch delay related statistic has changed,
            this will call 'calculate_batch_delay' if we haven't done so
            for at least 'batch.recalculate_delay'.
        """
        now = time.time()
        if self.batch_config.last_updated+self.batch_config.recalculate_delay<now:
            #simple timeout
            calculate_batch_delay(window, self.wid, self.batch_config, self.global_statistics, self.statistics,
                                  self._video_encoder, self._video_encoder_lock, self._video_encoder_speed, self._video_encoder_quality)
        if self.batch_config.delay>self.batch_config.min_delay:
            #already above batching threshold
            return
        #work out if we have too many damage requests
        #or too many pixels in those requests
        #for the last time_unit:
        event_min_time = now-self.batch_config.time_unit
        all_pixels = [pixels for event_time,pixels in self.global_statistics.damage_last_events if event_time>event_min_time]
        if len(all_pixels)>self.batch_config.max_events or sum(all_pixels)>self.batch_config.max_pixels:
            #force batching: set it just above min_delay
            self.batch_config.delay = max(self.batch_config.min_delay+0.01, self.batch_config.delay)

    def get_window_pixmap(self, window, sequence):
        """ Grabs the window's context (pixels) as a pixmap """
        # It's important to acknowledge changes *before* we extract them,
        # to avoid a race condition.
        window.acknowledge_changes()
        if self.is_cancelled(sequence):
            log("get_window_pixmap: dropping damage request with sequence=%s", sequence)
            return  None
        pixmap = window.get_property("client-contents")
        if pixmap is None and not self.is_cancelled(sequence):
            log.error("get_window_pixmap: wtf, pixmap is None for window %s, wid=%s", window, self.wid)
        return pixmap

    def damage(self, window, x, y, w, h, options=None):
        """ decide what to do with the damage area:
            * send it now (if not congested or batch.enabled is off)
            * add it to an existing delayed region
            * create a new delayed region if we find the client needs it
            Also takes care of updating the batch-delay in case of congestion.
            The options dict is currently used for carrying the
            "jpegquality" value, it could also be used for other purposes.
            Be aware though that when multiple
            damage requests are delayed and bundled together,
            the options may get quashed! So, specify a "batching"=False
            option to ensure no batching will occur for this request.
        """
        now = time.time()
        coding = self.encoding
        def damage_now(reason):
            self._sequence += 1
            logrec = "damage(%s, %s, %s, %s) %s, wid=%s, sending now with sequence %s", x, y, w, h, reason, self.wid, self._sequence
            log(*logrec)
            pixmap = self.get_window_pixmap(window, self._sequence)
            if pixmap:
                ww,wh = window.get_dimensions()
                actual_encoding = self.get_best_encoding(w*h, ww, wh, coding)
                if actual_encoding in ("x264", "vpx"):
                    #always fullscreen
                    self.process_damage_region(now, pixmap, 0, 0, ww, wh, actual_encoding, self._sequence, options)
                else:
                    self.process_damage_region(now, pixmap, x, y, w, h, actual_encoding, self._sequence, options)
                self.batch_config.last_delays.append((now, 0))
                self.batch_config.last_updated = time.time()
        #record this damage event in the damage_last_events queue
        #note: we may actually end up sending more pixels than this value (ie: full screen update)
        now = time.time()

        if not self.batch_config.enabled:
            return damage_now("batching disabled")
        if options and options.get("batching", True) is False:
            return damage_now("batching option is off")

        self.may_calculate_batch_delay(window)

        if self._damage_delayed:
            region = self._damage_delayed[2]
            region.union_with_rect(gtk.gdk.Rectangle(x, y, w, h))
            log("damage(%s, %s, %s, %s) wid=%s, using existing delayed region: %s", x, y, w, h, self.wid, self._damage_delayed)
            return

        if not self.batch_config.always and self.batch_config.delay<=self.batch_config.min_delay:
            return damage_now("delay (%s) is at the minimum threshold (%s)" % (self.batch_config.delay, self.batch_config.min_delay))

        #create a new delayed region:
        region = gtk.gdk.Region()
        region.union_with_rect(gtk.gdk.Rectangle(x, y, w, h))
        self._sequence += 1
        self._damage_delayed = (now, window, region, coding, self._sequence, options)
        def send_delayed():
            """ move the delayed rectangles to the expired list """
            if not self._damage_delayed:
                log("window %s already removed from delayed list?", self.wid)
                return False
            damage_time = self._damage_delayed[0]
            packets_backlog, _, _ = self.statistics.get_backlog(self.global_statistics.avg_client_latency)
            if packets_backlog>0:
                log.info("send_delayed for wid %s, delaying again because of backlog, batch delay is %s, elapsed time is %s ms", self.wid, self.batch_config.delay, dec1(1000*(time.time()-damage_time)))
                return True
            log("send_delayed for wid %s, batch delay is %s, elapsed time is %s ms", self.wid, self.batch_config.delay, dec1(1000*(time.time()-damage_time)))
            delayed = self._damage_delayed
            self._damage_delayed = None
            self.send_delayed_regions(*delayed)
            return False
        log("damage(%s, %s, %s, %s) wid=%s, scheduling batching expiry for sequence %s in %s ms", x, y, w, h, self.wid, self._sequence, dec1(self.batch_config.delay))
        self.batch_config.last_delays.append((now, self.batch_config.delay))
        gobject.timeout_add(int(self.batch_config.delay), send_delayed)

    def send_delayed_regions(self, damage_time, window, damage, coding, sequence, options):
        """ Called by 'send_delayed' when we expire a delayed region,
            There may be many rectangles within this delayed region,
            so figure out if we want to send them all or if we
            just send one full screen update instead.
        """
        log("send_delayed_regions: processing sequence=%s", sequence)
        if self.is_cancelled(sequence):
            log("send_delayed_regions: dropping request with sequence=%s", sequence)
            return
        regions = []
        ww,wh = window.get_dimensions()
        def send_full_screen_update(actual_encoding):
            log("send_delayed_regions: using full screen update")
            pixmap = self.get_window_pixmap(window, sequence)
            if pixmap:
                self.process_damage_region(damage_time, pixmap, 0, 0, ww, wh, actual_encoding, sequence, options)

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
                    if self.is_cancelled(sequence):
                        return
                    (x, y, w, h) = get_rectangle_from_region(damage)
                    pixel_count += w*h
                    #favor full screen updates over many regions:
                    if len(regions)>count_threshold or pixel_count+packet_cost*len(regions)>=pixels_threshold:
                        send_full_screen_update(coding)
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

        actual_encoding = self.get_best_encoding(pixel_count, ww, wh, coding)
        if actual_encoding in ("x264", "vpx"):
            send_full_screen_update(actual_encoding)
            return

        pixmap = self.get_window_pixmap(window, sequence)
        if pixmap is None:
            return
        log("send_delayed_regions: pixmap size=%s, window size=%s", pixmap.get_size(), (ww, wh))
        for region in regions:
            x, y, w, h = region
            if self.is_cancelled(sequence):
                return
            self.process_damage_region(damage_time, pixmap, x, y, w, h, actual_encoding, sequence, options)

    def get_best_encoding(self, pixel_count, ww, wh, current_encoding):
        #decide whether we send a full screen update
        #using the video encoder or if small region(s) will do:
        if current_encoding not in ("x264", "vpx"):
            return current_encoding
        def switch():
            coding = self.find_common_lossless_encoder(current_encoding)
            log("temporarily switching to %s encoder for %s pixels", coding, pixel_count)
            return  coding
        if ww==1 or wh==1:
            #x264 cannot handle 1 pixel wide/high areas
            #(as dimensions are rounded to an even number)
            #vpx can, but swscale has problems
            return  switch()
        if pixel_count<ww*wh*0.01:
            #less than one percent of total area
            return  switch()
        if pixel_count>MAX_NONVIDEO_PIXELS:
            #too many pixels, use current video encoder
            return current_encoding
        if pixel_count>0.5*ww*wh:
            #small, but over 50% of the full window
            return current_encoding
        return switch()

    def find_common_lossless_encoder(self, fallback):
        for e in ("png", "rgb24"):
            if e in ENCODINGS and e in self.encodings:
                return e
        return fallback

    def process_damage_region(self, damage_time, pixmap, x, y, w, h, coding, sequence, options):
        """
            Called by 'damage_now' or 'send_delayed_regions' to process a damage region,
            we extract the rgb data from the pixmap and place it on the damage queue.
        """
        process_damage_time = time.time()
        data = get_rgb_rawdata(damage_time, process_damage_time, self.wid, pixmap, x, y, w, h, coding, sequence, options)
        if data:
            log("process_damage_regions: adding pixel data %s to queue, elapsed time: %s ms", data[:6], dec1(1000*(time.time()-damage_time)))
            def make_data_packet(*args):
                #NOTE: this function is called from the damage data thread!
                packet = self.make_data_packet(*data)
                if packet:
                    self.queue_damage_packet(packet, damage_time, process_damage_time)
            self.queue_damage(make_data_packet)

    def queue_damage_packet(self, packet, damage_time, process_damage_time):
        """
            Adds the given packet to the damage_packet_queue,
            (warning: this runs from the non-UI thread 'data_to_packet')
            we also record a number of statistics:
            - damage packet queue size
            - number of pixels in damage packet queue
            - damage latency (via a callback once the packet is actually sent)
        """
        #packet = ["draw", wid, x, y, w, h, coding, data, self._damage_packet_sequence, rowstride]
        width = packet[4]
        height = packet[5]
        damage_packet_sequence = packet[8]
        actual_batch_delay = process_damage_time-damage_time
        def start_send(bytecount):
            now = time.time()
            self.statistics.damage_ack_pending[damage_packet_sequence] = [now, bytecount, 0, 0, width*height]
        def damage_packet_sent(bytecount):
            now = time.time()
            stats = self.statistics.damage_ack_pending[damage_packet_sequence]
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
        """
        log("packet decoding for window %s %sx%s took %s µs", self.wid, width, height, decode_time)
        if decode_time:
            self.statistics.client_decode_time.append((time.time(), width*height, decode_time))
        pending = self.statistics.damage_ack_pending.get(damage_packet_sequence)
        if pending is None:
            log("cannot find sent time for sequence %s", damage_packet_sequence)
            return
        del self.statistics.damage_ack_pending[damage_packet_sequence]
        if decode_time:
            start_send_at, start_bytes, end_send_at, end_bytes, pixels = pending
            bytecount = end_bytes-start_bytes
            self.global_statistics.record_latency(self.wid, decode_time, start_send_at, end_send_at, pixels, bytecount)

    def make_data_packet(self, damage_time, process_damage_time, wid, x, y, w, h, coding, data, rowstride, sequence, options):
        """
            Picture encoding - non-UI thread.
            Converts a damage item picked from the 'damage_data_queue'
            by the 'data_to_packet' thread and returns a packet
            ready for sending by the network layer.

            * 'mmap' will use 'mmap_send' - always if available, otherwise:
            * 'jpeg' and 'png' are handled by 'PIL_encode'.
            * 'x264' and 'vpx' use 'video_encode'
            * 'rgb24' uses the 'Compressed' wrapper to tell the network layer it is already zlibbed
        """
        if self.is_cancelled(sequence):
            log("make_data_packet: dropping data packet for window %s with sequence=%s", wid, sequence)
            return  None
        assert w>0 and h>0, "invalid dimensions: %sx%s" % (w, h)
        assert data, "data is missing"
        log("make_data_packet: damage data: %s", (wid, x, y, w, h, coding))
        start = time.time()
        if self._mmap and self._mmap_size>0 and len(data)>256:
            #try with mmap (will change coding to "mmap" if it succeeds)
            coding, data = self.mmap_send(coding, data)

        client_options = {}
        if coding in ("jpeg", "png"):
            data, client_options = self.PIL_encode(w, h, coding, data, rowstride, options)
        elif coding=="x264":
            #x264 needs sizes divisible by 2:
            w = w & 0xFFFE
            h = h & 0xFFFE
            if w==0 or h==0:
                return None
            data, client_options = self.video_encode(wid, x, y, w, h, coding, data, rowstride, options)
        elif coding=="vpx":
            data, client_options = self.video_encode(wid, x, y, w, h, coding, data, rowstride, options)
        elif coding=="rgb24":
            data, client_options = self.rgb24_encode(data)
        elif coding=="mmap":
            pass        #already handled via mmap_send
        else:
            raise Exception("invalid encoding: %s" % coding)
        #check cancellation list again since the code above may take some time:
        #but always send mmap data so we can reclaim the space!
        if coding!="mmap" and self.is_cancelled(sequence):
            log("make_data_packet: dropping data packet for window %s with sequence=%s", wid, sequence)
            return  None
        #actual network packet:
        packet = ["draw", wid, x, y, w, h, coding, data, self._damage_packet_sequence, rowstride, client_options]
        end = time.time()
        self._damage_packet_sequence += 1
        self.statistics.encoding_stats.append((coding, w*h, len(data), end-start))
        return packet

    def rgb24_encode(self, data):
        #compress here and return a wrapper so network code knows it is already zlib compressed:
        zlib = zlib_compress("rgb24", data)
        if not self.encoding_client_options or not self.supports_rgb24zlib:
            return  zlib, {}
        #wrap it using "Compressed" so the network layer receiving it
        #won't decompress it (leave it to the client's draw thread)
        return Compressed("rgb24", zlib.data), {"zlib" : zlib.level}

    def PIL_encode(self, w, h, coding, data, rowstride, options):
        assert coding in ENCODINGS
        import Image
        im = Image.fromstring("RGB", (w, h), data, "raw", "RGB", rowstride)
        buf = StringIO()
        client_options = {}
        if coding=="jpeg":
            q = 50
            if options:
                q = options.get("jpegquality", 50)
            q = min(99, max(1, q))
            log("sending with jpeg quality %s", q)
            im.save(buf, "JPEG", quality=q)
            client_options["quality"] = q
        else:
            log("sending as %s", coding)
            im.save(buf, coding.upper())
        data = buf.getvalue()
        buf.close()
        return Compressed(coding, data), client_options

    def make_video_encoder(self, coding):
        assert coding in ENCODINGS
        if coding=="x264":
            from xpra.x264.codec import Encoder as x264Encoder   #@UnresolvedImport
            return x264Encoder()
        elif coding=="vpx":
            from xpra.vpx.codec import Encoder as vpxEncoder      #@UnresolvedImport
            return vpxEncoder()
        else:
            raise Exception("invalid video encoder: %s" % coding)

    def video_encode(self, wid, x, y, w, h, coding, data, rowstride, options):
        """
            This method is used by make_data_packet to encode frames using x264 or vpx.
            Video encoders only deal with fixed dimensions,
            so we must clean and reinitialize the encoder if the window dimensions
            has changed.
            Since this runs in the non-UI thread 'data_to_packet', we must
            use the 'video_encoder_lock' to prevent races.

        """
        assert x==0 and y==0, "invalid position: %sx%s" % (x,y)
        #time_before = time.clock()
        try:
            self._video_encoder_lock.acquire()
            if self._video_encoder:
                if self._video_encoder.get_type()!=coding:
                    log("video_encode: switching from %s to %s", self._video_encoder.get_type(), coding)
                    self.video_encoder_cleanup()
                elif self._video_encoder.get_width()!=w or self._video_encoder.get_height()!=h:
                    log("%s: window dimensions have changed from %sx%s to %sx%s", coding, self._video_encoder.get_width(), self._video_encoder.get_height(), w, h)
                    old_pc = self._video_encoder.get_width() * self._video_encoder.get_height()
                    self._video_encoder.clean()
                    self._video_encoder.init_context(w, h, self.encoding_client_options)
                    #if we had an encoding speed set, restore it (also scaled):
                    if len(self._video_encoder_speed):
                        _, recent_speed = calculate_time_weighted_average(list(self._video_encoder_speed))
                        new_pc = w * h
                        new_speed = max(0, min(100, recent_speed*new_pc/old_pc))
                        self._video_encoder.set_encoding_speed(new_speed)
            if self._video_encoder is None:
                log("%s: new encoder for wid=%s %sx%s", coding, wid, w, h)
                self._video_encoder = self.make_video_encoder(coding)
                self._video_encoder.init_context(w, h, self.encoding_client_options)
            err, _, data = self._video_encoder.compress_image(data, rowstride, options)
            if err!=0:
                log.error("%s: ouch, compression error %s", coding, err)
                return None, None
            client_options = self._video_encoder.get_client_options(options)
            msg = "compress_image(..) %s wid=%s, result is %s bytes, client options=%s", coding, wid, len(data), client_options
            log(*msg)
            return Compressed(coding, data), client_options
        finally:
            self._video_encoder_lock.release()

    def mmap_send(self, coding, data):
        start = time.time()
        mmap_data = self._mmap_send(data)
        end = time.time()
        log("%s MBytes/s - %s bytes written to mmap in %s ms", int(len(data)/(end-start)/1024/1024), len(data), dec1(1000*(end-start)))
        if mmap_data is not None:
            self.global_statistics.mmap_bytes_sent += len(data)
            coding = "mmap"
            data = mmap_data
        return coding, data

    def _mmap_send(self, data):
        """
            Sends 'data' to the client via the mmap shared memory region,
            called by 'make_data_packet' from the non-UI thread 'data_to_packet'.
        """
        #This is best explained using diagrams:
        #mmap_area=[&S&E-------------data-------------]
        #The first pair of 4 bytes are occupied by:
        #S=data_start index is only updated by the client and tells us where it has read up to
        #E=data_end index is only updated here and marks where we have written up to (matches current seek)
        # '-' denotes unused/available space
        # '+' is for data we have written
        # '*' is for data we have just written in this call
        # E and S show the location pointed to by data_start/data_end
        start = max(8, self._mmap_data_start.value)
        end = max(8, self._mmap_data_end.value)
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
        #update global mmap stats:
        self.global_statistics.mmap_free_size = available-l
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
            self._mmap_data_end.value = end+l
        else:
            """ data does not fit in first chunk alone """
            if available>=(self._mmap_size/2) and available>=(l*3) and l<(start-8):
                """ still plenty of free space, don't wrap around: just start again """
                #[------------------S+++++++++E------]
                #[*******E----------S+++++++++-------]
                self._mmap.seek(8)
                self._mmap.write(data)
                data = [(8, l)]
                self._mmap_data_end.value = 8+l
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
                self._mmap_data_end.value = 8+l2
        log("sending damage with mmap: %s", data)
        return data
