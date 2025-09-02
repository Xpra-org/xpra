# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from typing import Any, TypeAlias
from collections.abc import Callable, Sequence
from time import sleep, monotonic
from threading import Event
from collections import deque
from queue import SimpleQueue

from xpra.util.thread import start_thread
from xpra.common import FULL_INFO, noop, BACKWARDS_COMPATIBLE
from xpra.util.objects import AtomicInteger, typedict, notypedict
from xpra.util.env import envbool
from xpra.net.common import Packet, PacketElement
from xpra.net.compression import compressed_wrapper, Compressed, LevelCompressed
from xpra.server.source.source_stats import GlobalPerformanceStatistics
from xpra.server.source.stub import StubClientConnection
from xpra.log import Logger

log = Logger("server")
notifylog = Logger("notify")

YIELD = envbool("XPRA_YIELD", False)

counter = AtomicInteger()

ENCODE_WORK_ITEM_TUPLE = tuple[bool, Callable, Sequence[Any]]
ENCODE_WORK_ITEM: TypeAlias = ENCODE_WORK_ITEM_TUPLE | None


class ClientConnection(StubClientConnection):
    """
    This class mediates between the server class
    (which only knows about actual window objects and display server events)
    and the client specific WindowSource instances (which only know about window ids
    and manage window pixel compression).
    It sends messages to the client via its 'protocol' instance (the network connection),
    directly for a number of cases (cursor, audio, notifications, etc.)
    or on behalf of the window sources for pixel data.

    Strategy: if we have 'ordinary_packets' to send, send those.
    When we don't, then send packets from the 'packet_queue'. (compressed pixels or clipboard data)
    See 'next_packet'.

    The UI thread calls damage(), which goes into WindowSource and eventually (batching may be involved)
    adds the damage pixels ready for processing to the encode_work_queue,
    items are picked off by the separate 'encode' thread (see 'encode_loop')
    and added to the damage_packet_queue.
    """

    def __init__(self, protocol, disconnect_cb: Callable, setting_changed: Callable[[str, Any], None]):
        StubClientConnection.__init__(self)
        self.counter = counter.increase()
        self.protocol = protocol
        self.connection_time = monotonic()
        self.close_event = Event()
        self.disconnect = disconnect_cb

        # holds actual packets ready for sending (already encoded)
        # these packets are picked off by the "protocol" via 'next_packet()'
        # format: packet, wid, pixels, start_send_cb, end_send_cb
        # (only packet is required - the rest can be 0/None for clipboard packets)
        self.packet_queue = deque[tuple[Packet, int, int, bool]]()
        # the encode work queue is used by subsystem that need to encode data before sending it,
        # ie: encodings and clipboard
        # this queue will hold functions to call to compress data (pixels, clipboard)
        # items placed in this queue are picked off by the "encode" thread,
        # the functions should add the packets they generate to the 'packet_queue'
        self.encode_work_queue: SimpleQueue[None | tuple[bool, Callable, Sequence[Any]]] = SimpleQueue()
        self.encode_thread = None
        self.ordinary_packets: list[tuple[Packet, bool, bool]] = []

        self.suspended = False
        self.client_packet_types = ()
        self.setting_changed = setting_changed
        self.queue_encode: Callable[[ENCODE_WORK_ITEM], None] = self.start_queue_encode

        def suspend() -> None:
            self.suspended = True

        def resume() -> None:
            self.suspended = False

        self.connect("suspend", suspend)
        self.connect("resume", resume)

    def run(self) -> None:
        # ready for processing:
        self.protocol.set_packet_source(self.next_packet)

    def __repr__(self) -> str:
        classname = type(self).__name__
        return f"{classname}({self.counter} : {self.protocol})"

    def init_state(self) -> None:
        self.hello_sent = 0.0
        self.share = False
        self.lock = False
        self.client_control_commands: Sequence[str] = ()
        self.xdg_menu = True
        self.menu = False
        self.ssh_auth_sock = ""
        # what we send back in hello packet:
        self.ui_client = True
        # default 'wants' is not including "events" or "default_cursor":
        self.wants = ["encodings", "versions", "features", "display", "packet-types"]
        # these statistics are shared by all WindowSource instances:
        self.statistics = GlobalPerformanceStatistics()

    def is_closed(self) -> bool:
        return self.close_event.is_set()

    def cleanup(self) -> None:
        log("%s.close()", self)
        self.close_event.set()
        self.protocol = None
        self.statistics.reset(0)

    def may_notify(self, *args, **kwargs) -> None:
        # fugly workaround,
        # MRO is depth first and would hit the default implementation
        # instead of the mixin unless we force it:
        notification_mixin = sys.modules.get("xpra.server.source.notification")
        if not notification_mixin:
            return
        NotificationConnection = notification_mixin.NotificationConnection
        if isinstance(self, NotificationConnection):
            NotificationConnection.may_notify(self, *args, **kwargs)

    def compressed_wrapper(self, datatype, data, **kwargs) -> Compressed | LevelCompressed:
        # set compression flags based on self.lz4:
        kw = {"lz4": getattr(self, "lz4", False)}
        kw.update(kwargs)
        return compressed_wrapper(datatype, data, can_inline=False, **kw)

    def may_update_bandwidth_limits(self) -> None:
        # this method is only available when the NetworkState mixin is enabled:
        update_bandwidth_limits = getattr(self, "update_bandwidth_limits", noop)
        if update_bandwidth_limits != noop:
            update_bandwidth_limits()

    def parse_client_caps(self, c: typedict) -> None:
        # general features:
        self.share = c.boolget("share")
        self.lock = c.boolget("lock")
        self.client_control_commands = c.strtupleget("control_commands")
        if BACKWARDS_COMPATIBLE:
            # `xdg-menu` is the pre v6.4 legacy name:
            self.xdg_menu = c.boolget("xdg-menu", False)
        self.menu = c.boolget("menu", False)
        self.ssh_auth_sock = c.strget("ssh-auth-sock")

    def startup_complete(self) -> None:
        log("startup_complete()")
        self.send("startup-complete")

    # The encode thread loop management:
    #
    def start_queue_encode(self, item: ENCODE_WORK_ITEM) -> None:
        # start the encode work queue:
        # holds functions to call to compress data (pixels, clipboard)
        # items placed in this queue are picked off by the "encode" thread,
        # the functions should add the packets they generate to the 'packet_queue'
        self.queue_encode = self.encode_work_queue.put
        self.queue_encode(item)
        self.encode_thread = start_thread(self.encode_loop, "encode")

    def encode_queue_size(self) -> int:
        return self.encode_work_queue.qsize()

    def call_in_encode_thread(self, optional: bool, fn: Callable, *args) -> None:
        """
            This is used by WindowSource to queue damage processing to be done in the 'encode' thread.
            The 'encode_and_send_cb' will then add the resulting packet to the 'packet_queue' via 'queue_packet'.
        """
        self.statistics.compression_work_qsizes.append((monotonic(), self.encode_queue_size()))
        self.queue_encode((optional, fn, args))

    def queue_packet(self, packet: Packet, wid=0, pixels=0,
                     wait_for_more=False) -> None:
        """
            Add a new 'draw' packet to the 'packet_queue'.
            Note: this code runs in the non-ui thread
        """
        now = monotonic()
        self.statistics.packet_qsizes.append((now, len(self.packet_queue)))
        if wid > 0:
            self.statistics.damage_packet_qpixels.append(
                (now, wid, sum(x[2] for x in tuple(self.packet_queue) if x[1] == wid))
            )
        self.packet_queue.append((packet, wid, pixels, wait_for_more))
        p = self.protocol
        if p:
            p.source_has_more()

    def encode_loop(self) -> None:
        """
            This runs in a separate thread and calls all the function callbacks
            which are added to the 'encode_work_queue'.
            Must run until we hit the end of queue marker,
            to ensure all the queued items get called,
            those that are marked as optional will be skipped when is_closed()
        """
        while True:
            item = self.encode_work_queue.get(True)
            if item is None:
                return  # empty marker
            # some function calls are optional and can be skipped when closing:
            # (but some are not, like encoder clean functions)
            optional_when_closing, fn, args = item
            if optional_when_closing and self.is_closed():
                continue
            try:
                fn(*args)
            except Exception as e:
                if self.is_closed():
                    log("ignoring encoding error calling %s because the source is already closed:", item)
                    log(" %s", e)
                else:
                    log.error("Error during encoding:", exc_info=True)
                del e
            if YIELD:
                sleep(0)

    ######################################################################
    # network:
    def next_packet(self) -> tuple[Packet, bool, bool]:
        """ Called by protocol.py when it is ready to send the next packet """
        if self.is_closed():
            return Packet("closed"), False, False
        synchronous = True
        more = False
        if self.ordinary_packets:
            packet, synchronous, more = self.ordinary_packets.pop(0)
        elif self.packet_queue:
            packet, _, _, more = self.packet_queue.popleft()
        else:
            packet = Packet("none")
        if not more:
            more = bool(packet) and bool(self.ordinary_packets or self.packet_queue)
        return packet, synchronous, more

    def send(self, packet_type: str, *parts: PacketElement, **kwargs) -> None:
        """ This method queues non-damage packets (higher priority) """
        synchronous = bool(kwargs.get("synchronous", True))
        will_have_more = bool(kwargs.get("will_have_more", not synchronous))
        p = self.protocol
        if p:
            packet = Packet(packet_type, *parts)
            self.ordinary_packets.append((packet, synchronous, will_have_more))
            p.source_has_more()

    def send_more(self, packet_type: str, *parts: PacketElement, **kwargs) -> None:
        kwargs["will_have_more"] = True
        self.send(packet_type, *parts, **kwargs)

    def send_async(self, packet_type: str, *parts: PacketElement, **kwargs) -> None:
        kwargs["synchronous"] = False
        kwargs["will_have_more"] = False
        self.send(packet_type, *parts, **kwargs)

    ######################################################################
    # info:
    def get_info(self) -> dict[str, Any]:
        if not FULL_INFO:
            return {"protocol": "xpra"}
        info = {
            "protocol": "xpra",
            "connection_time": int(self.connection_time),
            "elapsed_time": int(monotonic() - self.connection_time),
            "counter": self.counter,
            "hello-sent": bool(self.hello_sent),
            "ssh-auth-sock": self.ssh_auth_sock,
            "packet-types": self.client_packet_types,
            "control-commands": self.client_control_commands,
        }
        p = self.protocol
        if p:
            info["connection"] = p.get_info()
        info.update(self.get_features_info())
        return info

    def get_features_info(self) -> dict[str, Any]:
        info = {
            "lock": bool(self.lock),
            "share": bool(self.share),
            "menu": bool(self.menu),
        }
        if BACKWARDS_COMPATIBLE:
            # legacy pre v6.4 name:
            info["xdg-menu"] = bool(self.xdg_menu)
        return info

    def send_info_response(self, info: dict) -> None:
        self.send_async("info-response", notypedict(info))

    def send_setting_change(self, setting: str, value: PacketElement) -> None:
        self.send_more("setting-change", setting, value)

    def send_server_event(self, event_type: str, *args: PacketElement) -> None:
        if "events" in self.wants:
            self.send_more("server-event", event_type, *args)

    def send_client_command(self, command: str, *args: PacketElement) -> None:
        if self.hello_sent:
            self.send_more("control", command, *args)
