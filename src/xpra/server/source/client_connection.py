# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2018 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import sleep
from threading import Event
from collections import deque
from queue import Queue

from xpra.make_thread import start_thread
from xpra.os_util import monotonic_time
from xpra.util import notypedict, envbool, envint, typedict, AtomicInteger
from xpra.net.compression import compressed_wrapper, Compressed
from xpra.server.source.source_stats import GlobalPerformanceStatistics
from xpra.server.source.stub_source_mixin import StubSourceMixin
from xpra.log import Logger

log = Logger("server")
notifylog = Logger("notify")
bandwidthlog = Logger("bandwidth")


BANDWIDTH_DETECTION = envbool("XPRA_BANDWIDTH_DETECTION", True)
MIN_BANDWIDTH = envint("XPRA_MIN_BANDWIDTH", 5*1024*1024)
AUTO_BANDWIDTH_PCT = envint("XPRA_AUTO_BANDWIDTH_PCT", 80)
assert 1<AUTO_BANDWIDTH_PCT<=100, "invalid value for XPRA_AUTO_BANDWIDTH_PCT: %i" % AUTO_BANDWIDTH_PCT
YIELD = envbool("XPRA_YIELD", False)

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

class ClientConnection(StubSourceMixin):

    def __init__(self, protocol, disconnect_cb, session_name,
                 setting_changed,
                 socket_dir, unix_socket_paths, log_disconnect, bandwidth_limit, bandwidth_detection,
                 ):
        global counter
        self.counter = counter.increase()
        self.protocol = protocol
        self.connection_time = monotonic_time()
        self.close_event = Event()
        self.disconnect = disconnect_cb
        self.session_name = session_name

        #holds actual packets ready for sending (already encoded)
        #these packets are picked off by the "protocol" via 'next_packet()'
        #format: packet, wid, pixels, start_send_cb, end_send_cb
        #(only packet is required - the rest can be 0/None for clipboard packets)
        self.packet_queue = deque()
        # the encode work queue is used by mixins that need to encode data before sending it,
        # ie: encodings and clipboard
        #this queue will hold functions to call to compress data (pixels, clipboard)
        #items placed in this queue are picked off by the "encode" thread,
        #the functions should add the packets they generate to the 'packet_queue'
        self.encode_work_queue = None
        self.encode_thread = None
        self.ordinary_packets = []
        self.socket_dir = socket_dir
        self.unix_socket_paths = unix_socket_paths
        self.log_disconnect = log_disconnect

        self.setting_changed = setting_changed
        # network constraints:
        self.server_bandwidth_limit = bandwidth_limit
        self.bandwidth_detection = bandwidth_detection

        #these statistics are shared by all WindowSource instances:
        self.statistics = GlobalPerformanceStatistics()

    def run(self):
        # ready for processing:
        self.queue_encode = self.start_queue_encode
        self.protocol.set_packet_source(self.next_packet)

    def __repr__(self) -> str:
        return  "%s(%i : %s)" % (type(self).__name__, self.counter, self.protocol)

    def init_state(self):
        self.hello_sent = False
        self.info_namespace = False
        self.send_notifications = False
        self.send_notifications_actions = False
        self.notification_callbacks = {}
        self.share = False
        self.lock = False
        self.control_commands = ()
        self.xdg_menu_update = False
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


    def is_closed(self) -> bool:
        return self.close_event.isSet()

    def cleanup(self):
        log("%s.close()", self)
        self.close_event.set()
        self.protocol = None
        self.statistics.reset(0)


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
        if not self.bandwidth_detection:
            return
        mmap_size = getattr(self, "mmap_size", 0)
        if mmap_size>0:
            return
        #calculate soft bandwidth limit based on send congestion data:
        bandwidth_limit = 0
        if BANDWIDTH_DETECTION:
            bandwidth_limit = self.statistics.avg_congestion_send_speed
            bandwidthlog("avg_congestion_send_speed=%s", bandwidth_limit)
            if bandwidth_limit>20*1024*1024:
                #ignore congestion speed if greater 20Mbps
                bandwidth_limit = 0
        if (self.bandwidth_limit or 0)>0:
            #command line options could overrule what we detect?
            bandwidth_limit = min(self.bandwidth_limit, bandwidth_limit)
        if bandwidth_limit>0:
            bandwidth_limit = max(MIN_BANDWIDTH, bandwidth_limit)
        self.soft_bandwidth_limit = bandwidth_limit
        bandwidthlog("update_bandwidth_limits() bandwidth_limit=%s, soft bandwidth limit=%s",
                     self.bandwidth_limit, bandwidth_limit)
        #figure out how to distribute the bandwidth amongst the windows,
        #we use the window size,
        #(we should use the number of bytes actually sent: framerate, compression, etc..)
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
        total_weight = max(1, sum(window_weight.values()))
        for wid, ws in self.window_sources.items():
            if bandwidth_limit==0:
                ws.bandwidth_limit = 0
            else:
                weight = window_weight.get(wid, 0)
                ws.bandwidth_limit = max(MIN_BANDWIDTH//10, bandwidth_limit*weight//total_weight)


    def parse_client_caps(self, c : typedict):
        #general features:
        self.info_namespace = c.boolget("info-namespace")
        self.send_notifications = c.boolget("notifications")
        self.send_notifications_actions = c.boolget("notifications.actions")
        log("notifications=%s, actions=%s", self.send_notifications, self.send_notifications_actions)
        self.share = c.boolget("share")
        self.lock = c.boolget("lock")
        self.control_commands = c.strtupleget("control_commands")
        self.xdg_menu_update = c.boolget("xdg-menu-update")
        bandwidth_limit = c.intget("bandwidth-limit", 0)
        server_bandwidth_limit = self.server_bandwidth_limit
        if self.server_bandwidth_limit is None:
            server_bandwidth_limit = self.get_socket_bandwidth_limit() or bandwidth_limit
        self.bandwidth_limit = min(server_bandwidth_limit, bandwidth_limit)
        if self.bandwidth_detection:
            self.bandwidth_detection = c.boolget("bandwidth-detection", True)
        self.client_connection_data = c.dictget("connection-data", {})
        self.jitter = typedict(self.client_connection_data).intget("jitter", 0)
        bandwidthlog("server bandwidth-limit=%s, client bandwidth-limit=%s, value=%s, detection=%s",
                     server_bandwidth_limit, bandwidth_limit, self.bandwidth_limit, self.bandwidth_detection)

        if getattr(self, "mmap_size", 0)>0:
            log("mmap enabled, ignoring bandwidth-limit")
            self.bandwidth_limit = 0
        #adjust max packet size if file transfers are enabled:
        #TODO: belongs in mixin:
        file_transfer = getattr(self, "file_transfer", None)
        if file_transfer:
            self.protocol.max_packet_size = max(self.protocol.max_packet_size, self.file_size_limit*1024*1024)

    def get_socket_bandwidth_limit(self) -> int:
        p = self.protocol
        if not p:
            return 0
        #auto-detect:
        pinfo = p.get_info()
        socket_speed = pinfo.get("socket", {}).get("device", {}).get("speed")
        if not socket_speed:
            return 0
        bandwidthlog("get_socket_bandwidth_limit() socket_speed=%s", socket_speed)
        #auto: use 80% of socket speed if we have it:
        return socket_speed*AUTO_BANDWIDTH_PCT//100 or 0


    def startup_complete(self):
        log("startup_complete()")
        self.send("startup-complete")


    #
    # The encode thread loop management:
    #
    def start_queue_encode(self, item):
        #start the encode work queue:
        #holds functions to call to compress data (pixels, clipboard)
        #items placed in this queue are picked off by the "encode" thread,
        #the functions should add the packets they generate to the 'packet_queue'
        self.encode_work_queue = Queue()
        self.queue_encode = self.encode_work_queue.put
        self.queue_encode(item)
        self.encode_thread = start_thread(self.encode_loop, "encode")

    def encode_queue_size(self) -> int:
        ewq = self.encode_work_queue
        if ewq is None:
            return 0
        return ewq.qsize()

    def call_in_encode_thread(self, *fn_and_args):
        """
            This is used by WindowSource to queue damage processing to be done in the 'encode' thread.
            The 'encode_and_send_cb' will then add the resulting packet to the 'packet_queue' via 'queue_packet'.
        """
        self.statistics.compression_work_qsizes.append((monotonic_time(), self.encode_queue_size()))
        self.queue_encode(fn_and_args)

    def queue_packet(self, packet, wid=0, pixels=0,
                     start_send_cb=None, end_send_cb=None, fail_cb=None, wait_for_more=False):
        """
            Add a new 'draw' packet to the 'packet_queue'.
            Note: this code runs in the non-ui thread
        """
        now = monotonic_time()
        self.statistics.packet_qsizes.append((now, len(self.packet_queue)))
        if wid>0:
            self.statistics.damage_packet_qpixels.append(
                (now, wid, sum(x[2] for x in tuple(self.packet_queue) if x[1]==wid))
                )
        self.packet_queue.append((packet, wid, pixels, start_send_cb, end_send_cb, fail_cb, wait_for_more))
        p = self.protocol
        if p:
            p.source_has_more()

    def encode_loop(self):
        """
            This runs in a separate thread and calls all the function callbacks
            which are added to the 'encode_work_queue'.
            Must run until we hit the end of queue marker,
            to ensure all the queued items get called,
            those that are marked as optional will be skipped when is_closed()
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
            if YIELD:
                sleep(0)

    ######################################################################
    # network:
    def next_packet(self):
        """ Called by protocol.py when it is ready to send the next packet """
        packet, start_send_cb, end_send_cb, fail_cb = None, None, None, None
        synchronous, have_more, will_have_more = True, False, False
        if not self.is_closed():
            if self.ordinary_packets:
                packet, synchronous, fail_cb, will_have_more = self.ordinary_packets.pop(0)
            elif self.packet_queue:
                packet, _, _, start_send_cb, end_send_cb, fail_cb, will_have_more = self.packet_queue.popleft()
            have_more = packet is not None and (self.ordinary_packets or self.packet_queue)
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


    ######################################################################
    # info:
    def get_info(self) -> dict:
        info = {
                "protocol"          : "xpra",
                "connection_time"   : int(self.connection_time),
                "elapsed_time"      : int(monotonic_time()-self.connection_time),
                "counter"           : self.counter,
                "hello-sent"        : self.hello_sent,
                "jitter"            : self.jitter,
                "bandwidth-limit"   : {
                    "detection"     : self.bandwidth_detection,
                    "actual"        : self.soft_bandwidth_limit or 0,
                    }
                }
        p = self.protocol
        if p:
            info.update({
                         "connection"       : p.get_info(),
                         })
        info.update(self.get_features_info())
        return info

    def get_features_info(self) -> dict:
        info = {
            "lock"  : bool(self.lock),
            "share" : bool(self.share),
            "notifications" : self.send_notifications,
            }
        return info


    def send_info_response(self, info):
        self.send_async("info-response", notypedict(info))


    def send_setting_change(self, setting, value):
        if self.client_setting_change:
            self.send_more("setting-change", setting, value)


    def send_server_event(self, *args):
        if self.wants_events:
            self.send_more("server-event", *args)


    ######################################################################
    # notifications:
    # Utility functions for mixins (makes notifications optional)
    def may_notify(self, nid, summary, body, actions=(), hints=None, expire_timeout=10*1000,
                   icon_name=None, user_callback=None):
        try:
            from xpra.platform.paths import get_icon_filename
            from xpra.notifications.common import parse_image_path
        except ImportError as e:
            notifylog("not sending notification: %s", e)
        else:
            icon_filename = get_icon_filename(icon_name)
            icon = parse_image_path(icon_filename) or ""
            self.notify("", nid, "Xpra", 0, "",
                        summary, body, actions, hints or {},
                        expire_timeout, icon, user_callback)

    def notify(self, dbus_id, nid, app_name, replaces_nid, app_icon,
               summary, body, actions, hints, expire_timeout, icon, user_callback=None):
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
        except UnicodeEncodeError:
            summary = str(summary)
        try:
            body = body.encode("utf8")
        except UnicodeEncodeError:
            body = str(body)
        if self.hello_sent:
            #Warning: actions and hints are send last because they were added later (in version 2.3)
            self.send_async("notify_show", dbus_id, nid, app_name, replaces_nid, app_icon,
                            summary, body, expire_timeout, icon, actions, hints)
        return True

    def notify_close(self, nid : int):
        if not self.send_notifications or self.suspended  or not self.hello_sent:
            return
        self.send_more("notify_close", nid)


    def set_deflate(self, level : int):
        self.send("set_deflate", level)


    def send_client_command(self, *args):
        if self.hello_sent:
            self.send_more("control", *args)


    def rpc_reply(self, *args):
        if self.hello_sent:
            self.send("rpc-reply", *args)
