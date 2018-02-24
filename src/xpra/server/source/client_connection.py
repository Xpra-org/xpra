# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from collections import deque
from threading import Event
from math import sqrt
from time import sleep

from xpra.log import Logger
log = Logger("server")
elog = Logger("encoding")
keylog = Logger("keyboard")
mouselog = Logger("mouse")
cursorlog = Logger("cursor")
metalog = Logger("metadata")
timeoutlog = Logger("timeout")
proxylog = Logger("proxy")
avsynclog = Logger("av-sync")
statslog = Logger("stats")
notifylog = Logger("notify")
netlog = Logger("network")
bandwidthlog = Logger("bandwidth")


from xpra.server.source.source_stats import GlobalPerformanceStatistics
from xpra.server.source.audio_mixin import AudioMixin
from xpra.server.source.mmap_connection import MMAP_Connection
from xpra.server.source.fileprint_mixin import FilePrintMixin
from xpra.server.source.clipboard_connection import ClipboardConnection
from xpra.server.source.networkstate_mixin import NetworkStateMixin
from xpra.server.source.clientinfo_mixin import ClientInfoMixin
from xpra.server.source.dbus_mixin import DBUS_Mixin
from xpra.server.window.window_video_source import WindowVideoSource
from xpra.server.window.batch_config import DamageBatchConfig
from xpra.server.window.metadata import make_window_metadata
from xpra.simple_stats import get_list_stats
from xpra.codecs.video_helper import getVideoHelper
from xpra.codecs.codec_constants import video_spec
from xpra.net import compression
from xpra.net.compression import compressed_wrapper, Compressed
from xpra.make_thread import start_thread
from xpra.os_util import Queue, monotonic_time, BytesIOClass, strtobytes
from xpra.server.background_worker import add_work_item
from xpra.util import csv, typedict, merge_dicts, flatten_dict, notypedict, get_screen_info, envint, envbool, AtomicInteger, \
                    DEFAULT_METADATA_SUPPORTED, XPRA_BANDWIDTH_NOTIFICATION_ID, XPRA_IDLE_NOTIFICATION_ID

NOYIELD = not envbool("XPRA_YIELD", False)
GRACE_PERCENT = envint("XPRA_GRACE_PERCENT", 90)
AV_SYNC_DELTA = envint("XPRA_AV_SYNC_DELTA", 0)
BANDWIDTH_DETECTION = envbool("XPRA_BANDWIDTH_DETECTION", True)
CONGESTION_WARNING_EVENT_COUNT = envint("XPRA_CONGESTION_WARNING_EVENT_COUNT", 10)
SKIP_METADATA = os.environ.get("XPRA_SKIP_METADATA", "").split(",")

PROPERTIES_DEBUG = [x.strip() for x in os.environ.get("XPRA_WINDOW_PROPERTIES_DEBUG", "").split(",")]

MIN_PIXEL_RECALCULATE = envint("XPRA_MIN_PIXEL_RECALCULATE", 2000)

counter = AtomicInteger()


"""
This class mediates between the server class (which only knows about actual window objects and display server events)
and the client specific WindowSource instances (which only know about window ids
and manage window pixel compression).
It sends messages to the client via its 'protocol' instance (the network connection),
directly for a number of cases (cursor, sound, notifications, etc)
or on behalf of the window sources for pixel data.

Strategy: if we have 'ordinary_packets' to send, send those.
When we don't, then send packets from the 'packet_queue'. (compressed pixels or clipboard data)
See 'next_packet'.

The UI thread calls damage(), which goes into WindowSource and eventually (batching may be involved)
adds the damage pixels ready for processing to the encode_work_queue,
items are picked off by the separate 'encode' thread (see 'encode_loop')
and added to the damage_packet_queue.
"""
class ClientConnection(AudioMixin, MMAP_Connection, ClipboardConnection, FilePrintMixin, NetworkStateMixin, ClientInfoMixin, DBUS_Mixin):

    def __init__(self, protocol, disconnect_cb, idle_add, timeout_add, source_remove, setting_changed,
                 idle_timeout, idle_timeout_cb, idle_grace_timeout_cb,
                 socket_dir, unix_socket_paths, log_disconnect, dbus_control,
                 get_transient_for, get_focus, get_cursor_data_cb,
                 get_window_id,
                 window_filters,
                 file_transfer,
                 supports_mmap, mmap_filename, min_mmap_size,
                 bandwidth_limit,
                 av_sync,
                 core_encodings, encodings, default_encoding, scaling_control,
                 sound_properties,
                 sound_source_plugin,
                 supports_speaker, supports_microphone,
                 speaker_codecs, microphone_codecs,
                 default_quality, default_min_quality,
                 default_speed, default_min_speed):
        log("ServerSource%s", (protocol, disconnect_cb, idle_add, timeout_add, source_remove, setting_changed,
                 idle_timeout, idle_timeout_cb, idle_grace_timeout_cb,
                 socket_dir, unix_socket_paths, log_disconnect, dbus_control,
                 get_transient_for, get_focus,
                 get_window_id,
                 window_filters,
                 file_transfer,
                 supports_mmap, mmap_filename, min_mmap_size,
                 bandwidth_limit,
                 av_sync,
                 core_encodings, encodings, default_encoding, scaling_control,
                 sound_properties,
                 sound_source_plugin,
                 supports_speaker, supports_microphone,
                 speaker_codecs, microphone_codecs,
                 default_quality, default_min_quality,
                 default_speed, default_min_speed))
        AudioMixin.__init__(self, sound_properties, sound_source_plugin,
                 supports_speaker, supports_microphone, speaker_codecs, microphone_codecs)
        MMAP_Connection.__init__(self, supports_mmap, mmap_filename, min_mmap_size)
        ClipboardConnection.__init__(self)
        FilePrintMixin.__init__(self, file_transfer)
        NetworkStateMixin.__init__(self)
        ClientInfoMixin.__init__(self)
        DBUS_Mixin.__init__(self, dbus_control)
        global counter
        self.counter = counter.increase()
        self.close_event = Event()
        self.ordinary_packets = []
        self.protocol = protocol
        self.disconnect = disconnect_cb
        self.idle_add = idle_add
        self.timeout_add = timeout_add
        self.source_remove = source_remove
        self.setting_changed = setting_changed
        self.idle = False
        self.idle_timeout = idle_timeout
        self.idle_timeout_cb = idle_timeout_cb
        self.idle_grace_timeout_cb = idle_grace_timeout_cb
        #grace duration is at least 10 seconds:
        self.idle_grace_duration = max(10, int(self.idle_timeout*(100-GRACE_PERCENT)//100))
        self.idle_timer = None
        self.idle_grace_timer = None
        self.schedule_idle_grace_timeout()
        self.schedule_idle_timeout()
        self.socket_dir = socket_dir
        self.unix_socket_paths = unix_socket_paths
        self.log_disconnect = log_disconnect
        self.get_transient_for = get_transient_for
        self.get_focus = get_focus
        self.get_cursor_data_cb = get_cursor_data_cb
        self.get_window_id = get_window_id
        self.window_filters = window_filters
        # network constraints:
        self.server_bandwidth_limit = bandwidth_limit
        # mouse echo:
        self.mouse_show = False
        self.mouse_last_position = None
        self.av_sync = av_sync
        self.av_sync_delay = 0
        self.av_sync_delay_total = 0
        self.av_sync_delta = AV_SYNC_DELTA

        self.icc = None
        self.display_icc = {}

        self.server_core_encodings = core_encodings
        self.server_encodings = encodings
        self.default_encoding = default_encoding
        self.scaling_control = scaling_control

        self.default_quality = default_quality      #default encoding quality for lossy encodings
        self.default_min_quality = default_min_quality #default minimum encoding quality
        self.default_speed = default_speed          #encoding speed (only used by x264)
        self.default_min_speed = default_min_speed  #default minimum encoding speed

        self.default_batch_config = DamageBatchConfig()     #contains default values, some of which may be supplied by the client
        self.global_batch_config = self.default_batch_config.clone()      #global batch config

        self.connection_time = monotonic_time()

        # the queues of damage requests we work through:
        self.encode_work_queue = Queue()            #holds functions to call to compress data (pixels, clipboard)
                                                    #items placed in this queue are picked off by the "encode" thread,
                                                    #the functions should add the packets they generate to the 'packet_queue'
        self.packet_queue = deque()                 #holds actual packets ready for sending (already encoded)
                                                    #these packets are picked off by the "protocol" via 'next_packet()'
                                                    #format: packet, wid, pixels, start_send_cb, end_send_cb
                                                    #(only packet is required - the rest can be 0/None for clipboard packets)
        #if we "proxy video", we will modify the video helper to add
        #new encoders, so we must make a deep copy to preserve the original
        #which may be used by other clients (other ServerSource instances)
        self.video_helper = getVideoHelper().clone()
        #these statistics are shared by all WindowSource instances:
        self.statistics = GlobalPerformanceStatistics()
        self.last_user_event = monotonic_time()

        self.init_vars()

        # ready for processing:
        protocol.set_packet_source(self.next_packet)
        self.encode_thread = start_thread(self.encode_loop, "encode")


    def __repr__(self):
        return  "%s(%i : %s)" % (type(self).__name__, self.counter, self.protocol)

    def init_vars(self):
        self.hello_sent = False

        self.encoding = None                        #the default encoding for all windows
        self.encodings = ()                         #all the encodings supported by the client
        self.core_encodings = ()
        self.window_icon_encodings = ["premult_argb32"]
        self.rgb_formats = ("RGB",)
        self.encoding_options = typedict()
        self.icons_encoding_options = typedict()
        self.default_encoding_options = typedict()

        self.window_sources = {}                    #WindowSource for each Window ID
        self.suspended = False

        self.auto_refresh_delay = 0
        self.info_namespace = False
        self.send_cursors = False
        self.cursor_encodings = ()
        self.send_bell = False
        self.send_notifications = False
        self.send_notifications_actions = False
        self.notification_callbacks = {}
        self.send_windows = True
        self.pointer_grabs = False
        self.randr_notify = False
        self.window_initiate_moveresize = False
        self.share = False
        self.lock = False
        self.desktop_size = None
        self.desktop_mode_size = None
        self.desktop_size_unscaled = None
        self.desktop_size_server = None
        self.screen_sizes = ()
        self.desktops = 1
        self.desktop_names = ()
        self.system_tray = False
        self.control_commands = ()
        self.metadata_supported = ()
        self.show_desktop_allowed = False
        self.supports_transparency = False
        self.vrefresh = -1
        self.double_click_time  = -1
        self.double_click_distance = -1, -1
        self.bandwidth_limit = self.server_bandwidth_limit
        self.soft_bandwidth_limit = self.bandwidth_limit
        self.bandwidth_warnings = True
        self.bandwidth_warning_time = 0
        #what we send back in hello packet:
        self.ui_client = True
        self.wants_aliases = True
        self.wants_encodings = True
        self.wants_versions = True
        self.wants_features = True
        self.wants_display = True
        self.wants_events = False
        self.wants_default_cursor = False

        self.keyboard_config = None
        self.cursor_timer = None
        self.last_cursor_sent = None

        #for managing the recalculate_delays work:
        self.calculate_window_pixels = {}
        self.calculate_window_ids = set()
        self.calculate_timer = 0
        self.calculate_last_time = 0


    def is_closed(self):
        return self.close_event.isSet()

    def close(self):
        log("%s.close()", self)
        for c in ClientConnection.__bases__:
            c.cleanup(self)
        self.close_event.set()
        for window_source in self.window_sources.values():
            window_source.cleanup()
        self.window_sources = {}
        #it is now safe to add the end of queue marker:
        #(all window sources will have stopped queuing data)
        self.encode_work_queue.put(None)
        #this should be a noop since we inherit an initialized helper:
        self.video_helper.cleanup()
        self.cancel_recalculate_timer()
        self.cancel_cursor_timer()
        self.protocol = None


    def compressed_wrapper(self, datatype, data, min_saving=128):
        if self.zlib or self.lz4 or self.lzo:
            cw = compressed_wrapper(datatype, data, zlib=self.zlib, lz4=self.lz4, lzo=self.lzo, can_inline=False)
            if len(cw)+min_saving<=len(data):
                #the compressed version is smaller, use it:
                return cw
            #skip compressed version: fall through
        #we can't compress, so at least avoid warnings in the protocol layer:
        return Compressed(datatype, data, can_inline=True)


    def update_bandwidth_limits(self):
        if self.mmap_size>0:
            return
        #calculate soft bandwidth limit based on send congestion data:
        bandwidth_limit = 0
        if BANDWIDTH_DETECTION:
            bandwidth_limit = self.statistics.avg_congestion_send_speed
            bandwidthlog("avg_congestion_send_speed=%s", bandwidth_limit)
            if bandwidth_limit>20*1024*1024:
                #ignore congestion speed if greater 20Mbps
                bandwidth_limit = 0
        if self.bandwidth_limit>0:
            #command line options could overrule what we detect?
            bandwidth_limit = min(self.bandwidth_limit, bandwidth_limit)
        self.soft_bandwidth_limit = bandwidth_limit
        bandwidthlog("update_bandwidth_limits() bandwidth_limit=%s, soft bandwidth limit=%s", self.bandwidth_limit, bandwidth_limit)
        if self.soft_bandwidth_limit<=0:
            return
        #figure out how to distribute the bandwidth amongst the windows,
        #we use the window size,
        #(we should actually use the number of bytes actually sent: framerate, compression, etc..)
        window_weight = {}
        for wid, ws in self.window_sources.items():
            weight = 0
            if not ws.suspended:
                ww, wh = ws.window_dimensions
                #try to reserve bandwidth for at least one screen update,
                #and add the number of pixels damaged:
                weight = ww*wh + ws.statistics.get_damage_pixels()
            window_weight[wid] = weight
        bandwidthlog("update_bandwidth_limits() window weights=%s", window_weight)
        total_weight = sum(window_weight.values())
        for wid, ws in self.window_sources.items():
            weight = window_weight.get(wid)
            if weight is not None:
                ws.bandwidth_limit = max(1, bandwidth_limit*weight//total_weight)

    def recalculate_delays(self):
        """ calls update_averages() on ServerSource.statistics (GlobalStatistics)
            and WindowSource.statistics (WindowPerformanceStatistics) for each window id in calculate_window_ids,
            this runs in the worker thread.
        """
        self.calculate_timer = 0
        if self.is_closed():
            return
        now = monotonic_time()
        self.calculate_last_time = now
        self.statistics.bytes_sent.append((now, self.protocol._conn.output_bytecount))
        self.statistics.update_averages()
        self.update_bandwidth_limits()
        wids = tuple(self.calculate_window_ids)  #make a copy so we don't clobber new wids
        focus = self.get_focus()
        sources = self.window_sources.items()
        maximized_wids = [wid for wid, source in sources if source is not None and source.maximized]
        fullscreen_wids = [wid for wid, source in sources if source is not None and source.fullscreen]
        log("recalculate_delays() wids=%s, focus=%s, maximized=%s, fullscreen=%s", wids, focus, maximized_wids, fullscreen_wids)
        for wid in wids:
            #this is safe because we only add to this set from other threads:
            self.calculate_window_ids.remove(wid)
            try:
                del self.calculate_window_pixels[wid]
            except:
                pass
            ws = self.window_sources.get(wid)
            if ws is None:
                continue
            try:
                ws.statistics.update_averages()
                ws.calculate_batch_delay(wid==focus,
                                         len(fullscreen_wids)>0 and wid not in fullscreen_wids,
                                         len(maximized_wids)>0 and wid not in maximized_wids)
                ws.reconfigure()
            except:
                log.error("error on window %s", wid, exc_info=True)
            if self.is_closed():
                return
            #allow other threads to run
            #(ideally this would be a low priority thread)
            sleep(0)
        #calculate weighted average as new global default delay:
        wdimsum, wdelay, tsize, tcount = 0, 0, 0, 0
        for ws in tuple(self.window_sources.values()):
            if ws.batch_config.last_updated<=0:
                continue
            w, h = ws.window_dimensions
            tsize += w*h
            tcount += 1
            time_w = 2.0+(now-ws.batch_config.last_updated)     #add 2 seconds to even things out
            weight = w*h*time_w
            wdelay += ws.batch_config.delay*weight
            wdimsum += weight
        if wdimsum>0 and tcount>0:
            #weighted delay:
            avg_size = tsize/tcount
            wdelay = wdelay / wdimsum
            #store the delay as a normalized value per megapixel:
            delay = wdelay * 1000000 / avg_size
            self.global_batch_config.last_delays.append((now, delay))
            self.global_batch_config.delay = delay

    def may_recalculate(self, wid, pixel_count):
        if wid in self.calculate_window_ids:
            return  #already scheduled
        v = self.calculate_window_pixels.get(wid, 0)+pixel_count
        self.calculate_window_pixels[wid] = v
        if v<MIN_PIXEL_RECALCULATE:
            return  #not enough pixel updates
        statslog("may_recalculate(%i, %i) total %i pixels, scheduling recalculate work item", wid, pixel_count, v)
        self.calculate_window_ids.add(wid)
        if self.calculate_timer:
            #already due
            return
        delta = monotonic_time() - self.calculate_last_time
        RECALCULATE_DELAY = 1.0           #1s
        if delta>RECALCULATE_DELAY:
            add_work_item(self.recalculate_delays)
        else:
            self.calculate_timer = self.timeout_add(int(1000*(RECALCULATE_DELAY-delta)), add_work_item, self.recalculate_delays)

    def cancel_recalculate_timer(self):
        ct = self.calculate_timer
        if ct:
            self.calculate_timer = 0
            self.source_remove(ct)


    def suspend(self, ui, wd):
        log("suspend(%s, %s) suspended=%s",
                  ui, wd, self.suspended)
        if ui:
            self.suspended = True
        for wid in wd.keys():
            ws = self.window_sources.get(wid)
            if ws:
                ws.suspend()

    def resume(self, ui, wd):
        log("resume(%s, %s) suspended=%s",
                  ui, wd, self.suspended)
        if ui:
            self.suspended = False
        for wid in wd.keys():
            ws = self.window_sources.get(wid)
            if ws:
                ws.resume()
        self.send_cursor()


    def go_idle(self):
        #usually fires from the server's idle_grace_timeout_cb
        if self.idle:
            return
        self.idle = True
        for window_source in self.window_sources.values():
            window_source.go_idle()

    def no_idle(self):
        #on user event, we stop being idle
        if not self.idle:
            return
        self.idle = False
        for window_source in self.window_sources.values():
            window_source.no_idle()


    def user_event(self):
        timeoutlog("user_event()")
        self.last_user_event = monotonic_time()
        self.schedule_idle_grace_timeout()
        self.schedule_idle_timeout()
        if self.idle:
            self.no_idle()
        try:
            self.notification_callbacks.pop(XPRA_IDLE_NOTIFICATION_ID)
        except KeyError:
            pass
        else:
            self.notify_close(XPRA_IDLE_NOTIFICATION_ID)
        

    def schedule_idle_timeout(self):
        timeoutlog("schedule_idle_timeout() idle_timer=%s, idle_timeout=%s", self.idle_timer, self.idle_timeout)
        if self.idle_timer:
            self.source_remove(self.idle_timer)
            self.idle_timer = None
        if self.idle_timeout>0:
            self.idle_timer = self.timeout_add(self.idle_timeout*1000, self.idle_timedout)

    def schedule_idle_grace_timeout(self):
        timeoutlog("schedule_idle_grace_timeout() grace timer=%s, idle_timeout=%s", self.idle_grace_timer, self.idle_timeout)
        if self.idle_grace_timer:
            self.source_remove(self.idle_grace_timer)
            self.idle_grace_timer = None
        if self.idle_timeout>0 and not self.is_closed():
            grace = self.idle_timeout - self.idle_grace_duration
            self.idle_grace_timer = self.timeout_add(max(0, int(grace*1000)), self.idle_grace_timedout)

    def idle_grace_timedout(self):
        self.idle_grace_timer = None
        timeoutlog("idle_grace_timedout() callback=%s", self.idle_grace_timeout_cb)
        self.idle_grace_timeout_cb(self)

    def idle_timedout(self):
        self.idle_timer = None
        timeoutlog("idle_timedout() callback=%s", self.idle_timeout_cb)
        self.idle_timeout_cb(self)
        if not self.is_closed():
            self.schedule_idle_timeout()


    def parse_hello(self, c):
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
            v = parse_batch_int(c.get(cpname), cpname)
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
        self.ui_client = c.boolget("ui_client", True)
        self.wants_encodings = c.boolget("wants_encodings", self.ui_client)
        self.wants_display = c.boolget("wants_display", self.ui_client)
        self.wants_events = c.boolget("wants_events", False)
        self.wants_aliases = c.boolget("wants_aliases", True)
        self.wants_versions = c.boolget("wants_versions", True)
        self.wants_features = c.boolget("wants_features", True)
        self.wants_default_cursor = c.boolget("wants_default_cursor", False)

        ClientInfoMixin.parse_client_caps(self, c)
        FilePrintMixin.parse_client_caps(self, c)
        AudioMixin.parse_client_caps(self, c)
        MMAP_Connection.parse_client_caps(self, c)

        #general features:
        self.zlib = c.boolget("zlib", True)
        self.lz4 = c.boolget("lz4", False) and compression.use_lz4
        self.lzo = c.boolget("lzo", False) and compression.use_lzo
        self.send_windows = self.ui_client and c.boolget("windows", True)
        self.pointer_grabs = c.boolget("pointer.grabs")
        self.info_namespace = c.boolget("info-namespace")
        self.send_cursors = self.send_windows and c.boolget("cursors")
        self.cursor_encodings = c.strlistget("encodings.cursor")
        self.send_bell = c.boolget("bell")
        self.send_notifications = c.boolget("notifications")
        self.send_notifications_actions = c.boolget("notifications.actions")
        self.randr_notify = c.boolget("randr_notify")
        self.mouse_show = c.boolget("mouse.show")
        self.mouse_last_position = c.intpair("mouse.initial-position")
        self.share = c.boolget("share")
        self.lock = c.boolget("lock")
        self.window_initiate_moveresize = c.boolget("window.initiate-moveresize")
        self.system_tray = c.boolget("system_tray")
        self.control_commands = c.strlistget("control_commands")
        self.metadata_supported = c.strlistget("metadata.supported", DEFAULT_METADATA_SUPPORTED)
        self.show_desktop_allowed = c.boolget("show-desktop")
        self.vrefresh = c.intget("vrefresh", -1)
        self.double_click_time = c.intget("double_click.time")
        self.double_click_distance = c.intpair("double_click.distance")
        self.window_frame_sizes = typedict(c.dictget("window.frame_sizes") or {})
        bandwidth_limit = c.intget("bandwidth-limit", 0)
        if self.server_bandwidth_limit<=0:
            self.bandwidth_limit = bandwidth_limit
        else:
            self.bandwidth_limit = min(self.server_bandwidth_limit, bandwidth_limit)
        bandwidthlog("server bandwidth-limit=%s, client bandwidth-limit=%s, value=%s", self.server_bandwidth_limit, bandwidth_limit, self.bandwidth_limit)

        default_min_delay = max(DamageBatchConfig.MIN_DELAY, 1000//(self.vrefresh or 60))
        self.default_batch_config.always = bool(batch_value("always", DamageBatchConfig.ALWAYS))
        self.default_batch_config.min_delay = batch_value("min_delay", default_min_delay, 0, 1000)
        self.default_batch_config.max_delay = batch_value("max_delay", DamageBatchConfig.MAX_DELAY, 1, 15000)
        self.default_batch_config.max_events = batch_value("max_events", DamageBatchConfig.MAX_EVENTS)
        self.default_batch_config.max_pixels = batch_value("max_pixels", DamageBatchConfig.MAX_PIXELS)
        self.default_batch_config.time_unit = batch_value("time_unit", DamageBatchConfig.TIME_UNIT, 1)
        self.default_batch_config.delay = batch_value("delay", DamageBatchConfig.START_DELAY, 0)
        log("default batch config: %s", self.default_batch_config)

        self.desktop_size = c.intpair("desktop_size")
        if self.desktop_size is not None:
            w, h = self.desktop_size
            if w<=0 or h<=0 or w>=32768 or h>=32768:
                log.warn("ignoring invalid desktop dimensions: %sx%s", w, h)
                self.desktop_size = None
        self.desktop_mode_size = c.intpair("desktop_mode_size")
        self.desktop_size_unscaled = c.intpair("desktop_size.unscaled")
        self.set_screen_sizes(c.listget("screen_sizes"))
        self.set_desktops(c.intget("desktops", 1), c.strlistget("desktop.names"))

        self.icc = c.dictget("icc")
        self.display_icc = c.dictget("display-icc")

        av_sync = c.boolget("av-sync")
        self.set_av_sync_delay(int(self.av_sync and av_sync) * c.intget("av-sync.delay.default", 150))
        avsynclog("av-sync: server=%s, client=%s, total=%s", self.av_sync, av_sync, self.av_sync_delay_total)
        log("cursors=%s (encodings=%s), bell=%s, notifications=%s", self.send_cursors, self.cursor_encodings, self.send_bell, self.send_notifications)
        log("client uuid %s", self.uuid)

        cinfo = self.get_connect_info()
        for i,ci in enumerate(cinfo):
            log.info("%s%s", ["", " "][int(i>0)], ci)
        if self.client_proxy:
            from xpra.version_util import version_compat_check
            msg = version_compat_check(self.proxy_version)
            if msg:
                proxylog.warn("Warning: proxy version may not be compatible: %s", msg)
        self.update_connection_data(c.dictget("connection-data"))

        #keyboard is now injected into this class, default to undefined:
        self.keyboard_config = None

        #encodings:
        self.encodings = c.strlistget("encodings")
        self.core_encodings = c.strlistget("encodings.core", self.encodings)
        if self.send_windows and not self.core_encodings:
            raise Exception("client failed to specify any supported encodings")
        if "png" in self.core_encodings:
            self.window_icon_encodings.append("png")
        self.window_icon_encodings = c.strlistget("encodings.window-icon", ["premult_argb32"])
        self.rgb_formats = c.strlistget("encodings.rgb_formats", ["RGB"])
        #skip all other encoding related settings if we don't send pixels:
        if not self.send_windows:
            log("windows/pixels forwarding is disabled for this client")
        else:
            self.parse_encoding_caps(c)
        if self.mmap_size>0:
            log("mmap enabled, ignoring bandwidth-limit")
            self.bandwidth_limit = 0
        #window filters:
        try:
            for object_name, property_name, operator, value in c.listget("window-filters"):
                self.add_window_filter(object_name, property_name, operator, value)
        except Exception as e:
            log.error("Error parsing window-filters: %s", e)
        #adjust max packet size if file transfers are enabled:
        if self.file_transfer:
            self.protocol.max_packet_size = max(self.protocol.max_packet_size, self.file_size_limit*1024*1024)


    def parse_encoding_caps(self, c):
        self.set_encoding(c.strget("encoding", None), None)
        #encoding options (filter):
        #1: these properties are special cased here because we
        #defined their name before the "encoding." prefix convention,
        #or because we want to pass default values (zlib/lz4):
        for k,ek in {"initial_quality"          : "initial_quality",
                     "quality"                  : "quality",
                     }.items():
            if k in c:
                self.encoding_options[ek] = c.intget(k)
        for k,ek in {"zlib"                     : "rgb_zlib",
                     "lz4"                      : "rgb_lz4",
                     }.items():
            if k in c:
                self.encoding_options[ek] = c.boolget(k)
        #2: standardized encoding options:
        for k in c.keys():
            if k.startswith(b"theme.") or  k.startswith(b"encoding.icons."):
                self.icons_encoding_options[k.replace(b"encoding.icons.", b"").replace(b"theme.", b"")] = c[k]
            elif k.startswith(b"encoding."):
                stripped_k = k[len(b"encoding."):]
                if stripped_k in (b"transparency",
                                  b"rgb_zlib", b"rgb_lz4", b"rgb_lzo",
                                  b"video_scaling"):
                    v = c.boolget(k)
                elif stripped_k in (b"initial_quality", b"initial_speed",
                                    b"min-quality", b"quality",
                                    b"min-speed", b"speed"):
                    v = c.intget(k)
                else:
                    v = c.get(k)
                self.encoding_options[stripped_k] = v
        elog("encoding options: %s", self.encoding_options)
        elog("icons encoding options: %s", self.icons_encoding_options)

        #handle proxy video: add proxy codec to video helper:
        pv = self.encoding_options.boolget("proxy.video")
        proxylog("proxy.video=%s", pv)
        if pv:
            #enabling video proxy:
            try:
                self.parse_proxy_video()
            except:
                proxylog.error("failed to parse proxy video", exc_info=True)

        self.default_encoding_options["scaling.control"] = self.encoding_options.get("scaling.control", self.scaling_control)
        q = self.encoding_options.intget("quality", self.default_quality)         #0.7 onwards:
        if q>0:
            self.default_encoding_options["quality"] = q
        mq = self.encoding_options.intget("min-quality", self.default_min_quality)
        if mq>0 and (q<=0 or q>mq):
            self.default_encoding_options["min-quality"] = mq
        s = self.encoding_options.intget("speed", self.default_speed)
        if s>0:
            self.default_encoding_options["speed"] = s
        ms = self.encoding_options.intget("min-speed", self.default_min_speed)
        if ms>0 and (s<=0 or s>ms):
            self.default_encoding_options["min-speed"] = ms
        elog("default encoding options: %s", self.default_encoding_options)
        self.auto_refresh_delay = c.intget("auto_refresh_delay", 0)
        if self.mmap_size==0:
            others = [x for x in self.core_encodings if x in self.server_core_encodings and x!=self.encoding]
            if self.encoding=="auto":
                s = "automatic picture encoding enabled"
            else:
                s = "using %s as primary encoding" % self.encoding
            if others:
                elog.info(" %s, also available:", s)
                elog.info("  %s", ", ".join(others))
            else:
                elog.warn(" %s", s)
                elog.warn("  no other encodings are available!")

    def parse_proxy_video(self):
        from xpra.codecs.enc_proxy.encoder import Encoder
        proxy_video_encodings = self.encoding_options.get("proxy.video.encodings")
        proxylog("parse_proxy_video() proxy.video.encodings=%s", proxy_video_encodings)
        for encoding, colorspace_specs in proxy_video_encodings.items():
            for colorspace, spec_props in colorspace_specs.items():
                for spec_prop in spec_props:
                    #make a new spec based on spec_props:
                    spec = video_spec(codec_class=Encoder, codec_type="proxy", encoding=encoding)
                    for k,v in spec_prop.items():
                        setattr(spec, k, v)
                    proxylog("parse_proxy_video() adding: %s / %s / %s", encoding, colorspace, spec)
                    self.video_helper.add_encoder_spec(encoding, colorspace, spec)


    def startup_complete(self):
        log("startup_complete()")
        self.send("startup-complete")


    ######################################################################
    # a/v sync:
    def set_av_sync_delta(self, delta):
        avsynclog("set_av_sync_delta(%i)", delta)
        self.av_sync_delta = delta
        self.update_av_sync_delay_total()

    def set_av_sync_delay(self, v):
        #update all window sources with the given delay
        self.av_sync_delay = v
        self.update_av_sync_delay_total()

    def update_av_sync_delay_total(self):
        if self.av_sync:
            encoder_latency = self.get_sound_source_latency()
            self.av_sync_delay_total = min(1000, max(0, int(self.av_sync_delay) + self.av_sync_delta + encoder_latency))
            avsynclog("av-sync set to %ims (from client queue latency=%s, encoder latency=%s, delta=%s)", self.av_sync_delay_total, self.av_sync_delay, encoder_latency, self.av_sync_delta)
        else:
            avsynclog("av-sync support is disabled, setting it to 0")
            self.av_sync_delay_total = 0
        for ws in self.window_sources.values():
            ws.set_av_sync_delay(self.av_sync_delay_total)


    ######################################################################
    # keyboard :
    def set_layout(self, layout, variant, options):
        return self.keyboard_config.set_layout(layout, variant, options)

    def keys_changed(self):
        if self.keyboard_config:
            self.keyboard_config.compute_modifier_map()
            self.keyboard_config.compute_modifier_keynames()
        keylog("keys_changed() updated keyboard config=%s", self.keyboard_config)

    def make_keymask_match(self, modifier_list, ignored_modifier_keycode=None, ignored_modifier_keynames=None):
        if self.keyboard_config and self.keyboard_config.enabled:
            self.keyboard_config.make_keymask_match(modifier_list, ignored_modifier_keycode, ignored_modifier_keynames)

    def set_default_keymap(self):
        keylog("set_default_keymap() keyboard_config=%s", self.keyboard_config)
        if self.keyboard_config:
            self.keyboard_config.set_default_keymap()
        return self.keyboard_config


    def set_keymap(self, current_keyboard_config, keys_pressed, force=False, translate_only=False):
        keylog("set_keymap%s", (current_keyboard_config, keys_pressed, force, translate_only))
        if self.keyboard_config and self.keyboard_config.enabled:
            current_id = None
            if current_keyboard_config and current_keyboard_config.enabled:
                current_id = current_keyboard_config.get_hash()
            keymap_id = self.keyboard_config.get_hash()
            keylog("current keyboard id=%s, new keyboard id=%s", current_id, keymap_id)
            if force or current_id is None or keymap_id!=current_id:
                self.keyboard_config.keys_pressed = keys_pressed
                self.keyboard_config.set_keymap(translate_only)
                self.keyboard_config.owner = self.uuid
                current_keyboard_config = self.keyboard_config
            else:
                keylog.info("keyboard mapping already configured (skipped)")
                self.keyboard_config = current_keyboard_config
        return current_keyboard_config


    def get_keycode(self, client_keycode, keyname, modifiers):
        if self.keyboard_config is None:
            keylog.info("ignoring client key %s / %s since keyboard is not configured", client_keycode, keyname)
            return -1
        return self.keyboard_config.get_keycode(client_keycode, keyname, modifiers)


    def update_mouse(self, wid, x, y, rx, ry):
        mouselog("update_mouse(%s, %i, %i, %i, %i) current=%s, client=%i, show=%s", wid, x, y, rx, ry, self.mouse_last_position, self.counter, self.mouse_show)
        if not self.mouse_show:
            return
        if self.mouse_last_position!=(x, y, rx, ry):
            self.mouse_last_position = (x, y, rx, ry)
            self.send_async("pointer-position", wid, x, y, rx, ry)


    ######################################################################
    # network:
    def next_packet(self):
        """ Called by protocol.py when it is ready to send the next packet """
        packet, start_send_cb, end_send_cb, fail_cb, synchronous, have_more, will_have_more = None, None, None, None, True, False, False
        if not self.is_closed():
            if len(self.ordinary_packets)>0:
                packet, synchronous, fail_cb, will_have_more = self.ordinary_packets.pop(0)
            elif len(self.packet_queue)>0:
                packet, _, _, start_send_cb, end_send_cb, fail_cb, will_have_more = self.packet_queue.popleft()
            have_more = packet is not None and (len(self.ordinary_packets)>0 or len(self.packet_queue)>0)
        return packet, start_send_cb, end_send_cb, fail_cb, synchronous, have_more, will_have_more

    def send(self, *parts, **kwargs):
        """ This method queues non-damage packets (higher priority) """
        synchronous = kwargs.get("synchronous", True)
        will_have_more = kwargs.get("will_have_more", not synchronous)
        fail_cb = kwargs.get("fail_cb", None)
        p = self.protocol
        if p:
            self.ordinary_packets.append((parts, synchronous, fail_cb, will_have_more))
            p.source_has_more()

    def send_more(self, *parts, **kwargs):
        kwargs["will_have_more"] = True
        self.send(*parts, **kwargs)

    def send_async(self, *parts, **kwargs):
        kwargs["synchronous"] = False
        self.send(*parts, **kwargs)


    #client tells us about network connection status:
    def update_connection_data(self, data):
        netlog("update_connection_data(%s)", data)
        self.client_connection_data = data


    ######################################################################
    # Functions used by the server to request something
    # (window events, stats, user requests, etc)
    #
    def set_auto_refresh_delay(self, delay, window_ids):
        if window_ids is not None:
            wss = (self.window_sources.get(wid) for wid in window_ids)
        else:
            wss = self.window_sources.values()
        for ws in wss:
            if ws is not None:
                ws.set_auto_refresh_delay(delay)

    def set_encoding(self, encoding, window_ids, strict=False):
        """ Changes the encoder for the given 'window_ids',
            or for all windows if 'window_ids' is None.
        """
        log("set_encoding(%s, %s, %s)", encoding, window_ids, strict)
        if not self.ui_client:
            return
        if encoding and encoding!="auto":
            #old clients (v0.9.x and earlier) only supported 'rgb24' as 'rgb' mode:
            if encoding=="rgb24":
                encoding = "rgb"
            if encoding not in self.encodings:
                log.warn("Warning: client specified '%s' encoding,", encoding)
                log.warn(" but it only supports: %s" % csv(self.encodings))
            if encoding not in self.server_encodings:
                log.error("Error: encoding %s is not supported by this server", encoding)
                encoding = None
        if not encoding:
            encoding = "auto"
        if window_ids is not None:
            wss = [self.window_sources.get(wid) for wid in window_ids]
        else:
            wss = self.window_sources.values()
        #if we're updating all the windows, reset global stats too:
        if set(wss).issuperset(self.window_sources.values()):
            log("resetting global stats")
            self.statistics.reset()
            self.global_batch_config = self.default_batch_config.clone()
        for ws in wss:
            if ws is not None:
                ws.set_new_encoding(encoding, strict)
        if not window_ids:
            self.encoding = encoding

    def send_hello(self, server_capabilities):
        capabilities = server_capabilities.copy()
        merge_dicts(capabilities, AudioMixin.get_caps(self))
        merge_dicts(capabilities, MMAP_Connection.get_caps(self))
        if self.wants_encodings and self.encoding:
            capabilities["encoding"] = self.encoding
        if self.wants_features:
            capabilities.update({
                         "auto_refresh_delay"   : self.auto_refresh_delay,
                         })
        #expose the "modifier_client_keycodes" defined in the X11 server keyboard config object,
        #so clients can figure out which modifiers map to which keys:
        if self.keyboard_config:
            mck = getattr(self.keyboard_config, "modifier_client_keycodes", None)
            if mck:
                capabilities["modifier_keycodes"] = mck
        self.send("hello", capabilities)
        self.hello_sent = True


    ######################################################################
    # info:
    def get_info(self):
        info = {
                "protocol"          : "xpra",
                "idle_time"         : int(monotonic_time()-self.last_user_event),
                "idle"              : self.idle,
                "auto_refresh"      : self.auto_refresh_delay,
                "desktop_size"      : self.desktop_size or "",
                "desktops"          : self.desktops,
                "desktop_names"     : self.desktop_names,
                "connection_time"   : int(self.connection_time),
                "elapsed_time"      : int(monotonic_time()-self.connection_time),
                "suspended"         : self.suspended,
                "counter"           : self.counter,
                "hello-sent"        : self.hello_sent,
                "bandwidth-limit"   : {
                    "setting"       : self.bandwidth_limit,
                    "actual"        : self.soft_bandwidth_limit,
                    }
                }
        if self.desktop_mode_size:
            info["desktop_mode_size"] = self.desktop_mode_size
        if self.client_connection_data:
            info["connection-data"] = self.client_connection_data
        if self.desktop_size_unscaled:
            info["desktop_size"] = {"unscaled" : self.desktop_size_unscaled}

        def addattr(k, name):
            v = getattr(self, name)
            if v is not None:
                info[k] = v
        for x in ("type", "platform", "release", "machine", "processor", "proxy", "wm_name", "session_type"):
            addattr(x, "client_"+x)
        #remove very large item:
        ieo = dict(self.icons_encoding_options)
        try:
            del ieo["default.icons"]
        except:
            pass
        #encoding:
        info.update({
                     "encodings"        : {
                                           ""      : self.encodings,
                                           "core"  : self.core_encodings,
                                           "window-icon"    : self.window_icon_encodings,
                                           },
                     "icons"            : ieo,
                     "connection"       : self.protocol.get_info(),
                     "av-sync"          : {
                                           "client"     : {"delay"  : self.av_sync_delay},
                                           "total"      : self.av_sync_delay_total,
                                           "delta"      : self.av_sync_delta,
                                           },
                     })
        einfo = {"default"      : self.default_encoding or ""}
        einfo.update(self.default_encoding_options)
        einfo.update(self.encoding_options)
        info.setdefault("encoding", {}).update(einfo)
        if self.window_frame_sizes:
            info.setdefault("window", {}).update({"frame-sizes" : self.window_frame_sizes})
        if self.window_filters:
            i = 0
            finfo = {}
            for uuid, f in self.window_filters:
                if uuid==self.uuid:
                    finfo[i] = str(f)
                    i += 1
            info["window-filter"] = finfo
        info.update(self.get_features_info())
        info.update(self.get_screen_info())
        merge_dicts(info, FilePrintMixin.get_info(self))
        merge_dicts(info, AudioMixin.get_info(self))
        merge_dicts(info, MMAP_Connection.get_info(self))
        merge_dicts(info, NetworkStateMixin.get_info(self))
        merge_dicts(info, ClientInfoMixin.get_info(self))
        return info

    def get_screen_info(self):
        return get_screen_info(self.screen_sizes)

    def get_features_info(self):
        info = {}
        def battr(k, prop):
            info[k] = bool(getattr(self, prop))
        for prop in ("lock", "share", "randr_notify",
                     "system_tray",
                     "lz4", "lzo"):
            battr(prop, prop)
        for prop, name in {
            "send_windows"       : "windows",
            "send_cursors"       : "cursors",
            "send_notifications" : "notifications",
            "send_bell"          : "bell",
            }.items():
            battr(name, prop)
        for prop, name in {
                           "vrefresh"               : "vertical-refresh",
                           "file_size_limit"        : "file-size-limit",
                           }.items():
            info[name] = getattr(self, prop)
        dcinfo = info.setdefault("double_click", {})
        for prop, name in {
                           "double_click_time"      : "time",
                           "double_click_distance"  : "distance",
                           }.items():
            dcinfo[name] = getattr(self, prop)
        return info

    def get_window_info(self, window_ids=[]):
        """
            Adds encoding and window specific information
        """
        pqpixels = [x[2] for x in tuple(self.packet_queue)]
        pqpi = get_list_stats(pqpixels)
        if len(pqpixels)>0:
            pqpi["current"] = pqpixels[-1]
        info = {"damage"    : {
                               "compression_queue"      : {"size" : {"current" : self.encode_work_queue.qsize()}},
                               "packet_queue"           : {"size" : {"current" : len(self.packet_queue)}},
                               "packet_queue_pixels"    : pqpi,
                               },
                "batch"     : self.global_batch_config.get_info(),
                }
        info.update(self.statistics.get_info())

        if len(window_ids)>0:
            total_pixels = 0
            total_time = 0.0
            in_latencies, out_latencies = [], []
            winfo = {}
            for wid in window_ids:
                ws = self.window_sources.get(wid)
                if ws is None:
                    continue
                #per-window source stats:
                winfo[wid] = ws.get_info()
                #collect stats for global averages:
                for _, _, pixels, _, _, encoding_time in tuple(ws.statistics.encoding_stats):
                    total_pixels += pixels
                    total_time += encoding_time
                in_latencies += [x*1000 for _, _, _, x in tuple(ws.statistics.damage_in_latency)]
                out_latencies += [x*1000 for _, _, _, x in tuple(ws.statistics.damage_out_latency)]
            info["window"] = winfo
            v = 0
            if total_time>0:
                v = int(total_pixels / total_time)
            info.setdefault("encoding", {})["pixels_encoded_per_second"] = v
            dinfo = info.setdefault("damage", {})
            dinfo["in_latency"] = get_list_stats(in_latencies, show_percentile=[9])
            dinfo["out_latency"] = get_list_stats(out_latencies, show_percentile=[9])
        return info


    def send_info_response(self, info):
        if self.info_namespace:
            v = notypedict(info)
        else:
            v = flatten_dict(info)
        self.send_async("info-response", v)


    def send_setting_change(self, setting, value):
        if self.client_setting_change:
            self.send_more("setting-change", setting, value)


    def send_server_event(self, *args):
        if self.wants_events:
            self.send_more("server-event", *args)


    ######################################################################
    # grabs:
    def pointer_grab(self, wid):
        if self.pointer_grabs and self.hello_sent:
            self.send("pointer-grab", wid)

    def pointer_ungrab(self, wid):
        if self.pointer_grabs and self.hello_sent:
            self.send("pointer-ungrab", wid)


    ######################################################################
    # cursors:
    def send_cursor(self):
        if not self.send_cursors or self.suspended or not self.hello_sent:
            return
        #if not pending already, schedule it:
        if not self.cursor_timer:
            delay = max(10, int(self.global_batch_config.delay/4))
            self.cursor_timer = self.timeout_add(delay, self.do_send_cursor, delay)

    def cancel_cursor_timer(self):
        ct = self.cursor_timer
        if ct:
            self.cursor_timer = None
            self.source_remove(ct)

    def do_send_cursor(self, delay):
        self.cursor_timer = None
        cd = self.get_cursor_data_cb()
        if cd and cd[0]:
            cursor_data, cursor_sizes = cd
            #skip first two fields (if present) as those are coordinates:
            if self.last_cursor_sent and self.last_cursor_sent[2:9]==cursor_data[2:9]:
                cursorlog("do_send_cursor(..) cursor identical to the last one we sent, nothing to do")
                return
            self.last_cursor_sent = cursor_data[:9]
            w, h, _xhot, _yhot, serial, pixels, name = cursor_data[2:9]
            #compress pixels if needed:
            encoding = None
            if pixels is not None:
                #convert bytearray to string:
                cpixels = strtobytes(pixels)
                if "png" in self.cursor_encodings:
                    from xpra.codecs.loader import get_codec
                    PIL = get_codec("PIL")
                    assert PIL
                    img = PIL.Image.frombytes("RGBA", (w, h), cpixels, "raw", "BGRA", w*4, 1)
                    buf = BytesIOClass()
                    img.save(buf, "PNG")
                    cpixels = Compressed("png cursor", buf.getvalue(), can_inline=True)
                    buf.close()
                    encoding = "png"
                elif len(cpixels)>=256 and ("raw" in self.cursor_encodings or not self.cursor_encodings):
                    cpixels = self.compressed_wrapper("cursor", pixels)
                    cursorlog("do_send_cursor(..) pixels=%s ", cpixels)
                    encoding = "raw"
                cursor_data[7] = cpixels
            cursorlog("do_send_cursor(..) %sx%s %s cursor name=%s, serial=%i with delay=%s (cursor_encodings=%s)", w, h, (encoding or "empty"), name, serial, delay, self.cursor_encodings)
            args = list(cursor_data[:9]) + [cursor_sizes[0]] + list(cursor_sizes[1])
            if self.cursor_encodings and encoding:
                args = [encoding] + args
        else:
            cursorlog("do_send_cursor(..) sending empty cursor with delay=%s", delay)
            args = [""]
            self.last_cursor_sent = None
        self.send_more("cursor", *args)


    ######################################################################
    # notifications:
    """ Utility functions for mixins (makes notifications optional) """
    def may_notify(self, nid, summary, body, actions=[], hints={}, expire_timeout=10*1000, icon_name=None, user_callback=None):
        try:
            from xpra.platform.paths import get_icon_filename
            from xpra.notifications.common import parse_image_path
        except ImportError as e:
            notifylog("not sending notification: %s", e)
        else:
            icon_filename = get_icon_filename(icon_name)
            icon = parse_image_path(icon_filename)
            self.notify("", nid, "Xpra", 0, "", summary, body, actions, hints, expire_timeout, icon, user_callback)

    def notify(self, dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, actions, hints, expire_timeout, icon, user_callback=None):
        args = (dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, actions, hints, expire_timeout, icon)
        notifylog("notify%s types=%s", args, tuple(type(x) for x in args))
        if not self.send_notifications:
            notifylog("client %s does not support notifications", self)
            return False
        if self.suspended:
            notifylog("client %s is suspended, notification not sent", self)
            return False
        if user_callback:
            self.notification_callbacks[nid] = user_callback
        #this is one of the few places where we actually do care about character encoding:
        try:
            summary = summary.encode("utf8")
        except:
            summary = str(summary)
        try:
            body = body.encode("utf8")
        except:
            body = str(body)
        if self.hello_sent:
            #Warning: actions and hints are send last because they were added later (in version 2.3)
            self.send_async("notify_show", dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout, icon, actions, hints)
        return True

    def notify_close(self, nid):
        if not self.send_notifications or self.suspended  or not self.hello_sent:
            return
        self.send_more("notify_close", nid)


    def set_deflate(self, level):
        self.send("set_deflate", level)


    def bell(self, wid, device, percent, pitch, duration, bell_class, bell_id, bell_name):
        if not self.send_bell or self.suspended or not self.hello_sent:
            return
        self.send_async("bell", wid, device, percent, pitch, duration, bell_class, bell_id, bell_name)


    ######################################################################
    # webcam:
    def send_webcam_ack(self, device, frame, *args):
        if self.hello_sent:
            self.send_async("webcam-ack", device, frame, *args)

    def send_webcam_stop(self, device, message):
        if self.hello_sent:
            self.send_async("webcam-stop", device, message)


    def send_client_command(self, *args):
        if self.hello_sent:
            self.send_more("control", *args)


    def rpc_reply(self, *args):
        if self.hello_sent:
            self.send("rpc-reply", *args)


    ######################################################################
    # screen and desktops:
    def set_screen_sizes(self, screen_sizes):
        self.screen_sizes = screen_sizes or []
        log("client screen sizes: %s", screen_sizes)

    def set_desktops(self, desktops, desktop_names):
        self.desktops = desktops or 1
        self.desktop_names = desktop_names or []

    def updated_desktop_size(self, root_w, root_h, max_w, max_h):
        log("updated_desktop_size%s randr_notify=%s, desktop_size=%s", (root_w, root_h, max_w, max_h), self.randr_notify, self.desktop_size)
        if not self.hello_sent:
            return False
        if self.randr_notify and (not self.desktop_size_server or tuple(self.desktop_size_server)!=(root_w, root_h)):
            self.desktop_size_server = root_w, root_h
            self.send("desktop_size", root_w, root_h, max_w, max_h)
            return True
        return False

    def show_desktop(self, show):
        if self.show_desktop_allowed and self.hello_sent:
            self.send_async("show-desktop", show)

    ######################################################################
    # window filters:
    def reset_window_filters(self):
        self.window_filters = [(uuid, f) for uuid, f in self.window_filters if uuid!=self.uuid]

    def get_all_window_filters(self):
        return [f for uuid, f in self.window_filters if uuid==self.uuid]

    def get_window_filter(self, object_name, property_name, operator, value):
        if object_name!="window":
            raise ValueError("invalid object name")
        from xpra.server.window.filters import WindowPropertyIn, WindowPropertyNotIn
        if operator=="=":
            return WindowPropertyIn(property_name, [value])
        elif operator=="!=":
            return WindowPropertyNotIn(property_name, [value])
        raise ValueError("unknown filter operator: %s" % operator)

    def add_window_filter(self, object_name, property_name, operator, value):
        window_filter = self.get_window_filter(object_name, property_name, operator, value)
        assert window_filter
        self.window_filters.append((self.uuid, window_filter.show))

    def can_send_window(self, window):
        if not self.hello_sent:
            return False
        for uuid,x in self.window_filters:
            v = x(window)
            if v is True:
                return uuid==self.uuid
        if self.send_windows and self.system_tray:
            #common case shortcut
            return True
        if window.is_tray():
            return self.system_tray
        return self.send_windows


    ######################################################################
    # windows:
    def initiate_moveresize(self, wid, window, x_root, y_root, direction, button, source_indication):
        if not self.can_send_window(window) or not self.window_initiate_moveresize:
            return
        log("initiate_moveresize sending to %s", self)
        self.send("initiate-moveresize", wid, x_root, y_root, direction, button, source_indication)

    def or_window_geometry(self, wid, window, x, y, w, h):
        if not self.can_send_window(window):
            return
        self.send("configure-override-redirect", wid, x, y, w, h)

    def window_metadata(self, wid, window, prop):
        if not self.can_send_window(window):
            return
        if prop=="icon":
            self.send_window_icon(wid, window)
        else:
            v = self._make_metadata(window, prop)
            if prop in PROPERTIES_DEBUG:
                metalog.info("make_metadata(%s, %s, %s)=%s", wid, window, prop, v)
            else:
                metalog("make_metadata(%s, %s, %s)=%s", wid, window, prop, v)
            if len(v)>0:
                self.send("window-metadata", wid, v)


    # Takes the name of a WindowModel property, and returns a dictionary of
    # xpra window metadata values that depend on that property
    def _make_metadata(self, window, propname):
        if propname not in self.metadata_supported:
            metalog("make_metadata: client does not support '%s'", propname)
            return {}
        return make_window_metadata(window, propname,
                                        get_transient_for=self.get_transient_for,
                                        get_window_id=self.get_window_id)

    def new_tray(self, wid, window, w, h):
        assert window.is_tray()
        if not self.can_send_window(window):
            return
        metadata = {}
        for propname in list(window.get_property_names()):
            metadata.update(self._make_metadata(window, propname))
        self.send_async("new-tray", wid, w, h, metadata)

    def new_window(self, ptype, wid, window, x, y, w, h, client_properties):
        if not self.can_send_window(window):
            return
        send_props = list(window.get_property_names())
        send_raw_icon = "icon" in send_props
        if send_raw_icon:
            send_props.remove("icon")
        metadata = {}
        for prop in send_props:
            v = self._make_metadata(window, prop)
            if prop in PROPERTIES_DEBUG:
                metalog.info("make_metadata(%s, %s, %s)=%s", wid, window, prop, v)
            else:
                metalog("make_metadata(%s, %s, %s)=%s", wid, window, prop, v)
            metadata.update(v)
        log("new_window(%s, %s, %s, %s, %s, %s, %s, %s) metadata(%s)=%s", ptype, window, wid, x, y, w, h, client_properties, send_props, metadata)
        self.send_async(ptype, wid, x, y, w, h, metadata, client_properties or {})
        if send_raw_icon:
            self.send_window_icon(wid, window)

    def send_window_icon(self, wid, window):
        if not self.can_send_window(window):
            return
        #we may need to make a new source at this point:
        ws = self.make_window_source(wid, window)
        if ws:
            ws.send_window_icon()


    def lost_window(self, wid, window):
        if not self.can_send_window(window):
            return
        self.send("lost-window", wid)

    def move_resize_window(self, wid, window, x, y, ww, wh, resize_counter=0):
        """
        The server detected that the application window has been moved and/or resized,
        we forward it if the client supports this type of event.
        """
        if not self.can_send_window(window):
            return
        self.send("window-move-resize", wid, x, y, ww, wh, resize_counter)

    def resize_window(self, wid, window, ww, wh, resize_counter=0):
        if not self.can_send_window(window):
            return
        self.send("window-resized", wid, ww, wh, resize_counter)


    def cancel_damage(self, wid):
        """
        Use this method to cancel all currently pending and ongoing
        damage requests for a window.
        """
        ws = self.window_sources.get(wid)
        if ws:
            ws.cancel_damage()

    def unmap_window(self, wid, _window):
        ws = self.window_sources.get(wid)
        if ws:
            ws.unmap()

    def raise_window(self, wid, window):
        if not self.can_send_window(window):
            return
        self.send_async("raise-window", wid)

    def remove_window(self, wid, window):
        """ The given window is gone, ensure we free all the related resources """
        if not self.can_send_window(window):
            return
        ws = self.window_sources.get(wid)
        if ws:
            del self.window_sources[wid]
            ws.cleanup()
        try:
            del self.calculate_window_pixels[wid]
        except:
            pass


    ######################################################################
    # encoding attributes
    def set_min_quality(self, min_quality):
        for ws in tuple(self.window_sources.values()):
            ws.set_min_quality(min_quality)

    def set_quality(self, quality):
        for ws in tuple(self.window_sources.values()):
            ws.set_quality(quality)

    def set_min_speed(self, min_speed):
        for ws in tuple(self.window_sources.values()):
            ws.set_min_speed(min_speed)

    def set_speed(self, speed):
        for ws in tuple(self.window_sources.values()):
            ws.set_speed(speed)


    def refresh(self, wid, window, opts):
        if not self.can_send_window(window):
            return
        self.cancel_damage(wid)
        w, h = window.get_dimensions()
        self.damage(wid, window, 0, 0, w, h, opts)

    def update_batch(self, wid, window, batch_props):
        ws = self.window_sources.get(wid)
        if ws:
            if "reset" in batch_props:
                ws.batch_config = self.make_batch_config(wid, window)
            for x in ("always", "locked"):
                if x in batch_props:
                    setattr(ws.batch_config, x, batch_props.boolget(x))
            for x in ("min_delay", "max_delay", "timeout_delay", "delay"):
                if x in batch_props:
                    setattr(ws.batch_config, x, batch_props.intget(x))
            log("batch config updated for window %s: %s", wid, ws.batch_config)

    def set_client_properties(self, wid, window, new_client_properties):
        assert self.send_windows
        ws = self.make_window_source(wid, window)
        ws.set_client_properties(new_client_properties)

    def make_batch_config(self, wid, window):
        batch_config = self.default_batch_config.clone()
        batch_config.wid = wid
        #scale initial delay based on window size
        #(the global value is normalized to 1MPixel)
        #but use sqrt to smooth things and prevent excesses
        #(ie: a 4MPixel window, will start at 2 times the global delay)
        #(ie: a 0.5MPixel window will start at 0.7 times the global delay)
        w, h = window.get_dimensions()
        ratio = float(w*h) / 1000000
        batch_config.delay = self.global_batch_config.delay * sqrt(ratio)
        return batch_config


    def get_window_source(self, wid):
        return self.window_sources.get(wid)

    def make_window_source(self, wid, window):
        ws = self.window_sources.get(wid)
        if ws is None:
            batch_config = self.make_batch_config(wid, window)
            ww, wh = window.get_dimensions()
            bandwidth_limit = self.bandwidth_limit
            if self.mmap_size>0:
                bandwidth_limit = 0
            ws = WindowVideoSource(
                              self.idle_add, self.timeout_add, self.source_remove,
                              ww, wh,
                              self.record_congestion_event, self.queue_size, self.call_in_encode_thread, self.queue_packet, self.compressed_wrapper,
                              self.statistics,
                              wid, window, batch_config, self.auto_refresh_delay,
                              self.av_sync, self.av_sync_delay,
                              self.video_helper,
                              self.server_core_encodings, self.server_encodings,
                              self.encoding, self.encodings, self.core_encodings, self.window_icon_encodings, self.encoding_options, self.icons_encoding_options,
                              self.rgb_formats,
                              self.default_encoding_options,
                              self.mmap, self.mmap_size, bandwidth_limit)
            self.window_sources[wid] = ws
            if len(self.window_sources)>1:
                #re-distribute bandwidth:
                self.update_bandwidth_limits()
        return ws

    def damage(self, wid, window, x, y, w, h, options=None):
        """
            Main entry point from the window manager,
            we dispatch to the WindowSource for this window id
            (creating a new one if needed)
        """
        if not self.can_send_window(window):
            return
        assert window is not None
        damage_options = {}
        if options:
            damage_options = options.copy()
        self.statistics.damage_last_events.append((wid, monotonic_time(), w*h))
        ws = self.make_window_source(wid, window)
        ws.damage(x, y, w, h, damage_options)

    def client_ack_damage(self, damage_packet_sequence, wid, width, height, decode_time, message):
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
            self.statistics.client_decode_time.append((wid, monotonic_time(), width*height, decode_time))
        ws = self.window_sources.get(wid)
        if ws:
            ws.damage_packet_acked(damage_packet_sequence, width, height, decode_time, message)
            self.may_recalculate(wid, width*height)

#
# Methods used by WindowSource:
#
    def record_congestion_event(self, source, late_pct=0, send_speed=0):
        if not BANDWIDTH_DETECTION:
            return
        gs = self.statistics
        if not gs:
            #window cleaned up?
            return
        statslog("record_congestion_event(%s, %i, %i)", source, late_pct, send_speed)
        now = monotonic_time()
        gs.last_congestion_time = now
        gs.congestion_send_speed.append((now, late_pct, send_speed))
        if self.bandwidth_warnings and now-self.bandwidth_warning_time>60:
            #enough congestion events?
            min_time = now-10
            count = len(tuple(True for x in gs.congestion_send_speed if x[0]>min_time))
            if count>CONGESTION_WARNING_EVENT_COUNT:
                self.bandwidth_warning_time = now
                nid = XPRA_BANDWIDTH_NOTIFICATION_ID
                summary = "Network Performance Issue"
                body = "Your network connection is struggling to keep up,\n" + \
                        "consider lowering the bandwidth limit,\n" + \
                        "or lowering the picture quality"
                actions = []
                if self.bandwidth_limit==0 or self.bandwidth_limit>1*1000*1000:
                    actions += ["lower-bandwidth", "Lower bandwidth limit"]
                #if self.default_min_quality>10:
                #    actions += ["lower-quality", "Lower quality"]
                actions += ["ignore", "Ignore"]
                hints = {}
                self.may_notify(nid, summary, body, actions, hints, icon_name="connect", user_callback=self.congestion_notification_callback)

    def congestion_notification_callback(self, nid, action_id):
        log("congestion_notification_callback(%i, %s)", nid, action_id)
        if action_id=="lower-bandwidth":
            bandwidth_limit = 50*1024*1024
            if self.bandwidth_limit>256*1024:
                bandwidth_limit = self.bandwidth_limit//2
            css = 50*1024*1024
            if self.statistics.avg_congestion_send_speed>256*1024:
                #round up:
                css = int(1+self.statistics.avg_congestion_send_speed//16/1024)*16*1024
            self.bandwidth_limit = min(bandwidth_limit, css)
            self.setting_changed("bandwidth-limit", self.bandwidth_limit)
        #elif action_id=="lower-quality":
        #    self.default_min_quality = max(1, self.default_min_quality-15)
        #    self.set_min_quality(self.default_min_quality)
        #    self.setting_changed("min-quality", self.default_min_quality)
        elif action_id=="ignore":
            self.bandwidth_warnings = False


    def queue_size(self):
        return self.encode_work_queue.qsize()

    def call_in_encode_thread(self, *fn_and_args):
        """
            This is used by WindowSource to queue damage processing to be done in the 'encode' thread.
            The 'encode_and_send_cb' will then add the resulting packet to the 'packet_queue' via 'queue_packet'.
        """
        self.statistics.compression_work_qsizes.append((monotonic_time(), self.encode_work_queue.qsize()))
        self.encode_work_queue.put(fn_and_args)

    def queue_packet(self, packet, wid=0, pixels=0, start_send_cb=None, end_send_cb=None, fail_cb=None, wait_for_more=False):
        """
            Add a new 'draw' packet to the 'packet_queue'.
            Note: this code runs in the non-ui thread
        """
        now = monotonic_time()
        self.statistics.packet_qsizes.append((now, len(self.packet_queue)))
        if wid>0:
            self.statistics.damage_packet_qpixels.append((now, wid, sum(x[2] for x in tuple(self.packet_queue) if x[1]==wid)))
        self.packet_queue.append((packet, wid, pixels, start_send_cb, end_send_cb, fail_cb, wait_for_more))
        p = self.protocol
        if p:
            p.source_has_more()

#
# The damage packet thread loop:
#
    def encode_loop(self):
        """
            This runs in a separate thread and calls all the function callbacks
            which are added to the 'encode_work_queue'.
            Must run until we hit the end of queue marker,
            to ensure all the queued items get called.
        """
        while True:
            fn_and_args = self.encode_work_queue.get(True)
            if fn_and_args is None:
                return              #empty marker
            #some function calls are optional and can be skipped when closing:
            #(but some are not, like encoder clean functions)
            optional_when_closing = fn_and_args[0]
            if optional_when_closing and self.is_closed():
                continue
            try:
                fn_and_args[1](*fn_and_args[2:])
            except Exception as e:
                if self.is_closed():
                    log("ignoring encoding error in %s as source is already closed:", fn_and_args[0])
                    log(" %s", e)
                else:
                    log.error("Error during encoding:", exc_info=True)
                del e
            NOYIELD or sleep(0)
