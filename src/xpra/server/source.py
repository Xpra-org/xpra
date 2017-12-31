# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2017 Antoine Martin <antoine@devloop.org.uk>
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
soundlog = Logger("sound")
keylog = Logger("keyboard")
mouselog = Logger("mouse")
cursorlog = Logger("cursor")
metalog = Logger("metadata")
printlog = Logger("printing")
filelog = Logger("file")
timeoutlog = Logger("timeout")
proxylog = Logger("proxy")
avsynclog = Logger("av-sync")
mmaplog = Logger("mmap")
dbuslog = Logger("dbus")
statslog = Logger("stats")
notifylog = Logger("notify")
clipboardlog = Logger("clipboard")
netlog = Logger("network")


from xpra.server.source_stats import GlobalPerformanceStatistics
from xpra.server.window.window_video_source import WindowVideoSource
from xpra.server.window.batch_config import DamageBatchConfig
from xpra.simple_stats import get_list_stats, std_unit
from xpra.codecs.video_helper import getVideoHelper
from xpra.codecs.codec_constants import video_spec
from xpra.net import compression
from xpra.net.compression import compressed_wrapper, Compressed, Compressible
from xpra.net.file_transfer import FileTransferHandler
from xpra.make_thread import start_thread
from xpra.os_util import platform_name, Queue, get_machine_id, get_user_uuid, monotonic_time, BytesIOClass, strtobytes, bytestostr, WIN32, POSIX
from xpra.server.background_worker import add_work_item
from xpra.util import csv, std, typedict, updict, flatten_dict, notypedict, get_screen_info, envint, envbool, AtomicInteger, \
                    CLIENT_PING_TIMEOUT, WORKSPACE_UNSET, DEFAULT_METADATA_SUPPORTED
def no_legacy_names(v):
    return v
try:
    from xpra.sound.common import NEW_CODEC_NAMES, LEGACY_CODEC_NAMES, new_to_legacy
except:
    LEGACY_CODEC_NAMES, NEW_CODEC_NAMES = {}, {}
    new_to_legacy = no_legacy_names

NOYIELD = not envbool("XPRA_YIELD", False)
MAX_CLIPBOARD_LIMIT = envint("XPRA_CLIPBOARD_LIMIT", 30)
MAX_CLIPBOARD_LIMIT_DURATION = envint("XPRA_CLIPBOARD_LIMIT_DURATION", 3)
ADD_LOCAL_PRINTERS = envbool("XPRA_ADD_LOCAL_PRINTERS", False)
GRACE_PERCENT = envint("XPRA_GRACE_PERCENT", 90)
AV_SYNC_DELTA = envint("XPRA_AV_SYNC_DELTA", 0)
NEW_STREAM_SOUND = envbool("XPRA_NEW_STREAM_SOUND", True)
PING_DETAILS = envbool("XPRA_PING_DETAILS", True)
PING_TIMEOUT = envint("XPRA_PING_TIMEOUT", 60)
DETECT_BANDWIDTH_LIMIT = envbool("XPRA_DETECT_BANDWIDTH_LIMIT", True)

PRINTER_LOCATION_STRING = os.environ.get("XPRA_PRINTER_LOCATION_STRING", "via xpra")
PROPERTIES_DEBUG = [x.strip() for x in os.environ.get("XPRA_WINDOW_PROPERTIES_DEBUG", "").split(",")]

MIN_PIXEL_RECALCULATE = envint("XPRA_MIN_PIXEL_RECALCULATE", 2000)

counter = AtomicInteger()


def make_window_metadata(window, propname, get_transient_for=None, get_window_id=None):
    #note: some of the properties handled here aren't exported to the clients,
    #but we do expose them via xpra info
    def raw():
        return window.get_property(propname)
    if propname in ("title", "icon-title", "command", "content-type"):
        v = raw()
        if v is None:
            return {propname: ""}
        return {propname: v.encode("utf-8")}
    elif propname in ("pid", "workspace", "bypass-compositor", "depth"):
        v = raw()
        assert v is not None, "%s is None!" % propname
        if v<0 or (v==WORKSPACE_UNSET and propname=="workspace"):
            #meaningless
            return {}
        return {propname : v}
    elif propname == "size-hints":
        #just to confuse things, this is renamed
        #and we have to filter out ratios as floats (already exported as pairs anyway)
        v = dict((k,v) for k,v in raw().items() if k not in("max_aspect", "min_aspect"))
        return {"size-constraints": v}
    elif propname == "strut":
        strut = raw()
        if not strut:
            strut = {}
        else:
            strut = strut.todict()
        return {"strut": strut}
    elif propname == "class-instance":
        c_i = raw()
        if c_i is None:
            return {}
        return {"class-instance": [x.encode("utf-8") for x in c_i]}
    elif propname == "client-machine":
        client_machine = raw()
        if client_machine is None:
            import socket
            client_machine = socket.gethostname()
            if client_machine is None:
                return {}
        return {"client-machine": client_machine.encode("utf-8")}
    elif propname == "transient-for":
        wid = None
        if get_transient_for:
            wid = get_transient_for(window)
        if wid:
            return {"transient-for" : wid}
        return {}
    elif propname in ("window-type", "shape", "menu"):
        #always send unchanged:
        return {propname : raw()}
    elif propname in ("decorations", ):
        #-1 means unset, don't send it
        v = raw()
        if v<0:
            return {}
        return {propname : v}
    elif propname in ("iconic", "fullscreen", "maximized", "above", "below", "shaded", "sticky", "skip-taskbar", "skip-pager", "modal", "focused"):
        #always send these when requested
        return {propname : bool(raw())}
    elif propname in ("has-alpha", "override-redirect", "tray", "shadow", "set-initial-position"):
        v = raw()
        if v is False:
            #save space: all these properties are assumed false if unspecified
            return {}
        return {propname : v}
    elif propname in ("role", "opacity", "fullscreen-monitors"):
        v = raw()
        if v is None or v=="":
            return {}
        return {propname : v}
    elif propname == "xid":
        return {"xid" : hex(raw() or 0)}
    elif propname == "group-leader":
        gl = raw()
        if not gl or not get_window_id:
            return  {}
        xid, gdkwin = gl
        p = {}
        if xid:
            p["group-leader-xid"] = xid
        if gdkwin and get_window_id:
            glwid = get_window_id(gdkwin)
            if glwid:
                p["group-leader-wid"] = glwid
        return p
    #the properties below are not actually exported to the client (yet?)
    #it was just easier to handle them here
    #(convert to a type that can be encoded for xpra info):
    elif propname in ("state", "protocols"):
        return {"state" : tuple(raw() or [])}
    elif propname == "allowed-actions":
        return {"allowed-actions" : tuple(raw())}
    elif propname == "frame":
        frame = raw()
        if not frame:
            return {}
        return {"frame" : tuple(frame)}
    raise Exception("unhandled property name: %s" % propname)


class WindowPropertyFilter(object):
    def __init__(self, property_name, value):
        self.property_name = property_name
        self.value = value

    def get_window_value(self, window):
        return window.get_property(self.property_name)

    def show(self, window):
        try:
            v = self.get_window_value(window)
            log("%s.show(%s) %s(..)=%s", type(self).__name__, window, self.get_window_value, v)
        except Exception:
            log("%s.show(%s) %s(..) error:", type(self).__name__, window, self.get_window_value, exc_info=True)
            v = None
        e = self.evaluate(v)
        return e

    def evaluate(self, window_value):
        raise NotImplementedError()


class WindowPropertyIn(WindowPropertyFilter):

    def evaluate(self, window_value):
        return window_value in self.value


class WindowPropertyNotIn(WindowPropertyIn):

    def evaluate(self, window_value):
        return not(WindowPropertyIn.evaluate(window_value))


class ServerSource(FileTransferHandler):
    """
    A ServerSource represents a client connection.
    It mediates between the server class (which only knows about actual window objects and display server events)
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

    def __init__(self, protocol, disconnect_cb, idle_add, timeout_add, source_remove,
                 idle_timeout, idle_timeout_cb, idle_grace_timeout_cb,
                 socket_dir, unix_socket_paths, log_disconnect, dbus_control,
                 get_transient_for, get_focus, get_cursor_data_cb,
                 get_window_id,
                 window_filters,
                 file_transfer,
                 supports_mmap, mmap_filename,
                 bandwidth_limit,
                 av_sync,
                 core_encodings, encodings, default_encoding, scaling_control,
                 sound_properties,
                 sound_source_plugin,
                 supports_speaker, supports_microphone,
                 speaker_codecs, microphone_codecs,
                 default_quality, default_min_quality,
                 default_speed, default_min_speed):
        log("ServerSource%s", (protocol, disconnect_cb, idle_add, timeout_add, source_remove,
                 idle_timeout, idle_timeout_cb, idle_grace_timeout_cb,
                 socket_dir, unix_socket_paths, log_disconnect, dbus_control,
                 get_transient_for, get_focus,
                 get_window_id,
                 window_filters,
                 file_transfer,
                 supports_mmap, mmap_filename,
                 bandwidth_limit,
                 av_sync,
                 core_encodings, encodings, default_encoding, scaling_control,
                 sound_properties,
                 sound_source_plugin,
                 supports_speaker, supports_microphone,
                 speaker_codecs, microphone_codecs,
                 default_quality, default_min_quality,
                 default_speed, default_min_speed))
        FileTransferHandler.__init__(self, file_transfer)
        global counter
        self.counter = counter.increase()
        self.close_event = Event()
        self.ordinary_packets = []
        self.protocol = protocol
        self.disconnect = disconnect_cb
        self.idle_add = idle_add
        self.timeout_add = timeout_add
        self.source_remove = source_remove
        self.idle = False
        self.idle_timeout = idle_timeout
        self.idle_timeout_cb = idle_timeout_cb
        self.idle_grace_timeout_cb = idle_grace_timeout_cb
        self.idle_timer = None
        self.idle_grace_timer = None
        self.schedule_idle_grace_timeout()
        self.schedule_idle_timeout()
        self.socket_dir = socket_dir
        self.unix_socket_paths = unix_socket_paths
        self.log_disconnect = log_disconnect
        self.dbus_control = dbus_control
        self.dbus_server = None
        self.get_transient_for = get_transient_for
        self.get_focus = get_focus
        self.get_cursor_data_cb = get_cursor_data_cb
        self.get_window_id = get_window_id
        self.window_filters = window_filters
        # mmap:
        self.supports_mmap = supports_mmap
        self.mmap_filename = mmap_filename
        self.mmap = None
        self.mmap_size = 0
        self.mmap_client_token = None                   #the token we write that the client may check
        self.mmap_client_token_index = 512
        self.mmap_client_token_bytes = 0
        # network constraints:
        self.server_bandwidth_limit = bandwidth_limit
        # mouse echo:
        self.mouse_show = False
        self.mouse_last_position = None
        # sound:
        self.sound_properties = sound_properties
        self.sound_source_plugin = sound_source_plugin
        self.supports_speaker = supports_speaker
        self.speaker_codecs = speaker_codecs
        self.supports_microphone = supports_microphone
        self.microphone_codecs = microphone_codecs
        self.sound_source_sequence = 0
        self.sound_source = None
        self.sound_sink = None
        self.codec_full_names = False
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
        self.last_ping_echoed_time = 0
        self.check_ping_echo_timers = {}

        self.clipboard_progress_timer = None
        self.clipboard_stats = deque(maxlen=MAX_CLIPBOARD_LIMIT*MAX_CLIPBOARD_LIMIT_DURATION)

        self.init_vars()

        # ready for processing:
        protocol.set_packet_source(self.next_packet)
        self.encode_thread = start_thread(self.encode_loop, "encode")
        #dbus:
        if self.dbus_control:
            from xpra.server.dbus.dbus_common import dbus_exception_wrap
            def make_dbus_server():
                from xpra.server.dbus.dbus_source import DBUS_Source
                return DBUS_Source(self, os.environ.get("DISPLAY", "").lstrip(":"))
            self.dbus_server = dbus_exception_wrap(make_dbus_server, "setting up client dbus instance")


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

        self.uuid = ""
        self.machine_id = ""
        self.hostname = ""
        self.username = ""
        self.name = ""
        self.argv = ()
        # client capabilities/options:
        self.client_type = None
        self.client_version = None
        self.client_revision= None
        self.client_platform = None
        self.client_machine = None
        self.client_processor = None
        self.client_release = None
        self.client_proxy = False
        self.client_wm_name = None
        self.client_session_type = None
        self.client_session_type_full = None
        self.client_connection_data = {}
        self.auto_refresh_delay = 0
        self.info_namespace = False
        self.send_cursors = False
        self.cursor_encodings = ()
        self.send_bell = False
        self.send_notifications = False
        self.send_windows = True
        self.pointer_grabs = False
        self.randr_notify = False
        self.window_initiate_moveresize = False
        self.clipboard_enabled = False
        self.clipboard_notifications = False
        self.clipboard_notifications_current = 0
        self.clipboard_notifications_pending = 0
        self.clipboard_set_enabled = False
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
        self.printers = {}
        self.vrefresh = -1
        self.double_click_time  = -1
        self.double_click_distance = -1, -1
        self.bandwidth_limit = self.server_bandwidth_limit
        self.soft_bandwidth_limit = self.bandwidth_limit
        #what we send back in hello packet:
        self.ui_client = True
        self.wants_aliases = True
        self.wants_encodings = True
        self.wants_versions = True
        self.wants_features = True
        self.wants_display = True
        self.wants_sound = True
        self.wants_events = False
        self.wants_default_cursor = False
        #sound props:
        self.pulseaudio_id = None
        self.pulseaudio_server = None
        self.sound_decoders = ()
        self.sound_encoders = ()

        self.keyboard_config = None
        self.cursor_timer = None
        self.last_cursor_sent = None
        self.ping_timer = None
        self.sound_fade_timer = None

        #for managing the recalculate_delays work:
        self.calculate_window_pixels = {}
        self.calculate_window_ids = set()
        self.calculate_timer = 0
        self.calculate_last_time = 0


    def is_closed(self):
        return self.close_event.isSet()

    def close(self):
        log("%s.close()", self)
        FileTransferHandler.cleanup(self)
        self.close_event.set()
        for window_source in self.window_sources.values():
            window_source.cleanup()
        self.window_sources = {}
        #it is now safe to add the end of queue marker:
        #(all window sources will have stopped queuing data)
        self.encode_work_queue.put(None)
        #this should be a noop since we inherit an initialized helper:
        self.video_helper.cleanup()
        mmap = self.mmap
        if mmap:
            self.mmap = None
            self.mmap_size = 0
            mmap.close()
        self.cancel_recalculate_timer()
        self.cancel_ping_echo_timers()
        self.cancel_cursor_timer()
        self.cancel_ping_timer()
        self.cancel_sound_fade_timer()
        self.stop_sending_sound()
        self.stop_receiving_sound()
        self.remove_printers()
        self.cancel_clipboard_progress_timer()
        ds = self.dbus_server
        if ds:
            self.dbus_server = None
            self.idle_add(ds.cleanup)
        self.protocol = None


    def update_bandwidth_limits(self):
        if self.mmap_size>0:
            return
        #calculate soft bandwidth limit based on send congestion data:
        bandwidth_limit = 0
        if DETECT_BANDWIDTH_LIMIT:
            bandwidth_limit = self.statistics.avg_congestion_send_speed
            statslog("avg_congestion_send_speed=%s", bandwidth_limit)
            if bandwidth_limit>20*1024*1024:
                #ignore congestion speed if greater 20Mbps
                bandwidth_limit = 0
        if self.bandwidth_limit>0:
            #command line options could overrule what we detect?
            bandwidth_limit = min(self.bandwidth_limit, bandwidth_limit)
        self.soft_bandwidth_limit = bandwidth_limit
        statslog("update_bandwidth_limits() bandwidth_limit=%s, soft bandwidth limit=%s", self.bandwidth_limit, bandwidth_limit)
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
        log("update_bandwidth_limits() window weights=%s", window_weight)
        total_weight = sum(window_weight.values())
        for wid, ws in self.window_sources.items():
            weight = window_weight.get(wid)
            if weight is not None:
                ws.bandwidth_limit = max(1, bandwidth_limit*weight/total_weight)

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
        log("suspend(%s, %s) suspended=%s, sound_source=%s",
                  ui, wd, self.suspended, self.sound_source)
        if ui:
            self.suspended = True
        for wid in wd.keys():
            ws = self.window_sources.get(wid)
            if ws:
                ws.suspend()

    def resume(self, ui, wd):
        log("resume(%s, %s) suspended=%s, sound_source=%s",
                  ui, wd, self.suspended, self.sound_source)
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
            #grace timer is 90% of real timer:
            grace = int(self.idle_timeout*1000*GRACE_PERCENT/100)
            self.idle_grace_timer = self.timeout_add(grace, self.idle_grace_timedout)

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


    def parse_hello(self, c, min_mmap_size):
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
        self.wants_sound = c.boolget("wants_sound", True)
        self.wants_events = c.boolget("wants_events", False)
        self.wants_aliases = c.boolget("wants_aliases", True)
        self.wants_versions = c.boolget("wants_versions", True)
        self.wants_features = c.boolget("wants_features", True)
        self.wants_default_cursor = c.boolget("wants_default_cursor", False)

        self.default_batch_config.always = bool(batch_value("always", DamageBatchConfig.ALWAYS))
        self.default_batch_config.min_delay = batch_value("min_delay", DamageBatchConfig.MIN_DELAY, 0, 1000)
        self.default_batch_config.max_delay = batch_value("max_delay", DamageBatchConfig.MAX_DELAY, 1, 15000)
        self.default_batch_config.max_events = batch_value("max_events", DamageBatchConfig.MAX_EVENTS)
        self.default_batch_config.max_pixels = batch_value("max_pixels", DamageBatchConfig.MAX_PIXELS)
        self.default_batch_config.time_unit = batch_value("time_unit", DamageBatchConfig.TIME_UNIT, 1)
        self.default_batch_config.delay = batch_value("delay", DamageBatchConfig.START_DELAY, 0)
        log("default batch config: %s", self.default_batch_config)
        #client uuid:
        self.uuid = c.strget("uuid")
        self.machine_id = c.strget("machine_id")
        self.hostname = c.strget("hostname")
        self.username = c.strget("username")
        self.name = c.strget("name")
        self.argv = c.strlistget("argv")
        self.client_type = c.strget("client_type", "PyGTK")
        self.client_platform = c.strget("platform")
        self.client_machine = c.strget("platform.machine")
        self.client_processor = c.strget("platform.processor")
        self.client_release = c.strget("platform.sysrelease")
        self.client_version = c.strget("version")
        self.client_revision = c.strget("build.revision")
        self.client_proxy = c.boolget("proxy")
        self.client_wm_name = c.strget("wm_name")
        self.client_session_type = c.strget("session-type")
        self.client_session_type_full = c.strget("session-type.full", "")
        #file transfers and printing:
        self.parse_file_transfer_caps(c)
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
        self.randr_notify = c.boolget("randr_notify")
        self.mouse_show = c.boolget("mouse.show")
        self.mouse_last_position = c.intpair("mouse.initial-position")
        self.clipboard_enabled = c.boolget("clipboard", True)
        self.clipboard_notifications = c.boolget("clipboard.notifications")
        self.clipboard_set_enabled = c.boolget("clipboard.set_enabled")
        clipboardlog("client clipboard: enabled=%s, notifications=%s, set-enabled=%s", self.clipboard_enabled, self.clipboard_notifications, self.clipboard_set_enabled)
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
        netlog("server bandwidth-limit=%s, client bandwidth-limit=%s, value=%s", self.server_bandwidth_limit, bandwidth_limit, self.bandwidth_limit)

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

        #sound stuff:
        self.pulseaudio_id = c.strget("sound.pulseaudio.id")
        self.pulseaudio_server = c.strget("sound.pulseaudio.server")
        self.codec_full_names = c.boolget("sound.codec-full-names")
        try:
            if not self.codec_full_names:
                from xpra.sound.common import legacy_to_new as conv
            else:
                def conv(v):
                    return v
            self.sound_decoders = conv(c.strlistget("sound.decoders", []))
            self.sound_encoders = conv(c.strlistget("sound.encoders", []))
        except:
            soundlog("Error: cannot parse client sound codecs", exc_info=True)
        self.sound_receive = c.boolget("sound.receive")
        self.sound_send = c.boolget("sound.send")
        self.sound_bundle_metadata = c.boolget("sound.bundle-metadata")
        av_sync = c.boolget("av-sync")
        self.set_av_sync_delay(int(self.av_sync and av_sync) * c.intget("av-sync.delay.default", 150))
        soundlog("pulseaudio id=%s, server=%s, full-names=%s, sound decoders=%s, sound encoders=%s, receive=%s, send=%s",
                 self.pulseaudio_id, self.pulseaudio_server, self.codec_full_names, self.sound_decoders, self.sound_encoders, self.sound_receive, self.sound_send)
        avsynclog("av-sync: server=%s, client=%s, total=%s", self.av_sync, av_sync, self.av_sync_delay_total)
        log("cursors=%s (encodings=%s), bell=%s, notifications=%s", self.send_cursors, self.cursor_encodings, self.send_bell, self.send_notifications)
        log("client uuid %s", self.uuid)
        pinfo = ""
        if self.client_platform:
            pinfo = " %s" % platform_name(self.client_platform, c.strlistget("platform.linux_distribution") or self.client_release)
        if self.client_session_type:
            pinfo += " %s" % self.client_session_type
        revinfo = ""
        if self.client_revision:
            revinfo="-r%s" % self.client_revision
        bits = c.intget("python.bits")
        bitsstr = ""
        if bits:
            bitsstr = " %i-bit" % bits
        log.info("%s%s client version %s%s%s", std(self.client_type), pinfo, std(self.client_version), std(revinfo), bitsstr)
        msg = ""
        if self.hostname:
            msg += " connected from '%s'" % std(self.hostname)
        if self.username:
            msg += " as '%s'" % std(self.username)
            if self.name and self.name!=self.username:
                msg += " - '%s'" % std(self.name)
        if msg:
            log.info(msg)
        if c.boolget("proxy"):
            proxy_hostname = c.strget("proxy.hostname")
            proxy_platform = c.strget("proxy.platform")
            proxy_release = c.strget("proxy.platform.sysrelease")
            proxy_version = c.strget("proxy.version")
            proxy_version = c.strget("proxy.build.version", proxy_version)
            msg = "via %s proxy version %s" % (platform_name(proxy_platform, proxy_release), std(proxy_version or "unknown"))
            if proxy_hostname:
                msg += " on '%s'" % std(proxy_hostname)
            proxylog.info(msg)
            from xpra.version_util import version_compat_check
            msg = version_compat_check(proxy_version)
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
        self.window_icon_encodings = ["premult_argb32"]
        if "png" in self.core_encodings:
            self.window_icon_encodings.append("png")
        self.window_icon_encodings = c.strlistget("encodings.window-icon", self.window_icon_encodings)
        self.rgb_formats = c.strlistget("encodings.rgb_formats", ["RGB"])
        #skip all other encoding related settings if we don't send pixels:
        if not self.send_windows:
            log("windows/pixels forwarding is disabled for this client")
        else:
            self.parse_encoding_caps(c, min_mmap_size)
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


    def parse_encoding_caps(self, c, min_mmap_size):
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
        #mmap:
        mmap_filename = c.strget("mmap_file")
        mmap_size = c.intget("mmap_size", 0)
        mmaplog("client supplied mmap_file=%s", mmap_filename)
        mmap_token = c.intget("mmap_token")
        mmaplog("mmap supported=%s, token=%s", self.supports_mmap, mmap_token)
        if mmap_filename:
            if self.mmap_filename:
                mmaplog("using global server specified mmap file path: '%s'", self.mmap_filename)
                mmap_filename = self.mmap_filename
            if not self.supports_mmap:
                mmaplog("client enabled mmap but mmap mode is not supported", mmap_filename)
            elif WIN32 and mmap_filename.startswith("/"):
                mmaplog("mmap_file '%s' is a unix path", mmap_filename)
            elif not os.path.exists(mmap_filename):
                mmaplog("mmap_file '%s' cannot be found!", mmap_filename)
            else:
                from xpra.net.mmap_pipe import init_server_mmap, read_mmap_token, write_mmap_token, DEFAULT_TOKEN_INDEX, DEFAULT_TOKEN_BYTES
                self.mmap, self.mmap_size = init_server_mmap(mmap_filename, mmap_size)
                mmaplog("found client mmap area: %s, %i bytes - min mmap size=%i", self.mmap, self.mmap_size, min_mmap_size)
                if self.mmap_size>0:
                    index = c.intget("mmap_token_index", DEFAULT_TOKEN_INDEX)
                    count = c.intget("mmap_token_bytes", DEFAULT_TOKEN_BYTES)
                    v = read_mmap_token(self.mmap, index, count)
                    mmaplog("mmap_token=%#x, verification=%#x", mmap_token, v)
                    if v!=mmap_token:
                        log.warn("Warning: mmap token verification failed, not using mmap area!")
                        log.warn(" expected '%#x', found '%#x'", mmap_token, v)
                        self.mmap.close()
                        self.mmap = None
                        self.mmap_size = 0
                    elif self.mmap_size<min_mmap_size:
                        mmaplog.warn("Warning: client supplied mmap area is too small, discarding it")
                        mmaplog.warn(" we need at least %iMB and this area is %iMB", min_mmap_size//1024//1024, self.mmap_size//1024//1024)
                        self.mmap.close()
                        self.mmap = None
                        self.mmap_size = 0
                    else:
                        from xpra.os_util import get_int_uuid
                        self.mmap_client_token = get_int_uuid()
                        self.mmap_client_token_bytes = DEFAULT_TOKEN_BYTES
                        if c.intget("mmap_token_index"):
                            #we can write the token anywhere we want and tell the client,
                            #so write it right at the end:
                            self.mmap_client_token_index = self.mmap_size-self.mmap_client_token_bytes
                        else:
                            #use the expected default for older versions:
                            self.mmap_client_token_index = DEFAULT_TOKEN_INDEX
                        write_mmap_token(self.mmap, self.mmap_client_token, self.mmap_client_token_index, self.mmap_client_token_bytes)

        if self.mmap_size>0:
            mmaplog.info(" mmap is enabled using %sB area in %s", std_unit(self.mmap_size, unit=1024), mmap_filename)
        else:
            others = [x for x in self.core_encodings if x in self.server_core_encodings and x!=self.encoding]
            if self.encoding=="auto":
                s = "automatic picture encoding enabled"
            else:
                s = "using %s as primary encoding" % self.encoding
            if others:
                elog.info(" %s, also available:", s)
                elog.info("  %s", ", ".join(others))
            else:
                elog.warn(" %s")
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

    def start_sending_sound(self, codec=None, volume=1.0, new_stream=None, new_buffer=None, skip_client_codec_check=False):
        assert self.hello_sent
        soundlog("start_sending_sound(%s)", codec)
        if self.suspended:
            soundlog.warn("Warning: not starting sound whilst in suspended state")
            return None
        if not self.supports_speaker:
            soundlog.error("Error sending sound: support not enabled on the server")
            return None
        if self.sound_source:
            soundlog.error("Error sending sound: forwarding already in progress")
            return None
        if not self.sound_receive:
            soundlog.error("Error sending sound: support is not enabled on the client")
            return None
        if not self.codec_full_names:
            codec = NEW_CODEC_NAMES.get(codec, codec)
        if codec is None:
            codecs = [x for x in self.sound_decoders if x in self.speaker_codecs]
            if not codecs:
                soundlog.error("Error sending sound: no codecs in common")
                return None
            codec = codecs[0]
        elif codec not in self.speaker_codecs:
            soundlog.warn("Warning: invalid codec specified: %s", codec)
            return None
        elif (codec not in self.sound_decoders) and not skip_client_codec_check:
            soundlog.warn("Error sending sound: invalid codec '%s'", codec)
            soundlog.warn(" is not in the list of decoders supported by the client: %s", csv(self.sound_decoders))
            return None
        ss = None
        try:
            from xpra.sound.gstreamer_util import ALLOW_SOUND_LOOP, loop_warning
            if self.machine_id and self.machine_id==get_machine_id() and not ALLOW_SOUND_LOOP:
                #looks like we're on the same machine, verify it's a different user:
                if self.uuid==get_user_uuid():
                    loop_warning("speaker", self.uuid)
                    return None
            from xpra.sound.wrapper import start_sending_sound
            plugins = self.sound_properties.strlistget("plugins", [])
            ss = start_sending_sound(plugins, self.sound_source_plugin, None, codec, volume, True, [codec], self.pulseaudio_server, self.pulseaudio_id)
            self.sound_source = ss
            soundlog("start_sending_sound() sound source=%s", ss)
            if not ss:
                return None
            ss.sequence = self.sound_source_sequence
            ss.connect("new-buffer", new_buffer or self.new_sound_buffer)
            ss.connect("new-stream", new_stream or self.new_stream)
            ss.connect("info", self.sound_source_info)
            ss.connect("exit", self.sound_source_exit)
            ss.connect("error", self.sound_source_error)
            ss.start()
            return ss
        except Exception as e:
            soundlog.error("error setting up sound: %s", e, exc_info=True)
            self.stop_sending_sound()
            ss = None
            return None
        finally:
            if ss is None:
                #tell the client we're not sending anything:
                self.send_eos(codec)

    def sound_source_error(self, source, message):
        #this should be printed to stderr by the sound process already
        if source==self.sound_source:
            soundlog("sound source error: %s", message)

    def sound_source_exit(self, source, *args):
        soundlog("sound_source_exit(%s, %s)", source, args)
        if source==self.sound_source:
            self.stop_sending_sound()

    def sound_source_info(self, source, info):
        soundlog("sound_source_info(%s, %s)", source, info)

    def stop_sending_sound(self):
        ss = self.sound_source
        soundlog("stop_sending_sound() sound_source=%s", ss)
        if ss:
            self.sound_source = None
            self.send_eos(ss.codec, ss.sequence)
            ss.cleanup()

    def send_eos(self, codec, sequence=0):
        #tell the client this is the end:
        self.send("sound-data", codec, "", {"end-of-stream" : True,
                                            "sequence"      : sequence})


    def new_stream(self, sound_source, codec):
        if NEW_STREAM_SOUND:
            try:
                from xpra.platform.paths import get_resources_dir
                sample = os.path.join(get_resources_dir(), "bell.wav")
                soundlog("new_stream(%s, %s) sample=%s, exists=%s", sound_source, codec, sample, os.path.exists(sample))
                if os.path.exists(sample):
                    if POSIX:
                        sink = "alsasink"
                    else:
                        sink = "autoaudiosink"
                    cmd = ["gst-launch-1.0", "-q", "filesrc", "location=%s" % sample, "!", "decodebin", "!", "audioconvert", "!", sink]
                    import subprocess
                    proc = subprocess.Popen(cmd, close_fds=True)
                    soundlog("Popen(%s)=%s", cmd, proc)
                    from xpra.child_reaper import getChildReaper
                    getChildReaper().add_process(proc, "new-stream-sound", cmd, ignore=True, forget=True)
            except:
                pass
        soundlog("new_stream(%s, %s)", sound_source, codec)
        if self.sound_source!=sound_source:
            soundlog("dropping new-stream signal (current source=%s, signal source=%s)", self.sound_source, sound_source)
            return
        codec = codec or sound_source.codec
        if not self.codec_full_names:
            codec = LEGACY_CODEC_NAMES.get(codec, codec)
        sound_source.codec = codec
        #tell the client this is the start:
        self.send("sound-data", codec, "",
                  {
                   "start-of-stream"    : True,
                   "codec"              : codec,
                   "sequence"           : sound_source.sequence,
                   })
        self.update_av_sync_delay_total()

    def new_sound_buffer(self, sound_source, data, metadata, packet_metadata=[]):
        soundlog("new_sound_buffer(%s, %s, %s, %s) info=%s, suspended=%s",
                 sound_source, len(data or []), metadata, [len(x) for x in packet_metadata], sound_source.info, self.suspended)
        if self.sound_source!=sound_source or self.is_closed():
            soundlog("sound buffer dropped: from old source or closed")
            return
        if sound_source.sequence<self.sound_source_sequence:
            soundlog("sound buffer dropped: old sequence number: %s (current is %s)", sound_source.sequence, self.sound_source_sequence)
            return
        if packet_metadata:
            if not self.sound_bundle_metadata:
                #client does not support bundling, send packet metadata as individual packets before the main packet:
                for x in packet_metadata:
                    self.send_sound_data(sound_source, x)
                packet_metadata = ()
            else:
                #the packet metadata is compressed already:
                packet_metadata = Compressed("packet metadata", packet_metadata, can_inline=True)
        #don't drop the first 10 buffers
        can_drop_packet = (sound_source.info or {}).get("buffer_count", 0)>10
        self.send_sound_data(sound_source, data, metadata, packet_metadata, can_drop_packet)

    def send_sound_data(self, sound_source, data, metadata={}, packet_metadata=(), can_drop_packet=False):
        packet_data = [sound_source.codec, Compressed(sound_source.codec, data), metadata]
        if packet_metadata:
            assert self.sound_bundle_metadata
            packet_data.append(packet_metadata)
        sequence = sound_source.sequence
        if sequence>=0:
            metadata["sequence"] = sequence
        fail_cb = None
        if can_drop_packet:
            def sound_data_fail_cb():
                #ideally we would tell gstreamer to send an audio "key frame"
                #or synchronization point to ensure the stream recovers
                soundlog("a sound data buffer was not received and will not be resent")
            fail_cb = sound_data_fail_cb
        self._send(fail_cb, False, "sound-data", *packet_data)

    def stop_receiving_sound(self):
        ss = self.sound_sink
        soundlog("stop_receiving_sound() sound_sink=%s", ss)
        if ss:
            self.sound_sink = None
            ss.cleanup()


    def sound_control(self, action, *args):
        assert self.hello_sent
        action = bytestostr(action)
        soundlog("sound_control(%s, %s)", action, args)
        if action=="stop":
            if len(args)>0:
                try:
                    sequence = int(args[0])
                except ValueError:
                    msg = "sound sequence number '%s' is invalid" % args[0]
                    log.warn(msg)
                    return msg
                if sequence!=self.sound_source_sequence:
                    log.warn("sound sequence mismatch: %i vs %i", sequence, self.sound_source_sequence)
                    return "not stopped"
                soundlog("stop: sequence number matches")
            self.stop_sending_sound()
            return "stopped"
        elif action in ("start", "fadein"):
            codec = None
            if len(args)>0:
                codec = bytestostr(args[0])
            if action=="start":
                volume = 1.0
            else:
                volume = 0.0
            if not self.start_sending_sound(codec, volume):
                return "failed to start sound"
            if action=="fadein":
                delay = 1000
                if len(args)>1:
                    delay = max(1, min(10*1000, int(args[1])))
                step = 1.0/(delay/100.0)
                soundlog("sound_control fadein delay=%s, step=%1.f", delay, step)
                def fadein():
                    ss = self.sound_source
                    if not ss:
                        return False
                    volume = ss.get_volume()
                    soundlog("fadein() volume=%.1f", volume)
                    if volume<1.0:
                        volume = min(1.0, volume+step)
                        ss.set_volume(volume)
                    return volume<1.0
                self.cancel_sound_fade_timer()
                self.sound_fade_timer = self.timeout_add(100, fadein)
            msg = "sound started"
            if codec:
                msg += " using codec %s" % codec
            return msg
        elif action=="fadeout":
            assert self.sound_source, "no active sound source"
            delay = 1000
            if len(args)>0:
                delay = max(1, min(10*1000, int(args[0])))
            step = 1.0/(delay/100.0)
            soundlog("sound_control fadeout delay=%s, step=%1.f", delay, step)
            def fadeout():
                ss = self.sound_source
                if not ss:
                    return False
                volume = ss.get_volume()
                log("fadeout() volume=%.1f", volume)
                if volume>0:
                    ss.set_volume(max(0, volume-step))
                    return True
                self.stop_sending_sound()
                return False
            self.cancel_sound_fade_timer()
            self.sound_fade_timer = self.timeout_add(100, fadeout)
        elif action=="new-sequence":
            self.sound_source_sequence = int(args[0])
            return "new sequence is %s" % self.sound_source_sequence
        elif action=="sync":
            assert self.av_sync, "av-sync is not enabled"
            self.set_av_sync_delay(int(args[0]))
            return "av-sync delay set to %ims" % self.av_sync_delay
        elif action=="av-sync-delta":
            assert self.av_sync, "av-sync is not enabled"
            self.set_av_sync_delta(int(args[0]))
            return "av-sync delta set to %ims" % self.av_sync_delta
        #elif action=="quality":
        #    assert self.sound_source
        #    quality = args[0]
        #    self.sound_source.set_quality(quality)
        #    self.start_sending_sound()
        else:
            msg = "unknown sound action: %s" % action
            log.error(msg)
            return msg

    def cancel_sound_fade_timer(self):
        sft = self.sound_fade_timer
        if sft:
            self.sound_fade_timer = None
            self.source_remove(sft)

    def sound_data(self, codec, data, metadata, packet_metadata=()):
        soundlog("sound_data(%s, %s, %s, %s) sound sink=%s", codec, len(data or []), metadata, packet_metadata, self.sound_sink)
        if self.is_closed():
            return
        codec = NEW_CODEC_NAMES.get(codec, codec)
        if self.sound_sink is not None and codec!=self.sound_sink.codec:
            soundlog.info("sound codec changed from %s to %s", self.sound_sink.codec, codec)
            self.sound_sink.cleanup()
            self.sound_sink = None
        if metadata.get("end-of-stream"):
            soundlog("client sent end-of-stream, closing sound pipeline")
            self.stop_receiving_sound()
            return
        if not self.sound_sink:
            try:
                def sound_sink_error(*args):
                    soundlog("sound_sink_error%s", args)
                    soundlog.warn("stopping sound input because of error")
                    self.stop_receiving_sound()
                from xpra.sound.wrapper import start_receiving_sound
                codec = NEW_CODEC_NAMES.get(codec, codec)
                ss = start_receiving_sound(codec)
                if not ss:
                    return
                self.sound_sink = ss
                soundlog("sound_data(..) created sound sink: %s", self.sound_sink)
                ss.connect("error", sound_sink_error)
                ss.start()
                soundlog("sound_data(..) sound sink started")
            except Exception:
                soundlog.error("failed to setup sound", exc_info=True)
                return
        if packet_metadata:
            if not self.sound_properties.boolget("bundle-metadata"):
                for x in packet_metadata:
                    self.sound_sink.add_data(x)
                packet_metadata = ()
        self.sound_sink.add_data(data, metadata, packet_metadata)


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
            encoder_latency = 0
            ss = self.sound_source
            cinfo = ""
            if ss:
                try:
                    encoder_latency = ss.info.get("queue", {}).get("cur", 0)
                    avsynclog("server side queue level: %s", encoder_latency)
                    #get the latency from the source info, if it has it:
                    encoder_latency = ss.info.get("latency", -1)
                    if encoder_latency<0:
                        #fallback to hard-coded values:
                        from xpra.sound.gstreamer_util import ENCODER_LATENCY, RECORD_PIPELINE_LATENCY
                        encoder_latency = RECORD_PIPELINE_LATENCY + ENCODER_LATENCY.get(ss.codec, 0)
                    cinfo = "%s " % ss.codec
                except Exception as e:
                    encoder_latency = 0
                    avsynclog("failed to get encoder latency for %s: %s", ss.codec, e)
            self.av_sync_delay_total = min(1000, max(0, int(self.av_sync_delay) + self.av_sync_delta + encoder_latency))
            avsynclog("av-sync set to %ims (from client queue latency=%s, %sencoder latency=%s, delta=%s)", self.av_sync_delay_total, self.av_sync_delay, cinfo, encoder_latency, self.av_sync_delta)
        else:
            avsynclog("av-sync support is disabled, setting it to 0")
            self.av_sync_delay_total = 0
        for ws in self.window_sources.values():
            ws.set_av_sync_delay(self.av_sync_delay_total)


    def set_screen_sizes(self, screen_sizes):
        self.screen_sizes = screen_sizes or []
        log("client screen sizes: %s", screen_sizes)

    def set_desktops(self, desktops, desktop_names):
        self.desktops = desktops or 1
        self.desktop_names = desktop_names or []

    # Takes the name of a WindowModel property, and returns a dictionary of
    # xpra window metadata values that depend on that property
    def _make_metadata(self, window, propname):
        if propname not in self.metadata_supported:
            metalog("make_metadata: client does not support '%s'", propname)
            return {}
        return make_window_metadata(window, propname,
                                        get_transient_for=self.get_transient_for,
                                        get_window_id=self.get_window_id)

#
# Keyboard magic
#
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

#
# Functions for interacting with the network layer:
#
    def next_packet(self):
        """ Called by protocol.py when it is ready to send the next packet """
        packet, start_send_cb, end_send_cb, fail_cb, synchronous, have_more = None, None, None, None, True, False
        if not self.is_closed():
            if len(self.ordinary_packets)>0:
                packet, synchronous, fail_cb = self.ordinary_packets.pop(0)
            elif len(self.packet_queue)>0:
                packet, _, _, start_send_cb, end_send_cb, fail_cb = self.packet_queue.popleft()
            have_more = packet is not None and (len(self.ordinary_packets)>0 or len(self.packet_queue)>0)
        return packet, start_send_cb, end_send_cb, fail_cb, synchronous, have_more

    def send(self, *parts):
        """ This method queues non-damage packets (higher priority) """
        self._send(None, True, *parts)

    def send_async(self, *parts):
        self._send(None, False, *parts)

    def _send(self, fail_cb=None, synchronous=True, *parts):
        """ This method queues non-damage packets (higher priority) """
        #log.info("_send%s", (fail_cb, synchronous, parts))
        p = self.protocol
        if p:
            self.ordinary_packets.append((parts, synchronous, fail_cb))
            p.source_has_more()


    #client tells us about network connection status:
    def update_connection_data(self, data):
        netlog("update_connection_data(%s)", data)
        self.client_connection_data = data

#
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
        if self.wants_sound and self.sound_properties:
            sound_props = self.sound_properties.copy()
            #only translate codec names if the client doesn't understand new full names:
            if not self.codec_full_names:
                name_trans = new_to_legacy
            else:
                name_trans = no_legacy_names
            sound_props.update({
                                "codec-full-names"  : True,
                                "encoders"  : name_trans(self.speaker_codecs),
                                "decoders"  : name_trans(self.microphone_codecs),
                                "send"      : self.supports_speaker and len(self.speaker_codecs)>0,
                                "receive"   : self.supports_microphone and len(self.microphone_codecs)>0,
                                })
            updict(capabilities, "sound", sound_props)
        if self.wants_encodings and self.encoding:
            capabilities["encoding"] = self.encoding
        if self.wants_features:
            capabilities.update({
                         "mmap_enabled"         : self.mmap_size>0,
                         "auto_refresh_delay"   : self.auto_refresh_delay,
                         })
        if self.mmap_client_token:
            capabilities.update({
                "mmap_token"        : self.mmap_client_token,
                "mmap_token_index"  : self.mmap_client_token_index,
                "mmap_token_bytes"  : self.mmap_client_token_bytes,
                })
        #expose the "modifier_client_keycodes" defined in the X11 server keyboard config object,
        #so clients can figure out which modifiers map to which keys:
        if self.keyboard_config:
            mck = getattr(self.keyboard_config, "modifier_client_keycodes", None)
            if mck:
                capabilities["modifier_keycodes"] = mck
        self.send("hello", capabilities)
        self.hello_sent = True


    def get_info(self):
        lpe = 0
        if self.last_ping_echoed_time>0:
            lpe = int(monotonic_time()*1000-self.last_ping_echoed_time)
        info = {
                "protocol"          : "xpra",
                "version"           : self.client_version or "unknown",
                "revision"          : self.client_revision or "unknown",
                "platform_name"     : platform_name(self.client_platform, self.client_release),
                "session-type"      : self.client_session_type,
                "session-type.full" : self.client_session_type_full,
                "uuid"              : self.uuid,
                "idle_time"         : int(monotonic_time()-self.last_user_event),
                "idle"              : self.idle,
                "hostname"          : self.hostname,
                "argv"              : self.argv,
                "auto_refresh"      : self.auto_refresh_delay,
                "desktop_size"      : self.desktop_size or "",
                "desktops"          : self.desktops,
                "desktop_names"     : self.desktop_names,
                "connection_time"   : int(self.connection_time),
                "elapsed_time"      : int(monotonic_time()-self.connection_time),
                "last-ping-echo"    : lpe,
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
        info["file-transfers"] = FileTransferHandler.get_info(self)
        info["sound"] = self.get_sound_info()
        info["mmap"] = {
            "supported"     : self.supports_mmap,
            "enabled"       : self.mmap is not None,
            "size"          : self.mmap_size,
            "filename"      : self.mmap_filename or "",
            }
        info.update(self.get_features_info())
        info.update(self.get_screen_info())
        return info

    def get_screen_info(self):
        return get_screen_info(self.screen_sizes)

    def get_features_info(self):
        info = {}
        def battr(k, prop):
            info[k] = bool(getattr(self, prop))
        for prop in ("lock", "share", "randr_notify",
                     "clipboard_notifications", "system_tray",
                     "lz4", "lzo"):
            battr(prop, prop)
        for prop, name in {"clipboard_enabled"  : "clipboard",
                           "send_windows"       : "windows",
                           "send_cursors"       : "cursors",
                           "send_notifications" : "notifications",
                           "send_bell"          : "bell"}.items():
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
        if self.printers:
            info["printers"] = self.printers
        return info

    def get_sound_info(self):
        def sound_info(supported, prop, codecs):
            i = {"codecs" : codecs}
            if not supported:
                i["state"] = "disabled"
                return i
            if prop is None:
                i["state"] = "inactive"
                return i
            i.update(prop.get_info())
            return i
        info = {
                "speaker"       : sound_info(self.supports_speaker, self.sound_source, self.sound_decoders),
                "microphone"    : sound_info(self.supports_microphone, self.sound_sink, self.sound_encoders),
                }
        for prop in ("pulseaudio_id", "pulseaudio_server", "codec_full_names"):
            v = getattr(self, prop)
            if v is not None:
                info[prop] = v
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


    def send_server_event(self, *args):
        if self.wants_events:
            self.send("server-event", *args)


    def send_clipboard_enabled(self, reason=""):
        if not self.hello_sent:
            return
        self.send_async("set-clipboard-enabled", self.clipboard_enabled, reason)

    def cancel_clipboard_progress_timer(self):
        cpt = self.clipboard_progress_timer
        if cpt:
            self.clipboard_progress_timer = None
            self.source_remove(cpt)

    def send_clipboard_progress(self, count):
        if not self.clipboard_notifications or not self.hello_sent or self.clipboard_progress_timer:
            return
        #always set "pending" to the latest value:
        self.clipboard_notifications_pending = count
        #but send the latest value via a timer to tame toggle storms:
        def may_send_progress_update():
            self.clipboard_progress_timer = None
            if self.clipboard_notifications_current!=self.clipboard_notifications_pending:
                self.clipboard_notifications_current = self.clipboard_notifications_pending
                clipboardlog("sending clipboard-pending-requests=%s to %s", self.clipboard_notifications_current, self)
                self.send("clipboard-pending-requests", self.clipboard_notifications_current)
        delay = (count==0)*100
        self.clipboard_progress_timer = self.timeout_add(delay, may_send_progress_update)

    def send_clipboard(self, packet):
        if not self.clipboard_enabled or self.suspended or not self.hello_sent:
            return
        now = monotonic_time()
        self.clipboard_stats.append(now)
        if len(self.clipboard_stats)>=MAX_CLIPBOARD_LIMIT:
            event = self.clipboard_stats[-MAX_CLIPBOARD_LIMIT]
            elapsed = now-event
            clipboardlog("send_clipboard(..) elapsed=%.2f, clipboard_stats=%s", elapsed, self.clipboard_stats)
            if elapsed<1:
                msg = "more than %s clipboard requests per second!" % MAX_CLIPBOARD_LIMIT
                clipboardlog.warn("Warning: %s", msg)
                #disable if this rate is sustained for more than S seconds:
                events = [x for x in self.clipboard_stats if x>(now-MAX_CLIPBOARD_LIMIT_DURATION)]
                if len(events)>=MAX_CLIPBOARD_LIMIT*MAX_CLIPBOARD_LIMIT_DURATION:
                    clipboardlog.warn(" limit sustained for more than %i seconds,", MAX_CLIPBOARD_LIMIT_DURATION)
                    clipboardlog.warn(" the clipboard is now disabled")
                    self.clipboard_enabled = False
                    self.send_clipboard_enabled(msg)
                return
        #call compress_clibboard via the work queue:
        self.encode_work_queue.put((True, self.compress_clipboard, packet))

    def compress_clipboard(self, packet):
        #Note: this runs in the 'encode' thread!
        packet = list(packet)
        for i in range(len(packet)):
            v = packet[i]
            if type(v)==Compressible:
                packet[i] = self.compressed_wrapper(v.datatype, v.data)
        self.queue_packet(packet)


    def pointer_grab(self, wid):
        if self.pointer_grabs and self.hello_sent:
            self.send("pointer-grab", wid)

    def pointer_ungrab(self, wid):
        if self.pointer_grabs and self.hello_sent:
            self.send("pointer-ungrab", wid)


    def compressed_wrapper(self, datatype, data, min_saving=128):
        if self.zlib or self.lz4 or self.lzo:
            cw = compressed_wrapper(datatype, data, zlib=self.zlib, lz4=self.lz4, lzo=self.lzo, can_inline=False)
            if len(cw)+min_saving<=len(data):
                #the compressed version is smaller, use it:
                return cw
            #skip compressed version: fall through
        #we can't compress, so at least avoid warnings in the protocol layer:
        return Compressed(datatype, data, can_inline=True)

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
        self.send("cursor", *args)


    def bell(self, wid, device, percent, pitch, duration, bell_class, bell_id, bell_name):
        if not self.send_bell or self.suspended or not self.hello_sent:
            return
        self.send_async("bell", wid, device, percent, pitch, duration, bell_class, bell_id, bell_name)

    def notify(self, dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout):
        if not self.send_notifications:
            notifylog("client %s does not support notifications", self)
            return False
        if self.suspended:
            notifylog("client %s is suspended, notification not sent", self)
            return False
        if self.hello_sent:
            self.send_async("notify_show", dbus_id, int(nid), str(app_name), int(replaces_nid), str(app_icon), str(summary), str(body), int(expire_timeout))
        return True

    def notify_close(self, nid):
        if not self.send_notifications or self.suspended  or not self.hello_sent:
            return
        self.send("notify_close", nid)

    def set_deflate(self, level):
        self.send("set_deflate", level)


    def send_webcam_ack(self, device, frame, *args):
        if self.hello_sent:
            self.send_async("webcam-ack", device, frame, *args)

    def send_webcam_stop(self, device, message):
        if self.hello_sent:
            self.send_async("webcam-stop", device, message)


    def set_printers(self, printers, password_file, auth, encryption, encryption_keyfile):
        printlog("set_printers(%s, %s, %s, %s, %s) for %s", printers, password_file, auth, encryption, encryption_keyfile, self)
        if self.machine_id==get_machine_id() and not ADD_LOCAL_PRINTERS:
            self.printers = printers
            printlog("local client with identical machine id,")
            printlog(" not configuring local printers")
            return
        if not self.uuid:
            printlog.warn("Warning: client did not supply a UUID,")
            printlog.warn(" printer forwarding cannot be enabled")
            return
        from xpra.platform.pycups_printing import remove_printer
        #remove the printers no longer defined
        #or those whose definition has changed (and we will re-add them):
        for k in tuple(self.printers.keys()):
            cpd = self.printers.get(k)
            npd = printers.get(k)
            if cpd==npd:
                #unchanged: make sure we don't try adding it again:
                try:
                    del printers[k]
                except:
                    pass
                continue
            if npd is None:
                printlog("printer %s no longer exists", k)
            else:
                printlog("printer %s has been modified:", k)
                printlog(" was %s", cpd)
                printlog(" now %s", npd)
            #remove it:
            try:
                del self.printers[k]
                remove_printer(k)
            except Exception as e:
                printlog.error("Error: failed to remove printer %s:", k)
                printlog.error(" %s", e)
                del e
        #expand it here so the xpraforwarder doesn't need to import anything xpra:
        attributes = {"display"         : os.environ.get("DISPLAY"),
                      "source"          : self.uuid}
        def makeabs(filename):
            #convert to an absolute path since the backend may run as a different user:
            return os.path.abspath(os.path.expanduser(filename))
        if auth:
            auth_password_file = None
            try:
                name, authclass, authoptions = auth
                auth_password_file = authoptions.get("file")
                log("file for %s / %s: '%s'", name, authclass, password_file)
            except Exception as e:
                log.error("Error: cannot forward authentication attributes to printer backend:")
                log.error(" %s", e)
            if auth_password_file or password_file:
                attributes["password-file"] = makeabs(auth_password_file or password_file)
        if encryption:
            if not encryption_keyfile:
                log.error("Error: no encryption keyfile found for printing")
            else:
                attributes["encryption"] = encryption
                attributes["encryption-keyfile"] = makeabs(encryption_keyfile)
        #if we can, tell it exactly where to connect:
        if self.unix_socket_paths:
            #prefer sockets in public paths:
            spath = self.unix_socket_paths[0]
            for x in self.unix_socket_paths:
                if x.startswith("/tmp") or x.startswith("/var") or x.startswith("/run"):
                    spath = x
            attributes["socket-path"] = spath
        log("printer attributes: %s", attributes)
        for k,props in printers.items():
            if k not in self.printers:
                self.setup_printer(k, props, attributes)

    def setup_printer(self, name, props, attributes):
        from xpra.platform.pycups_printing import add_printer
        info = props.get("printer-info", "")
        attrs = attributes.copy()
        attrs["remote-printer"] = name
        attrs["remote-device-uri"] = props.get("device-uri")
        location = PRINTER_LOCATION_STRING
        if self.hostname:
            location = "on %s"
            if PRINTER_LOCATION_STRING:
                #ie: on FOO (via xpra)
                location = "on %s (%s)" % (self.hostname, PRINTER_LOCATION_STRING)
        try:
            def printer_added():
                #once the printer has been added, register it in the list
                #(so it will be removed on exit)
                printlog.info("the remote printer '%s' has been configured", name)
                self.printers[name] = props
            add_printer(name, props, info, location, attrs, success_cb=printer_added)
        except Exception as e:
            printlog.warn("Warning: failed to add printer %s: %s", name, e)
            printlog("setup_printer(%s, %s, %s)", name, props, attributes, exc_info=True)

    def remove_printers(self):
        if self.machine_id==get_machine_id() and not ADD_LOCAL_PRINTERS:
            return
        printers = self.printers.copy()
        self.printers = {}
        for k in printers:
            from xpra.platform.pycups_printing import remove_printer
            remove_printer(k)


    def send_client_command(self, *args):
        if self.hello_sent:
            self.send("control", *args)


    def rpc_reply(self, *args):
        if self.hello_sent:
            self.send("rpc-reply", *args)

    def ping(self):
        self.ping_timer = None
        #NOTE: all ping time/echo time/load avg values are in milliseconds
        now_ms = int(1000*monotonic_time())
        log("sending ping to %s with time=%s", self.protocol, now_ms)
        self.send_async("ping", now_ms)
        timeout = PING_TIMEOUT
        self.check_ping_echo_timers[now_ms] = self.timeout_add(timeout*1000, self.check_ping_echo_timeout, now_ms, timeout)

    def check_ping_echo_timeout(self, now_ms, timeout):
        try:
            del self.check_ping_echo_timers[now_ms]
        except:
            pass
        if self.last_ping_echoed_time<now_ms and not self.is_closed():
            self.disconnect(CLIENT_PING_TIMEOUT, "waited %s seconds without a response" % timeout)

    def cancel_ping_echo_timers(self):
        timers = self.check_ping_echo_timers.values()
        self.check_ping_echo_timers = {}
        for t in timers:
            self.source_remove(t)

    def process_ping(self, time_to_echo):
        l1,l2,l3 = 0,0,0
        cl = -1
        if PING_DETAILS:
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
        self.send_async("ping_echo", time_to_echo, l1, l2, l3, cl)
        #if the client is pinging us, ping it too:
        if not self.ping_timer:
            self.ping_timer = self.timeout_add(500, self.ping)

    def cancel_ping_timer(self):
        pt = self.ping_timer
        if pt:
            self.ping_timer = None
            self.source_remove(pt)


    def process_ping_echo(self, packet):
        echoedtime, l1, l2, l3, server_ping_latency = packet[1:6]
        timer = self.check_ping_echo_timers.get(echoedtime)
        if timer:
            try:
                self.source_remove(timer)
                del self.check_ping_echo_timers[echoedtime]
            except:
                pass
        self.last_ping_echoed_time = echoedtime
        client_ping_latency = monotonic_time()-echoedtime/1000.0
        self.statistics.client_ping_latency.append((monotonic_time(), client_ping_latency))
        self.client_load = l1, l2, l3
        if server_ping_latency>=0:
            self.statistics.server_ping_latency.append((monotonic_time(), server_ping_latency/1000.0))
        log("ping echo client load=%s, measured server latency=%s", self.client_load, server_ping_latency)

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

    def reset_window_filters(self):
        self.window_filters = [(uuid, f) for uuid, f in self.window_filters if uuid!=self.uuid]

    def get_all_window_filters(self):
        return [f for uuid, f in self.window_filters if uuid==self.uuid]

    def get_window_filter(self, object_name, property_name, operator, value):
        if object_name!="window":
            raise ValueError("invalid object name")
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
                              self.queue_size, self.call_in_encode_thread, self.queue_packet, self.compressed_wrapper,
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
    def queue_size(self):
        return self.encode_work_queue.qsize()

    def call_in_encode_thread(self, *fn_and_args):
        """
            This is used by WindowSource to queue damage processing to be done in the 'encode' thread.
            The 'encode_and_send_cb' will then add the resulting packet to the 'packet_queue' via 'queue_packet'.
        """
        self.statistics.compression_work_qsizes.append((monotonic_time(), self.encode_work_queue.qsize()))
        self.encode_work_queue.put(fn_and_args)

    def queue_packet(self, packet, wid=0, pixels=0, start_send_cb=None, end_send_cb=None, fail_cb=None):
        """
            Add a new 'draw' packet to the 'packet_queue'.
            Note: this code runs in the non-ui thread
        """
        now = monotonic_time()
        self.statistics.packet_qsizes.append((now, len(self.packet_queue)))
        if wid>0:
            self.statistics.damage_packet_qpixels.append((now, wid, sum(x[2] for x in tuple(self.packet_queue) if x[1]==wid)))
        self.packet_queue.append((packet, wid, pixels, start_send_cb, end_send_cb, fail_cb))
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
