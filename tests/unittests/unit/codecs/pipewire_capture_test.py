#!/usr/bin/env python3

import os
import tempfile
import unittest
import sys
from unittest.mock import patch

from xpra.codecs.pipewire.capture import Capture, download_dmabuf, make_cpu_image


class Backend:
    def __init__(self, fd, node_id, callback):
        self.fd = fd
        self.node_id = node_id
        self.callback = callback
        self.starts = 0
        self.cleans = 0

    def start(self):
        self.starts += 1

    def clean(self):
        self.cleans += 1
        os.close(self.fd)

    def get_info(self):
        return {"test": True}


class PipeWireCaptureTest(unittest.TestCase):
    def make_capture(self):
        read_fd, write_fd = os.pipe()
        os.close(write_fd)
        capture = Capture(read_fd, 7, 2, 2, Backend)
        return capture, capture._backend

    def test_cpu_frame_padding_offset_and_dimensions(self):
        data = b"xxxx" + b"abcdefgh----ijklmnop----"
        image = make_cpu_image(data, 4, 24, 2, 2, 12, "BGRA")
        self.assertEqual(image.get_pixels(), b"abcdefgh----ijklmnop----")
        self.assertEqual(image.get_rowstride(), 12)
        self.assertEqual((image.get_width(), image.get_height()), (2, 2))
        with self.assertRaises(ValueError):
            make_cpu_image(data, 4, 15, 2, 2, 8, "BGRA")

    def test_latest_frame_and_refresh_coalescing(self):
        capture, backend = self.make_capture()
        callbacks = []
        frame = {"type": "memory", "data": b"A" * 16, "offset": 0, "size": 16,
                 "width": 2, "height": 2, "stride": 8, "format": "BGRX"}
        with patch("xpra.codecs.pipewire.capture.GLib.idle_add",
                   side_effect=lambda callback, *args: callbacks.append((callback, args)) or 1):
            capture.native_frame(frame)
            frame2 = dict(frame, data=b"B" * 8, width=1, stride=4, size=8)
            capture.native_frame(frame2)
        self.assertEqual(len(callbacks), 1)
        image = capture.get_image()
        self.assertEqual(image.get_pixels(), b"B" * 8)
        self.assertEqual((capture.width, capture.height), (1, 2))
        image.free()
        capture.clean()
        self.assertEqual(backend.cleans, 1)

    def test_start_clean_idempotent(self):
        capture, backend = self.make_capture()
        capture.start()
        capture.start()
        self.assertEqual(backend.starts, 1)
        capture.clean()
        capture.clean()
        self.assertEqual(backend.cleans, 1)

    def test_native_extension_absence_closes_fd(self):
        read_fd, write_fd = os.pipe()
        os.close(write_fd)
        with patch.dict(sys.modules, {"xpra.codecs.pipewire._native": None}):
            with self.assertRaisesRegex(RuntimeError, "--with-pipewire"):
                Capture(read_fd, 9)
        with self.assertRaises(OSError):
            os.fstat(read_fd)

    def test_linear_dmabuf_download(self):
        with tempfile.TemporaryFile() as f:
            f.write(b"pad!" + b"01234567abcdefgh")
            f.flush()
            image = download_dmabuf(f.fileno(), 4, 8, 2, 2, "BGRA", 0)
        self.assertEqual(image.get_pixels(), b"01234567abcdefgh")
        self.assertEqual(image.get_rowstride(), 8)
        with tempfile.TemporaryFile() as f:
            with self.assertRaises(ValueError):
                download_dmabuf(f.fileno(), 0, 8, 2, 2, "BGRA", 1)

    def test_unsupported_dmabuf_is_released(self):
        capture, _backend = self.make_capture()
        released = []
        capture.native_frame({
            "type": "dmabuf", "width": 2, "height": 2, "stride": 8,
            "format": "BGRA", "modifier": 42, "drm-format": 0x34325241,
            "fds": (-1,), "strides": (8,), "offsets": (0,),
            "release": lambda: released.append(True),
        })
        self.assertEqual(released, [True])
        self.assertIsNone(capture.get_image())
        capture.clean()


if __name__ == "__main__":
    unittest.main()
