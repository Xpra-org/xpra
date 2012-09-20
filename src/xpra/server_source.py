# coding=utf8
# This file is part of Parti.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import gobject
import ctypes
try:
    from queue import Queue         #@UnresolvedImport @UnusedImport (python3)
except:
    from Queue import Queue         #@Reimport
from collections import deque

from wimpiggy.log import Logger
log = Logger()

from xpra.deque import maxdeque
from xpra.window_source import WindowSource, DamageBatchConfig
from xpra.maths import add_list_stats, dec1
from xpra.scripts.main import ENCODINGS


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
                                                        #(wid, event_time, no of pixels, decoding_time*1000*1000)
        self.min_client_latency = None                  #The lowest client latency ever recorded: the time it took
                                                        #from the moment the damage packet got sent until we got the ack packet
        self.client_latency = maxdeque(NRECS)           #how long it took for a packet to get to the client and get the echo back.
                                                        #(wid, event_time, no of pixels, client_latency)
        self.avg_client_latency = None
        self.client_ping_latency = maxdeque(NRECS)
        self.server_ping_latency = maxdeque(NRECS)
        self.client_load = None

    def record_latency(self, wid, decode_time, start_send_at, end_send_at, pixels, bytecount):
        now = time.time()
        send_diff = now-start_send_at
        echo_diff = now-end_send_at
        send_latency = max(0, send_diff-decode_time/1000.0/1000.0)
        echo_latency = max(0, echo_diff-decode_time/1000.0/1000.0)
        log("record_latency: took %s ms round trip (%s just for echo), %s for decoding of %s pixels, %s bytes sent over the network in %s ms (%s ms for echo)",
                dec1(send_diff*1000), dec1(echo_diff*1000), dec1(decode_time/1000.0), pixels, bytecount, dec1(send_latency*1000), dec1(echo_latency*1000))
        if self.min_client_latency is None or self.min_client_latency>send_latency:
            self.min_client_latency = send_latency
        self.client_latency.append((wid, time.time(), pixels, send_latency))

    def add_stats(self, info, suffix=""):
        info["output_mmap_bytecount%s" % suffix] = self.mmap_bytes_sent
        if self.min_client_latency is not None:
            info["client_latency%s.absmin" % suffix] = int(self.min_client_latency*1000)
        qsizes = [x for _,x in list(self.damage_data_qsizes)]
        add_list_stats(info, "damage_data_queue_size%s" % suffix,  qsizes)
        qsizes = [x for _,x in list(self.damage_packet_qsizes)]
        add_list_stats(info, "damage_packet_queue_size%s" % suffix,  qsizes)
        latencies = [x*1000 for (_, _, _, x) in list(self.client_latency)]
        add_list_stats(info, "client_latency%s" % suffix,  latencies)

        add_list_stats(info, "server_ping_latency%s" % suffix, [x for _, x in self.server_ping_latency])
        add_list_stats(info, "client_ping_latency%s" % suffix, [x for _, x in self.client_ping_latency])

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
            info["pixels_decoded_per_second%s" % suffix] = pixels_decoded_per_second
        if start_time:
            elapsed = now-start_time
            pixels_per_second = int(total_pixels/elapsed)
            info["pixels_per_second%s" % suffix] = pixels_per_second
            info["regions_per_second%s" % suffix] = int(len(region_sizes)/elapsed)
            info["average_region_size%s" % suffix] = int(total_pixels/len(region_sizes))


class ServerSource(object):
    """
    A ServerSource mediates between the server (which only knows about windows)
    and the WindowSource (which only knows about window ids) instances
    which manage damage data processing.
    It sends damage pixels to the client via its 'protocol' instance (network connection).

    Strategy: if we have 'ordinary_packets' to send, send those.
    When we don't, then send window updates from the 'damage_packet_queue'.
    See 'next_packet'.

    The UI thread calls damage(), which goes into WindowSource and eventually (batching may be involved)
    adds the damage pixels ready for processing to the damage_data_queue,
    items are picked off by the separate 'data_to_packet' thread and added to the
    damage_packet_queue.
    """

    def __init__(self, protocol, supports_mmap):
        self.closed = False
        self.ordinary_packets = []
        self.protocol = protocol
        self.supports_rgb24zlib = False
        # mmap:
        self.supports_mmap = supports_mmap
        self.mmap = None
        self.mmap_size = 0

        self.encoding = None                       #the default encoding for all windows
        self.encodings = []                        #all the encodings supported by the client
        self.encoding_client_options = False       #does the client support encoding options?
        self.png_window_icons = False
        self.default_batch_config = DamageBatchConfig()
        self.default_damage_options = {}

        self.window_sources = {}                    #WindowSource for each Window ID

        self.uuid = None
        # client capabilities:
        self.server_window_resize = False
        self.send_cursors = False
        self.send_bell = False
        self.send_notifications = False
        self.randr_notify = False
        self.clipboard_enabled = False
        self.share = False
        self.desktop_size = None

        # the queues of damage requests we work through:
        self.damage_data_queue = Queue()           #holds functions to call to process damage data
                                                    #items placed in this queue are picked off by the "data_to_packet" thread,
                                                    #the functions should add the packets they generate to the 'damage_packet_queue'
        self.damage_packet_queue = deque()         #holds actual packets ready for sending (already encoded)
                                                    #these packets are picked off by the "protocol" via 'next_packet()'
                                                    #format: packet, wid, pixels, start_send_cb, end_send_cb
        #these statistics are shared by all WindowSource instances:
        self.statistics = GlobalPerformanceStatistics()
        # ready for processing:
        protocol.source = self
        self.datapacket_thread = start_daemon_thread(self.data_to_packet, "data_to_packet")

    def close(self):
        self.closed = True
        self.damage_data_queue.put(None, block=False)
        for window_source in self.window_sources.values():
            window_source.cleanup()
        self.window_sources = {}
        self.close_mmap()

    def parse_hello(self, capabilities):
        #batch options:
        self.default_batch_config = DamageBatchConfig()
        self.default_batch_config.enabled = bool(capabilities.get("batch.enabled", DamageBatchConfig.ENABLED))
        self.default_batch_config.always = bool(capabilities.get("batch.always", False))
        self.default_batch_config.min_delay = min(1000, max(1, capabilities.get("batch.min_delay", DamageBatchConfig.MIN_DELAY)))
        self.default_batch_config.max_delay = min(15000, max(1, capabilities.get("batch.max_delay", DamageBatchConfig.MAX_DELAY)))
        self.default_batch_config.delay = min(1000, max(1, capabilities.get("batch.delay", DamageBatchConfig.START_DELAY)))
        #client uuid:
        self.uuid = capabilities.get("uuid", "")
        #general features:
        self.server_window_resize = capabilities.get("server-window-resize", False)
        self.send_cursors = capabilities.get("cursors", False)
        self.send_bell = capabilities.get("bell", False)
        self.send_notifications = capabilities.get("notifications", False)
        self.randr_notify = capabilities.get("randr_notify", False)
        self.clipboard_enabled = capabilities.get("clipboard", True)
        self.share = capabilities.get("share", False)
        self.desktop_size = capabilities.get("desktop_size")
        #encodings:
        self.encoding_client_options = capabilities.get("encoding_client_options", False)
        self.supports_rgb24zlib = capabilities.get("rgb24zlib", False)
        self.encodings = capabilities.get("encodings", [])
        self.set_encoding(capabilities.get("encoding", None), None)
        if "jpeg" in capabilities:
            self.default_damage_options["jpegquality"] = capabilities["jpeg"]
        self.png_window_icons = "png" in self.encodings and "png" in ENCODINGS
        #mmap:
        mmap_file = capabilities.get("mmap_file")
        mmap_token = capabilities.get("mmap_token")
        log("client supplied mmap_file=%s, mmap supported=%s", mmap_file, self.supports_mmap)
        if self.supports_mmap and mmap_file and os.path.exists(mmap_file):
            self.init_mmap(mmap_file, mmap_token)
        log("cursors=%s, bell=%s, notifications=%s", self.send_cursors, self.send_bell, self.send_notifications)

#
# Functions for interacting with the network layer:
#
    def next_packet(self):
        """ Called by protocol.py when it is ready to send the next packet """
        packet, start_send_cb, end_send_cb, have_more = None, None, None, False
        if not self.closed:
            if self.ordinary_packets:
                packet = self.ordinary_packets.pop(0)
            elif len(self.damage_packet_queue)>0:
                packet, _, _, start_send_cb, end_send_cb = self.damage_packet_queue.popleft()
            have_more = packet is not None and (bool(self.ordinary_packets) or len(self.damage_packet_queue)>0)
        return packet, start_send_cb, end_send_cb, have_more

    def send(self, packet):
        """ This method queues non-damage packets (higher priority) """
        assert self.protocol
        self.ordinary_packets.append(packet)
        self.protocol.source_has_more()

#
# Functions used by the server to request something
# (window events, stats, user requests, etc)
#
    def set_encoding(self, encoding, window_ids):
        """ Changes the encoder for the given 'window_ids',
            or for all windows if 'window_ids' is None.
        """
        if encoding:
            assert encoding in self.encodings, "encoding %s is not supported, client supplied list: %s" % (encoding, self.encodings)
            if encoding not in ENCODINGS:
                log.error("encoding %s is not supported by this server! " \
                         "Will use the first commonly supported encoding instead", encoding)
                encoding = None
        else:
            log("encoding not specified, will use the first match")
        if not encoding:
            #not specified or not supported, find intersection of supported encodings:
            common = [e for e in self.encodings if e in ENCODINGS]
            log("encodings supported by both ends: %s", common)
            if not common:
                raise Exception("cannot find compatible encoding between "
                                "client (%s) and server (%s)" % (self.encodings, ENCODINGS))
            encoding = common[0]
        if window_ids is not None:
            wss = [self.window_sources.get(wid) for wid in window_ids]
        else:
            wss = self.window_sources.values()
        for ws in wss:
            if ws is not None:
                ws.set_new_encoding(encoding)
        if not window_ids or self.encoding is None:
            self.encoding = encoding

    def hello(self, server_capabilities):
        capabilities = server_capabilities.copy()
        capabilities["encoding"] = self.encoding
        capabilities["mmap_enabled"] = self.mmap_size>0
        self.send(["hello", capabilities])

    def add_info(self, info, suffix=""):
        info["clipboard%s" % suffix] = self.clipboard_enabled
        info["cursors%" % suffix] = self.send_cursors
        info["bell%" % suffix] = self.send_bell
        info["notifications%" % suffix] = self.send_notifications

    def send_clipboard(self, packet):
        if self.clipboard_enabled:
            self.send(packet)

    def send_cursor(self, cursor_data):
        if self.send_cursors:
            if cursor_data:
                self.send(["cursor"] + cursor_data)
            else:
                self.send(["cursor", ""])

    def bell(self, wid, device, percent, pitch, duration, bell_class, bell_id, bell_name):
        if self.send_bell:
            self.send(["bell", wid, device, percent, pitch, duration, bell_class, bell_id, bell_name])

    def notify(self, dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout):
        if self.send_notifications:
            self.send(["notify_show", dbus_id, int(nid), str(app_name), int(replaces_nid), str(app_icon), str(summary), str(body), int(expire_timeout)])

    def notify_close(self, nid):
        if self.send_notifications:
            self.send(["notify_close", nid])

    def set_deflate(self, level):
        self.send(["set_deflate", level])

    def ping(self):
        self.send(["ping", int(1000*time.time())])

    def process_ping(self, time_to_echo):
        #send back the load average:
        try:
            (fl1, fl2, fl3) = os.getloadavg()
            l1,l2,l3 = int(fl1*1000), int(fl2*1000), int(fl3*1000)
        except:
            l1,l2,l3 = 0,0,0
        cl = -1
        #and the last client ping latency we measured (if any):
        if len(self.statistics.client_ping_latency)>0:
            _, cl = self.statistics.client_ping_latency[-1]
        self.send(["ping_echo", time_to_echo, l1, l2, l3, cl])
        #if the client is pinging us, ping it too:
        gobject.timeout_add(500, self.ping)

    def process_ping_echo(self, client_ping_latency, server_ping_latency, load):
        self.statistics.client_ping_latency.append((time.time(), client_ping_latency/1000.0))
        self.client_load = load
        if server_ping_latency>=0:
            self.statistics.server_ping_latency.append((time.time(), server_ping_latency/1000.0))
        log("ping echo client load=%s, measured server latency=%s", load, server_ping_latency)

    def updated_desktop_size(self, root_w, root_h, max_w, max_h):
        if self.randr_notify:
            self.send(["desktop_size", root_w, root_h, max_w, max_h])

    def or_window_geometry(self, wid, x, y, w, h):
        self.send(["configure-override-redirect", wid, x, y, w, h])

    def window_metadata(self, wid, metadata):
        self.send(["window-metadata", wid, metadata])

    def new_window(self, ptype, wid, x, y, w, h, metadata, client_properties):
        self.send([ptype, wid, x, y, w, h, metadata, client_properties or {}])

    def lost_window(self, wid):
        self.send(["lost-window", wid])

    def resize_window(self, wid, ww, wh):
        """
        The server detected that the application window has been resized,
        we forward it if the client supports this type of event.
        """
        if self.server_window_resize:
            self.send(["window-resized", wid, ww, wh])

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

    def add_stats(self, info, window_ids=[], suffix=""):
        """
            Adds most of the statistics available to the 'info' dict passed in.
            This is used by server.py to provide those statistics to clients
            via the 'xpra info' command.
        """
        info["client_encodings%s" % suffix] = ",".join(self.encodings)
        info["damage_data_queue_size%s.current" % suffix] = self.damage_data_queue.qsize()
        info["damage_packet_queue_size%s.current" % suffix] = len(self.damage_packet_queue)
        qpixels = [x[2] for x in list(self.damage_packet_queue)]
        add_list_stats(info, "damage_packet_queue_pixels%s" % suffix,  qpixels)
        if len(qpixels)>0:
            info["damage_packet_queue_pixels%s.current" % suffix] = qpixels[-1]
        self.ping()

        self.protocol.add_stats(info, suffix=suffix)
        self.statistics.add_stats(info, suffix=suffix)
        batch_delays = []
        if window_ids:
            total_pixels = 0
            total_time = 0.0
            for wid in window_ids:
                ws = self.window_sources.get(wid)
                if ws:
                    #per-window stats:
                    ws.add_stats(info, suffix=suffix)
                    #collect stats for global averages:
                    for _, pixels, _, encoding_time in ws.statistics.encoding_stats:
                        total_pixels += pixels
                        total_time += encoding_time
                    info["pixels_encoded_per_second%s" % suffix] = int(total_pixels / total_time)
                    batch = ws.batch_config
                    for _,d in list(batch.last_delays):
                        batch_delays.append(d)
        if len(batch_delays)>0:
            add_list_stats(info, "batch_delay%s" % suffix, batch_delays)

    def set_default_quality(self, quality):
        self.default_damage_options["jpegquality"] = quality

    def refresh(self, wid, window, opts):
        self.cancel_damage(wid)
        w, h = window.get_dimensions()
        self.damage(wid, window, 0, 0, w, h, opts)

    def damage(self, wid, window, x, y, w, h, options=None):
        """
            Main entry point from the window manager,
            we dispatch to the WindowSource for this window id
            (creating a new one if needed)
        """
        if options is None:
            damage_options = self.default_damage_options
        else:
            damage_options = self.default_damage_options.copy()
            for k,v in options.items():
                damage_options[k] = v
        self.statistics.damage_last_events.append((wid, time.time(), w*h))
        ws = self.window_sources.get(wid)
        if ws is None:
            batch_config = self.default_batch_config.clone()
            batch_config.wid = wid
            ws = WindowSource(self.queue_damage, self.queue_packet, self.statistics,
                              wid, batch_config,
                              self.encoding, self.encodings,
                              self.encoding_client_options, self.supports_rgb24zlib,
                              self.mmap, self.mmap_size)
            self.window_sources[wid] = ws
        ws.damage(window, x, y, w, h, damage_options)

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
        self.statistics.damage_data_qsizes.append((time.time(), self.damage_data_queue.qsize()))
        self.damage_data_queue.put(encode_and_send_cb)

    def queue_packet(self, packet, wid, pixels, start_send_cb, end_send_cb):
        """
            Add a new 'draw' packet to the 'damage_packet_queue'.
            Note: this code runs in the non-ui thread so we have to use idle_add to call into protocol.
        """
        now = time.time()
        self.statistics.damage_packet_qsizes.append((now, len(self.damage_packet_queue)))
        self.statistics.damage_packet_qpixels.append((now, wid, sum([x[1] for x in list(self.damage_packet_queue) if x[2]==wid])))
        self.damage_packet_queue.append((packet, wid, pixels, start_send_cb, end_send_cb))
        #if self.protocol._write_queue.empty():
        gobject.idle_add(self.protocol.source_has_more)

#
# The damage packet thread loop:
#
    def data_to_packet(self):
        """
            This runs in a separate thread and calls all the function callbacks
            which are added to the 'damage_data_queue'.
        """
        while not self.closed:
            encode_and_queue = self.damage_data_queue.get(True)
            if encode_and_queue is None:
                return              #empty marker
            try:
                encode_and_queue()
            except Exception, e:
                log.error("error processing damage data: %s", e, exc_info=True)
            NOYIELD or time.sleep(0)

#
# Management of mmap area:
#
    def init_mmap(self, mmap_file, mmap_token):
        import mmap
        try:
            f = open(mmap_file, "r+b")
            self.mmap_size = os.path.getsize(mmap_file)
            self.mmap = mmap.mmap(f.fileno(), self.mmap_size)
            if mmap_token:
                #verify the token:
                v = 0
                for i in range(0,16):
                    v = v<<8
                    peek = ctypes.c_ubyte.from_buffer(self.mmap, 512+15-i)
                    v += peek.value
                log("mmap_token=%s, verification=%s", mmap_token, v)
                if v!=mmap_token:
                    log.error("WARNING: mmap token verification failed, not using mmap area!")
                    self.close_mmap()
            if self.mmap:
                log.info("using client supplied mmap file=%s, size=%s", mmap_file, self.mmap_size)
                self.statistics.mmap_size = self.mmap_size
        except Exception, e:
            log.error("cannot use mmap file '%s': %s", mmap_file, e)
            self.close_mmap()

    def close_mmap(self):
        if self.mmap:
            self.mmap.close()
            self.mmap = None
        self.mmap_size = 0
