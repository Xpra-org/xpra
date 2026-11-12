#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from io import BytesIO
from unittest.mock import MagicMock

from xpra.net.common import Packet
from xpra.net.webcam_packet import (
    parse_webcam_start_packet, parse_webcam_stop_packet, parse_webcam_ack_packet,
    parse_webcam_frame_packet, check_webcam_frame,
)


def png_data(w: int, h: int) -> bytes:
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (w, h)).save(buf, "PNG")
    return buf.getvalue()


def frame_packet(encoding="png", w=4, h=4, data=None, options=None) -> Packet:
    if data is None:
        data = png_data(w, h)
    return Packet("webcam-frame", 0, 1, encoding, w, h, data, options or {})


class WebcamPacketTest(unittest.TestCase):

    def test_start_stop_ack(self):
        self.assertEqual(parse_webcam_start_packet(Packet("webcam-start", 0, 640, 480)), (0, 640, 480))
        self.assertEqual(parse_webcam_stop_packet(Packet("webcam-stop", 0)), (0, ""))
        self.assertEqual(parse_webcam_stop_packet(Packet("webcam-stop", 0, "end")), (0, "end"))
        self.assertEqual(parse_webcam_ack_packet(Packet("webcam-ack", 0, 5)), (0, 5))
        self.assertEqual(parse_webcam_ack_packet(Packet("webcam-ack", 0, 0, 640, 480)), (0, 0))
        for fn, packet in (
            (parse_webcam_start_packet, Packet("webcam-start", 0, 640)),
            (parse_webcam_start_packet, Packet("webcam-start", 0, 0, 480)),
            (parse_webcam_start_packet, Packet("webcam-start", 0, 640, 2**16)),
            (parse_webcam_start_packet, Packet("webcam-start", 0, 20000, 20)),
            (parse_webcam_stop_packet, Packet("webcam-stop", 0, "x" * 257)),
            (parse_webcam_stop_packet, Packet("webcam-stop", 0, "end", 1)),
            (parse_webcam_ack_packet, Packet("webcam-ack", 0, -1)),
            (parse_webcam_ack_packet, Packet("webcam-ack", 0, 0, 640)),
        ):
            with self.assertRaises(ValueError, msg=f"{packet!r} accepted"):
                fn(packet)

    def test_frame(self):
        frame = parse_webcam_frame_packet(frame_packet())
        self.assertEqual(check_webcam_frame(frame), "")
        mmap = parse_webcam_frame_packet(frame_packet("mmap", 4, 4, b"", {"chunks": ((0, 64), ), "pixel-format": "BGRX"}))
        self.assertEqual(check_webcam_frame(mmap), "")
        rgb = parse_webcam_frame_packet(frame_packet("mmap", 4, 4, b"", {"chunks": ((0, 30), (100, 18)), "pixel-format": "RGB"}))
        self.assertEqual(check_webcam_frame(rgb), "")
        for packet in (
            Packet(*frame_packet()[:6]),
            Packet(*frame_packet(), 1),
            frame_packet(w=0, data=png_data(4, 4)),
            frame_packet(data=bytes(4 * 4 * 8 + 65537)),
            frame_packet(options={f"key{i}": i for i in range(17)}),
            frame_packet(options={"pixel-format": "XYZ"}),
            frame_packet(options={"chunks": ((0, 0), )}),
            frame_packet(options={"chunks": ((0, 8), ) * 257}),
            frame_packet(options={"other": object()}),
        ):
            with self.assertRaises((ValueError, TypeError), msg=f"{packet!r} accepted"):
                parse_webcam_frame_packet(packet)

    def test_frame_data(self):
        for packet, message in (
            (frame_packet("h264", data=b"data"), "unsupported"),
            (frame_packet("jpeg"), "invalid jpeg"),
            (frame_packet(data=b"\x89PNG" + bytes(10)), "invalid png"),
            (frame_packet("mmap", data=b"", options={}), "chunks"),
            (frame_packet("mmap", data=b"x", options={"chunks": ((0, 64), )}), "pixel data"),
            (frame_packet("mmap", data=b"", options={"chunks": ((0, 63), )}), "not enough"),
            (frame_packet("mmap", data=b"", options={"chunks": ((0, 65), )}), "expected 64"),
            (frame_packet("mmap", data=b"", options={"chunks": ((0, 64), (128, 64))}), "expected 64"),
            (frame_packet("mmap", data=b"", options={"chunks": ((0, 48), ), "pixel-format": "BGRX"}), "not enough"),
        ):
            self.assertIn(message, check_webcam_frame(parse_webcam_frame_packet(packet)))
        self.assertIn("unsupported", check_webcam_frame(parse_webcam_frame_packet(frame_packet()), ("jpeg", )))


class WebcamSourceTest(unittest.TestCase):

    def make_source(self):
        from xpra.server.source.webcam import WebcamConnection
        source = WebcamConnection()
        source.webcam_encodings = ["png", "jpeg", "webp"]
        source.sent = []
        source.send_async = lambda *args: source.sent.append(args)
        device = MagicMock()
        source.webcam_forwarding_devices[0] = device
        return source, device

    def test_invalid_frame_stops(self):
        source, device = self.make_source()
        # mmap is not enabled for this connection:
        frame = parse_webcam_frame_packet(frame_packet("mmap", 4, 4, b"", {"chunks": ((0, 64), )}))
        self.assertFalse(source.process_webcam_frame(*frame))
        self.assertEqual(source.sent[0][0], "webcam-stop")
        self.assertIn("unsupported", source.sent[0][2])
        device.clean.assert_called_once()
        self.assertEqual(source.webcam_forwarding_devices, {})

    def test_oversized_mmap_is_rejected_before_read(self):
        source, device = self.make_source()
        source.mmap_supported = True
        source.mmap_read_area = MagicMock()
        frame = parse_webcam_frame_packet(frame_packet("mmap", 4, 4, b"", {"chunks": ((8, 65), )}))
        self.assertFalse(source.process_webcam_frame(*frame))
        source.mmap_read_area.mmap_read.assert_not_called()
        device.clean.assert_called_once()
        self.assertIn("expected 64", source.sent[0][2])

    def test_decoded_size_mismatch(self):
        source, device = self.make_source()
        # a valid 8x8 png, claiming to be 4x4:
        frame = parse_webcam_frame_packet(frame_packet("png", 4, 4, png_data(8, 8)))
        self.assertEqual(check_webcam_frame(frame), "")
        self.assertFalse(source.process_webcam_frame(*frame))
        device.push_image.assert_not_called()
        self.assertEqual(source.sent[0][0], "webcam-stop")
        self.assertIn("8x8", source.sent[0][2])


def main():
    unittest.main()


if __name__ == '__main__':
    main()
