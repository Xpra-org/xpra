# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time
from collections import deque
from threading import Event

from xpra.log import Logger, debug_if_env
log = Logger()
elog = debug_if_env(log, "XPRA_ENCODING_DEBUG")
soundlog = debug_if_env(log, "XPRA_SOUND_DEBUG")

from xpra.server.source_stats import GlobalPerformanceStatistics
from xpra.server.window_video_source import WindowVideoSource
from xpra.server.batch_config import DamageBatchConfig
from xpra.simple_stats import add_list_stats, std_unit
from xpra.scripts.config import python_platform
from xpra.codecs.loader import get_codec, has_codec, OLD_ENCODING_NAMES_TO_NEW, NEW_ENCODING_NAMES_TO_OLD
from xpra.net.protocol import compressed_wrapper, Compressed
from xpra.daemon_thread import make_daemon_thread
from xpra.os_util import platform_name, StringIOClass, thread, Queue, get_machine_id, get_user_uuid
from xpra.server.background_worker import add_work_item
from xpra.util import std, typedict


ALLOW_SOUND_LOOP = os.environ.get("XPRA_ALLOW_SOUND_LOOP", "0")=="1"
NOYIELD = os.environ.get("XPRA_YIELD") is None
debug = log.debug


def make_window_metadata(window, propname, generic_window_types=False, client_supports_png=False, get_transient_for=None, get_window_id=None):
    if propname in ("title", "icon-title"):
        v = window.get_property(propname)
        if v is None:
            return {propname: ""}
        return {propname: v.encode("utf-8")}
    elif propname == "pid":
        return {"pid" : window.get_property("pid") or -1}
    elif propname == "size-hints":
        hints_metadata = {}
        hints = window.get_property("size-hints")
        if hints is not None:
            hints_metadata = hints.to_dict()
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
        return {"icon": make_window_icon(surf, client_supports_png)}
    elif propname == "client-machine":
        client_machine = window.get_property("client-machine")
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
    elif propname == "window-type":
        window_types = window.get_property("window-type")
        assert window_types is not None, "window-type is not defined for %s" % window
        log("window_types=%s", window_types)
        wts = []
        for window_type in window_types:
            s = str(window_type)
            if generic_window_types:
                s = s.replace("_NET_WM_WINDOW_TYPE_", "").replace("_NET_WM_TYPE_", "")
            else:
                #for older clients: ensure values do have the prefix.
                #(shadow servers expose their root window as "NORMAL",
                #we handle all the legitimate values here for correctness):
                if s in ("NORMAL", "DIALOG", "MENU", "TOOLBAR", "SPLASH",
                         "UTILITY", "DOCK", "DESKTOP", "DROPDOWN_MENU",
                         "POPUP_MENU", "TOOLTIP", "NOTIFICATION", "COMBO", "DND"):
                    s = "_NET_WM_WINDOW_TYPE_"+s
            wts.append(s)
        log("window_types=%s", wts)
        return {"window-type" : wts}
    elif propname in ("has-alpha", "override-redirect", "tray", "modal", "fullscreen", "maximized"):
        return {propname : window.get_property(propname)}
    elif propname in ("role"):
        v = window.get_property(propname)
        if v is None:
            return {}
        return {propname : v}
    elif propname == "xid":
        return {"xid" : hex(window.get_property("xid") or 0)}
    elif propname == "group-leader":
        gl = window.get_property("group-leader")
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
    raise Exception("unhandled property name: %s" % propname)

def make_window_icon(surf, client_supports_png):
    pixel_data = surf.get_data()
    pixel_format = surf.get_format()
    stride = surf.get_stride()
    w = surf.get_width()
    h = surf.get_height()
    use_png = client_supports_png and has_codec("PIL")
    log("found new window icon: %sx%s, sending as png=%s", w, h, use_png)
    if use_png:
        return make_png_window_icon(client_supports_png, pixel_data, pixel_format, stride, w, h)
    return make_argb32_window_icon(pixel_data, pixel_format, stride, w, h)

def make_png_window_icon(client_supports_png, pixel_data, pixel_format, stride, w, h):
    PIL = get_codec("PIL")
    img = PIL.Image.frombuffer("RGBA", (w,h), pixel_data, "raw", "BGRA", 0, 1)
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
        img = img.resize((w,h), PIL.Image.ANTIALIAS)
    output = StringIOClass()
    img.save(output, 'PNG')
    raw_data = output.getvalue()
    output.close()
    return w, h, "png", str(raw_data)

def make_argb32_window_icon(pixel_data, pixel_format, stride, w, h):
    import cairo
    assert pixel_format == cairo.FORMAT_ARGB32
    assert stride == 4 * w
    return w, h, "premult_argb32", str(pixel_data)


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

    def __init__(self, protocol, disconnect_cb, idle_add, timeout_add, source_remove,
                 get_transient_for, get_focus,
                 get_window_id,
                 supports_mmap,
                 core_encodings, encodings, default_encoding,
                 supports_speaker, supports_microphone,
                 speaker_codecs, microphone_codecs,
                 default_quality, default_min_quality,
                 default_speed, default_min_speed):
        log("ServerSource%s", (protocol, disconnect_cb, idle_add, timeout_add, source_remove,
                 get_transient_for, get_focus,
                 get_window_id,
                 supports_mmap,
                 core_encodings, encodings, default_encoding,
                 supports_speaker, supports_microphone,
                 speaker_codecs, microphone_codecs,
                 default_quality, default_min_quality,
                 default_speed, default_min_speed))
        self.close_event = Event()
        self.ordinary_packets = []
        self.protocol = protocol
        self.disconnect = disconnect_cb
        self.idle_add = idle_add
        self.timeout_add = timeout_add
        self.source_remove = source_remove
        self.get_transient_for = get_transient_for
        self.get_focus = get_focus
        self.get_window_id = get_window_id
        # mmap:
        self.supports_mmap = supports_mmap
        self.mmap = None
        self.mmap_size = 0
        self.mmap_client_token = None                   #the token we write that the client may check
        # sound:
        self.supports_speaker = supports_speaker
        self.speaker_codecs = speaker_codecs
        self.supports_microphone = supports_microphone
        self.microphone_codecs = microphone_codecs
        self.sound_source_sequence = -1
        self.sound_source = None
        self.sound_sink = None

        self.server_core_encodings = core_encodings
        self.server_encodings = encodings
        self.default_encoding = default_encoding

        self.default_quality = default_quality      #default encoding quality for lossy encodings
        self.default_min_quality = default_min_quality #default minimum encoding quality
        self.default_speed = default_speed          #encoding speed (only used by x264)
        self.default_min_speed = default_min_speed  #default minimum encoding speed
        self.encoding = None                        #the default encoding for all windows
        self.encodings = []                         #all the encodings supported by the client
        self.core_encodings = []
        self.rgb_formats = ["RGB"]
        self.generic_rgb_encodings = False
        self.generic_encodings = False
        self.encoding_options = typedict()
        self.default_batch_config = DamageBatchConfig()     #contains default values, some of which may be supplied by the client
        self.global_batch_config = self.default_batch_config.clone()      #global batch config
        self.default_encoding_options = {}

        self.window_sources = {}                    #WindowSource for each Window ID
        self.suspended = False

        self.uuid = ""
        self.machine_id = ""
        self.hostname = ""
        self.username = ""
        self.name = ""
        self.connection_time = time.time()
        # client capabilities/options:
        self.client_type = None
        self.client_version = None
        self.client_platform = None
        self.client_machine = None
        self.client_processor = None
        self.client_release = None
        self.client_proxy = False
        self.auto_refresh_delay = 0
        self.server_window_resize = False
        self.send_cursors = False
        self.send_bell = False
        self.send_notifications = False
        self.send_windows = True
        self.window_raise = False
        self.randr_notify = False
        self.named_cursors = False
        self.clipboard_enabled = False
        self.clipboard_notifications = False
        self.clipboard_set_enabled = False
        self.share = False
        self.desktop_size = None
        self.screen_sizes = []
        self.raw_window_icons = False
        self.namespace = False
        self.system_tray = False
        self.generic_window_types = False
        self.notify_startup_complete = False
        self.control_commands = []
        #sound props:
        self.pulseaudio_id = None
        self.pulseaudio_server = None
        self.sound_decoders = []
        self.sound_encoders = []
        self.server_driven = False

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
        self.last_ping_echoed_time = 0
        # ready for processing:
        protocol.set_packet_source(self.next_packet)
        self.datapacket_thread = make_daemon_thread(self.data_to_packet, "encode")
        self.datapacket_thread.start()
        #for managing the recalculate_delays work:
        self.calculate_window_ids = set()
        self.calculate_due = False
        self.calculate_last_time = 0

    def __str__(self):
        return  "ServerSource(%s)" % self.protocol

    def is_closed(self):
        return self.close_event.isSet()


    def recalculate_delays(self):
        """ calls update_averages() on ServerSource.statistics (GlobalStatistics)
            and WindowSource.statistics (WindowPerformanceStatistics) for each window id in calculate_window_ids,
        """
        debug("recalculate_delays()")
        if self.is_closed():
            return
        self.statistics.update_averages()
        wids = list(self.calculate_window_ids)  #make a copy so we don't clobber new wids
        focus = self.get_focus()
        for wid in wids:
            self.calculate_window_ids.remove(wid)
            ws = self.window_sources.get(wid)
            if ws is None:
                continue
            try:
                ws.statistics.update_averages()
                ws.calculate_batch_delay(wid==focus)
                ws.reconfigure()
            except:
                log.error("error on window %s", wid, exc_info=True)
            if self.is_closed():
                return
            #allow other threads to run
            #(ideally this would be a low priority thread)
            time.sleep(0)
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
            self.global_batch_config.last_delays.append((now, delay))
            self.global_batch_config.delay = delay

    def may_recalculate(self, wid):
        self.calculate_window_ids.add(wid)
        if self.calculate_due:
            #already due
            return
        self.calculate_due = True
        def recalculate_work():
            self.calculate_due = False
            self.calculate_last_time = time.time()
            self.recalculate_delays()
        delta = time.time() - self.calculate_last_time
        RECALCULATE_DELAY = 1.0           #1s
        if delta>RECALCULATE_DELAY:
            add_work_item(recalculate_work)
        else:
            self.timeout_add(int(1000*(RECALCULATE_DELAY-delta)), add_work_item, recalculate_work)

    def close(self):
        self.close_event.set()
        self.damage_data_queue.put(None, block=False)
        for window_source in self.window_sources.values():
            window_source.cleanup()
        self.window_sources = {}
        if self.mmap:
            self.mmap.close()
            self.mmap = None
            self.mmap_size = 0
        self.stop_sending_sound()
        if self.protocol:
            self.protocol.close()
            self.protocol = None

    def suspend(self, ui, wd):
        log.debug("suspend(%s, %s) suspended=%s, sound_source=%s",
                  ui, wd, self.suspended, self.sound_source)
        if ui:
            self.suspended = True
        for wid in wd.keys():
            ws = self.window_sources.get(wid)
            if ws:
                ws.suspend()

    def resume(self, ui, wd):
        log.debug("resume(%s, %s) suspended=%s, sound_source=%s",
                  ui, wd, self.suspended, self.sound_source)
        if ui:
            self.suspended = False
        for wid, window in wd.items():
            ws = self.window_sources.get(wid)
            if ws:
                ws.resume(window)
        self.do_send_cursor()


    def user_event(self):
        self.last_user_event = time.time()

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
        self.default_batch_config.always = bool(batch_value("always", DamageBatchConfig.ALWAYS))
        self.default_batch_config.min_delay = batch_value("min_delay", DamageBatchConfig.MIN_DELAY, 0, 1000)
        self.default_batch_config.max_delay = batch_value("max_delay", DamageBatchConfig.MAX_DELAY, 1, 15000)
        self.default_batch_config.max_events = batch_value("max_events", DamageBatchConfig.MAX_EVENTS)
        self.default_batch_config.max_pixels = batch_value("max_pixels", DamageBatchConfig.MAX_PIXELS)
        self.default_batch_config.time_unit = batch_value("time_unit", DamageBatchConfig.TIME_UNIT, 1)
        self.default_batch_config.delay = batch_value("delay", DamageBatchConfig.START_DELAY, 0)
        log.debug("default batch config: %s", self.default_batch_config)
        #client uuid:
        self.uuid = c.strget("uuid")
        self.machine_id = c.strget("machine_id")
        self.hostname = c.strget("hostname")
        self.username = c.strget("username")
        self.name = c.strget("name")
        self.client_type = c.strget("client_type", "PyGTK")
        self.client_platform = c.strget("platform")
        self.client_machine = c.strget("platform.machine")
        self.client_processor = c.strget("platform.processor")
        self.client_release = c.strget("platform.release")
        self.client_version = c.strget("version")
        self.client_proxy = c.boolget("proxy")
        #general features:
        self.lz4 = c.boolget("lz4", False)
        self.send_windows = c.boolget("windows", True)
        self.window_raise = c.boolget("window.raise")
        self.server_window_resize = c.boolget("server-window-resize")
        self.send_cursors = self.send_windows and c.boolget("cursors")
        self.send_bell = c.boolget("bell")
        self.send_notifications = c.boolget("notifications")
        self.randr_notify = c.boolget("randr_notify")
        self.clipboard_enabled = c.boolget("clipboard", True)
        self.clipboard_notifications = c.boolget("clipboard.notifications")
        self.clipboard_set_enabled = c.boolget("clipboard.set_enabled")
        self.share = c.boolget("share")
        self.named_cursors = c.boolget("named_cursors")
        self.raw_window_icons = c.boolget("raw_window_icons")
        self.system_tray = c.boolget("system_tray")
        self.generic_window_types = c.boolget("generic_window_types")
        self.notify_startup_complete = c.boolget("notify-startup-complete")
        self.namespace = c.boolget("namespace")
        self.control_commands = c.strlistget("control_commands")

        self.desktop_size = c.intpair("desktop_size")
        self.set_screen_sizes(c.listget("screen_sizes"))

        #sound stuff:
        self.pulseaudio_id = c.strget("sound.pulseaudio.id")
        self.pulseaudio_server = c.strget("sound.pulseaudio.server")
        self.sound_decoders = c.strlistget("sound.decoders", [])
        self.sound_encoders = c.strlistget("sound.encoders", [])
        self.sound_receive = c.boolget("sound.receive")
        self.sound_send = c.boolget("sound.send")
        self.server_driven = c.boolget("sound.server_driven")
        soundlog("pulseaudio id=%s, server=%s, sound decoders=%s, sound encoders=%s, receive=%s, send=%s",
                 self.pulseaudio_id, self.pulseaudio_server, self.sound_decoders, self.sound_encoders, self.sound_receive, self.sound_send)

        log("cursors=%s, bell=%s, notifications=%s", self.send_cursors, self.send_bell, self.send_notifications)
        log("client uuid %s", self.uuid)
        msg = "%s %s client version %s" % (std(self.client_type), platform_name(self.client_platform, self.client_release), std(self.client_version))
        if self.hostname:
            msg += " connected from '%s'" % std(self.hostname)
        if self.username:
            msg += " as '%s'" % std(self.username)
            if self.name:
                msg += " ('%s')" % std(self.name)
        log.info(msg)
        if c.boolget("proxy"):
            proxy_hostname = c.strget("proxy.hostname")
            proxy_platform = c.strget("proxy.platform")
            proxy_release = c.strget("proxy.platform.release")
            proxy_version = c.strget("proxy.version")
            msg = "via %s proxy version %s" % (platform_name(proxy_platform, proxy_release), std(proxy_version))
            if proxy_hostname:
                msg += " on '%s'" % std(proxy_hostname)
            log.info(msg)
            from xpra.version_util import version_compat_check
            msg = version_compat_check(proxy_version)
            if msg:
                log.warn("Warning: proxy version may not be compatible: %s", msg)

        #keyboard:
        try:
            from xpra.x11.server_keyboard_config import KeyboardConfig
            self.keyboard_config = KeyboardConfig()
            self.keyboard_config.enabled = self.send_windows and c.boolget("keyboard", True)
            self.assign_keymap_options(c)
            self.keyboard_config.xkbmap_layout = c.strget("xkbmap_layout")
            self.keyboard_config.xkbmap_variant = c.strget("xkbmap_variant")
        except ImportError, e:
            log.error("failed to load keyboard support: %s", e)
            self.keyboard_config = None

        #encodings:
        def getenclist(k, default_value=[]):
            #deals with old servers and substitute old encoding names for the new ones
            v = c.strlistget(k, default_value)
            if not v:
                return v
            return [OLD_ENCODING_NAMES_TO_NEW.get(x, x) for x in v]
        self.encodings = getenclist("encodings")
        self.core_encodings = getenclist("encodings.core", self.encodings)
        self.rgb_formats = getenclist("encodings.rgb_formats", ["RGB"])
        self.generic_rgb_encodings = c.boolget("generic-rgb-encodings")
        self.generic_encodings = c.boolget("encoding.generic")
        #skip all other encoding related settings if we don't send pixels:
        if not self.send_windows:
            log.info("windows/pixels forwarding is disabled for this client")
        else:
            self.parse_encoding_caps(c)

    def parse_encoding_caps(self, c):
        self.set_encoding(c.strget("encoding", None), None)
        #encoding options (filter):
        #1: these properties are special cased here because we
        #defined their name before the "encoding." prefix convention,
        #or because we want to pass default values (zlib/lz4):
        for k,ek in {"initial_quality"          : "initial_quality",
                     "rgb24zlib"                : "rgb24zlib",
                     "encoding_client_options"  : "client_options",
                     "quality"                  : "quality",
                     "zlib"                     : "rgb_zlib",
                     "lz4"                      : "rgb_lz4",
                     }.items():
            if k in c:
                self.encoding_options[ek] = c.get(k)
        #2: standardized encoding options:
        for k, v in c.items():
            if k.startswith("encoding."):
                k = k[len("encoding."):]
                self.encoding_options[k] = v
        elog("encoding options: %s", self.encoding_options)

        q = c.intget("jpeg", self.default_quality)  #pre 0.7 versions
        q = self.encoding_options.intget("quality", q)         #0.7 onwards:
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
        mmap_token = c.intget("mmap_token")
        log("client supplied mmap_file=%s, mmap supported=%s, token=%s", mmap_filename, self.supports_mmap, mmap_token)
        if mmap_filename:
            if not self.supports_mmap:
                log.warn("client supplied an mmap_file: %s but mmap mode is not supported", mmap_filename)
            elif not os.path.exists(mmap_filename):
                log.warn("client supplied an mmap_file: %s but we cannot find it", mmap_filename)
            else:
                from xpra.net.mmap_pipe import init_server_mmap
                from xpra.os_util import get_int_uuid
                new_token = get_int_uuid()
                self.mmap, self.mmap_size = init_server_mmap(mmap_filename, mmap_token, new_token)
                if self.mmap_size>0:
                    self.mmap_client_token = new_token

        if self.mmap_size>0:
            log.info("mmap is enabled using %sB area in %s", std_unit(self.mmap_size, unit=1024), mmap_filename)
        else:
            others = [x for x in self.core_encodings if x in self.server_core_encodings and x!=self.encoding]
            log.info("using %s as primary encoding, also available: %s", self.encoding, ", ".join(others))

    def startup_complete(self):
        log("startup_complete()")
        if self.notify_startup_complete:
            self.send("startup-complete")

    def start_sending_sound(self, codec, volume=1.0):
        soundlog("start_sending_sound(%s)", codec)
        if self.suspended:
            log.warn("not starting sound as we are suspended")
            return
        if self.machine_id and self.machine_id==get_machine_id() and not ALLOW_SOUND_LOOP:
            #looks like we're on the same machine, verify it's a different user:
            if self.uuid==get_user_uuid():
                log.warn("cannot start sound: identical user environment as the server (loop)")
                return
        assert self.supports_speaker, "cannot send sound: support not enabled on the server"
        assert self.sound_source is None, "a sound source already exists"
        assert self.sound_receive, "cannot send sound: support is not enabled on the client"
        try:
            from xpra.sound.gstreamer_util import start_sending_sound
            self.sound_source = start_sending_sound(codec, volume, self.sound_decoders, self.microphone_codecs, self.pulseaudio_server, self.pulseaudio_id)
            soundlog("start_sending_sound() sound source=%s", self.sound_source)
            if self.sound_source:
                if self.server_driven:
                    #tell the client this is the start:
                    self.send("sound-data", self.sound_source.codec, "",
                              {"start-of-stream"    : True,
                               "codec"              : self.sound_source.codec,
                               "sequence"           : self.sound_source_sequence})
                self.sound_source.connect("new-buffer", self.new_sound_buffer)
                self.sound_source.start()
        except Exception, e:
            log.error("error setting up sound: %s", e)

    def stop_sending_sound(self):
        ss = self.sound_source
        soundlog("stop_sending_sound() sound_source=%s", ss)
        if ss:
            self.sound_source = None
            if self.server_driven:
                #tell the client this is the end:
                self.send("sound-data", ss.codec, "", {"end-of-stream" : True})
            def stop_sending_sound_thread(*args):
                soundlog("stop_sending_sound_thread(%s)", args)
                ss.cleanup()
                soundlog("stop_sending_sound_thread(%s) done", args)
            thread.start_new_thread(stop_sending_sound_thread, ())

    def new_sound_buffer(self, sound_source, data, metadata):
        soundlog("new_sound_buffer(%s, %s, %s) source=%s, suspended=%s, sequence=%s",
                 sound_source, len(data or []), metadata, self.sound_source, self.suspended, self.sound_source_sequence)
        if self.sound_source is None:
            return
        if self.sound_source_sequence>0:
            metadata["sequence"] = self.sound_source_sequence
        self.send("sound-data", self.sound_source.codec, Compressed(self.sound_source.codec, data), metadata)

    def stop_receiving_sound(self):
        ss = self.sound_sink
        soundlog("stop_receiving_sound() sound_sink=%s", ss)
        if ss:
            self.sound_sink = None
            def stop_receiving_sound_thread(*args):
                soundlog("stop_receiving_sound_thread() sound_sink=%s", ss)
                ss.cleanup()
                soundlog("stop_receiving_sound_thread() done")
            thread.start_new_thread(stop_receiving_sound_thread, ())


    def sound_control(self, action, *args):
        soundlog("sound_control(%s, %s)", action, args)
        if action=="stop":
            self.stop_sending_sound()
            return "stopped"
        elif action in ("start", "fadein"):
            codec = None
            if len(args)>0:
                codec = args[0]
            if action=="start":
                volume = 1.0
            else:
                volume = 0.0
            self.start_sending_sound(codec, volume)
            if action=="fadein":
                delay = 1000
                if len(args)>0:
                    delay = max(1, min(10*1000, int(args[0])))
                step = 1.0/(delay/100.0)
                log("sound_control fadein delay=%s, step=%1.f", delay, step)
                def fadein():
                    ss = self.sound_source
                    if not ss:
                        return False
                    volume = ss.get_volume()
                    log("fadein() volume=%.1f", volume)
                    if volume<1.0:
                        volume = min(1.0, volume+step)
                        ss.set_volume(volume)
                    return volume<1.0
                self.timeout_add(100, fadein)
            return "started %s" % codec
        elif action=="fadeout":
            assert self.sound_source, "no active sound source"
            delay = 1000
            if len(args)>0:
                delay = max(1, min(10*1000, int(args[0])))
            step = 1.0/(delay/100.0)
            log("sound_control fadeout delay=%s, step=%1.f", delay, step)
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
            self.timeout_add(100, fadeout)
        elif action=="new-sequence":
            self.sound_source_sequence = args[0]
            return "new sequence is %s" % self.sound_source_sequence
        #elif action=="quality":
        #    assert self.sound_source
        #    quality = args[0]
        #    self.sound_source.set_quality(quality)
        #    self.start_sending_sound()
        else:
            msg = "unknown sound action: %s" % action
            log.error(msg)
            return msg

    def sound_data(self, codec, data, metadata, *args):
        soundlog("sound_data(%s, %s, %s, %s) sound sink=%s", codec, len(data or []), metadata, args, self.sound_sink)
        if self.sound_sink is not None and codec!=self.sound_sink.codec:
            log.info("sound codec changed from %s to %s", self.sound_sink.codec, codec)
            self.sound_sink.cleanup()
            self.sound_sink = None
        if not self.sound_sink:
            try:
                def sound_sink_error(*args):
                    log.warn("stopping sound input because of error")
                    self.stop_receiving_sound()
                def sound_sink_overrun(*args):
                    log.warn("re-starting sound input because of overrun")
                    def sink_clean():
                        soundlog("sink_clean() sound_sink=%s", self.sound_sink)
                        if self.sound_sink:
                            self.sound_sink.cleanup()
                            self.sound_sink = None
                    self.idle_add(sink_clean)
                    #Note: the next sound packet will take care of starting a new pipeline
                from xpra.sound.sink import SoundSink
                self.sound_sink = SoundSink(codec=codec)
                soundlog("sound_data(..) created sound sink: %s", self.sound_sink)
                self.sound_sink.connect("error", sound_sink_error)
                self.sound_sink.connect("overrun", sound_sink_overrun)
                self.sound_sink.start()
                soundlog("sound_data(..) sound sink started")
            except Exception, e:
                log.error("failed to setup sound: %s", e)
                return
        self.sound_sink.add_data(data, metadata)

    def set_screen_sizes(self, screen_sizes):
        self.screen_sizes = screen_sizes or []
        log("client screen sizes: %s", screen_sizes)

    # Takes the name of a WindowModel property, and returns a dictionary of
    # xpra window metadata values that depend on that property
    def _make_metadata(self, wid, window, propname):
        return make_window_metadata(window, propname,
                                        generic_window_types=self.generic_window_types,
                                        client_supports_png=("png" in self.encodings),
                                        get_transient_for=self.get_transient_for,
                                        get_window_id=self.get_window_id)

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
        log("set_keymap%s", (current_keyboard_config, keys_pressed, force))
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
        encoding = OLD_ENCODING_NAMES_TO_NEW.get(encoding, encoding)
        if encoding:
            if encoding not in self.encodings:
                log.warn("client specified an encoding it does not support: %s, client supplied list: %s" % (encoding, self.encodings))
            #old clients (v0.9.x and earlier) only supported 'rgb24' as 'rgb' mode:
            if encoding=="rgb24":
                encoding = "rgb"
            if encoding not in self.server_encodings:
                log.error("encoding %s is not supported by this server! " \
                         "Will use the first commonly supported encoding instead", encoding)
                encoding = None
        else:
            elog("encoding not specified, will use the first match")
        if not encoding:
            #not specified or not supported, try server default
            if self.default_encoding and self.default_encoding in self.encodings:
                encoding = self.default_encoding
            else:
                #or find intersection of supported encodings:
                common = [e for e in self.encodings if e in self.server_encodings]
                elog("encodings supported by both ends: %s", common)
                if not common:
                    raise Exception("cannot find compatible encoding between "
                                    "client (%s) and server (%s)" % (self.encodings, self.server_encodings))
                encoding = common[0]
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
                ws.set_new_encoding(encoding)
        if not window_ids or self.encoding is None:
            self.encoding = encoding

    def hello(self, server_capabilities):
        capabilities = server_capabilities.copy()
        try:
            from xpra.sound.gstreamer_util import has_gst, add_gst_capabilities
        except:
            has_gst = False
        if has_gst:
            try:
                from xpra.sound.pulseaudio_util import add_pulseaudio_capabilities
                add_pulseaudio_capabilities(capabilities)
                add_gst_capabilities(capabilities,
                                     receive=self.supports_microphone, send=self.supports_speaker,
                                     receive_codecs=self.speaker_codecs, send_codecs=self.microphone_codecs,
                                     new_namespace=self.namespace)
                log("sound capabilities: %s", [(k,v) for k,v in capabilities.items() if k.startswith("sound.")])
            except Exception, e:
                log.error("failed to setup sound: %s", e)
        if self.send_windows:
            assert self.encoding
            encoding = self.encoding
            if not self.generic_encodings:
                #translate back into the legacy names:
                encoding = NEW_ENCODING_NAMES_TO_OLD.get(encoding, encoding)
            capabilities["encoding"] = encoding
        capabilities.update({
                     "mmap_enabled"         : self.mmap_size>0,
                     "auto_refresh_delay"   : self.auto_refresh_delay,
                     })
        if self.mmap_client_token:
            capabilities["mmap_token"] = self.mmap_client_token
        if self.keyboard_config:
            capabilities["modifier_keycodes"] = self.keyboard_config.modifier_client_keycodes
        self.rewrite_encoding_values(capabilities)
        self.send("hello", capabilities)

    def add_info(self, info, suffix=""):
        if self.namespace:
            k = "server.python.version"
        else:
            k = "python_version"
        info[k] = python_platform.python_version()
        def cv(name, v):
            info["client."+name+suffix] = v
        def cvs(update):
            for k,v in update.items():
                cv(k, v)
        def addattr(k, name):
            try:
                v = getattr(self, name)
                if v is not None:
                    cv(k, v)
            except:
                log.warn("cannot add attribute %s / %s", k, name, exc_info=True)
        cv("version", self.client_version or "unknown")
        for x in ("type", "platform", "release", "machine", "processor", "proxy"):
            addattr(x, "client_" + x)
        cvs({
             "platform_name"      : platform_name(self.client_platform, self.client_release),
             "uuid"               : self.uuid,
             "idle_time"          : int(time.time()-self.last_user_event),
             "hostname"           : self.hostname,
             "auto_refresh"       : self.auto_refresh_delay,
             "desktop_size"       : self.desktop_size or "",
             "connection_time"    : int(self.connection_time),
             "elapsed_time"       : int(time.time()-self.connection_time),
             "suspended"          : self.suspended,
             })
        #= time.time()
        #self.start_time = time.time()
        if self.screen_sizes:
            info["client.screens" + suffix] = len(self.screen_sizes)
            i = 0
            for x in self.screen_sizes:
                if type(x) not in (tuple, list):
                    #legacy clients:
                    cv("screen[%s]=" % i, str(x))
                    continue
                cv("screen[%s].display" % i, x[0])
                if len(x)>=3:
                    cv("screen[%s].size" % i, (x[1], x[2]))
                if len(x)>=5:
                    cv("screen[%s].size_mm" % i, (x[3], x[4]))
                if len(x)>=6:
                    monitors = x[5]
                    j = 0
                    for monitor in monitors:
                        if len(monitor)>=7:
                            cv("screen[%s].monitor[%s].name" % (i, j), monitor[0])
                            cv("screen[%s].monitor[%s].geometry" % (i, j), monitor[1:5])
                            cv("screen[%s].monitor[%s].size_mm" % (i, j), monitor[5:7])
                        j += 1
                if len(x)>=10:
                    cv("screen[%s].workarea" % i, x[6:10])
                i += 1
        for prop in ("named_cursors", "server_window_resize", "share", "randr_notify",
                     "clipboard_notifications", "raw_window_icons", "system_tray", "generic_window_types",
                     "notify_startup_complete", "namespace", "lz4"):
            addattr("features."+prop, prop)
        for prop, name in {"clipboard_enabled"  : "clipboard",
                           "send_windows"       : "windows",
                           "send_cursors"       : "cursors",
                           "send_notifications" : "notifications",
                           "send_bell"          : "bell"}.items():
            addattr("features."+name, prop)
        #encoding:
        cvs({
             "encodings"         : self.encodings,
             "encodings.core"    : self.core_encodings,
             "encoding.default"  : self.default_encoding or ""
             })
        for k,v in self.default_encoding_options.items():
            cv("encoding.%s" % k, v)
        for k,v in self.encoding_options.items():
            cv("encoding.%s" % k, v)
        def get_sound_info(supported, prop):
            if not supported:
                return {"state" : "disabled"}
            if prop is None:
                return {"state" : "inactive"}
            return prop.get_info()
        #sound:
        for prop in ("pulseaudio_id", "pulseaudio_server"):
            addattr(prop, prop)
        for k,v in get_sound_info(self.supports_speaker, self.sound_source).items():
            cv("speaker.%s" % k, v)
        for k,v in get_sound_info(self.supports_microphone, self.sound_sink).items():
            cv("microphone.%s" % k, v)

    def send_info_response(self, info):
        self.rewrite_encoding_values(info)
        self.send("info-response", info)


    def rewrite_encoding_values(self, d):
        """
            The server class does not know
            what encoding name values the client supports.
            (this is used for patching the contents of "hello" and "info" packets for older clients)
        """
        replace = {}
        if not self.generic_rgb_encodings:
            replace["rgb"] = ("rgb24", "rgb32")
        if not self.generic_encodings:
            replace["h264"] = ("x264", )
            replace["vp8"] = ("vpx", )
        if len(replace)==0:
            return
        #filter only "encodings.*" keys:
        for k in [x for x in d.keys() if x=="encodings" or x.startswith("encodings.")]:
            v = d.get(k)
            if type(v) not in (list, tuple):
                continue
            l = list(v)
            newlist = l
            for new_encoding_name, old_encoding_names in replace.items():
                if new_encoding_name not in l:
                    continue
                p = newlist.index(new_encoding_name)
                newlist = newlist[:p] + list(old_encoding_names) + newlist[p+1:]
            if l!=newlist:
                d[k] = newlist
                debug("rewrite_encoding_values for key '%s': %s replaced by %s", k, l, newlist)


    def send_clipboard_enabled(self, reason=""):
        self.send("set-clipboard-enabled", self.clipboard_enabled, reason)

    def send_clipboard(self, packet):
        if not self.clipboard_enabled or self.suspended:
            return
        self.send(*packet)

    def send_cursor(self, cursor_data):
        if not self.send_cursors or self.suspended:
            return
        self.cursor_data = cursor_data
        if not self.send_cursor_pending:
            self.send_cursor_pending = True
            delay = max(10, int(self.global_batch_config.delay*4))
            self.timeout_add(delay, self.do_send_cursor)

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
        if not self.send_bell or self.suspended:
            return
        self.send("bell", wid, device, percent, pitch, duration, bell_class, bell_id, bell_name)

    def notify(self, dbus_id, nid, app_name, replaces_nid, app_icon, summary, body, expire_timeout):
        if not self.send_notifications or self.suspended:
            return
        self.send("notify_show", dbus_id, int(nid), str(app_name), int(replaces_nid), str(app_icon), str(summary), str(body), int(expire_timeout))

    def notify_close(self, nid):
        if not self.send_notifications or self.suspended:
            return
        self.send("notify_close", nid)

    def set_deflate(self, level):
        self.send("set_deflate", level)


    def send_client_command(self, *args):
        self.send("control", *args)


    def rpc_reply(self, *args):
        self.send("rpc-reply", *args)

    def ping(self):
        #NOTE: all ping time/echo time/load avg values are in milliseconds
        now_ms = int(1000*time.time())
        log("sending ping to %s with time=%s", self.protocol, now_ms)
        self.send("ping", now_ms)
        timeout = 60
        def check_echo_timeout(*args):
            if self.last_ping_echoed_time<now_ms and not self.is_closed():
                self.disconnect("client ping timeout, - waited %s seconds without a response" % timeout)
        self.timeout_add(timeout*1000, check_echo_timeout)

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
        self.timeout_add(500, self.ping)

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
        metadata = {}
        for propname in list(window.get_property_names()):
            metadata.update(self._make_metadata(wid, window, propname))
        self.send("new-tray", wid, w, h, metadata)

    def new_window(self, ptype, wid, window, x, y, w, h, client_properties):
        if not self.can_send_window(window):
            return
        send_props = list(window.get_property_names())
        send_raw_icon = self.raw_window_icons and "icon" in send_props
        if send_raw_icon:
            send_props.remove("icon")
        metadata = {}
        for propname in send_props:
            metadata.update(self._make_metadata(wid, window, propname))
        log("new_window(%s, %s, %s, %s, %s, %s, %s, %s) metadata=%s", ptype, window, wid, x, y, w, h, client_properties, metadata)
        self.send(ptype, wid, x, y, w, h, metadata, client_properties or {})
        if send_raw_icon:
            self.send_window_icon(wid, window)

    def send_window_icon(self, wid, window):
        surf = window.get_property("icon")
        log("send_window_icon(%s,%s) icon=%s", window, wid, surf)
        if surf is not None:
            w, h, pixel_format, pixel_data = make_window_icon(surf, ("png" in self.encodings))
            assert pixel_format in ("premult_argb32", "png")
            if pixel_format=="premult_argb32":
                data = compressed_wrapper("argb32", pixel_data)
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

    def unmap_window(self, wid, window):
        ws = self.window_sources.get(wid)
        if ws:
            ws.unmap()

    def raise_window(self, wid, window):
        if self.window_raise:
            self.send("raise-window", wid)

    def remove_window(self, wid, window):
        """ The given window is gone, ensure we free all the related resources """
        if not self.can_send_window(window):
            return
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
        info["damage.data_queue.size%s.current" % suffix] = self.damage_data_queue.qsize()
        info["damage.packet_queue.size%s.current" % suffix] = len(self.damage_packet_queue)
        qpixels = [x[2] for x in list(self.damage_packet_queue)]
        add_list_stats(info, "damage_packet_queue_pixels"+suffix,  qpixels)
        if len(qpixels)>0:
            info["damage_packet_queue_pixels%s.current" % suffix] = qpixels[-1]

        self.protocol.add_stats(info, prefix="client.connection.", suffix=suffix)
        self.statistics.add_stats(info, suffix=suffix)
        if len(window_ids)>0:
            total_pixels = 0
            total_time = 0.0
            in_latencies = []
            out_latencies = []
            for wid in window_ids:
                ws = self.window_sources.get(wid)
                if ws is None:
                    continue
                #per-window source stats:
                ws.add_stats(info, suffix=suffix)
                #collect stats for global averages:
                for _, pixels, _, _, encoding_time in list(ws.statistics.encoding_stats):
                    total_pixels += pixels
                    total_time += encoding_time
                in_latencies += [x*1000 for _, _, _, x in list(ws.statistics.damage_in_latency)]
                out_latencies += [x*1000 for _, _, _, x in list(ws.statistics.damage_out_latency)]
            v = 0
            if total_time>0:
                v = int(total_pixels / total_time)
            info["encoding.pixels_encoded_per_second"+suffix] = v
            add_list_stats(info, "damage.in_latency",  in_latencies, show_percentile=[9])
            add_list_stats(info, "damage.out_latency",  out_latencies, show_percentile=[9])
        self.global_batch_config.add_stats(info, "", suffix)

    def reconfigure(self, force_reload=False):
        for ws in self.window_sources.values():
            ws.reconfigure(force_reload)

    def set_min_quality(self, min_quality):
        self.default_encoding_options["min-quality"] = min_quality
        elog("set_min_quality(%s) default_encoding_options=%s", min_quality, self.default_encoding_options)
        self.reconfigure()

    def set_quality(self, quality):
        if quality<=0:
            if "quality" in self.default_encoding_options:
                del self.default_encoding_options["quality"]
        else:
            self.default_encoding_options["quality"] = max(quality, self.default_encoding_options.get("min-quality", 0))
        elog("set_quality(%s) default_encoding_options=%s", quality, self.default_encoding_options)
        self.reconfigure()

    def set_min_speed(self, min_speed):
        self.default_encoding_options["min-speed"] = min_speed
        elog("set_min_speed(%s) default_encoding_options=%s", min_speed, self.default_encoding_options)
        self.reconfigure()

    def set_speed(self, speed):
        prev_speed = self.default_encoding_options.get("speed", 0)
        if speed<=0:
            if "speed" in self.default_encoding_options:
                del self.default_encoding_options["speed"]
        else:
            self.default_encoding_options["speed"] = max(speed, self.default_encoding_options.get("min-speed", 0))
        elog("set_speed(%s) prev_speed=%s, default_encoding_options=%s", speed, prev_speed, self.default_encoding_options)
        self.reconfigure(force_reload=(speed>99 and prev_speed<=99) or (speed<=99 and prev_speed>99))

    def refresh(self, wid, window, opts):
        if not self.can_send_window(window):
            return
        self.cancel_damage(wid, window)
        w, h = window.get_dimensions()
        self.damage(wid, window, 0, 0, w, h, opts)

    def set_client_properties(self, wid, window, new_client_properties):
        ws = self.make_window_source(wid, window)
        ws.set_client_properties(new_client_properties)

    def make_window_source(self, wid, window):
        ws = self.window_sources.get(wid)
        if ws is None:
            batch_config = self.global_batch_config.clone()
            batch_config.wid = wid
            ws = WindowVideoSource(self.idle_add, self.timeout_add, self.source_remove,
                              self.queue_damage, self.queue_packet,
                              self.statistics,
                              wid, window, batch_config, self.auto_refresh_delay,
                              self.server_core_encodings, self.server_encodings,
                              self.encoding, self.encodings, self.core_encodings, self.encoding_options, self.rgb_formats,
                              self.default_encoding_options,
                              self.mmap, self.mmap_size)
            self.window_sources[wid] = ws
        return ws

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
        ws = self.make_window_source(wid, window)
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
