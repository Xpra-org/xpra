# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import re
from math import sqrt
import os
import time
import gobject
import ctypes
try:
    from queue import Queue         #@UnresolvedImport @UnusedImport (python3)
except:
    from Queue import Queue         #@Reimport
from collections import deque
from threading import Event

from wimpiggy.log import Logger
log = Logger()

try:
    from StringIO import StringIO   #@UnusedImport
except:
    from io import StringIO         #@UnresolvedImport @Reimport

from xpra.deque import maxdeque
from xpra.window_source import WindowSource, DamageBatchConfig
from xpra.stats.base import add_list_stats, std_unit
from xpra.stats.maths import logp, calculate_time_weighted_average, calculate_for_target, queue_inspect
from xpra.scripts.config import HAS_SOUND, ENCODINGS
from xpra.protocol import zlib_compress, Compressed
from xpra.daemon_thread import make_daemon_thread

NOYIELD = os.environ.get("XPRA_YIELD") is None

NRECS = 500

debug = log.debug

def platform_name(sys_platform, release):
    PLATFORMS = {"win32"    : "Microsoft Windows",
                 "cygwin"   : "Windows/Cygwin",
                 "linux2"   : "Linux",
                 "darwin"   : "Mac OSX",
                 "freebsd.*": "FreeBSD",
                 "os2"      : "OS/2",
                 }
    def rel(v):
        if sys_platform=="win32" and release:
            return "%s %s" % (v, release)
        return v
    for k,v in PLATFORMS.items():
        regexp = re.compile(k)
        if regexp.match(sys_platform):
            return rel(v)
    return rel(sys_platform)


class GlobalPerformanceStatistics(object):
    """
    Statistics which are shared by all WindowSources
    """
    def __init__(self):
        self.reset()

    #assume 100ms until we get some data to compute the real values
    DEFAULT_LATENCY = 0.1

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
        self.client_latency = maxdeque(NRECS)           #how long it took for a packet to get to the client and get the echo back.
                                                        #(wid, event_time, no of pixels, client_latency)
        self.client_ping_latency = maxdeque(NRECS)      #time it took to get a ping_echo back from the client:
                                                        #(event_time, elapsed_time_in_seconds)
        self.server_ping_latency = maxdeque(NRECS)      #time it took for the client to get a ping_echo back from us:
                                                        #(event_time, elapsed_time_in_seconds)
        self.client_load = None
        self.last_ping_echoed_time = 0
        #these values are calculated from the values above (see update_averages)
        self.min_client_latency = self.DEFAULT_LATENCY
        self.avg_client_latency = self.DEFAULT_LATENCY
        self.recent_client_latency = self.DEFAULT_LATENCY
        self.min_client_ping_latency = self.DEFAULT_LATENCY
        self.avg_client_ping_latency = self.DEFAULT_LATENCY
        self.recent_client_ping_latency = self.DEFAULT_LATENCY
        self.min_server_ping_latency = self.DEFAULT_LATENCY
        self.avg_server_ping_latency = self.DEFAULT_LATENCY
        self.recent_server_ping_latency = self.DEFAULT_LATENCY

    def record_latency(self, wid, decode_time, start_send_at, end_send_at, pixels, bytecount):
        now = time.time()
        send_diff = now-start_send_at
        echo_diff = now-end_send_at
        send_latency = max(0, send_diff-decode_time/1000.0/1000.0)
        echo_latency = max(0, echo_diff-decode_time/1000.0/1000.0)
        log("record_latency: took %.1f ms round trip (%.1f just for echo), %.1f for decoding of %s pixels, %s bytes sent over the network in %.1f ms (%.1f ms for echo)",
                send_diff*1000, echo_diff*1000, decode_time/1000, pixels, bytecount, send_latency*1000, echo_latency*1000)
        if self.min_client_latency is None or self.min_client_latency>send_latency:
            self.min_client_latency = send_latency
        self.client_latency.append((wid, time.time(), pixels, send_latency))

    def get_damage_pixels(self, wid):
        """ returns the list of (event_time, pixelcount) for the given window id """
        return [(event_time, value) for event_time, dwid, value in list(self.damage_packet_qpixels) if dwid==wid]

    def update_averages(self):
        if len(self.client_latency)>0:
            data = [(when, latency) for _, when, _, latency in list(self.client_latency)]
            self.min_client_latency = min([x for _,x in data])
            self.avg_client_latency, self.recent_client_latency = calculate_time_weighted_average(data)
        #client ping latency: from ping packets
        if len(self.client_ping_latency)>0:
            data = list(self.client_ping_latency)
            self.min_client_ping_latency = min([x for _,x in data])
            self.avg_client_ping_latency, self.recent_client_ping_latency = calculate_time_weighted_average(data)
        #server ping latency: from ping packets
        if len(self.server_ping_latency)>0:
            data = list(self.server_ping_latency)
            self.min_server_ping_latency = min([x for _,x in data])
            self.avg_server_ping_latency, self.recent_server_ping_latency = calculate_time_weighted_average(data)

    def get_factors(self, target_latency, pixel_count):
        factors = []
        if len(self.client_latency)>0:
            #client latency: (we want to keep client latency as low as can be)
            msg = "client latency:"
            l = 0.005 + self.min_client_latency
            wm = logp(l / 0.020)
            factors.append(calculate_for_target(msg, l, self.avg_client_latency, self.recent_client_latency, aim=0.8, slope=0.005, smoothing=sqrt, weight_multiplier=wm))
        if len(self.client_ping_latency)>0:
            msg = "client ping latency:"
            l = 0.005 + self.min_client_ping_latency
            wm = logp(l / 0.050)
            factors.append(calculate_for_target(msg, l, self.avg_client_ping_latency, self.recent_client_ping_latency, aim=0.95, slope=0.005, smoothing=sqrt, weight_multiplier=wm))
        if len(self.server_ping_latency)>0:
            msg = "server ping latency:"
            l = 0.005 + self.min_server_ping_latency
            wm = logp(l / 0.050)
            factors.append(calculate_for_target(msg, l, self.avg_server_ping_latency, self.recent_server_ping_latency, aim=0.95, slope=0.005, smoothing=sqrt, weight_multiplier=wm))
        #damage packet queue size: (includes packets from all windows)
        factors.append(queue_inspect("damage packet queue size:", self.damage_packet_qsizes, smoothing=sqrt))
        #damage packet queue pixels (global):
        qpix_time_values = [(event_time, value) for event_time, _, value in list(self.damage_packet_qpixels)]
        factors.append(queue_inspect("damage packet queue pixels:", qpix_time_values, div=pixel_count, smoothing=sqrt))
        #damage data queue: (This is an important metric since each item will consume a fair amount of memory and each will later on go through the other queues.)
        factors.append(queue_inspect("damage data queue:", self.damage_data_qsizes))
        if self.mmap_size>0:
            #full: effective range is 0.0 to ~1.2
            full = 1.0-float(self.mmap_free_size)/self.mmap_size
            #aim for ~33%
            factors.append(("mmap area %s%% full" % int(100*full), logp(3*full), (3*full)**2))
        return factors

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

        add_list_stats(info, "server_ping_latency%s" % suffix, [1000.0*x for _, x in list(self.server_ping_latency)])
        add_list_stats(info, "client_ping_latency%s" % suffix, [1000.0*x for _, x in list(self.client_ping_latency)])

        #client pixels per second:
        now = time.time()
        time_limit = now-30             #ignore old records (30s)
        #pixels per second: decode time and overall
        total_pixels = 0                #total number of pixels processed
        total_time = 0                  #total decoding time
        start_time = None               #when we start counting from (oldest record)
        region_sizes = []
        for _, event_time, pixels, decode_time in list(self.client_decode_time):
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

    def __init__(self, protocol, disconnect_cb,
                 get_transient_for,
                 supports_mmap,
                 supports_speaker, supports_microphone,
                 speaker_codecs, microphone_codecs,
                 default_quality, default_min_quality,
                 default_speed, default_min_speed):
        self.close_event = Event()
        self.ordinary_packets = []
        self.protocol = protocol
        self.disconnect = disconnect_cb
        self.get_transient_for = get_transient_for
        # mmap:
        self.supports_mmap = supports_mmap
        self.mmap = None
        self.mmap_size = 0
        # sound:
        self.supports_speaker = supports_speaker
        self.speaker_codecs = speaker_codecs
        self.supports_microphone = supports_microphone
        self.microphone_codecs = microphone_codecs
        self.sound_source = None
        self.sound_sink = None

        self.default_quality = default_quality      #default encoding quality for lossy encodings
        self.default_min_quality = default_min_quality #default minimum encoding quality
        self.default_speed = default_speed          #encoding speed (only used by x264)
        self.default_min_speed = default_min_speed  #default minimum encoding speed
        self.encoding = None                        #the default encoding for all windows
        self.encodings = []                         #all the encodings supported by the client
        self.encoding_options = {}
        self.default_batch_config = DamageBatchConfig()
        self.default_encoding_options = {}

        self.window_sources = {}                    #WindowSource for each Window ID
        self.window_metdata_cache = {}

        self.uuid = ""
        self.hostname = ""
        # client capabilities/options:
        self.client_type = None
        self.client_version = None
        self.client_platform = None
        self.client_machine = None
        self.client_processor = None
        self.client_release = None
        self.png_window_icons = False
        self.auto_refresh_delay = 0
        self.server_window_resize = False
        self.send_cursors = False
        self.send_bell = False
        self.send_notifications = False
        self.send_windows = True
        self.randr_notify = False
        self.named_cursors = False
        self.clipboard_enabled = False
        self.clipboard_notifications = False
        self.share = False
        self.desktop_size = None
        self.screen_sizes = []
        self.raw_window_icons = False
        self.system_tray = False
        #sound props:
        self.pulseaudio_id = None
        self.pulseaudio_server = None
        self.sound_decoders = []
        self.sound_encoders = []

        self.keyboard_config = None
        self.cursor_data = None
        self.send_cursor_pending = False

        # the queues of damage requests we work through:
        self.damage_data_queue = Queue()           #holds functions to call to process damage data
                                                    #items placed in this queue are picked off by the "data_to_packet" thread,
                                                    #the functions should add the packets they generate to the 'damage_packet_queue'
        self.damage_packet_queue = deque()         #holds actual packets ready for sending (already encoded)
                                                    #these packets are picked off by the "protocol" via 'next_packet()'
                                                    #format: packet, wid, pixels, start_send_cb, end_send_cb
        #these statistics are shared by all WindowSource instances:
        self.statistics = GlobalPerformanceStatistics()
        self.last_user_event = time.time()
        # ready for processing:
        protocol.set_packet_source(self.next_packet)
        self.datapacket_thread = make_daemon_thread(self.data_to_packet, "encode")
        self.datapacket_thread.start()
        self.calculate_window_ids = set()
        self.calculate_event = Event()
        self.calculate_thread = make_daemon_thread(self.calculate_delay_thread, "calculate_delay")
        self.calculate_thread.start()

    def __str__(self):
        return  "ServerSource(%s)" % self.protocol

    def is_closed(self):
        return self.close_event.isSet()

    def calculate_delay_thread(self):
        try:
            self.do_calculate_delay_thread()
        except:
            if not self.is_closed():
                log.error("error in calculate thread!", exc_info=True)

    def do_calculate_delay_thread(self):
        """ calls update_averages() on ServerSource.statistics (GlobalStatistics)
            and WindowSource.statistics (WindowPerformanceStatistics) for each window id in calculate_window_ids,
            no more often than every RECALCULATE_DELAY
        """
        RECALCULATE_DELAY = 0.250           #250ms
        AFTER_EACH_WINDOW_WAIT = 0.010      #10ms
        INITIAL_WAIT = 0.025                #25ms
        while not self.is_closed():
            self.calculate_event.wait()
            if self.is_closed():
                return
            wait_time = RECALCULATE_DELAY-INITIAL_WAIT
            self.close_event.wait(INITIAL_WAIT)     #give time for the source/windows to disappear
            if self.is_closed():
                return
            self.statistics.update_averages()
            wids = list(self.calculate_window_ids)  #make a copy so we don't clobber new wids
            for wid in wids:
                self.calculate_window_ids.remove(wid)
                ws = self.window_sources.get(wid)
                if ws is None:
                    continue
                try:
                    ws.statistics.update_averages()
                    ws.calculate_batch_delay()
                    ws.update_video_encoder()
                except:
                    log.error("error on window %s", wid, exc_info=True)
                wait_time -= AFTER_EACH_WINDOW_WAIT
                self.close_event.wait(AFTER_EACH_WINDOW_WAIT)
                if self.is_closed():
                    return
            #calculate weighted average as new global default delay:
            now = time.time()
            wdimsum, wdelay = 0, 0
            for ws in list(self.window_sources.values()):
                if ws.batch_config.last_updated<=0:
                    continue
                w, h = ws.window_dimensions
                time_w = 2.0+(now-ws.batch_config.last_updated)     #add 2 seconds to even things out
                weight = w*h*time_w
                wdelay += ws.batch_config.delay*weight
                wdimsum += weight
            if wdimsum>0:
                delay = wdelay / wdimsum
                self.default_batch_config.last_delays.append((now, delay))
                self.default_batch_config.delay = delay
            self.calculate_event.clear()
            if wait_time>0:
                #wait before trying to run again:
                self.close_event.wait(wait_time)

    def may_recalculate(self, wid):
        self.calculate_window_ids.add(wid)
        self.calculate_event.set()

    def close(self):
        self.close_event.set()
        self.calculate_event.set()
        self.damage_data_queue.put(None, block=False)
        for window_source in self.window_sources.values():
            window_source.cleanup()
        self.window_sources = {}
        self.window_metdata_cache = {}
        self.close_mmap()
        self.stop_sending_sound()
        if self.protocol:
            self.protocol.close()
            self.protocol = None

    def user_event(self):
        self.last_user_event = time.time()

    def parse_hello(self, capabilities):
        #batch options:
        def batch_value(prop, default, minv=None, maxv=None):
            assert default is not None
            def parse_batch_int(value, varname):
                if value is not None:
                    try:
                        return int(value)
                    except:
                        log.error("invalid value for batch option %s: %s", varname, value)
                return None
            #from client caps first:
            cpname = "batch.%s" % prop
            v = parse_batch_int(capabilities.get(cpname), cpname)
            #try env:
            if v is None:
                evname = "XPRA_BATCH_%s" % prop.upper()
                v = parse_batch_int(os.environ.get(evname), evname)
            #fallback to default:
            if v is None:
                v = default
            if minv is not None:
                v = max(minv, v)
            if maxv is not None:
                v = min(maxv, v)
            assert v is not None
            return v
        self.default_batch_config = DamageBatchConfig()
        self.default_batch_config.always = bool(batch_value("always", DamageBatchConfig.ALWAYS))
        self.default_batch_config.min_delay = batch_value("min_delay", DamageBatchConfig.MIN_DELAY, 0, 1000)
        self.default_batch_config.max_delay = batch_value("max_delay", DamageBatchConfig.MAX_DELAY, 1, 15000)
        self.default_batch_config.max_events = batch_value("max_events", DamageBatchConfig.MAX_EVENTS)
        self.default_batch_config.max_pixels = batch_value("max_pixels", DamageBatchConfig.MAX_PIXELS)
        self.default_batch_config.time_unit = batch_value("time_unit", DamageBatchConfig.TIME_UNIT, 1)
        self.default_batch_config.delay = batch_value("delay", DamageBatchConfig.START_DELAY, 0)
        log.debug("default batch config: %s", self.default_batch_config)
        #client uuid:
        self.uuid = capabilities.get("uuid", "")
        self.hostname = capabilities.get("hostname", "")
        self.client_type = capabilities.get("client_type", "PyGTK")
        self.client_platform = capabilities.get("platform", "")
        self.client_machine = capabilities.get("platform.machine", "")
        self.client_processor = capabilities.get("platform.processor", "")
        self.client_release = capabilities.get("platform.release", "")
        self.client_version = capabilities.get("version", None)
        #general features:
        self.send_windows = capabilities.get("windows", True)
        self.server_window_resize = capabilities.get("server-window-resize", False)
        self.send_cursors = self.send_windows and capabilities.get("cursors", False)
        self.send_bell = capabilities.get("bell", False)
        self.send_notifications = capabilities.get("notifications", False)
        self.randr_notify = capabilities.get("randr_notify", False)
        self.clipboard_enabled = capabilities.get("clipboard", True)
        self.clipboard_notifications = capabilities.get("clipboard.notifications", False)
        self.share = capabilities.get("share", False)
        self.desktop_size = capabilities.get("desktop_size")
        self.set_screen_sizes(capabilities.get("screen_sizes"))
        self.named_cursors = capabilities.get("named_cursors", False)
        self.raw_window_icons = capabilities.get("raw_window_icons", False)
        self.system_tray = capabilities.get("system_tray", False)
        #encoding options (filter):
        #1: these properties are special cased here because we
        #defined their name before the "encoding." prefix convention:
        for k,ek in {"initial_quality"          : "initial_quality",
                     "rgb24zlib"                : "rgb24zlib",
                     "encoding_client_options"  : "client_options",
                     "quality"                  : "quality",
                     }.items():
            if k in capabilities:
                self.encoding_options[ek] = capabilities.get(k)
        #2: standardized encoding options:
        for k, v in capabilities.items():
            if k.startswith("encoding."):
                k = k[len("encoding."):]
                self.encoding_options[k] = v
        log("encoding options: %s", self.encoding_options)
        #encodings:
        self.encodings = capabilities.get("encodings", [])
        self.set_encoding(capabilities.get("encoding", None), None)
        q = self.default_quality
        if "jpeg" in capabilities:      #pre 0.7 versions
            q = capabilities["jpeg"]
        if "quality" in self.encoding_options:   #0.7 onwards:
            q = self.encoding_options["quality"]
        if q>0:
            self.default_encoding_options["quality"] = q
        mq = self.default_min_quality
        if "min-quality" in self.encoding_options:
            mq = self.encoding_options["min-quality"]
        if mq>0:
            self.default_encoding_options["min-quality"] = mq
        s = self.default_speed
        if "speed" in self.encoding_options:
            s = self.encoding_options["speed"]
        if s>0:
            self.default_encoding_options["speed"] = s
        ms = self.default_min_speed
        if "min-speed" in self.encoding_options:
            ms = self.encoding_options["min-speed"]
        if ms>0:
            self.default_encoding_options["min-speed"] = ms
        log("default encoding options: %s", self.default_encoding_options)
        self.png_window_icons = "png" in self.encodings and "png" in ENCODINGS
        self.auto_refresh_delay = int(capabilities.get("auto_refresh_delay", 0))
        elog = log
        if os.environ.get("XPRA_ENCODING_DEBUG", "0")!="0":
            elog = log.info
        elog("encoding_options: %s", self.encoding_options)
        #keyboard:
        try:
            from xpra.server_keyboard_config import KeyboardConfig
            self.keyboard_config = KeyboardConfig()
            self.keyboard_config.enabled = self.send_windows and bool(capabilities.get("keyboard", True))
            self.assign_keymap_options(capabilities)
            self.keyboard_config.xkbmap_layout = capabilities.get("xkbmap_layout")
            self.keyboard_config.xkbmap_variant = capabilities.get("xkbmap_variant")
        except ImportError, e:
            log.error("failed to load keyboard support: %s", e)
            self.keyboard_config = None
        #mmap:
        if self.send_windows:
            #we don't need mmap if not sending pixels
            mmap_file = capabilities.get("mmap_file")
            mmap_token = capabilities.get("mmap_token")
            log("client supplied mmap_file=%s, mmap supported=%s", mmap_file, self.supports_mmap)
            if self.supports_mmap and mmap_file and os.path.exists(mmap_file):
                self.init_mmap(mmap_file, mmap_token)
        log("cursors=%s, bell=%s, notifications=%s", self.send_cursors, self.send_bell, self.send_notifications)
        log("client uuid %s", self.uuid)
        msg = "%s %s client version %s" % (self.client_type, platform_name(self.client_platform, self.client_release), self.client_version)
        if self.hostname:
            msg += " connected from '%s'" % self.hostname
        log.info(msg)
        if self.send_windows:
            if self.mmap_size>0:
                log.info("mmap is enabled using %sB area in %s", std_unit(self.mmap_size, unit=1024), mmap_file)
            else:
                log.info("using %s as primary encoding", self.encoding)
        else:
            log.info("windows forwarding is disabled")
        #sound stuff:
        self.pulseaudio_id = capabilities.get("sound.pulseaudio.id")
        self.pulseaudio_server = capabilities.get("sound.pulseaudio.server")
        self.sound_decoders = capabilities.get("sound.decoders", [])
        self.sound_encoders = capabilities.get("sound.encoders", [])
        self.sound_receive = capabilities.get("sound.receive", False)
        self.sound_send = capabilities.get("sound.send", False)

    def start_sending_sound(self):
        assert self.supports_speaker, "cannot send sound: support not enabled on the server"
        assert self.sound_source is None, "a sound source already exists"
        assert self.sound_receive, "cannot send sound: support is not enabled on the client"
        try:
            from xpra.sound.gstreamer_util import start_sending_sound
            self.sound_source = start_sending_sound(self.sound_decoders, self.microphone_codecs, self.pulseaudio_server, self.pulseaudio_id)
            if self.sound_source:
                self.sound_source.connect("new-buffer", self.new_sound_buffer)
                self.sound_source.start()
        except Exception, e:
            log.error("error setting up sound: %s", e)

    def stop_sending_sound(self):
        if self.sound_source:
            self.sound_source.stop()
            self.sound_source.cleanup()
            self.sound_source = None

    def new_sound_buffer(self, sound_source, data, metadata):
        assert self.sound_source
        self.send("sound-data", self.sound_source.codec, Compressed(self.sound_source.codec, data), metadata)

    def sound_control(self, action, *args):
        if action=="stop":
            self.stop_sending_sound()
        elif action=="start":
            self.start_sending_sound()
        #elif action=="quality":
        #    assert self.sound_source
        #    quality = args[0]
        #    self.sound_source.set_quality(quality)
        #    self.start_sending_sound()
        else:
            log.error("unknown sound action: %s", action)

    def sound_data(self, codec, data, metadata, *args):
        if self.sound_sink is not None and codec!=self.sound_sink.codec:
            log.info("sound codec changed from %s to %s", self.sound_sink.codec, codec)
            self.sound_sink.stop()
            self.sound_sink.cleanup()
            self.sound_sink = None
        if not self.sound_sink:
            try:
                from xpra.sound.sink import SoundSink
                self.sound_sink = SoundSink(codec=codec)
                self.sound_sink.start()
            except Exception, e:
                log.error("failed to setup sound: %s", e)
                return
        self.sound_sink.add_data(data, metadata)

    def set_screen_sizes(self, screen_sizes):
        self.screen_sizes = screen_sizes or []
        log("client screen sizes: %s", screen_sizes)

    # Takes the name of a WindowModel property, and returns a dictionary of
    # xpra window metadata values that depend on that property
    # (this method just caches the results, see do_make_metadata)
    def _make_metadata(self, wid, window, propname):
        cache = self.window_metdata_cache.setdefault(wid, {})
        if len(cache)==0:
            #these never change and are never queried,
            #but we want to report on them via "xpra info",
            #so populate them here
            cache["override-redirect"] = window.is_OR()
            cache["tray"] = window.is_tray()
            try:
                from wimpiggy.lowlevel import get_xwindow       #@UnresolvedImport
                cache["xid"] = hex(get_xwindow(window.client_window))
            except:
                pass
        props = self.do_make_metadata(window, propname)
        cache.update(props)
        return props

    def do_make_metadata(self, window, propname):
        if propname == "title":
            title = window.get_property("title")
            if title is None:
                return {}
            return {"title": title.encode("utf-8")}
        elif propname == "modal":
            return {"modal" : window.get_property("modal")}
        elif propname == "pid":
            return {"pid" : window.get_property("pid") or -1}
        elif propname == "size-hints":
            hints_metadata = {}
            hints = window.get_property("size-hints")
            if hints is not None:
                for attr, metakey in [
                    ("max_size", "maximum-size"),
                    ("min_size", "minimum-size"),
                    ("base_size", "base-size"),
                    ("resize_inc", "increment"),
                    ("min_aspect_ratio", "minimum-aspect-ratio"),
                    ("max_aspect_ratio", "maximum-aspect-ratio"),
                    ]:
                    v = getattr(hints, attr)
                    if v is not None:
                        hints_metadata[metakey] = v
            return {"size-constraints": hints_metadata}
        elif propname == "class-instance":
            c_i = window.get_property("class-instance")
            if c_i is None:
                return {}
            return {"class-instance": [x.encode("utf-8") for x in c_i]}
        elif propname == "icon":
            surf = window.get_property("icon")
            if surf is None:
                return {}
            return {"icon": self.make_window_icon(surf.get_data(), surf.get_format(), surf.get_stride(), surf.get_width(), surf.get_height())}
        elif propname == "client-machine":
            client_machine = window.get_property("client-machine")
            if client_machine is None:
                import socket
                client_machine = socket.gethostname()
                if client_machine is None:
                    return {}
            return {"client-machine": client_machine.encode("utf-8")}
        elif propname == "transient-for":
            wid = self.get_transient_for(window)
            if wid:
                return {"transient-for" : wid}
            return {}
        elif propname == "window-type":
            window_types = window.get_property("window-type")
            assert window_types is not None, "window-type is not defined for %s" % window
            log("window_types=%s", window_types)
            wts = []
            for window_type in window_types:
                wts.append(str(window_type))
            log("window_types=%s", wts)
            return {"window-type" : wts}
        raise Exception("unhandled property name: %s" % propname)


    def make_window_icon(self, pixel_data, pixel_format, stride, w, h):
        log("found new window icon: %sx%s, sending as png=%s", w, h, self.png_window_icons)
        if self.png_window_icons:
            import Image
            img = Image.frombuffer("RGBA", (w,h), pixel_data, "raw", "BGRA", 0, 1)
            MAX_SIZE = 64
            if w>MAX_SIZE or h>MAX_SIZE:
                #scale icon down
                if w>=h:
                    h = int(h*MAX_SIZE/w)
                    w = MAX_SIZE
                else:
                    w = int(w*MAX_SIZE/h)
                    h = MAX_SIZE
                log("scaling window icon down to %sx%s", w, h)
                img = img.resize((w,h), Image.ANTIALIAS)
            output = StringIO()
            img.save(output, 'PNG')
            raw_data = output.getvalue()
            output.close()
            return w, h, "png", str(raw_data)
        import cairo
        assert pixel_format == cairo.FORMAT_ARGB32
        assert stride == 4 * w
        return w, h, "premult_argb32", str(pixel_data)

#
# Keyboard magic
#
    def set_layout(self, layout, variant):
        if layout!=self.keyboard_config.xkbmap_layout or variant!=self.keyboard_config.xkbmap_variant:
            self.keyboard_config.xkbmap_layout = layout
            self.keyboard_config.xkbmap_variant = variant
            return True
        return False

    def assign_keymap_options(self, props):
        """ used by both process_hello and process_keymap
            to set the keyboard attributes """
        modded = False
        for x in ["xkbmap_print", "xkbmap_query", "xkbmap_mod_meanings",
                  "xkbmap_mod_managed", "xkbmap_mod_pointermissing",
                  "xkbmap_keycodes", "xkbmap_x11_keycodes"]:
            cv = getattr(self.keyboard_config, x)
            nv = props.get(x)
            if cv!=nv:
                setattr(self.keyboard_config, x, nv)
                modded = True
        return modded

    def keys_changed(self):
        if self.keyboard_config:
            self.keyboard_config.compute_modifier_map()
            self.keyboard_config.compute_modifier_keynames()

    def make_keymask_match(self, modifier_list, ignored_modifier_keycode=None, ignored_modifier_keynames=None):
        if self.keyboard_config and self.keyboard_config.enabled:
            self.keyboard_config.make_keymask_match(modifier_list, ignored_modifier_keycode, ignored_modifier_keynames)

    def set_keymap(self, current_keyboard_config, keys_pressed, force):
        if self.keyboard_config and self.keyboard_config.enabled:
            current_id = None
            if current_keyboard_config and current_keyboard_config.enabled:
                current_id = current_keyboard_config.get_hash()
            keymap_id = self.keyboard_config.get_hash()
            log("current keyboard id=%s, new keyboard id=%s", current_id, keymap_id)
            if force or current_id is None or keymap_id!=current_id:
                self.keyboard_config.keys_pressed = keys_pressed
                self.keyboard_config.set_keymap(self.client_platform)
                current_keyboard_config = self.keyboard_config
            else:
                log.info("keyboard mapping already configured (skipped)")
                self.keyboard_config = current_keyboard_config
        return current_keyboard_config

    def get_keycode(self, client_keycode, keyname, modifiers):
        if self.keyboard_config is None or not self.keyboard_config.enabled:
            log.info("ignoring keycode since keyboard is turned off")
            return -1
        server_keycode = self.keyboard_config.keycode_translation.get((client_keycode, keyname))
        if server_keycode is None:
            if self.keyboard_config.is_native_keymap:
                #native: assume no translation for this key
                server_keycode = client_keycode
            else:
                #non-native: try harder to find matching keysym
                server_keycode = self.keyboard_config.keycode_translation.get(keyname, client_keycode)
        return server_keycode


#
# Functions for interacting with the network layer:
#
    def next_packet(self):
        """ Called by protocol.py when it is ready to send the next packet """
        packet, start_send_cb, end_send_cb, have_more = None, None, None, False
        if not self.is_closed():
            if len(self.ordinary_packets)>0:
                packet = self.ordinary_packets.pop(0)
            elif len(self.damage_packet_queue)>0:
                packet, _, _, start_send_cb, end_send_cb = self.damage_packet_queue.popleft()
            have_more = packet is not None and (len(self.ordinary_packets)>0 or len(self.damage_packet_queue)>0)
        return packet, start_send_cb, end_send_cb, have_more

    def send(self, *parts):
        """ This method queues non-damage packets (higher priority) """
        self.ordinary_packets.append(parts)
        p = self.protocol
        if p:
            p.source_has_more()

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
        if HAS_SOUND:
            try:
                from xpra.sound.pulseaudio_util import add_pulseaudio_capabilities
                add_pulseaudio_capabilities(capabilities)
                from xpra.sound.gstreamer_util import add_gst_capabilities
                add_gst_capabilities(capabilities,
                                     receive=self.supports_microphone, send=self.supports_speaker,
                                     receive_codecs=self.speaker_codecs, send_codecs=self.microphone_codecs)
                log("sound capabilities: %s", [(k,v) for k,v in capabilities.items() if k.startswith("sound.")])
            except Exception, e:
                log.error("failed to setup sound: %s", e)
        capabilities["encoding"] = self.encoding
        capabilities["mmap_enabled"] = self.mmap_size>0
        if self.keyboard_config:
            capabilities["modifier_keycodes"] = self.keyboard_config.modifier_client_keycodes
        capabilities["auto_refresh_delay"] = self.auto_refresh_delay
        self.send("hello", capabilities)

    def add_info(self, info, suffix=""):
        info["client_clipboard%s" % suffix] = self.clipboard_enabled
        info["client_cursors%s" % suffix] = self.send_cursors
        info["client_bell%s" % suffix] = self.send_bell
        info["client_notifications%s" % suffix] = self.send_notifications
        info["client_idle_time%s" % suffix] = int(time.time()-self.last_user_event)
        info["client_hostname%s" % suffix] = self.hostname
        for x in ("machine", "processor", "release"):
            info["client.platform.%s%s" % (x, suffix)] = getattr(self, "client_%s" % x)
        info["auto_refresh%s" % suffix] = self.auto_refresh_delay
        for k,v in self.encoding_options.items():
            info["encoding.%s" % k] = v
        for k,v in self.default_encoding_options.items():
            info["encoding.%s" % k] = v
        def get_sound_state(supported, prop):
            if not supported:
                return "disabled"
            if prop is None:
                return "inactive"
            return prop.get_state()
        state = get_sound_state(self.supports_speaker, self.sound_source)
        info["speaker.state"] = state
        if state=="active":
            info["speaker.codec"] = self.sound_source.codec
            info["speaker.codec_description"] = self.sound_source.codec_description
            bitrate = self.sound_source.get_bitrate()
            if bitrate>0:
                info["speaker.bitrate"] = bitrate
        state = get_sound_state(self.supports_microphone, self.sound_sink)
        info["microphone.state"] = state
        if state=="active":
            info["microphone.codec"] = self.sound_sink.codec
            info["microphone.codec_description"] = self.sound_sink.codec_description
            bitrate = self.sound_sink.get_bitrate()
            if bitrate>0:
                info["microphone.bitrate"] = bitrate

    def send_info_response(self, info):
        self.send("info-response", info)

    def send_clipboard(self, packet):
        if self.clipboard_enabled:
            self.send(*packet)

    def send_cursor(self, cursor_data):
        if not self.send_cursors:
            return
        self.cursor_data = cursor_data
        if not self.send_cursor_pending:
            self.send_cursor_pending = True
            delay = max(10, int(self.default_batch_config.delay*4))
            gobject.timeout_add(delay, self.do_send_cursor)

    def do_send_cursor(self):
        self.send_cursor_pending = False
        if self.cursor_data:
            #only newer versions support cursor names:
            if not self.named_cursors:
                self.cursor_data = self.cursor_data[:8]
            self.send("cursor", *self.cursor_data)
        else:
            self.send("cursor", "")

    def bell(self, wid, device, percent, pitch, duration, bell_class, bell_id, bell_name):
        if self.send_bell:
            self.send("bell", wid, device, percent, pitch, duration, bell_class, bell_id, bell_name)

    def notify(self, dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout):
        if self.send_notifications:
            self.send("notify_show", dbus_id, int(nid), str(app_name), int(replaces_nid), str(app_icon), str(summary), str(body), int(expire_timeout))

    def notify_close(self, nid):
        if self.send_notifications:
            self.send("notify_close", nid)

    def set_deflate(self, level):
        self.send("set_deflate", level)

    def ping(self):
        #NOTE: all ping time/echo time/load avg values are in milliseconds
        now_ms = int(1000*time.time())
        log("sending ping to %s with time=%s", self.protocol, now_ms)
        self.send("ping", now_ms)
        timeout = 60
        def check_echo_timeout(*args):
            if self.last_ping_echoed_time<now_ms and not self.is_closed():
                self.disconnect("client ping timeout, - waited %s seconds without a response" % timeout)
        gobject.timeout_add(timeout*1000, check_echo_timeout)

    def process_ping(self, time_to_echo):
        #send back the load average:
        try:
            (fl1, fl2, fl3) = os.getloadavg()
            l1,l2,l3 = int(fl1*1000), int(fl2*1000), int(fl3*1000)
        except:
            l1,l2,l3 = 0,0,0
        #and the last client ping latency we measured (if any):
        if len(self.statistics.client_ping_latency)>0:
            _, cl = self.statistics.client_ping_latency[-1]
            cl = int(1000.0*cl)
        else:
            cl = -1
        self.send("ping_echo", time_to_echo, l1, l2, l3, cl)
        #if the client is pinging us, ping it too:
        gobject.timeout_add(500, self.ping)

    def process_ping_echo(self, packet):
        echoedtime, l1, l2, l3, server_ping_latency = packet[1:6]
        self.last_ping_echoed_time = echoedtime
        client_ping_latency = time.time()-echoedtime/1000.0
        self.statistics.client_ping_latency.append((time.time(), client_ping_latency))
        self.client_load = l1, l2, l3
        if server_ping_latency>=0:
            self.statistics.server_ping_latency.append((time.time(), server_ping_latency/1000.0))
        log("ping echo client load=%s, measured server latency=%s", self.client_load, server_ping_latency)

    def updated_desktop_size(self, root_w, root_h, max_w, max_h):
        if self.randr_notify:
            self.send("desktop_size", root_w, root_h, max_w, max_h)

    def or_window_geometry(self, wid, window, x, y, w, h):
        if not self.can_send_window(window):
            return
        self.send("configure-override-redirect", wid, x, y, w, h)

    def window_metadata(self, wid, window, prop):
        if not self.can_send_window(window):
            return
        if prop=="icon" and self.raw_window_icons:
            self.send_window_icon(window, wid)
        else:
            metadata = self._make_metadata(wid, window, prop)
            if len(metadata)>0:
                self.send("window-metadata", wid, metadata)

    def can_send_window(self, window):
        if not self.send_windows and not window.is_tray():
            return  False
        if window.is_tray() and not self.system_tray:
            return  False
        return True

    def new_tray(self, wid, window, w, h):
        assert window.is_tray()
        if not self.can_send_window(window):
            return
        self.send("new-tray", wid, w, h)

    def new_window(self, ptype, wid, window, x, y, w, h, properties, client_properties):
        if not self.can_send_window(window):
            return
        send_props = list(properties)
        send_raw_icon = self.raw_window_icons and "icon" in properties
        if send_raw_icon:
            send_props.remove("icon")
        metadata = {}
        for propname in send_props:
            metadata.update(self._make_metadata(wid, window, propname))
        log("new_window(%s, %s, %s, %s, %s, %s, %s, %s, %s) metadata=%s", ptype, window, wid, x, y, w, h, properties, client_properties, metadata)
        self.send(ptype, wid, x, y, w, h, metadata, client_properties or {})
        if send_raw_icon:
            self.send_window_icon(wid, window)

    def send_window_icon(self, wid, window):
        surf = window.get_property("icon")
        log("send_window_icon(%s,%s) icon=%s", window, wid, surf)
        if surf is not None:
            w, h, pixel_format, pixel_data = self.make_window_icon(surf.get_data(), surf.get_format(), surf.get_stride(), surf.get_width(), surf.get_height())
            assert pixel_format in ("premult_argb32", "png")
            if pixel_format=="premult_argb32":
                data = zlib_compress("rgb24", pixel_data)
            else:
                data = Compressed("png", pixel_data)
            self.send("window-icon", wid, w, h, pixel_format, data)

    def lost_window(self, wid, window):
        if not self.can_send_window(window):
            return
        self.send("lost-window", wid)

    def resize_window(self, wid, window, ww, wh):
        """
        The server detected that the application window has been resized,
        we forward it if the client supports this type of event.
        """
        if not self.can_send_window(window):
            return
        if self.server_window_resize:
            self.send("window-resized", wid, ww, wh)

    def cancel_damage(self, wid, window):
        """
        Use this method to cancel all currently pending and ongoing
        damage requests for a window.
        """
        if not self.can_send_window(window):
            return
        ws = self.window_sources.get(wid)
        if ws:
            ws.cancel_damage()

    def remove_window(self, wid, window):
        """ The given window is gone, ensure we free all the related resources """
        if not self.can_send_window(window):
            return
        ws = self.window_sources.get(wid)
        if ws:
            del self.window_sources[wid]
            ws.cleanup()
        if wid in self.window_metdata_cache:
            del self.window_metdata_cache[wid]

    def add_stats(self, info, window_ids=[], suffix=""):
        """
            Adds most of the statistics available to the 'info' dict passed in.
            This is used by server.py to provide those statistics to clients
            via the 'xpra info' command.
        """
        info["client_type%s" % suffix] = self.client_type
        info["client_version%s" % suffix] = self.client_version or "unknown"
        info["client_uuid%s" % suffix] = self.uuid
        info["keyboard%s" % suffix] = self.keyboard_config.enabled
        try:
            info["client_connection%s" % suffix] = str(self.protocol._conn.target or self.protocol._conn.filename)
        except:
            pass
        info["client_encodings%s" % suffix] = ",".join(self.encodings)
        info["damage_data_queue_size%s.current" % suffix] = self.damage_data_queue.qsize()
        info["damage_packet_queue_size%s.current" % suffix] = len(self.damage_packet_queue)
        qpixels = [x[2] for x in list(self.damage_packet_queue)]
        add_list_stats(info, "damage_packet_queue_pixels%s" % suffix,  qpixels)
        if len(qpixels)>0:
            info["damage_packet_queue_pixels%s.current" % suffix] = qpixels[-1]

        self.protocol.add_stats(info, suffix=suffix)
        self.statistics.add_stats(info, suffix=suffix)
        if len(window_ids)>0:
            total_pixels = 0
            total_time = 0.0
            in_latencies = []
            out_latencies = []
            for wid in window_ids:
                ws = self.window_sources.get(wid)
                if ws:
                    #per-window stats:
                    metadata = self.window_metdata_cache.get(wid)
                    ws.add_stats(info, metadata, suffix=suffix)
                    #collect stats for global averages:
                    for _, pixels, _, encoding_time in list(ws.statistics.encoding_stats):
                        total_pixels += pixels
                        total_time += encoding_time
                    in_latencies += [x*1000 for _, _, _, x in list(ws.statistics.damage_in_latency)]
                    out_latencies += [x*1000 for _, _, _, x in list(ws.statistics.damage_out_latency)]
            v = 0
            if total_time>0:
                v = int(total_pixels / total_time)
            info["pixels_encoded_per_second%s" % suffix] = v
            add_list_stats(info, "damage_in_latency",  in_latencies, show_percentile=[9])
            add_list_stats(info, "damage_out_latency",  out_latencies, show_percentile=[9])

        if len(self.default_batch_config.last_delays)>0:
            batch_delays = [x for _,x in list(self.default_batch_config.last_delays)]
            add_list_stats(info, "batch_delay%s" % suffix, batch_delays)

    def update_video_encoders(self):
        for ws in self.window_sources.values():
            ws.update_video_encoder()

    def set_min_quality(self, min_quality):
        self.default_encoding_options["min-quality"] = min_quality
        self.update_video_encoders()

    def set_quality(self, quality):
        if quality<=0:
            if "quality" in self.default_encoding_options:
                del self.default_encoding_options["quality"]
        else:
            self.default_encoding_options["quality"] = max(quality, self.default_encoding_options.get("min-quality", 0))
        self.update_video_encoders()

    def set_min_speed(self, min_speed):
        self.default_encoding_options["min-speed"] = min_speed
        self.update_video_encoders()

    def set_speed(self, speed):
        if speed<=0:
            if "speed" in self.default_encoding_options:
                del self.default_encoding_options["speed"]
        else:
            self.default_encoding_options["speed"] = max(speed, self.default_encoding_options.get("min-speed", 0))
        self.update_video_encoders()

    def refresh(self, wid, window, opts):
        if not self.can_send_window(window):
            return
        self.cancel_damage(wid, window)
        w, h = window.get_dimensions()
        self.damage(wid, window, 0, 0, w, h, opts)

    def damage(self, wid, window, x, y, w, h, options=None):
        """
            Main entry point from the window manager,
            we dispatch to the WindowSource for this window id
            (creating a new one if needed)
        """
        if not self.can_send_window(window):
            return
        if options is None or options.get("calculate", True):
            self.may_recalculate(wid)
        assert window is not None
        damage_options = {}
        if options:
            damage_options = options.copy()
        self.statistics.damage_last_events.append((wid, time.time(), w*h))
        ws = self.window_sources.get(wid)
        if ws is None:
            batch_config = self.default_batch_config.clone()
            batch_config.wid = wid
            ws = WindowSource(self.queue_damage, self.queue_packet, self.statistics,
                              wid, batch_config, self.auto_refresh_delay,
                              self.encoding, self.encodings, self.encoding_options,
                              self.default_encoding_options,
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
        if not self.send_windows:
            log.error("client_ack_damage when we don't send any window data!?")
            return
        if decode_time>0:
            self.statistics.client_decode_time.append((wid, time.time(), width*height, decode_time))
        ws = self.window_sources.get(wid)
        if ws:
            ws.damage_packet_acked(damage_packet_sequence, width, height, decode_time)
            self.may_recalculate(wid)

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
            Note: this code runs in the non-ui thread
        """
        now = time.time()
        self.statistics.damage_packet_qsizes.append((now, len(self.damage_packet_queue)))
        self.statistics.damage_packet_qpixels.append((now, wid, sum([x[2] for x in list(self.damage_packet_queue) if x[1]==wid])))
        self.damage_packet_queue.append((packet, wid, pixels, start_send_cb, end_send_cb))
        #if self.protocol._write_queue.empty():
        p = self.protocol
        if p:
            p.source_has_more()

#
# The damage packet thread loop:
#
    def data_to_packet(self):
        """
            This runs in a separate thread and calls all the function callbacks
            which are added to the 'damage_data_queue'.
        """
        while not self.is_closed():
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
                log("using client supplied mmap file=%s, size=%s", mmap_file, self.mmap_size)
                self.statistics.mmap_size = self.mmap_size
        except Exception, e:
            log.error("cannot use mmap file '%s': %s", mmap_file, e)
            self.close_mmap()

    def close_mmap(self):
        if self.mmap:
            self.mmap.close()
            self.mmap = None
        self.mmap_size = 0
