#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.net.common import Packet
from xpra.constants import WINDOW_DECODE_LOST
from xpra.net import draw_packet
from xpra.net.draw_packet import DrawRequest, parse_draw_packet
from xpra.client.subsystem.window.draw import WindowDraw


class Draw(WindowDraw):
    """ just enough of a client to call `_do_draw` directly """

    def __init__(self, window):  # pylint: disable=super-init-not-called
        self.window = window
        self._draw_counter = 0
        self.pixel_counter = deque(maxlen=100)
        self.acks = []

    def get_window(self, _wid):
        return self.window

    def get_subsystem(self, _name):
        return None

    @staticmethod
    def idle_add(fn, *args):
        fn(*args)

    def send_now(self, *args):
        self.acks.append(args)


def mmap_packet(img_data) -> Packet:
    chunks = ((8, 400), )
    return Packet("window-draw", 1, 0, 0, 10, 10, "mmap", img_data, 1, 40, {"chunks": chunks})


class WindowDrawTest(unittest.TestCase):

    def test_overloaded_pixel_data(self):
        # v7 servers running in backwards compatible mode duplicate the mmap `chunks` in the pixel data:
        window = Mock()
        with patch.object(draw_packet, "BACKWARDS_COMPATIBLE", True):
            Draw(window)._do_draw(parse_draw_packet(mmap_packet(((8, 400), ))))
        window.draw_region.assert_called_once()
        args = window.draw_region.call_args.args
        self.assertEqual(args[4], "mmap")
        self.assertEqual(args[5], b"")
        self.assertEqual(args[7]["chunks"], ((8, 400), ))

    def test_overloaded_pixel_data_rejected(self):
        window = Mock()
        with patch.object(draw_packet, "BACKWARDS_COMPATIBLE", False):
            with self.assertRaises((TypeError, ValueError)):
                Draw(window)._do_draw(parse_draw_packet(mmap_packet(((8, 400), ))))
        window.draw_region.assert_not_called()

    def test_buffer_pixel_data(self):
        for backwards_compatible in (False, True):
            window = Mock()
            with patch.object(draw_packet, "BACKWARDS_COMPATIBLE", backwards_compatible):
                Draw(window)._do_draw(parse_draw_packet(mmap_packet(b"")))
            window.draw_region.assert_called_once()


JPEG = b"\xff\xd8\xff\xe0" + bytes(100)


def make_draw_packet(coding="rgb24", width=4, height=2, data=None, rowstride=12, options=None) -> Packet:
    if data is None:
        data = bytes(rowstride * height)
    return Packet("window-draw", 1, 0, 0, width, height, coding, data, 7, rowstride, options or {})


class DrawValidationTest(unittest.TestCase):

    def test_arity(self):
        packet = make_draw_packet()
        parse_draw_packet(packet)
        for bad in (Packet(*packet[:10]), Packet(*packet, 0)):
            with self.assertRaises(ValueError):
                parse_draw_packet(bad)
            with self.assertRaises(ValueError):
                Fragments()._process_draw(bad)
        with self.assertRaises(ValueError):
            Fragments()._process_eos(Packet("window-eos", 1, 2))

    def check_invalid_options(self, *options: dict):
        for opts in options:
            with self.assertRaises((ValueError, TypeError), msg=f"options {opts} accepted"):
                parse_draw_packet(make_draw_packet(options=opts))

    def test_options(self):
        self.check_invalid_options(
            {f"key{i}": i for i in range(65)},
            {"": 1},
            {"x" * 65: 1},
            {"long": "x" * 2000},
            {"list": list(range(100))},
            {"deep": ((((1, ), ), ), )},
            {"object": object()},
            {"scaled_size": (0, 10)},
            {"scaled_size": (10, 10**6)},
            {"scaled_size": (10, )},
            {"window-size": "100x100"},
            {"chunks": ((8, ), )},
            {"chunks": ((-1, 400), )},
            {"chunks": ((8, 0), )},
            {"chunks": ((0, 8), ) * 257},
            {"scroll": ((0, 0, 10, 10, 0), )},
            {"scroll": ((0, 0, 0, 10, 0, 5), )},
            {"scroll": ((0, 0, 10, 10, 0, 2**20), )},
        )
        request = parse_draw_packet(make_draw_packet(options={
            "quality": 50, "csc": "YUV420P", "scaled_size": [2, 1], "fragments": 4, "missing-fragments": (1, ),
        }))
        # client-only options are dropped, and the sizes are normalized:
        self.assertEqual(request.options, {"quality": 50, "csc": "YUV420P", "scaled_size": (2, 1)})

    def do_draw(self, packet: Packet, encodings=("rgb24", "rgb32", "h264", "jpeg", "png", "webp")):
        window = Mock()
        client = Draw(window)
        encoding = SimpleNamespace(allowed_encodings=encodings)
        client.get_subsystem = lambda name: encoding if name == "encoding" else None
        client._do_draw(parse_draw_packet(packet))
        return window, client

    def assert_draw_error(self, packet: Packet, message: str):
        from xpra.constants import WINDOW_DECODE_ERROR
        window, client = self.do_draw(packet)
        window.draw_region.assert_not_called()
        self.assertEqual(len(client.acks), 1)
        self.assertEqual(client.acks[0][5], WINDOW_DECODE_ERROR)
        self.assertIn(message, client.acks[0][6])

    def assert_drawn(self, packet: Packet):
        window, client = self.do_draw(packet)
        window.draw_region.assert_called_once()
        self.assertEqual(client.acks, [])

    def test_rgb(self):
        self.assert_drawn(make_draw_packet())
        # rowstride 0 means tightly packed:
        self.assert_drawn(make_draw_packet(rowstride=0, data=bytes(24)))
        # the last row does not need the padding:
        self.assert_drawn(make_draw_packet(rowstride=16, data=bytes(28)))
        self.assert_drawn(make_draw_packet("rgb32", rowstride=16, data=bytes(32)))
        self.assert_draw_error(make_draw_packet(rowstride=8), "rowstride")
        self.assert_draw_error(make_draw_packet(data=bytes(23)), "not enough")
        self.assert_draw_error(make_draw_packet("rgb32", rowstride=12), "rowstride")
        self.assert_draw_error(make_draw_packet(options={"rgb_format": "XYZ"}), "XYZ")
        self.assert_draw_error(make_draw_packet(width=0), "invalid")
        self.assert_draw_error(make_draw_packet(width=10000, height=10000, rowstride=30000, data=b""), "pixels limit")
        # compressed:
        self.assert_drawn(make_draw_packet(data=b"z" * 10, options={"lz4": 1}))
        self.assert_draw_error(make_draw_packet(data=b"", options={"lz4": 1}), "compressed")
        self.assert_draw_error(make_draw_packet(data=bytes(100000), options={"lz4": 1}), "compressed")

    def test_compressed(self):
        self.assert_drawn(make_draw_packet("h264", 64, 32, b"data", 0))
        self.assert_drawn(make_draw_packet("jpeg", 64, 32, JPEG, 0))
        self.assert_drawn(make_draw_packet("webp", 64, 32, b"RIFF\0\0\0\0WEBP", 0))
        self.assert_draw_error(make_draw_packet("h264", 64, 32, b"", 0), "no h264")
        self.assert_draw_error(make_draw_packet("h264", 64, 32, bytes(64 * 32 * 8 + 65537), 0), "too much")
        # the limit applies to the scaled size:
        self.assert_draw_error(make_draw_packet("h264", 64, 32, bytes(32 * 16 * 8 + 65537), 0, {"scaled_size": (32, 16)}),
                               "too much")
        self.assert_draw_error(make_draw_packet("jpeg", 64, 32, b"\x89PNG" + bytes(100), 0), "signature")
        self.assert_draw_error(make_draw_packet("png", 64, 32, JPEG, 0), "signature")

    def test_mmap(self):
        from xpra.net.draw_packet import check_draw_request
        mmap = parse_draw_packet(mmap_packet(b""))
        self.assertEqual(check_draw_request(mmap), "")
        self.assertIn("not enough", check_draw_request(mmap._replace(options={"chunks": ((8, 100), )})))
        self.assertIn("chunks", check_draw_request(mmap._replace(options={})))
        self.assertIn("pixel data", check_draw_request(mmap._replace(data=b"x")))

    def test_scroll(self):
        from xpra.net.draw_packet import check_draw_request
        scroll = parse_draw_packet(make_draw_packet("scroll", 0, 0, b"", 0, {"scroll": ((0, 0, 10, 10, 0, 5), )}))
        self.assertEqual(check_draw_request(scroll), "")
        self.assertIn("scroll", check_draw_request(scroll._replace(options={})))


class Fragments(Draw):
    """ captures the draw work and the timers instead of running them """

    def __init__(self):
        super().__init__(Mock())
        self.frame_assemblers = {}
        self.fragment_timer = 0
        self.timers = []
        self.drawn = []

    def timeout_add(self, delay, fn, *args):
        self.timers.append((delay, fn, args))
        return len(self.timers)

    def source_remove(self, _timer):
        pass

    def add_decode_work(self, _fn, request):
        self.drawn.append(request)


def make_fragments(data: bytes, nals, datagram=100, frame_type="", stream_sequence=6, last_frame_loss=0):
    from xpra.server.window.compress import WindowSource
    source = object.__new__(WindowSource)
    source.wid = 1
    source.datagram = datagram
    source.last_stream_sequence = stream_sequence
    source.last_frame_loss = last_frame_loss
    source.parity_fragments = 0
    options = {"frame": 5, "nals": list(nals)}
    if frame_type:
        options["type"] = frame_type
    packet = Packet("window-draw", 1, 10, 20, 64, 32, "h264", data, 7, 0, options)
    return source.make_draw_fragments(packet)


class WindowDrawFragmentTest(unittest.TestCase):

    DATA = bytes(range(250)) * 2
    NALS = (50, 120, 300, 310, 500)

    def test_server_fragments(self):
        fragments = make_fragments(self.DATA, self.NALS)
        self.assertTrue(fragments)
        for index, fragment in enumerate(fragments):
            self.assertEqual(fragment.get_type(), "window-draw-fragment")
            self.assertEqual(tuple(fragment[1:7]), (1, 10, 20, 64, 32, "h264"))
            self.assertLessEqual(len(fragment[7]), 100)
            self.assertEqual(tuple(fragment[8:10]), (7, 0))
            # the boundaries are only used for splitting, they are not sent:
            self.assertEqual(fragment[10], {"frame": 5})
            self.assertEqual(fragment[11], index)
            self.assertEqual(fragment[12], len(fragments))
            self.assertEqual(fragment[15], 6)
        self.assertEqual(b"".join(f[7] for f in fragments), self.DATA)

    def test_server_does_not_fragment(self):
        # keyframes, frames without boundaries and frames needing too many fragments:
        self.assertEqual(make_fragments(self.DATA, self.NALS, frame_type="IDR"), [])
        self.assertEqual(make_fragments(self.DATA, ()), [])
        self.assertEqual(make_fragments(self.DATA, (10, 20)), [])
        with patch("xpra.server.window.compress.MAX_DRAW_FRAGMENTS", 3):
            self.assertEqual(make_fragments(self.DATA, self.NALS), [])

    def stream_packet(self, sequence: int) -> Packet:
        return Packet("window-draw", 1, 0, 0, 64, 32, "h264", b"key", sequence, 0, {"type": "IDR"})

    def test_reassembled(self):
        client = Fragments()
        client._process_draw(self.stream_packet(6))
        client.drawn = []
        fragments = make_fragments(self.DATA, self.NALS)
        for fragment in reversed(fragments):
            client._process_draw_fragment(fragment)
        self.assertEqual(len(client.drawn), 1)
        request = client.drawn[0]
        self.assertEqual(tuple(request[:6]), (1, 10, 20, 64, 32, "h264"))
        self.assertEqual(request.data, self.DATA)
        # the decoders are told that this frame was re-assembled:
        self.assertEqual(tuple(request[7:]), (7, 0, {"frame": 5, "fragments": len(fragments)}))
        self.assertEqual(client.get_info()["fragments"]["complete"], 1)

    def test_waits_for_stream_packet(self):
        client = Fragments()
        for fragment in make_fragments(self.DATA, self.NALS):
            client._process_draw_fragment(fragment)
        self.assertFalse(client.drawn)
        client._process_draw(self.stream_packet(6))
        self.assertEqual([p.sequence for p in client.drawn], [6, 7])

    def test_partial_after_timeout(self):
        client = Fragments()
        client._process_draw(self.stream_packet(6))
        client.drawn = []
        fragments = make_fragments(self.DATA, self.NALS)
        for fragment in fragments[1:]:
            client._process_draw_fragment(fragment)
        self.assertFalse(client.drawn)
        # the timer fires once the deadline has passed:
        self.assertEqual(len(client.timers), 1)
        with patch("xpra.client.subsystem.window.draw.monotonic", return_value=10**6):
            _delay, fn, args = client.timers[0]
            fn(*args)
        request = client.drawn[0]
        self.assertEqual(request.data, b"".join(f[7] for f in fragments[1:]))
        self.assertEqual(request.options["missing-fragments"], (0, ))
        self.assertEqual(request.options["fragments"], len(fragments))

    def test_stream_packet_flushes(self):
        client = Fragments()
        client._process_draw(self.stream_packet(6))
        client.drawn = []
        fragments = make_fragments(self.DATA, self.NALS)
        client._process_draw_fragment(fragments[0])
        # the next frame is sent on the stream (ie: a keyframe), the partial one must be painted first:
        client._process_draw(self.stream_packet(8))
        self.assertEqual([p.sequence for p in client.drawn], [7, 8])
        # fragments for frame 7 are now too late:
        client._process_draw_fragment(fragments[1])
        self.assertEqual(len(client.drawn), 2)

    def test_parity_after_losses(self):
        from time import monotonic
        # no parity until the client reports a loss:
        fragments = make_fragments(self.DATA, self.NALS)
        self.assertEqual(max(f[11] for f in fragments), len(fragments) - 1)
        with_parity = make_fragments(self.DATA, self.NALS, last_frame_loss=monotonic())
        count = with_parity[0][12]
        self.assertEqual(count, len(fragments))
        parity = [f for f in with_parity if f[11] >= count]
        self.assertEqual(len(parity), 1)
        # it can be used to recover any one of the fragments:
        client = Fragments()
        client._process_draw(self.stream_packet(6))
        client.drawn = []
        for fragment in with_parity[1:]:
            client._process_draw_fragment(fragment)
        self.assertEqual(len(client.drawn), 1)
        self.assertEqual(client.drawn[0].data, self.DATA)
        self.assertNotIn("missing-fragments", client.drawn[0].options)
        self.assertEqual(client.get_info()["fragments"]["recovered"], 1)

    def test_fixed_parity(self):
        with patch("xpra.server.window.compress.DRAW_FRAGMENT_FEC", 50):
            fragments = make_fragments(self.DATA, self.NALS)
        count = fragments[0][12]
        self.assertEqual(len(fragments), count + (count + 1) // 2)

    def test_lost_frame_is_acked(self):
        client = Fragments()
        client._process_draw(self.stream_packet(6))
        client.drawn = []
        client.acks = []
        fragments = make_fragments(self.DATA, (500, ))
        # only one piece of the single unit:
        client._process_draw_fragment(fragments[1])
        client.frame_assemblers[1].expire(10**6)
        self.assertFalse(client.drawn)
        self.assertEqual(len(client.acks), 1)
        ack = client.acks[0]
        self.assertEqual(ack[4], 7)
        self.assertEqual(ack[5], WINDOW_DECODE_LOST)
        self.assertEqual(ack[7], {"missing": (0, 2, 3, 4), "fragments": 5})

    def test_entirely_lost_frames_are_acked(self):
        client = Fragments()
        client._process_draw(self.stream_packet(6))
        client.drawn = []
        client.acks = []
        # frames 7 and 8 were lost entirely, we only receive frame 9:
        for fragment in make_fragments(self.DATA, self.NALS):
            fragment = Packet(*fragment[:8], 9, *fragment[9:])
            client._process_draw_fragment(fragment)
        self.assertEqual([p.sequence for p in client.drawn], [9])
        self.assertEqual([(ack[4], ack[5]) for ack in client.acks], [(7, WINDOW_DECODE_LOST), (8, WINDOW_DECODE_LOST)])

    def test_unknown_window(self):
        client = Fragments()
        client.window = None
        for fragment in make_fragments(self.DATA, self.NALS):
            client._process_draw_fragment(fragment)
        client._process_draw(self.stream_packet(6))
        # no assembler for windows that do not exist, the stream packet is still processed:
        self.assertEqual(client.frame_assemblers, {})
        self.assertEqual([p.sequence for p in client.drawn], [6])

    def test_assembler_dropped_with_window(self):
        client = Fragments()
        client._process_draw(self.stream_packet(6))
        client._process_draw_fragment(make_fragments(self.DATA, self.NALS)[0])
        self.assertIn(1, client.frame_assemblers)
        client.window = None
        client.fragment_timeout()
        self.assertEqual(client.frame_assemblers, {})

    def test_fragment_limits(self):
        client = Fragments()
        client._process_draw(self.stream_packet(6))
        fragment = make_fragments(self.DATA, self.NALS)[0]
        for bad in (
            Packet(*fragment[:12], 257, *fragment[13:]),
            Packet(*fragment[:7], bytes(65537), *fragment[8:]),
            Packet(*fragment[:15]),
        ):
            with self.assertRaises(ValueError):
                client._process_draw_fragment(bad)

    def test_fragment_metadata_mismatch(self):
        client = Fragments()
        client._process_draw(self.stream_packet(6))
        client.drawn = []
        fragments = make_fragments(self.DATA, self.NALS)
        client._process_draw_fragment(fragments[0])
        # a fragment of the same frame claiming a different geometry:
        client._process_draw_fragment(Packet(*fragments[1][:4], 128, *fragments[1][5:]))
        self.assertEqual(client.get_info()["fragments"]["invalid"], 1)

    def check_decode_ack(self, options: dict, success, expected_code, expected_extra):
        window = Mock()
        client = Draw(window)
        encoding = SimpleNamespace(allowed_encodings=("h264", ))
        client.get_subsystem = lambda name: encoding if name == "encoding" else None
        # as re-assembled by `draw_assembled_frame`:
        client._do_draw(DrawRequest(1, 0, 0, 64, 32, "h264", b"data", 7, 0, options))
        callbacks = window.draw_region.call_args.args[-1]
        for cb in callbacks:
            cb(success, "")
        ack = client.acks[-1]
        if expected_code is None:
            self.assertGreater(ack[5], 0)
        else:
            self.assertEqual(ack[5], expected_code)
        self.assertEqual(ack[7] if len(ack) > 7 else None, expected_extra)

    def test_decode_acks(self):
        from xpra.constants import WINDOW_DECODE_ERROR
        missing = {"fragments": 4, "missing-fragments": (2, )}
        extra = {"missing": (2, ), "fragments": 4}
        # a partial frame that was decoded:
        self.check_decode_ack(missing, True, None, extra)
        # a damaged frame, or one that depends on a damaged one, is lost - not a decoding error:
        self.check_decode_ack(missing, False, WINDOW_DECODE_LOST, extra)
        self.check_decode_ack({"fragments": 4}, False, WINDOW_DECODE_LOST, {"missing": (), "fragments": 4})
        # frames not sent as fragments are unchanged:
        self.check_decode_ack({}, True, None, None)
        self.check_decode_ack({}, False, WINDOW_DECODE_ERROR, None)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
