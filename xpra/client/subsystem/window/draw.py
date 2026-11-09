# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections import deque
from time import monotonic
from typing import Any

from xpra.net.common import Packet, BACKWARDS_COMPATIBLE
from xpra.net.fragments import FrameAssembler, AssembledFrame, FrameStatus
from xpra.net.packet_type import WINDOW_ACK, WINDOW_DRAW
from xpra.constants import WINDOW_DECODE_SKIPPED, WINDOW_DECODE_ERROR, WINDOW_NOT_FOUND, WINDOW_DECODE_LOST
from xpra.util.objects import typedict
from xpra.util.str_fn import repr_ellipsized
from xpra.util.env import envint, envbool
from xpra.client.base.stub import StubClientSubsystem
from xpra.log import Logger

log = Logger("window", "draw")
paintlog = Logger("window", "paint")

PAINT_FAULT_RATE: int = envint("XPRA_PAINT_FAULT_INJECTION_RATE")
PAINT_FAULT_TELL: bool = envbool("XPRA_PAINT_FAULT_INJECTION_TELL", True)
PAINT_DELAY: int = envint("XPRA_PAINT_DELAY", -1)
# how long to wait for the missing fragments of a video frame:
DRAW_FRAGMENT_TIMEOUT: int = envint("XPRA_DRAW_FRAGMENT_TIMEOUT", 50)

DRAW_LOG_FMT = "process_draw: %7i %8s for window %3i, sequence %8i, %4ix%-4i at %4i,%-4i" \
               " using %6s encoding with options=%s"

DRAW_TYPES: dict[type, str] = {bytes: "bytes", str: "bytes", tuple: "arrays", list: "arrays"}


class WindowDraw(StubClientSubsystem):
    __slots__ = ()
    # these mixins are all composed into a single `WindowClient` instance,
    # which is the subsystem registered as `window`: declaring the prefix here
    # too keeps each mixin usable (and testable) on its own
    PREFIX = "window"
    SLOT_NAMES = ("_draw_counter", "pixel_counter", "frame_assemblers", "fragment_timer")

    def __init__(self):
        self._draw_counter: int = 0
        self.pixel_counter: deque = deque(maxlen=1000)
        # one for each window receiving `window-draw-fragment` packets:
        self.frame_assemblers: dict[int, FrameAssembler] = {}
        self.fragment_timer: int = 0

    def cleanup(self) -> None:
        self.cancel_fragment_timer()
        self.frame_assemblers = {}

    def get_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "draw-counter": self._draw_counter,
        }
        fragments: dict[str, int] = {}
        for assembler in self.frame_assemblers.values():
            for k, v in assembler.stats.items():
                fragments[k] = fragments.get(k, 0) + v
        if fragments.get("fragments"):
            info["fragments"] = fragments
        return info

    ######################################################################
    # painting windows:
    # these handlers only queue the work, but they must stay on the UI thread
    # (`main_thread=True`): that hop is what orders them after the `new-window`
    # that creates the window they refer to - do not "optimize" it away.
    def _process_draw(self, packet: Packet) -> None:
        # the frames we are still assembling must be painted before this one,
        # and the ones sent after it must wait for it:
        assembler = self.get_frame_assembler(packet.get_wid())
        assembler.flush(packet.get_u64(8), lambda: self.queue_draw(packet))

    def get_frame_assembler(self, wid: int) -> FrameAssembler:
        assembler = self.frame_assemblers.get(wid)
        if assembler is None:
            def deliver(frame: AssembledFrame) -> None:
                self.draw_assembled_frame(wid, frame)
            assembler = self.frame_assemblers[wid] = FrameAssembler(deliver, DRAW_FRAGMENT_TIMEOUT / 1000)
        return assembler

    def queue_draw(self, packet: Packet) -> None:
        if PAINT_DELAY >= 0:
            self.timeout_add(PAINT_DELAY, self.add_decode_work, self._do_draw, packet)
        else:
            self.add_decode_work(self._do_draw, packet)

    def _process_eos(self, packet: Packet) -> None:
        self.add_decode_work(self._do_draw, packet)

    def _process_draw_fragment(self, packet: Packet) -> None:
        """
        A part of a `window-draw` packet, with the same fields,
        followed by the fragment's index, the number of fragments, the group it belongs to,
        and the sequence of the last `window-draw` packet sent on the stream before this frame.
        These may be received as datagrams, so they can be lost or re-ordered.
        """
        assembler = self.get_frame_assembler(packet.get_wid())
        metadata = tuple(packet[1:7]) + tuple(packet[8:11])
        assembler.add(packet.get_u64(8), packet.get_u16(11), packet.get_u16(12),
                      packet.get_u16(13), packet.get_u16(14), packet.get_buffer(7), metadata, monotonic(),
                      packet.get_u64(15))
        self.schedule_fragment_timer()

    def draw_assembled_frame(self, wid: int, frame: AssembledFrame) -> None:
        # metadata = (wid, x, y, width, height, coding, sequence, rowstride, options)
        metadata = frame.metadata
        width, height = metadata[3], metadata[4]
        log("draw_assembled_frame(%#x, %s) %i bytes from %i fragments, missing=%s",
            wid, frame.status, len(frame.data), frame.count, frame.missing)
        for sequence in frame.lost_sequences:
            # we have not received anything for these frames:
            self.send_draw_ack(wid, 0, 0, sequence, WINDOW_DECODE_LOST, "lost")
        if frame.status == FrameStatus.LOST:
            self.send_draw_ack(wid, width, height, frame.sequence, WINDOW_DECODE_LOST, "lost",
                               {"missing": frame.missing, "fragments": frame.count})
            return
        options = dict(metadata[8])
        # tells the decoders this frame may be damaged (see `record_decode_time`):
        options["fragments"] = frame.count
        if frame.missing:
            options["missing-fragments"] = frame.missing
        packet = Packet(WINDOW_DRAW, *metadata[:6], frame.data, *metadata[6:8], options)
        self.queue_draw(packet)

    def schedule_fragment_timer(self) -> None:
        if self.fragment_timer:
            return
        now = monotonic()
        deadlines = tuple(d for d in (a.next_deadline(now) for a in self.frame_assemblers.values()) if d > 0)
        if not deadlines:
            return
        delay = max(0, round((min(deadlines) - now) * 1000))
        self.fragment_timer = self.timeout_add(delay, self.fragment_timeout)

    def fragment_timeout(self) -> bool:
        self.fragment_timer = 0
        now = monotonic()
        for assembler in tuple(self.frame_assemblers.values()):
            assembler.expire(now)
        self.schedule_fragment_timer()
        return False

    def cancel_fragment_timer(self) -> None:
        if ft := self.fragment_timer:
            self.fragment_timer = 0
            self.source_remove(ft)

    def send_draw_ack(self, wid: int, width: int, height: int, packet_sequence: int,
                      decode_time: int, message="", extra: dict | None = None) -> None:
        args: tuple = (WINDOW_ACK, wid, width, height, packet_sequence, decode_time, message)
        if extra:
            args += (extra, )
        log("sending ack: %s", args)
        self.send_now(*args)

    def _do_draw(self, packet: Packet) -> None:
        """ this runs from the decode thread (see `xpra/client/subsystem/decode.py`) """
        wid = packet.get_wid()
        window = self.get_window(wid)
        # `window-eos` packets are routed here too:
        if packet.get_type() == "window-eos":
            if window:
                window.eos()
            return
        x = packet.get_i16(2)
        y = packet.get_i16(3)
        width = packet.get_u16(4)
        height = packet.get_u16(5)
        coding = packet.get_str(6)
        if BACKWARDS_COMPATIBLE and coding in ("mmap", "scroll") and not isinstance(packet[7], (bytes, bytearray, memoryview)):
            # v7 servers running in backwards compatible mode also send the `chunks` / `scroll` options here,
            # we only use the options:
            data = b""
        else:
            data = packet.get_buffer(7)
        packet_sequence = packet.get_u64(8)
        rowstride = packet.get_u32(9)
        # rename old encoding aliases early:
        options = typedict()
        if len(packet) > 10:
            options.update(packet.get_dict(10))
        dtype = DRAW_TYPES.get(type(data), type(data))
        log(DRAW_LOG_FMT, len(data), dtype, wid, packet_sequence, width, height, x, y, coding, options)
        start = monotonic()

        def record_draw_error(code=WINDOW_NOT_FOUND, message="window not found") -> None:
            self.send_draw_ack(wid, width, height, packet_sequence, code, message)

        def draw_abort(code=WINDOW_NOT_FOUND, message="window not found") -> None:
            if coding == "mmap":
                # we need to ack the data to free the space!
                # (the mmap read area is owned by the `mmap` subsystem)
                if mmap := self.get_subsystem("mmap"):
                    mmap.free_packet_chunks(data, options)
            record_draw_error(code, message)

        # frames re-assembled from datagram fragments may be damaged:
        fragments = options.intget("fragments", 0)
        missing = options.tupleget("missing-fragments", ())

        def record_decode_time(success: bool | int, message="") -> None:
            extra = {"missing": missing, "fragments": fragments} if missing else None
            if success > 0:
                end = monotonic()
                decode_time = max(1, round((end - start) * 1_000_000))
                self.pixel_counter.append((start, end, width * height))
                dms = "%sms" % (int(decode_time / 100) / 10.0)
                paintlog("record_decode_time(%s, %s) wid=%#x, %s: %sx%s, %s",
                         success, message, wid, coding, width, height, dms)
            elif success == 0 and fragments:
                # most likely caused by a lost fragment, the server should recover from it:
                decode_time = WINDOW_DECODE_LOST
                extra = {"missing": missing, "fragments": fragments}
                paintlog("record_decode_time(%s, %s) decoding error on wid=%#x, %s: %sx%s from %i fragments, missing %s",
                         success, message, wid, coding, width, height, fragments, missing)
            elif success == 0:
                decode_time = WINDOW_DECODE_ERROR
                paintlog("record_decode_time(%s, %s) decoding error on wid=%#x, %s: %sx%s",
                         success, message, wid, coding, width, height)
            else:
                assert success < 0
                decode_time = WINDOW_DECODE_SKIPPED
                paintlog("record_decode_time(%s, %s) decoding or painting skipped on wid=%#x, %s: %sx%s",
                         success, message, wid, coding, width, height)
            self.send_draw_ack(wid, width, height, packet_sequence, decode_time, repr_ellipsized(message, 512), extra)

        if not window:
            # window is gone
            self.idle_add(draw_abort, WINDOW_NOT_FOUND, "window not found")
            return

        # the list of allowed encodings is owned by the `encoding` subsystem:
        encoding_subsystem = self.get_subsystem("encoding")
        allowed_encodings = encoding_subsystem.allowed_encodings if encoding_subsystem else ("rgb32", "rgb24", "mmap",)
        if coding not in allowed_encodings and coding != "mmap":
            log.warn("Warning: server sent unsupported encoding %r", coding)
            self.idle_add(draw_abort, WINDOW_DECODE_ERROR, f"unsupported encoding {coding!r}")
            return

        self._draw_counter += 1
        if PAINT_FAULT_RATE > 0 and (self._draw_counter % PAINT_FAULT_RATE) == 0:
            log.warn("injecting paint fault for %s draw packet %i, sequence number=%i",
                     coding, self._draw_counter, packet_sequence)
            if PAINT_FAULT_TELL:
                msg = f"fault injection for {coding} draw packet {self._draw_counter}, sequence no={packet_sequence}"
                self.idle_add(draw_abort, WINDOW_DECODE_ERROR, msg)
            return
        # we could expose this to the csc step? (not sure how this could be used)
        # if self.xscale!=1 or self.yscale!=1:
        #    options["client-scaling"] = self.xscale, self.yscale
        try:
            window.draw_region(x, y, width, height, coding, data, rowstride, options, [record_decode_time])
        except Exception as e:
            log.error("Error drawing on window %#x", wid)
            log.error(f" using encoding {coding} with {options=}", exc_info=True)
            self.idle_add(record_draw_error, WINDOW_DECODE_ERROR, str(e))

    ######################################################################
    # packets:
    def init_authenticated_packet_handlers(self) -> None:
        # `main_thread=True` is required for ordering, not for the (trivial) handlers:
        # see `_process_draw` above
        self.add_packets("window-draw", "window-eos", "window-draw-fragment", main_thread=True)
