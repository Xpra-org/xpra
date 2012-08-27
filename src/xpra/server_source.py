# coding=utf8
# This file is part of Parti.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import gobject
try:
    from queue import Queue         #@UnresolvedImport @UnusedImport (python3)
except:
    from Queue import Queue         #@Reimport
from collections import deque

from wimpiggy.log import Logger
log = Logger()

from xpra.deque import maxdeque
from xpra.window_source import WindowSource
from xpra.maths import add_list_stats


def start_daemon_thread(target, name):
    from threading import Thread
    t = Thread(target=target)
    t.name = name
    t.daemon = True
    t.start()
    return t

import os
NOYIELD = os.environ.get("XPRA_YIELD") is None

NRECS = 500

class GlobalPerformanceStatistics(object):
    """
    Statistics which are shared by all WindowSources
    """
    def __init__(self):
        self.reset()

    def reset(self):
        # mmap state:
        self.mmap_size = 0
        self.mmap_bytes_sent = 0
        self.mmap_free_size = 0                        #how much of the mmap space is left (may be negative if we failed to write the last chunk)
        # queue statistics:
        self.damage_data_qsizes = maxdeque(NRECS)       #size of the damage_data_queue before we add a new record to it
                                                        #(event_time, size)
        self.damage_packet_qsizes = maxdeque(NRECS)     #size of the damage_packet_queue before we add a new packet to it
                                                        #(event_time, size)
        self.damage_packet_qpixels = maxdeque(NRECS)    #number of pixels waiting in the damage_packet_queue for a specific window,
                                                        #before we add a new packet to it
                                                        #(event_time, wid, size)
        self.damage_last_events = maxdeque(NRECS)       #records the x11 damage requests as they are received:
                                                        #(wid, event time, no of pixels)
        self.client_decode_time = maxdeque(NRECS)       #records how long it took the client to decode frames:
                                                        #(wid, event_time, no of pixels, decoding_time)
        self.min_client_latency = None                  #The lowest client latency ever recorded
        self.client_latency = maxdeque(NRECS)           #how long it took for a packet to get to the client and get the echo back.
                                                        #(wid, event_time, no of pixels, client_latency)
    def record_latency(self, wid, pixels, latency):
        if self.min_client_latency is None or self.min_client_latency>latency:
            self.min_client_latency = latency
        self.client_latency.append((wid, time.time(), pixels, latency))

    def add_stats(self, info):
        info["output_mmap_bytecount"] = self.mmap_bytes_sent
        if self.min_client_latency:
            info["client_latency.absmin"] = int(self.min_client_latency*1000)
        qsizes = [x for _,x in list(self.damage_data_qsizes)]
        add_list_stats(info, "damage_data_queue_size",  qsizes)
        qsizes = [x for _,x in list(self.damage_packet_qsizes)]
        add_list_stats(info, "damage_packet_queue_size",  qsizes)
        latencies = [x*1000 for (_, _, _, x) in list(self.client_latency)]
        add_list_stats(info, "client_latency",  latencies)

        #client pixels per second:
        now = time.time()
        time_limit = now-30             #ignore old records (30s)
        #pixels per second: decode time and overall
        total_pixels = 0                #total number of pixels processed
        total_time = 0                  #total decoding time
        start_time = None               #when we start counting from (oldest record)
        region_sizes = []
        for _, event_time, pixels, decode_time in self.client_decode_time:
            #time filter and ignore failed decoding (decode_time==0)
            if event_time<time_limit or decode_time<=0:
                continue
            if start_time is None or start_time>event_time:
                start_time = event_time
            total_pixels += pixels
            total_time += decode_time
            region_sizes.append(pixels)
        log("total_time=%s, total_pixels=%s", total_time, total_pixels)
        if total_time>0:
            pixels_decoded_per_second = int(total_pixels *1000*1000 / total_time)
            info["pixels_decoded_per_second"] = pixels_decoded_per_second
        if start_time:
            elapsed = now-start_time
            pixels_per_second = int(total_pixels/elapsed)
            info["pixels_per_second"] = pixels_per_second
            info["regions_per_second"] = int(len(region_sizes)/elapsed)
            info["average_region_size"] = int(total_pixels/len(region_sizes))


class ServerSource(object):
    """
    A ServerSource mediates between the server (which only knows about window ids)
    and the WindowSource instances which manage damage data processing.
    It sends damage pixels to the client via its 'protocol' instance (network connection).

    Strategy: if we have 'ordinary_packets' to send, send those.
    When we don't, then send window updates from the 'damage_packet_queue'.
    See 'next_packet'.

    The UI thread calls damage(), which goes into WindowSource and eventually (batching may be involved)
    adds the damage pixels ready for processing to the damage_data_queue,
    items are picked off by the separate 'data_to_packet' thread and added to the
    damage_packet_queue.
    """

    def __init__(self, protocol, batch_config, encoding, encodings, mmap, mmap_size, encoding_client_options):
        self._closed = False
        self._ordinary_packets = []
        self._protocol = protocol
        # mmap:
        self._mmap = mmap
        self._mmap_size = mmap_size

        self._encoding = encoding                   #the default encoding for all windows
        self._encodings = encodings                 #all the encodings supported by the client
        self._encoding_client_options = encoding_client_options #does the client support encoding options?
        self._default_batch_config = batch_config

        self.window_sources = {}                    #WindowSource for each Window ID

        # the queues of damage requests we work through:
        self._damage_data_queue = Queue()           #holds functions to call to process damage data
                                                    #items placed in this queue are picked off by the "data_to_packet" thread,
                                                    #the functions should add the packets they generate to the 'damage_packet_queue'
        self._damage_packet_queue = deque()         #holds actual packets ready for sending (already encoded)
                                                    #these packets are picked off by the "protocol" via 'next_packet()'
                                                    #format: packet, wid, pixels, start_send_cb, end_send_cb
        #these statistics are shared by all WindowSource instances:
        self.statistics = GlobalPerformanceStatistics()
        self.statistics.mmap_size = mmap_size
        # ready for processing:
        protocol.source = self
        self._datapacket_thread = start_daemon_thread(self.data_to_packet, "data_to_packet")

    def close(self):
        self._closed = True
        self._damage_data_queue.put(None, block=False)
        for window_source in self.window_sources.values():
            window_source.cleanup()
        self.window_sources = {}


#
# Functions for interacting with the network layer:
#
    def next_packet(self):
        """ Called by protocol.py when it is ready to send the next packet """
        packet, start_send_cb, end_send_cb, have_more = None, None, None, False
        if not self._closed:
            if self._ordinary_packets:
                packet = self._ordinary_packets.pop(0)
            elif len(self._damage_packet_queue)>0:
                packet, _, _, start_send_cb, end_send_cb = self._damage_packet_queue.popleft()
            have_more = packet is not None and (bool(self._ordinary_packets) or len(self._damage_packet_queue)>0)
        return packet, start_send_cb, end_send_cb, have_more

    def queue_ordinary_packet(self, packet):
        """ This method queues non-damage packets (higher priority) """
        assert self._protocol
        self._ordinary_packets.append(packet)
        self._protocol.source_has_more()

#
# Functions used by the server to request something
# (window events, stats, user requests, etc)
#
    def set_new_encoding(self, encoding, window_ids):
        """ Changes the encoder for the given 'window_ids',
            or for all windows if 'window_ids' is None.
        """
        if window_ids is not None:
            wss = [self.window_sources.get(wid) for wid in window_ids]
        else:
            wss = self.window_sources.values()
        for ws in wss:
            if ws is not None:
                ws.set_new_encoding(encoding)
        if not window_ids or self._encoding is None:
            self._encoding = encoding

    def cancel_damage(self, wid):
        """
        Use this method to cancel all currently pending and ongoing
        damage requests for a window.
        """
        ws = self.window_sources.get(wid)
        if ws:
            ws.cancel_damage()

    def remove_window(self, wid):
        """ The given window is gone, ensure we free all the related resources """
        ws = self.window_sources.get(wid)
        if ws:
            del self.window_sources[wid]
            ws.cleanup()

    def add_stats(self, info, window_ids=[]):
        """
            Adds most of the statistics available to the 'info' dict passed in.
            This is used by server.py to provide those statistics to clients
            via the 'xpra info' command.
        """
        info["damage_data_queue_size.current"] = self._damage_data_queue.qsize()
        info["damage_packet_queue_size.current"] = len(self._damage_packet_queue)
        qpixels = [x[2] for x in list(self._damage_packet_queue)]
        add_list_stats(info, "damage_packet_queue_pixels",  qpixels)
        if len(qpixels)>0:
            info["damage_packet_queue_pixels.current"] = qpixels[-1]

        self._protocol.add_stats(info)
        self.statistics.add_stats(info)
        batch_delays = []
        if window_ids:
            total_pixels = 0
            total_time = 0.0
            for wid in window_ids:
                ws = self.window_sources.get(wid)
                if ws:
                    #per-window stats:
                    ws.add_stats(info)
                    #collect stats for global averages:
                    for _, pixels, _, encoding_time in ws.statistics.encoding_stats:
                        total_pixels += pixels
                        total_time += encoding_time
                    info["pixels_encoded_per_second"] = int(total_pixels / total_time)
                    batch = ws.batch_config
                    for _,d in list(batch.last_delays):
                        batch_delays.append(d)
        if len(batch_delays)>0:
            add_list_stats(info, "batch_delay", batch_delays)


    def damage(self, wid, window, x, y, w, h, options=None):
        """
            Main entry point from the window manager,
            we dispatch to the WindowSource for this window id
            (creating a new one if needed)
        """
        self.statistics.damage_last_events.append((wid, time.time(), w*h))
        ws = self.window_sources.get(wid)
        if ws is None:
            ws = WindowSource(self.queue_damage, self.queue_packet, self.statistics,
                              wid, self._default_batch_config.clone(),
                              self._encoding, self._encodings, self._encoding_client_options,
                              self._mmap, self._mmap_size)
            self.window_sources[wid] = ws
        ws.damage(window, x, y, w, h, options)

    def client_ack_damage(self, damage_packet_sequence, wid, width, height, decode_time):
        """
            The client is acknowledging a damage packet,
            we record the 'client decode time' (which is provided by the client)
            and WindowSource will calculate and record the "client latency".
            (since it knows when the "draw" packet was sent)
        """
        log("packet decoding for window %s %sx%s took %s µs", wid, width, height, decode_time)
        if decode_time:
            self.statistics.client_decode_time.append((wid, time.time(), width*height, decode_time))
        ws = self.window_sources.get(wid)
        if ws:
            ws.damage_packet_acked(damage_packet_sequence, width, height, decode_time)

#
# Methods used by WindowSource:
#
    def queue_damage(self, encode_and_send_cb):
        """
            This is used by WindowSource to queue damage processing to be done in the 'data_to_packet' thread.
            The 'encode_and_send_cb' will then add the resulting packet to the 'damage_packet_queue' via 'queue_packet'.
        """
        self._damage_data_queue.put(encode_and_send_cb)

    def queue_packet(self, packet, wid, pixels, start_send_cb, end_send_cb):
        """
            Add a new 'draw' packet to the 'damage_packet_queue'.
            Note: this code runs in the non-ui thread so we have to use idle_add to call into protocol.
        """
        now = time.time()
        self.statistics.damage_packet_qsizes.append((now, len(self._damage_packet_queue)))
        self.statistics.damage_packet_qpixels.append((now, wid, sum([x[1] for x in list(self._damage_packet_queue) if x[2]==wid])))
        self._damage_packet_queue.append((packet, wid, pixels, start_send_cb, end_send_cb))
        #if self._protocol._write_queue.empty():
        gobject.idle_add(self._protocol.source_has_more)

#
# The damage packet thread loop:
#
    def data_to_packet(self):
        """
            This runs in a separate thread and calls all the function callbacks
            which are added to the 'damage_data_queue'.
        """
        while not self._closed:
            encode_and_queue = self._damage_data_queue.get(True)
            if encode_and_queue is None:
                return              #empty marker
            try:
                encode_and_queue()
            except Exception, e:
                log.error("error processing damage data: %s", e, exc_info=True)
            NOYIELD or time.sleep(0)
