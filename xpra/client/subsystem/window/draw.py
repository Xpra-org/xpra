# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections import deque
from time import sleep, monotonic
from queue import SimpleQueue
from threading import Thread
from typing import Any

from xpra.net.common import Packet, BACKWARDS_COMPATIBLE
from xpra.net.packet_type import WINDOW_DRAW_ACK
from xpra.exit_codes import ExitCode, ExitValue
from xpra.constants import WINDOW_DECODE_SKIPPED, WINDOW_DECODE_ERROR, WINDOW_NOT_FOUND
from xpra.util.thread import start_thread
from xpra.util.objects import typedict
from xpra.util.str_fn import repr_ellipsized
from xpra.util.env import envint, envbool
from xpra.client.base.stub import StubClientMixin
from xpra.log import Logger

log = Logger("window", "draw")
paintlog = Logger("window", "paint")

PAINT_FAULT_RATE: int = envint("XPRA_PAINT_FAULT_INJECTION_RATE")
PAINT_FAULT_TELL: bool = envbool("XPRA_PAINT_FAULT_INJECTION_TELL", True)
PAINT_DELAY: int = envint("XPRA_PAINT_DELAY", -1)

DRAW_LOG_FMT = "process_draw: %7i %8s for window %3i, sequence %8i, %4ix%-4i at %4i,%-4i" \
               " using %6s encoding with options=%s"

DRAW_TYPES: dict[type, str] = {bytes: "bytes", str: "bytes", tuple: "arrays", list: "arrays"}


class WindowDraw(StubClientMixin):

    def __init__(self):
        # draw thread:
        self._draw_queue = SimpleQueue[Packet | None]()
        self._draw_thread: Thread | None = None
        self._draw_counter: int = 0
        self.pixel_counter: deque = deque(maxlen=1000)

    def run(self) -> ExitValue:
        # we decode pixel data in this thread
        self._draw_thread = start_thread(self._draw_thread_loop, "draw")
        return ExitCode.OK

    def cleanup(self) -> None:
        log("WindowClient.cleanup()")
        # tell the draw thread to exit:
        if dq := self._draw_queue:
            dq.put(None)
        if dq:
            dq.put(None)
        dt = self._draw_thread
        log("WindowClient.cleanup() draw thread=%s, alive=%s", dt, dt and dt.is_alive())
        if dt and dt.is_alive():
            dt.join(0.1)
        log("WindowClient.cleanup() done")

    ######################################################################
    # hello:
    def get_caps(self) -> dict[str, Any]:
        caps = {
            "encoding": {
                "eos": True,
            },
        }
        return caps

    def get_info(self) -> dict[str, Any]:
        return {
            "draw-counter": self._draw_counter,
        }

    ######################################################################
    # painting windows:
    def _process_window_draw(self, packet: Packet) -> None:
        if PAINT_DELAY >= 0:
            self.timeout_add(PAINT_DELAY, self._draw_queue.put, packet)
        else:
            self._draw_queue.put(packet)

    def _process_eos(self, packet: Packet) -> None:
        self._draw_queue.put(packet)

    def send_damage_sequence(self, wid: int, packet_sequence: int, width: int, height: int,
                             decode_time: int, message="") -> None:
        packet = packet_sequence, wid, width, height, decode_time, message
        log("sending ack: %s", packet)
        self.send_now(WINDOW_DRAW_ACK, *packet)

    def _draw_thread_loop(self):
        while self.exit_code is None:
            packet = self._draw_queue.get()
            if packet is None:
                log("draw queue found exit marker")
                break
            with log.trap_error(f"Error processing {packet[0]} packet"):
                self._do_draw(packet)
                sleep(0)
        self._draw_thread = None
        log("draw thread ended")

    def _do_draw(self, packet: Packet) -> None:
        """ this runs from the draw thread above """
        wid = packet.get_wid()
        window = self.get_window(wid)
        if packet[0] == "eos":
            if window:
                window.eos()
            return
        x = packet.get_i16(2)
        y = packet.get_i16(3)
        width = packet.get_u16(4)
        height = packet.get_u16(5)
        coding = packet.get_str(6)
        # mmap can send a tuple, otherwise it's a buffer, see #4496:
        data = packet[7]
        packet_sequence = packet.get_u64(8)
        rowstride = packet.get_u32(9)
        if not window:
            # window is gone

            def draw_cleanup() -> None:
                if coding == "mmap":
                    if area := self.mmap_read_area:
                        from xpra.net.mmap.io import int_from_buffer
                        # we need to ack the data to free the space!
                        data_start = int_from_buffer(area.mmap, 0)
                        offset, length = data[-1]
                        data_start.value = offset + length
                        # clear the mmap area via idle_add so any pending draw requests
                        # will get a chance to run first (preserving the order)
                self.send_damage_sequence(wid, packet_sequence, width, height, WINDOW_NOT_FOUND, "window not found")

            self.idle_add(draw_cleanup)
            return
        # rename old encoding aliases early:
        options = typedict()
        if len(packet) > 10:
            options.update(packet.get_dict(10))
        dtype = DRAW_TYPES.get(type(data), type(data))
        log(DRAW_LOG_FMT, len(data), dtype, wid, packet_sequence, width, height, x, y, coding, options)
        start = monotonic()

        def record_decode_time(success: bool | int, message="") -> None:
            if success > 0:
                end = monotonic()
                decode_time = round(end * 1000 * 1000 - start * 1000 * 1000)
                self.pixel_counter.append((start, end, width * height))
                dms = "%sms" % (int(decode_time / 100) / 10.0)
                paintlog("record_decode_time(%s, %s) wid=%#x, %s: %sx%s, %s",
                         success, message, wid, coding, width, height, dms)
            elif success == 0:
                decode_time = WINDOW_DECODE_ERROR
                paintlog("record_decode_time(%s, %s) decoding error on wid=%#x, %s: %sx%s",
                         success, message, wid, coding, width, height)
            else:
                assert success < 0
                decode_time = WINDOW_DECODE_SKIPPED
                paintlog("record_decode_time(%s, %s) decoding or painting skipped on wid=%#x, %s: %sx%s",
                         success, message, wid, coding, width, height)
            self.send_damage_sequence(wid, packet_sequence, width, height, decode_time, repr_ellipsized(message, 512))

        self._draw_counter += 1
        if PAINT_FAULT_RATE > 0 and (self._draw_counter % PAINT_FAULT_RATE) == 0:
            log.warn("injecting paint fault for %s draw packet %i, sequence number=%i",
                     coding, self._draw_counter, packet_sequence)
            if PAINT_FAULT_TELL:
                msg = f"fault injection for {coding} draw packet {self._draw_counter}, sequence no={packet_sequence}"
                self.idle_add(record_decode_time, False, msg)
            return
        # we could expose this to the csc step? (not sure how this could be used)
        # if self.xscale!=1 or self.yscale!=1:
        #    options["client-scaling"] = self.xscale, self.yscale
        try:
            window.draw_region(x, y, width, height, coding, data, rowstride, options, [record_decode_time])
        except Exception as e:
            log.error("Error drawing on window %#x", wid)
            log.error(f" using encoding {coding} with {options=}", exc_info=True)
            self.idle_add(record_decode_time, False, str(e))
            raise

    ######################################################################
    # packets:
    def init_authenticated_packet_handlers(self) -> None:
        if BACKWARDS_COMPATIBLE:
            self.add_legacy_alias("draw", "window-draw")
        self.add_packets("window-draw", "eos", main_thread=True)
