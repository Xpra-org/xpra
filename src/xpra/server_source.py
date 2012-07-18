# coding=utf8
# This file is part of Parti.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#Set this variable to True and batch delay debug messages
#will be printed every 30 seconds or every MAX_DEBUG_MESSAGES messages
#(whichever comes first)
import os
DEBUG_DELAY = len(os.environ.get("XPRA_DEBUG_LATENCY", ""))>0
MAX_DEBUG_MESSAGES = 1000


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
from math import log as mathlog, sqrt, pow
def logp(x):
    return mathlog(1+x, 2)

#it would be nice to be able to get rid of those 2 imports here:
from wimpiggy.window import OverrideRedirectWindowModel
from wimpiggy.lowlevel import get_rectangle_from_region   #@UnresolvedImport

from wimpiggy.log import Logger
log = Logger()

from xpra.deque import maxdeque
from xpra.protocol import Compressible
from xpra.scripts.main import ENCODINGS


def start_daemon_thread(target, name):
    t = Thread(target=target)
    t.name = name
    t.daemon = True
    t.start()
    return t

def dec1(x):
    #for pretty debug output of numbers with one decimal
    return int(10.0*x)/10.0
def dec2(x):
    #for pretty debug output of numbers with one decimal
    return int(100.0*x)/100.0

def find_invpow(x, n):
    """Finds the integer component of the n'th root of x,
    an integer such that y ** n <= x < (y + 1) ** n.
    """
    high = 1
    while high ** n < x:
        high *= 2
    low = high/2
    while low < high:
        mid = (low + high) // 2
        if low < mid and mid**n < x:
            low = mid
        elif high > mid and mid**n > x:
            high = mid
        else:
            return mid
    return mid + 1

def get_rgb_rawdata(damage_time, process_damage_time, wid, pixmap, x, y, width, height, encoding, sequence, options):
    """
        Extracts pixels from the given pixmap
    """
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
    log("get_rgb_rawdata(..) pixbuf.get_from_drawable took %s ms", dec1(1000*(time.time()-start)))
    raw_data = pixbuf.get_pixels()
    rowstride = pixbuf.get_rowstride()
    return (damage_time, process_damage_time, wid, x, y, width, height, encoding, raw_data, rowstride, sequence, options)

def add_list_stats(info, basename, in_values):
    #this may be backed by a deque/list whichi is used by other threads
    #so make a copy before use:
    values = list(in_values)
    if len(values)==0:
        return
    info["%s.min" % basename] = int(min(values))
    info["%s.max" % basename] = int(max(values))
    #arithmetic mean
    avg = sum(values)/len(values)
    info["%s.avg" % basename] = int(avg)
    p = 1           #geometric mean
    h = 0           #harmonic mean
    var = 0         #variance
    counter = 0
    for x in values:
        if x!=0:
            p *= x
            h += 1.0/x
            counter += 1
        var += (x-avg)**2
    #standard deviation:
    std = sqrt(var/len(values))
    info["%s.std" % basename] = int(std)
    if avg!=0:
        #coefficient of variation
        info["%s.cv_pct" % basename] = int(100.0*std/avg)
    if counter>0:
        #geometric mean
        try:
            v = int(pow(p, 1.0/counter))
        except OverflowError:
            v = find_invpow(p, counter)
        info["%s.gm" % basename] = v
    if h!=0:
        #harmonic mean
        info["%s.h" % basename] = int(counter/h)
    #percentile
    svalues = sorted(values)
    for i in range(1,10):
        pct = i*10
        index = len(values)*i//10
        info["%s.%sp" % (basename, pct)] = int(svalues[index])


#how many historical records to keep
#for the various statistics we collect:
#(cannot be lower than DamageBatchConfig.MAX_EVENTS)
NRECS = 100


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
    MAX_DELAY = 15000
    RECALCULATE_DELAY = 0.04            #re-compute delay 25 times per second at most
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
        self.wid = 0

    def clone(self):
        c = DamageBatchConfig()
        for x in ["enabled", "always", "min_delay", "max_delay", "delay", "last_delays"]:
            setattr(c, x, getattr(self, x))
        return c


class ServerSource(object):
    """
    Strategy: if we have ordinary packets to send, send those.
    When we don't, then send window updates (expired ones first).
    See 'next_packet'.
    The UI thread adds damage requests to a queue - see damage()
    """

    def __init__(self, protocol, batch_config, encoding, mmap, mmap_size):
        self._closed = False
        self._ordinary_packets = []
        self._protocol = protocol
        self._encoding = encoding                   #the default encoding for all windows
        self._default_batch_config = batch_config
        self._batch_configs = {}                    #batch config per window
        # mmap:
        self._mmap = mmap
        self._mmap_size = mmap_size
        self._mmap_bytes_sent = 0
        self._mmap_free_size = 0                    #how much of the mmap space is left (may be negative if we failed to write the last chunk)
        # used for safely cleaninup video encoders (x264/vpx):
        self._video_encoder_cleanup = {}
        self._video_encoder_lock = Lock()
        # for managing/cancelling damage requests:
        self._damage_delayed = {}                   #may store delayed region (batching in progress) for each window
        self._sequence = 1                          #increase with every region we process or delay
        self._damage_cancelled = {}                 #stores the highest _sequence cancelled for a window
        # the queues of damage requests we work through:
        self._damage_data_queue = Queue()           #holds raw pixel data (pixbuf), dimensions, etc
                                                    #items placed in this queue are picked off by the "data_to_packet" thread
                                                    #which will then place one or more packets in the damage_packet_queue
        self._damage_packet_queue = deque()         #holds actual packets ready for sending (already encoded)
                                                    #these packets are picked off by the "protocol"
        # statistics:
        self._damage_last_events = {}               #records the x11 damage requests for each window as they are received
                                                    #last NRECS per window: (event time, no of pixels)
        self._damage_packet_sequence = 1            #increase with every damage packet created
        self._damage_ack_pending = {}               #records when damage packets are sent (per window dict),
                                                    #so we can calculate the "client_latency" when the client sends
                                                    #the corresponding ack ("damage-sequence" packet - see "client_ack_damage")
        self._min_client_latency = None             #the lowest client latency ever recorded
        self._client_latency = maxdeque(NRECS)      #how long it took for a packet to get to the client and get the echo back.
                                                    #last NRECS: (echo_time, no of pixels, client_latency)
        self._damage_in_latency = maxdeque(NRECS)   #records how long it took for a damage request to be sent
                                                    #last NRECS: (sent_time, no of pixels, actual batch delay, damage_latency)
        self._damage_out_latency = maxdeque(NRECS)  #records how long it took for a damage request to be processed
                                                    #last NRECS: (processed_time, no of pixels, actual batch delay, damage_latency)
        self._damage_send_speed = maxdeque(NRECS)   #how long it took to send damage packets (this is not a sustained speed)
                                                    #last NRECS: (sent_time, no_of_pixels, elapsed_time)
        self._last_packet_send_stats = None         #used by _damage_send_speed
        self._client_decode_time = {}               #records how long it took the client to decode frames:
                                                    #last NRECS per window: (ack_time, no of pixels, decoding_time)
        self._encoding_stats = maxdeque(NRECS)      #encoding statistics
                                                    #last NRECS: (wid, coding, pixels, compressed_size, encoding_time)

        self._last_client_delta = 0, 0              #records how far behind the client was last time we checked
                                                    # (no of packets, no of pixels)
        # queue statistics:
        self._damage_data_qsizes = maxdeque(NRECS)  #size of the damage_data_queue before we add a new record to it
                                                    #(event_time, size)
        self._damage_packet_qsizes = maxdeque(NRECS)#size of the damage_packet_queue before we add a new packet to it
                                                    #(event_time, size)
        self._damage_packet_qpixels = maxdeque(NRECS) #number of pixels waiting in the damage_packet_queue before we add a new packet to it
                                                    #(event_time, size)

        if DEBUG_DELAY:
            self._debug_delay_messages = []
            gobject.timeout_add(30*1000, self.dump_debug_delay_messages)

        # ready for processing:
        protocol.source = self
        self._datapacket_thread = start_daemon_thread(self.data_to_packet, "data_to_packet")

    def dump_debug_delay_messages(self):
        log.info("dump_debug_delay_messages():")
        for x in list(self._debug_delay_messages):
            log.info(*x)
        self._debug_delay_messages = []
        return  True

    def add_DEBUG_DELAY_MESSAGE(self, message):
        if len(self._debug_delay_messages)>=MAX_DEBUG_MESSAGES:
            self.dump_debug_delay_messages()
        self._debug_delay_messages.append(message)

    def close(self):
        self._closed = True
        self._damage_data_queue.put(None, block=False)
        self.video_encoder_cleanup()

    def video_encoder_cleanup(self, window_ids=None):
        """ Video encoders (x264 and vpx) require us to run
            cleanup code to free the memory they use.
            This method performs the cleanup for all the video encoders registered
            if 'windows_ids' is None, or just the given window ids given.
        """
        try:
            self._video_encoder_lock.acquire()
            for wid,cb in self._video_encoder_cleanup.items():
                if window_ids==None or wid in window_ids:
                    try:
                        log("calling %s for wid=%s", cb, wid)
                        cb()
                    except:
                        log.error("error on close callback %s", cb, exc_info=True)
            self._video_encoder_cleanup = {}
        finally:
            self._video_encoder_lock.release()

    def next_packet(self):
        """ Called by protocol.py when it is ready to send the next packet """
        packet, start_send_cb, end_send_cb, have_more = None, None, None, False
        if not self._closed:
            if self._ordinary_packets:
                packet = self._ordinary_packets.pop(0)
            elif len(self._damage_packet_queue)>0:
                packet, _, start_send_cb, end_send_cb = self._damage_packet_queue.popleft()
            have_more = packet is not None and (bool(self._ordinary_packets) or len(self._damage_packet_queue)>0)
        return packet, start_send_cb, end_send_cb, have_more

    def queue_ordinary_packet(self, packet):
        """ This method queues non-damage packets (higher priority) """
        assert self._protocol
        self._ordinary_packets.append(packet)
        self._protocol.source_has_more()

    def set_new_encoding(self, encoding, window_ids):
        """ Changes the encoder for the given 'window_ids',
            or for all windows if 'window_ids' is None.
        """
        self.video_encoder_cleanup(window_ids)
        if window_ids is not None:
            for wid in window_ids:
                self.cancel_damage(wid)
                batch = self.get_batch_config(wid, False)
                if batch and batch.encoding==encoding:
                    continue
                self.clear_stats(wid)
                batch.encoding = encoding
        else:
            for wid, batch in self._batch_configs.items():
                self.cancel_damage(wid)
                if batch.encoding==encoding:
                    continue
                self.clear_stats(wid)
                batch.encoding = encoding
        if not window_ids or self._encoding is None:
            self._encoding = encoding

    def cancel_damage(self, wid):
        """
        Use this method to cancel all currently pending and ongoing
        damage requests for a window.
        Damage methods check this cancel list via 'is_cancelled(wid)'.
        As one of the reasons for cancelling may be that the window is gone,
        we also clear the timeout entry after 30 seconds to avoid a small
        memory leak.
        """
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

    def is_cancelled(self, wid, sequence):
        """ See cancel_damage(wid) """
        return sequence>0 and self._damage_cancelled.get(wid, 0)>=sequence

    def remove_window(self, wid):
        """ The given window is gone, ensure we free all the related resources """
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

    def clear_stats(self, wid):
        """ Free all statistics for the given window """
        log("clearing stats for window %s", wid)
        #self._damage_delayed is cleared in cancel_damage
        #self._damage_cancelled is cleared automatically with a timer (also in cancel_damage)
        for d in [self._damage_last_events, self._client_decode_time, self._batch_configs, self._damage_ack_pending]:
            if wid in d:
                del d[wid]

    def get_batch_config(self, wid, create=True):
        """ Retrieves the DamageBatchConfig for the given window.
            May clone the default is one does not exist yet and create flag is True.
        """
        batch = self._batch_configs.get(wid)
        if not batch and create:
            batch = self._default_batch_config.clone()
            batch.wid = wid
            self._batch_configs[wid] = batch
        return batch

    def add_stats(self, info, window_ids=[]):
        """
            Adds most of the statistics available to the 'info' dict passed in.
            This is used by server.py to provide those statistics to clients
            via the 'xpra info' command.
        """
        info["encoding"] = self._encoding
        if self._protocol:
            info["input_bytecount"] = self._protocol.input_bytecount
            info["input_packetcount"] = self._protocol.input_packetcount
            info["input_raw_packetcount"] = self._protocol.input_raw_packetcount
            info["output_bytecount"] = self._protocol.output_bytecount
            info["output_packetcount"] = self._protocol.output_packetcount
            info["output_raw_packetcount"] = self._protocol.output_raw_packetcount
        info["output_mmap_bytecount"] = self._mmap_bytes_sent
        latencies = [x*1000 for _, _, _, x in list(self._damage_in_latency)]
        add_list_stats(info, "damage_in_latency",  latencies)
        latencies = [x*1000 for _, _, _, x in list(self._damage_out_latency)]
        add_list_stats(info, "damage_out_latency",  latencies)
        latencies = [x*1000 for (_, _, x) in list(self._client_latency)]
        add_list_stats(info, "client_latency",  latencies)
        if self._min_client_latency:
            info["client_latency.absmin"] = int(self._min_client_latency*1000)
        info["damage_data_queue_size.current"] = self._damage_data_queue.qsize()
        qsizes = [x for _,x in list(self._damage_data_qsizes)]
        add_list_stats(info, "damage_data_queue_size",  qsizes)
        info["damage_packet_queue_size.current"] = len(self._damage_packet_queue)
        qsizes = [x for _,x in list(self._damage_packet_qsizes)]
        add_list_stats(info, "damage_packet_queue_size",  qsizes)
        qpixels = [x[1] for x in list(self._damage_packet_queue)]
        if len(qpixels)>0:
            info["damage_packet_queue_pixels.current"] = qpixels[-1]
        add_list_stats(info, "damage_packet_queue_pixels",  qsizes)

        batch_delays = []
        for wid in window_ids:
            batch = self.get_batch_config(wid)
            if batch:
                for _,d in list(batch.last_delays):
                    batch_delays.append(d)
        add_list_stats(info, "batch_delay", batch_delays)

        estats = list(self._encoding_stats)
        if len(estats)>0:
            comp_ratios_pct = []
            comp_times_ns = []
            for wid, _, pixels, compressed_size, compression_time in estats:
                if compressed_size>0 and pixels>0:
                    comp_ratios_pct.append(int(100*compressed_size/(pixels*3)))
                    comp_times_ns.append(int(1000*1000*1000*compression_time/pixels))
            add_list_stats(info, "compression_ratio_pct", comp_ratios_pct)
            add_list_stats(info, "compression_pixels_per_ns", comp_times_ns)

        #client pixels per second:
        now = time.time()
        time_limit = now-30             #ignore old records (30s)
        #pixels per second: decode time and overall
        total_pixels = 0                #total number of pixels processed
        total_time = 0                  #total decoding time
        latest_start_time = 0           #the highest time any of the queues starts from
        for wid in window_ids:
            decode_time_list = self._client_decode_time.get(wid)
            if not decode_time_list:
                continue
            window_pixels = 0           #pixel count
            window_time = 0             #decoding time
            window_start_time = 0
            for when, pixels, decode_time in decode_time_list:
                if when<time_limit or decode_time<=0:
                    continue
                if window_start_time==0:
                    window_start_time = when
                    latest_start_time = max(latest_start_time, when)
                log("wid=%s, pixels=%s in %s", wid, pixels, decode_time)
                window_pixels += pixels
                window_time += decode_time
            log("wid=%s, window_time=%s, window_pixels=%s", wid, window_time, window_pixels)
            if window_time>0:
                #zero time means we dropped the data without processing it,
                #so don't count it (or try to divide by zero!)
                log("wid=%s, pixels/s=%s", wid, int(window_pixels *1000*1000 / window_time))
                total_time += window_time
                total_pixels += window_pixels
        log("total_time=%s, total_pixels=%s", total_time, total_pixels)
        if total_time>0:
            pixels_decoded_per_second = int(total_pixels *1000*1000 / total_time)
            info["pixels_decoded_per_second"] = pixels_decoded_per_second
            log("pixels_decoded_per_second=%s", pixels_decoded_per_second)

        if latest_start_time:
            elapsed = now-latest_start_time
            #count all pixels newer than this time
            total_pixels = 0
            for wid in window_ids:
                decode_time_list = self._client_decode_time.get(wid)
                if not decode_time_list:
                    continue
                for when, pixels, decode_time in decode_time_list:
                    if decode_time<=0:
                        continue
                    if when>=latest_start_time:
                        total_pixels += pixels
            pixels_per_second = int(total_pixels/elapsed)
            info["pixels_per_second"] = pixels_per_second
            log("pixels_per_second=%s", pixels_per_second)
        if len(self._encoding_stats)>0:
            total_pixels = 0
            total_time = 0
            for _, _, pixels, _, elapsed in list(self._encoding_stats):
                total_pixels += pixels
                total_time += elapsed
            pixels_encoded_per_second = int(total_pixels / total_time)
            info["pixels_encoded_per_second"] = pixels_encoded_per_second
            log("pixels_encoded_per_second=%s", pixels_encoded_per_second)

        #damage regions per second:
        total_pixels = 0            #pixels processed
        regions_count = 0           #weighted value: sum of (regions count * number of pixels / elapsed time)
        for wid in window_ids:
            last_events = self._damage_last_events.get(wid)
            if not last_events:
                continue
            start_when = 0
            window_regions = 0      #regions for this window
            window_pixels = 0       #pixel count
            for when, pixels in last_events:
                if when<time_limit:
                    continue
                window_regions += 1
                if start_when==0:
                    start_when = when
                log("wid=%s, pixels=%s", wid, pixels)
                window_pixels += pixels
                total_pixels += pixels
            log("wid=%s, window_pixels=%s", wid, window_pixels)
            if start_when>0:
                log("wid=%s, window_pixels=%s, regions=%s, elapsed=%s", wid, window_pixels, window_regions, now-start_when)
                log("wid=%s, regions_per_second=%s", wid, (window_regions/(now-start_when)))
                regions_count += window_pixels*window_regions/(now-start_when)
        log("regions_count=%s, total_pixels=%s", regions_count, total_pixels)
        if regions_count:
            regions_per_second = int(regions_count/total_pixels)
            info["regions_per_second"] = regions_per_second
            log("regions_per_second=%s", regions_per_second)


    def may_calculate_batch_delay(self, wid, window, batch):
        """
            Call this method whenever a batch delay related statistic has changed,
            this will call 'calculate_batch_delay' if we haven't done so
            for at least 'batch.recalculate_delay'.
        """
        now = time.time()
        if batch.last_updated+batch.recalculate_delay<now:
            #simple timeout
            self.calculate_batch_delay(wid, window, batch)
        last_events = self._damage_last_events.get(wid)
        if last_events:
            #work out if we have too many damage requests
            #or too many pixels in those requests
            #for the last time_unit:
            event_min_time = now-batch.time_unit
            all_pixels = [pixels for event_time,pixels in last_events if event_time>event_min_time]
            if len(all_pixels)>batch.max_events or sum(all_pixels)>batch.max_pixels:
                #force batching: set it above min_delay
                batch.delay = max(batch.min_delay+0.01, batch.delay)

    def calculate_time_weighted_average(self, data):
        """
            Given a list of items of the form [(event_time, value)],
            this method calculates a time-weighted average where
            recent values matter a lot more than more ancient ones.
            The 'recent' average is even more slanted towards recent values.
        """
        now = time.time()
        tv, tw, rv, rw = 0.0, 0.0, 0.0, 0.0
        for event_time, value in data:
            #newer matter more:
            w = 1.0/(1.0+(now-event_time))
            tv += value*w
            tw += w
            w = 1.0/(0.1+(now-event_time)**2)
            rv += value*w
            rw += w
        return tv / tw, rv / rw

    def calculate_timesize_weighted_average(self, data, sizeunit=1.0):
        """
            This is a time weighted average where the size
            of each record also gives it a weight boost.
            This is to prevent small packets from skewing the average.
            Data format: (event_time, size, elapsed_time)
        """
        size_avg = sum([x for _, x, _ in data])/len(data)
        now = time.time()
        tv, tw, rv, rw = 0.0, 0.0, 0.0, 0.0
        for event_time, size, elapsed_time in data:
            if elapsed_time<=0:
                continue        #invalid record
            pw = logp(size/size_avg)
            size_ps = max(1, size*sizeunit/elapsed_time)
            w = pw/(1.0+(now-event_time))
            tv += w*size_ps
            tw += w
            w = pw/(0.1+(now-event_time)**2)
            rv += w*size_ps
            rw += w
        return tv / tw, rv / rw

    def calculate_for_target(self, msg, target_value, avg_value, recent_value, div=1.0, slope=0.5):
        """
            Calculates factor and weight to try to bring us closer to 'target_value'.

            The factor is a function of how far the 'recent_value' if from it. (logp)
            It will be greater than 1.0 if recent_value is higher than the target_value,
            and less than 1.0 if it is lower.

            The weight is a function of how far the 'recent_value' is from the 'avg_value'.

            The 'slope' controls how the weight is calculated: the lower the slope (cannot be zero),
            the more the weight will be high in cases of differences between recent and average,
            the higher the slope, the more the weight will remain close to 1.
        """
        factor = logp((slope+recent_value)/(slope+target_value)/div)
        weight = logp((slope+abs(recent_value-target_value)) / (slope+abs(avg_value-target_value)))
        return  msg, factor, weight

    def calculate_for_average(self, msg, avg_value, recent_value, div=1.0):
        """
            Calculates factor and weight based on how far we are from the average value.
            This is used by metrics for which we do not know the optimal target value. 
        """
        avg = avg_value/div
        recent = recent_value/div
        factor = logp(recent/avg)
        if factor==0:
            weight = 0
        elif factor<1:
            weight = logp(avg/recent)
        else:
            weight = factor
        return  msg, factor, weight

    def queue_inspect(self, time_values, target=0.5, div=1.0):
        """
            Utility method used by:
            - get_damage_packet_queue_size_factor
            - get_damage_packet_queue_pixels_factor
            - get_damage_data_queue_factor
            Given an historical list of values and a current value,
            figure out if things are getting better or worse.
        """
        #inspect a queue size history: figure out if things are better or worse than before
        if len(time_values)==0:
            return  "(empty)", 1.0, 0.0
        avg, recent = self.calculate_time_weighted_average(list(time_values))
        msg = "avg=%s, recent=%s, target=%s, div=%s" % (avg, recent, target, div)
        return  self.calculate_for_target(msg, target, avg, recent, div=div)


    def calculate_average_damage_in_latency(self):
        """
            Returns the time-weighted average and recent average
            for the "damage in latency".
            (the time it takes for damage requests to be processed only)
        """
        if len(self._damage_in_latency)==0:
            return  0, 0
        data = [(when, latency) for when, _, _, latency in list(self._damage_in_latency)]
        return  self.calculate_time_weighted_average(data)

    def calculate_average_damage_out_latency(self):
        """
            Returns the time-weighted average and recent average
            for the "damage out latency".
            (the time it takes for damage requests to be processed and sent out)
        """
        if len(self._damage_out_latency)==0:
            return  0, 0
        data = [(when, latency) for when, _, _, latency in list(self._damage_out_latency)]
        return  self.calculate_time_weighted_average(data)

    def calculate_average_client_latency(self):
        """
            Returns the time-weighted average and recent average
            for the "client latency".
            (how long it takes for a packet to get to the client and get the echo back)
            See calculate_time_weighted_average()
        """
        if len(self._client_latency)==0:
            #assume 100ms until we get some data...
            return  0.1, 0.1
        data = [(when, latency) for when, _, latency in list(self._client_latency)]
        return  self.calculate_time_weighted_average(data)

    def calculate_client_backlog(self, ack_pending, sent_before):
        """
            Given the list of ACKs pending and a time cut off point
            (which is based on the client latency),
            we calculate how far behind the client is:
            how many packets and how many pixels it should have processed
            by now but has not.
        """
        if not ack_pending:
            return  0, 0
        packets_backlog, pixels_backlog = 0, 0
        for sent_at, pixels in ack_pending.values():
            if sent_at>sent_before:
                continue
            packets_backlog += 1
            pixels_backlog += pixels
        return packets_backlog, pixels_backlog

    def calculate_low_limit(self, window):
        """
            Ugly method to calculate the 'low_limit':
            the number of pixels which can be considered 'low'
            in terms of backlog.
            Generally, just one full frame, more with mmap
            because it is so fast that things can accumulate more quickly.
        """
        low_limit = 1024*1024
        if window:
            ww, wh = self.get_window_dimensions(window)
            low_limit = ww*wh
            if self._mmap and self._mmap_size>0:
                #mmap can accumulate much more as it is much faster
                low_limit *= 4
        return low_limit

    def calculate_client_decode_speed(self, wid):
        """
            This is a time and pixel size weighted average.
            The values are in pixels per second.
        """
        decode_time_list = self._client_decode_time.get(wid)
        if not decode_time_list:
            return  None, None
        #the elapsed time recorded is in microseconds, so multiply by 1000*1000 to get the real value:
        return  self.calculate_timesize_weighted_average(list(decode_time_list), sizeunit=1000*1000)

    def calculate_network_send_speed(self):
        """
            This is a time and packet size weighted average.
            This values are in bytes per second.
        """
        if len(self._damage_send_speed)==0:
            return  None, None
        return  self.calculate_timesize_weighted_average(list(self._damage_send_speed))

    def get_client_decode_speed_factor(self, avg, recent):
        """
            Returns the batch delay change factor based on changes
            to the "client decode time".
        """
        if avg is None or recent is None:
            return  None
        msg = "client decode speed: avg=%s, recent=%s (MPixels/s)" % (dec1(avg/1000/1000), dec1(recent/1000/1000))
        return  self.calculate_for_average(msg, avg, recent, div=10.0*1000*1000)

    def get_damage_in_latency_factor(self, avg, recent):
        """
            Returns the batch delay change factor based on changes
            to the "damage-in-latency".
        """
        if len(self._damage_in_latency)==0:
            return  None            #not enough records yet
        #(sent_time, no of pixels, actual batch delay, damage_latency)
        msg = "damage processing latency: avg=%s, recent=%s" % (dec1(1000*avg), dec1(1000*recent))
        target_latency = 0.010  #10ms
        return self.calculate_for_target(msg, target_latency, avg, recent)

    def get_damage_out_latency_factor(self, avg, recent):
        """
            Returns the batch delay change factor based on changes
            to the "damage-out-latency".
        """
        if len(self._damage_in_latency)==0:
            return  None            #not enough records yet
        #(sent_time, no of pixels, actual batch delay, damage_latency)
        msg = "damage send latency: avg=%s, recent=%s" % (dec1(1000*avg), dec1(1000*recent))
        target_latency = 0.020  #20ms
        return self.calculate_for_target(msg, target_latency, avg, recent)

    def get_network_send_speed_factor(self, avg_send_speed, recent_send_speed):
        if avg_send_speed is None or recent_send_speed is None:
            return  None
        msg = "network send speed: avg=%s, recent=%s (KBytes/s)" % (int(avg_send_speed/1024), int(recent_send_speed/1024))
        if recent_send_speed>10*1024*1024:
            return  [msg, 0, 0]
        return  self.calculate_for_average(msg, avg_send_speed, recent_send_speed)

    def get_elasped_time_factor(self, batch, highest_latency):
        """
            Returns the batch delay change factor based on
            the time since we last re-calculated it.
            If nothing happens for a while then we can reduce the batch delay,
            however we must ensure this is not caused by a high damage latency
            so we ignore short elapsed times.
        """
        if batch.last_updated==0 or highest_latency>0.25:
            return  None
        #if damage latency is high, it could just be that the
        #ui thread is too busy, so only fire if nothing happens for a substantial amount of time:
        ignore_time = 2*highest_latency
        ignore_count = 2 + ignore_time / batch.recalculate_delay
        elapsed = time.time()-batch.last_updated
        n_skipped_calcs = elapsed / batch.recalculate_delay
        #the longer the elapsed time, the more we slash:
        weight = logp(max(0, n_skipped_calcs-ignore_count))
        return ("delay not updated for %s ms (skipped %s times - highest latency is %s)" % (dec1(1000*elapsed), int(n_skipped_calcs), dec1(1000*highest_latency)),
                0, weight)

    def get_client_latency_factor(self, avg_client_latency, recent_client_latency):
        """
            Returns the batch delay change factor based on
            the "client latency".
            We want to keep client latency as low as can be.
        """
        if len(self._client_latency)==0 or avg_client_latency is None or recent_client_latency is None:
            return  None
        target_latency = 0.010
        if self._min_client_latency:
            target_latency = self._min_client_latency
        msg = "client latency: lowest=%s, avg=%s, recent=%s" % \
                (dec1(1000*target_latency), dec1(1000*avg_client_latency), dec1(1000*recent_client_latency))
        return  self.calculate_for_target(msg, target_latency, avg_client_latency, recent_client_latency)

    def get_damage_packet_queue_size_factor(self):
        """
            Returns the batch delay change factor based on
            the size of the packet queue.
            Although the number of packets waiting is important,
            it is not as important as the number of pixels in them.
            See:
            - queue_inspect
            - get_damage_packet_queue_pixels_factor
        """
        msg, factor, weight = self.queue_inspect(self._damage_packet_qsizes)
        return ("damage packet queue size: %s" % msg, factor, weight)

    def get_damage_packet_queue_pixels_factor(self, low_limit):
        """
            Returns the batch delay change factor based on
            the number of pixels waiting in the packet queue.
            See 'queue_inspect'
        """
        msg, factor, weight = self.queue_inspect(self._damage_packet_qpixels, target=3, div=low_limit)
        return ("damage packet queue pixels: %s" % msg, factor, weight)

    def get_damage_data_queue_factor(self):
        """
            Returns the batch delay change factor based on
            the number of items in the damage queue.
            This is an important metric since each item will
            consume a fair amount of memory and each will later on
            go through the other queues.
            See 'queue_inspect'
        """
        msg, factor, weight = self.queue_inspect(self._damage_data_qsizes)
        if factor>1.0:
            weight += (factor-1.0)/2
        return ("damage data queue: %s" % msg, factor, weight)

    def get_pending_acks_factor(self, ack_pending):
        """
            Returns the batch delay change factor based on
            the number of damage ACKs we are still waiting for.
            Because of latency, it is normal to have a few pending,
            so we only use this factor to reduce the batch delay
            when there is absolutely nothing pending, not to increase it.
        """
        if ack_pending is None or len(ack_pending)==0:
            return  ["client is fully up to date: no damage ACKs pending", 0, 2.0]
        return ("client has some ACKs pending: %s" % len(ack_pending), 1.0, 0)

    def get_client_backlog_factor(self, window, ack_pending, avg_client_latency, sent_before, low_limit):
        """
            Returns the batch delay change factor based on
            the client pixels and packets latency-adjusted backlog count.
            See calculate_client_backlog.
        """
        last_packets_backlog, last_pixels_backlog = self._last_client_delta
        self._last_client_delta = self.calculate_client_backlog(ack_pending, sent_before)
        packets_backlog, pixels_backlog = self._last_client_delta
        packets_factor = logp(packets_backlog)
        packets_weight = logp((1+packets_backlog)/(1+last_packets_backlog))
        pixels_factor = logp(pixels_backlog/low_limit)
        pixels_weight = logp((1+pixels_backlog)/(1+last_pixels_backlog)/low_limit)
        factor = (packets_factor+pixels_factor)/2
        weight = (packets_weight+pixels_weight)/2
        return  ("packets/pixels backlog from %s/%s to %s/%s" % (last_packets_backlog, last_pixels_backlog, packets_backlog, pixels_backlog),
                 factor, weight)

    def get_mmap_factor(self):
        if not self._mmap or self._mmap_size<=0:
            return  None
        #full: effective range is 0.0 to ~1.2
        full = 1.0-float(self._mmap_free_size)/self._mmap_size
        #aim for ~50%
        return ("mmap area %s full" % int(100*full), logp(2*full), 2*full)

    def update_batch_delay(self, batch, factors):
        """
            Given a list of factors of the form:
            [(description, factor, weight)]
            we calculate a new batch delay.
            We use a time-weighted average of previous delays as a starting value,
            then combine it with the new factors.
        """
        current_delay = batch.delay
        avg = 0
        tv, tw = 0.0, 0.0
        if len(batch.last_delays)>0:
            #get the weighted average:
            now = time.time()
            for when, delay in batch.last_delays:
                #newer matter more:
                w = 1.0/(1.0+(now-when)**2)
                d = max(batch.min_delay, min(batch.max_delay, delay))
                tv += d*w
                tw += w
            avg = tv / tw
        hist_w = tw

        valid_factors = [x for x in factors if x is not None]
        for _, factor, weight in valid_factors:
            target_delay = max(batch.min_delay, min(batch.max_delay, current_delay*factor))
            w = weight*max(1, hist_w)/len(valid_factors)
            tw += w
            tv += target_delay*w
        batch.delay = max(batch.min_delay, min(batch.max_delay, tv / tw))
        batch.last_updated = time.time()
        if DEBUG_DELAY:
            fps = 0
            now = time.time()
            for event_list in self._damage_last_events.values():
                for event_time, _ in event_list:
                    if event_time+1.0>now:
                        fps += 1
            decimal_delays = [dec1(x) for _,x in batch.last_delays]
            if len(decimal_delays)==0:
                decimal_delays.append(0)
            logfactors = [(msg, dec2(f), dec2(w)) for (msg, f, w) in valid_factors]
            rec = ("update_batch_delay: wid=%s, fps=%s, change factor=%s%%, delay min=%s, avg=%s, max=%s, cur=%s, w. average=%s, tot wgt=%s, hist_w=%s, new delay=%s -- %s",
                    batch.wid, fps, dec1(100*(batch.delay/current_delay-1)), min(decimal_delays), dec1(sum(decimal_delays)/len(decimal_delays)), max(decimal_delays),
                    dec1(current_delay), dec1(avg), dec1(tw), dec1(hist_w), dec1(batch.delay), logfactors)
            self.add_DEBUG_DELAY_MESSAGE(rec)

    def calculate_batch_delay(self, wid, window, batch):
        """
            Calculates a new batch delay.
            We first gather some statistics, see:
            - calculate_average_client_latency
            - calculate_average_damage_in_latency
            - calculate_average_damage_out_latency
            then use them to calculate a number of factors, see:
            - get_damage_latency_factor
            - get_elasped_time_factor
            - get_client_latency_factor
            - get_damage_packet_queue_size_factor
            - get_damage_packet_queue_pixels_factor
            - get_damage_data_queue_factor
            - get_client_backlog_factor
            which are then used to adjust the batch delay in 'update_batch_delay'.
        """
        #calculate some values and references we will need:
        avg_client_latency, recent_client_latency = self.calculate_average_client_latency()
        avg_damage_in_latency, recent_damage_in_latency = self.calculate_average_damage_in_latency()
        avg_damage_out_latency, recent_damage_out_latency = self.calculate_average_damage_out_latency()
        ack_pending = self._damage_ack_pending.get(wid)
        low_limit = self.calculate_low_limit(window)
        avg_decode_speed, recent_decode_speed = self.calculate_client_decode_speed(wid)
        avg_send_speed, recent_send_speed = self.calculate_network_send_speed()
        max_latency = max(avg_damage_in_latency, recent_damage_in_latency, avg_damage_out_latency, recent_damage_out_latency)
        #for each indicator: (description, factor, weight)
        factors = []
        factors.append(self.get_damage_in_latency_factor(avg_damage_in_latency, recent_damage_in_latency))
        factors.append(self.get_damage_out_latency_factor(avg_damage_out_latency, recent_damage_out_latency))
        factors.append(self.get_network_send_speed_factor(avg_send_speed, recent_send_speed))
        factors.append(self.get_client_decode_speed_factor(avg_decode_speed, recent_decode_speed))
        factors.append(self.get_elasped_time_factor(batch, max_latency))
        factors.append(self.get_client_latency_factor(avg_client_latency, recent_client_latency))
        factors.append(self.get_damage_packet_queue_size_factor())
        factors.append(self.get_damage_packet_queue_pixels_factor(low_limit))
        factors.append(self.get_damage_data_queue_factor())
        factors.append(self.get_pending_acks_factor(ack_pending))
        factors.append(self.get_client_backlog_factor(window, ack_pending, avg_client_latency, time.time()-avg_client_latency, low_limit))
        factors.append(self.get_mmap_factor())
        self.update_batch_delay(batch, factors)

    def get_encoding(self, wid):
        """ returns the encoding defined for the window given, or the default encoding """
        batch = self.get_batch_config(wid, False)
        if batch:
            return batch.encoding or self._encoding
        return self._encoding

    def get_window_pixmap(self, wid, window, sequence):
        """ Grabs the window's context (pixels) as a pixmap """
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
        """ OR and regular windows differ when it comes to getting their size... sigh """
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
            logrec = "damage(%s, %s, %s, %s, %s) %s, sending now with sequence %s", wid, x, y, w, h, reason, self._sequence
            if DEBUG_DELAY:
                self.add_DEBUG_DELAY_MESSAGE(logrec)
            log(*logrec)
            pixmap = self.get_window_pixmap(wid, window, self._sequence)
            if pixmap:
                self._process_damage_region(now, pixmap, wid, x, y, w, h, coding, self._sequence, options)
                batch.last_delays.append((now, 0))
                batch.last_updated = time.time()
        #record this damage event in the damage_last_events queue:
        now = time.time()
        last_events = self._damage_last_events.setdefault(wid, maxdeque(NRECS))
        last_events.append((now, w*h))

        if not batch.enabled:
            return damage_now("batching disabled")
        if options and options.get("batching", True) is False:
            return damage_now("batching option is off")

        self.may_calculate_batch_delay(wid, window, batch)

        delayed = self._damage_delayed.get(wid)
        if delayed:
            region = delayed[3]
            if coding not in ["x264", "vpx"]:
                region.union_with_rect(gtk.gdk.Rectangle(x, y, w, h))
            log("damage(%s, %s, %s, %s, %s) using existing delayed region: %s", wid, x, y, w, h, delayed)
            return

        if not batch.always and batch.delay<=batch.min_delay:
            return damage_now("delay (%s) is at the minimum threshold (%s)" % (batch.delay, batch.min_delay))

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
            else:
                log("window %s already removed from delayed list?", wid)
            return False
        log("damage(%s, %s, %s, %s, %s) scheduling batching expiry for sequence %s in %s ms", wid, x, y, w, h, self._sequence, dec1(batch.delay))
        batch.last_delays.append((now, batch.delay))
        gobject.timeout_add(int(batch.delay), send_delayed)

    def send_delayed_regions(self, damage_time, wid, window, damage, coding, sequence, options):
        """ Called by 'send_delayed' when we expire a delayed region,
            There may be many rectangles within this delayed region,
            so figure out if we want to send them all or if we
            just send one full screen update instead.
        """
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

        if coding in ["x264", "vpx"]:
            send_full_screen_update()
            return

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
        """
            Called by 'damage_now' or 'send_delayed_regions' to process a damage region,
            we extract the rgb data from the pixmap and place it on the damage queue.
        """
        process_damage_time = time.time()
        data = get_rgb_rawdata(damage_time, process_damage_time, wid, pixmap, x, y, w, h, coding, sequence, options)
        if data:
            log("process_damage_regions: adding pixel data %s to queue, elapsed time: %s ms, queue size=%s", data[:6], dec1(1000*(time.time()-damage_time)), self._damage_data_queue.qsize())
            self._damage_data_qsizes.append((time.time(), self._damage_data_queue.qsize()))
            self._damage_data_queue.put(data)

    def data_to_packet(self):
        """
            This runs in a separate thread and calls 'queue_damage_packet'
            with each data packet obtained from 'make_data_packet'.
        """
        while not self._closed:
            item = self._damage_data_queue.get(True)
            if item is None:
                return              #empty marker
            try:
                #damage_time, process_damage_time, wid, x, y, width, height, encoding, raw_data, rowstride, sequence, options = item
                damage_time = item[0]
                process_damage_time = item[1]
                log("data_to_packet: elapsed time before encoding=%s, size=%s", int(1000*(time.time()-damage_time)), len(self._damage_packet_queue))
                packet = self.make_data_packet(*item)
                if packet:
                    self.queue_damage_packet(packet, damage_time, process_damage_time)
            except Exception, e:
                log.error("error processing damage data: %s", e, exc_info=True)

    def queue_damage_packet(self, packet, damage_time, process_damage_time):
        """
            Adds the given packet to the damage_packet_queue,
            (warning: this runs from the non-UI thread 'data_to_packet')
            we also record a number of statistics:
            - damage packet queue size
            - number of pixels in damage packet queue
            - damage latency (via a callback once the packet is actually sent)
        """
        #log("queue_damage_packet: damage elapsed time=%s ms, queue size=%s", dec1(1000*(time.time()-damage_time)), len(self._damage_packet_queue))
        wid = packet[1]
        width = packet[4]
        height = packet[5]
        actual_batch_delay = process_damage_time-damage_time
        def start_send(bytecount):
            self._last_packet_send_stats = time.time(), bytecount
        def damage_packet_sent(bytecount):
            now = time.time()
            if self._last_packet_send_stats:
                start_send_time, start_bytecount = self._last_packet_send_stats
                self._damage_send_speed.append((now, bytecount-start_bytecount, now-start_send_time))
            #packet = ["draw", wid, x, y, w, h, coding, data, self._damage_packet_sequence, rowstride]
            damage_packet_sequence = packet[8]
            damage_out_latency = now-process_damage_time
            self._damage_out_latency.append((now, width*height, actual_batch_delay, damage_out_latency))
            ack_pending = self._damage_ack_pending.setdefault(wid, {})
            ack_pending[damage_packet_sequence] = now, width*height
            #log("damage_packet_sent: took %s ms for %s pixels of packet_sequence %s, %s ns per pixel",
            #         dec1(1000*damage_latency), width*height, packet_sequence, dec1(1000*1000*1000*damage_latency/(width*height)))
        now = time.time()
        damage_in_latency = now-process_damage_time
        self._damage_in_latency.append((now, width*height, actual_batch_delay, damage_in_latency))
        self._damage_packet_qsizes.append((now, len(self._damage_packet_queue)))
        self._damage_packet_queue.append((packet, width*height, start_send, damage_packet_sent))
        self._damage_packet_qpixels.append((now, sum([x[1] for x in list(self._damage_packet_queue)])))
        gobject.idle_add(self._protocol.source_has_more)

    def client_ack_damage(self, damage_packet_sequence, wid, width, height, decode_time):
        """
            The client is acknoledging a damage packet,
            we record the 'client decode time' (provided by the client itself)
            and the "client latency".
        """
        log("packet decoding for window %s %sx%s took %s µs", wid, width, height, decode_time)
        if decode_time:
            client_decode_list = self._client_decode_time.setdefault(wid, maxdeque(maxlen=NRECS))
            client_decode_list.append((time.time(), width*height, decode_time))
        ack_pending = self._damage_ack_pending.get(wid)
        if not ack_pending:
            log("cannot find damage_pending list for window %s - already removed?", wid)
            return
        pending = ack_pending.get(damage_packet_sequence)
        if pending is None:
            log("cannot find sent time for sequence %s", damage_packet_sequence)
            return
        del ack_pending[damage_packet_sequence]
        if decode_time:
            sent_at, pixels = pending
            now = time.time()
            diff = now-sent_at
            latency = max(0, diff-decode_time/1000/1000)
            log("client_ack_damage: took %s ms round trip, %s for decoding of %s pixels, %s for network", dec1(diff*1000), dec1(decode_time/1000), pixels, dec1(latency*1000))
            if self._min_client_latency is None or self._min_client_latency>latency:
                self._min_client_latency = latency
            self._client_latency.append((now, width*height, latency))

    def make_data_packet(self, damage_time, process_damage_time, wid, x, y, w, h, coding, data, rowstride, sequence, options):
        """
            Picture encoding - non-UI thread.
            Converts a damage item picked from the 'damage_data_queue'
            by the 'data_to_packet' thread and returns a packet
            ready for sending by the network layer.
            x264 and vpx use 'video_encode', mmap will use 'mmap_send',
            'rgb24', 'jpeg' and 'png' are handled within.

        """
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
        self._encoding_stats.append((wid, coding, w*h, len(data), end-start))
        return packet

    def video_encode(self, encoders, factory, wid, x, y, w, h, coding, data, rowstride):
        """
            This method is used by make_data_packet to encode frames using x264 or vpx.
            Video encoders only deal with fixed dimensions,
            so we must clean and reinitialize the encoder if the window dimensions
            has changed.
            Since this runs in the non-UI thread 'data_to_packet', we must
            use the 'video_encoder_lock' to prevent races.

        """
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
        self._mmap_free_size = available-l
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
