#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Yan Shoshitaishvili <yans@pwn.college>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import zlib
import unittest
from base64 import b64encode

from unit.client.terminal.terminal_test_util import APC, ST, DECSC, DECRC, split_escapes

try:
    from xpra.client.terminal import graphics
except ImportError:
    graphics = None

# 1 fully transparent RGBA pixel, which zlib makes bigger rather than smaller:
PIXEL = b"\0\0\0\0"


def raw_pixels(size: int) -> bytes:
    """ deterministic pixel data, only ever transmitted with compression disabled """
    return bytes(range(256)) * (size // 256) + bytes(range(size % 256))


def semi_random_pixels(size: int) -> bytes:
    """
    Deterministic pixel data with roughly 4 bits of entropy per byte:
    deflate shrinks it, but not enough to fit in a single chunk.
    """
    state = 12345
    data = bytearray(size)
    for i in range(size):
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        data[i] = (state >> 16) & 0x0F
    return bytes(data)


@unittest.skipIf(graphics is None, "the terminal client graphics module is not available")
class TestConstants(unittest.TestCase):

    def test_defaults(self):
        # the payload of every non-final chunk must be a multiple of 4:
        self.assertEqual(graphics.MAX_CHUNK % 4, 0)
        self.assertEqual(graphics.FRAME_ACTION, "a=f")

    def test_escape_without_payload(self):
        self.assertEqual(graphics.escape("a=d,i=1"), b"\x1b_Ga=d,i=1\x1b\\")

    def test_escape_with_payload(self):
        self.assertEqual(graphics.escape("a=t,i=1", b"AAAA"), b"\x1b_Ga=t,i=1;AAAA\x1b\\")


@unittest.skipIf(graphics is None, "the terminal client graphics module is not available")
class TestTransmit(unittest.TestCase):

    def test_single_pixel_golden(self):
        self.assertEqual(graphics.transmit(1, 1, 1, PIXEL),
                         b"\x1b_Ga=t,q=2,i=1,f=32,s=1,v=1;AAAAAA==\x1b\\")

    def test_rgb_golden(self):
        self.assertEqual(graphics.transmit(7, 2, 1, b"\x01\x02\x03\x04\x05\x06", alpha=False),
                         b"\x1b_Ga=t,q=2,i=7,f=24,s=2,v=1;AQIDBAUG\x1b\\")

    def test_quiet(self):
        self.assertIn("q=2", split_escapes(graphics.transmit(1, 1, 1, PIXEL))[0][0])

    def test_compression_skipped_when_it_does_not_help(self):
        # a single pixel deflates to more bytes than it started with:
        self.assertGreater(len(zlib.compress(PIXEL)), len(PIXEL))
        control, payload = split_escapes(graphics.transmit(1, 1, 1, PIXEL, compress=True))[0]
        self.assertNotIn("o=z", control)
        self.assertEqual(payload, b64encode(PIXEL))

    def test_compression_applied_when_it_helps(self):
        pixels = b"\0" * 4096
        deflated = zlib.compress(pixels)
        self.assertLess(len(deflated), len(pixels))
        control, payload = split_escapes(graphics.transmit(3, 32, 32, pixels))[0]
        self.assertEqual(control, "a=t,q=2,i=3,f=32,s=32,v=32,o=z")
        self.assertEqual(payload, b64encode(deflated))

    def test_compression_disabled(self):
        pixels = b"\0" * 1024
        control, payload = split_escapes(graphics.transmit(3, 16, 16, pixels, compress=False))[0]
        self.assertEqual(control, "a=t,q=2,i=3,f=32,s=16,v=16")
        self.assertEqual(payload, b64encode(pixels))

    def test_invalid_image_id(self):
        for image_id in (-1, 2 ** 32, 2 ** 40):
            with self.assertRaises(ValueError):
                graphics.transmit(image_id, 1, 1, PIXEL)


@unittest.skipIf(graphics is None, "the terminal client graphics module is not available")
class TestChunking(unittest.TestCase):

    def transmitted(self, raw_size: int):
        pixels = raw_pixels(raw_size)
        data = graphics.transmit(5, 1, raw_size // 4, pixels, compress=False)
        return pixels, split_escapes(data)

    def test_exactly_one_chunk(self):
        # 3 raw bytes encode to 4 base64 bytes: this hits the limit exactly
        raw_size = graphics.MAX_CHUNK // 4 * 3
        pixels, escapes = self.transmitted(raw_size)
        self.assertEqual(len(escapes), 1)
        control, payload = escapes[0]
        self.assertEqual(len(payload), graphics.MAX_CHUNK)
        self.assertNotIn("m=", control)
        self.assertEqual(payload, b64encode(pixels))

    def test_two_chunks(self):
        raw_size = graphics.MAX_CHUNK // 4 * 3 + 3
        pixels, escapes = self.transmitted(raw_size)
        self.assertEqual(len(escapes), 2)
        self.assertTrue(escapes[0][0].endswith(",m=1"), escapes[0][0])
        self.assertEqual(len(escapes[0][1]), graphics.MAX_CHUNK)
        self.assertEqual(escapes[1][0], "m=0")
        self.assertEqual(len(escapes[1][1]), 4)
        self.assertEqual(b"".join(payload for _, payload in escapes), b64encode(pixels))

    def test_many_chunks(self):
        raw_size = graphics.MAX_CHUNK * 3
        pixels, escapes = self.transmitted(raw_size)
        encoded = b64encode(pixels)
        expected = (len(encoded) + graphics.MAX_CHUNK - 1) // graphics.MAX_CHUNK
        self.assertEqual(len(escapes), expected)
        self.assertGreater(expected, 2)
        # only the first chunk carries the control data:
        self.assertEqual(escapes[0][0], "a=t,q=2,i=5,f=32,s=1,v=%i,m=1" % (raw_size // 4))
        for control, payload in escapes[1:-1]:
            self.assertEqual(control, "m=1")
            self.assertEqual(len(payload), graphics.MAX_CHUNK)
            self.assertEqual(len(payload) % 4, 0)
        self.assertEqual(escapes[-1][0], "m=0")
        # every chunk but the last one is full, and a multiple of 4:
        for _, payload in escapes[:-1]:
            self.assertEqual(len(payload), graphics.MAX_CHUNK)
            self.assertEqual(len(payload) % 4, 0)
        self.assertLessEqual(len(escapes[-1][1]), graphics.MAX_CHUNK)
        self.assertEqual(b"".join(payload for _, payload in escapes), encoded)

    def test_compressed_payload_is_chunked(self):
        pixels = semi_random_pixels(40000)
        deflated = zlib.compress(pixels)
        self.assertLess(len(deflated), len(pixels))
        encoded = b64encode(deflated)
        self.assertGreater(len(encoded), graphics.MAX_CHUNK * 2)
        escapes = split_escapes(graphics.transmit(5, 100, 100, pixels))
        self.assertGreater(len(escapes), 2)
        self.assertTrue(escapes[0][0].endswith(",m=1"), escapes[0][0])
        self.assertIn("o=z", escapes[0][0])
        for control, payload in escapes[1:-1]:
            self.assertEqual(control, "m=1")
            self.assertEqual(len(payload), graphics.MAX_CHUNK)
        self.assertEqual(escapes[-1][0], "m=0")
        self.assertEqual(b"".join(payload for _, payload in escapes), encoded)

    def test_patch_chunks_repeat_the_frame_action_and_target(self):
        # the protocol requires every continuation chunk of an `a=f` transmission to repeat `a=f`;
        # `i` and `r` are repeated as well: kitty computes the frame number from
        # each continuation chunk, and a missing `r` appends a new animation
        # frame instead of editing frame 1 (the edit is accepted, never shown)
        raw_size = graphics.MAX_CHUNK // 4 * 3 + 3
        pixels = raw_pixels(raw_size)
        escapes = split_escapes(graphics.patch(5, 0, 0, 1, raw_size // 4, pixels, compress=False))
        self.assertEqual(len(escapes), 2)
        self.assertTrue(escapes[0][0].startswith("a=f,"), escapes[0][0])
        self.assertTrue(escapes[0][0].endswith(",m=1"), escapes[0][0])
        self.assertEqual(len(escapes[0][1]), graphics.MAX_CHUNK)
        self.assertEqual(escapes[1][0], "a=f,i=5,r=1,m=0")
        self.assertEqual(b"".join(payload for _, payload in escapes), b64encode(pixels))

    def test_patch_many_chunks(self):
        raw_size = graphics.MAX_CHUNK * 3
        pixels = raw_pixels(raw_size)
        encoded = b64encode(pixels)
        escapes = split_escapes(graphics.patch(5, 2, 4, 1, raw_size // 4, pixels, compress=False))
        expected = (len(encoded) + graphics.MAX_CHUNK - 1) // graphics.MAX_CHUNK
        self.assertEqual(len(escapes), expected)
        self.assertGreater(expected, 2)
        self.assertEqual(escapes[0][0],
                         "a=f,q=2,i=5,r=1,x=2,y=4,s=1,v=%i,X=1,m=1" % (raw_size // 4))
        for control, payload in escapes[1:-1]:
            self.assertEqual(control, "a=f,i=5,r=1,m=1")
            self.assertEqual(len(payload), graphics.MAX_CHUNK)
            self.assertEqual(len(payload) % 4, 0)
        self.assertEqual(escapes[-1][0], "a=f,i=5,r=1,m=0")
        self.assertLessEqual(len(escapes[-1][1]), graphics.MAX_CHUNK)
        self.assertEqual(b"".join(payload for _, payload in escapes), encoded)

    def test_patch_golden_two_chunks(self):
        # the exact bytes of a 2 chunk frame transmission:
        pixels = raw_pixels(graphics.MAX_CHUNK // 4 * 3 + 3)
        encoded = b64encode(pixels)
        data = graphics.patch(5, 0, 0, 1, len(pixels) // 4, pixels, compress=False)
        self.assertEqual(data,
                         APC + b"a=f,q=2,i=5,r=1,x=0,y=0,s=1,v=%i,X=1,m=1;" % (len(pixels) // 4) +
                         encoded[:graphics.MAX_CHUNK] + ST +
                         APC + b"a=f,i=5,r=1,m=0;" + encoded[graphics.MAX_CHUNK:] + ST)

    def test_transmit_chunks_carry_no_action(self):
        # `a=t` is the opposite case: continuation chunks must carry only `m=`
        raw_size = graphics.MAX_CHUNK * 3
        _, escapes = self.transmitted(raw_size)
        for control, _ in escapes[1:]:
            self.assertNotIn("a=", control)

    def test_chunked_continuation_prefix(self):
        payload = b"A" * (graphics.MAX_CHUNK * 2)
        escapes = split_escapes(graphics.chunked("a=x,i=1", payload))
        self.assertEqual([control for control, _ in escapes], ["a=x,i=1,m=1", "m=0"])
        escapes = split_escapes(graphics.chunked("a=x,i=1", payload, cont="a=x"))
        self.assertEqual([control for control, _ in escapes], ["a=x,i=1,m=1", "a=x,m=0"])


@unittest.skipIf(graphics is None, "the terminal client graphics module is not available")
class TestSharedMemory(unittest.TestCase):

    def test_transmit_shm(self):
        escapes = split_escapes(graphics.transmit_shm(7, 1908, 1152, "/xpra-terminal-1-2"))
        self.assertEqual(len(escapes), 1)
        control, payload = escapes[0]
        self.assertEqual(control, "a=t,q=2,i=7,f=32,s=1908,v=1152,t=s,S=%i" % (1908 * 1152 * 4))
        self.assertEqual(payload, b64encode(b"/xpra-terminal-1-2"))

    def test_patch_shm(self):
        escapes = split_escapes(graphics.patch_shm(7, 10, 20, 640, 480, "/xpra-terminal-1-3"))
        self.assertEqual(len(escapes), 1)
        control, payload = escapes[0]
        self.assertEqual(control, "a=f,q=2,i=7,r=1,x=10,y=20,s=640,v=480,X=1,t=s,S=%i" % (640 * 480 * 4))
        self.assertEqual(payload, b64encode(b"/xpra-terminal-1-3"))

    def test_probe_shm_is_not_quieted(self):
        escapes = split_escapes(graphics.probe_shm(9, "/xpra-terminal-1-1"))
        self.assertEqual(len(escapes), 1)
        control, payload = escapes[0]
        self.assertEqual(control, "a=q,i=9,f=32,s=1,v=1,t=s,S=4")
        self.assertNotIn("q=2", control)
        self.assertEqual(payload, b64encode(b"/xpra-terminal-1-1"))


@unittest.skipIf(graphics is None, "the terminal client graphics module is not available")
class TestPlace(unittest.TestCase):

    def test_golden(self):
        self.assertEqual(graphics.place(1, 1, 3, 5, 2, 7, 10),
                         b"\x1b7\x1b[3;5H\x1b_Ga=p,q=2,i=1,p=1,z=10,C=1,X=2,Y=7\x1b\\\x1b8")

    def test_structure(self):
        data = graphics.place(9, 4, 12, 34, 5, 6, -3)
        self.assertTrue(data.startswith(DECSC), data)
        self.assertTrue(data.endswith(DECRC), data)
        cup_end = data.index(b"H")
        self.assertEqual(data[len(DECSC):cup_end + 1], b"\x1b[12;34H")
        # the escape sequence sits between the cursor save/restore pair:
        self.assertLess(cup_end, data.index(APC))
        self.assertLess(data.index(APC), data.index(DECRC, len(DECSC)))

    def test_negative_z(self):
        data = graphics.place(1, 1, 1, 1, 0, 0, -5)
        control = data[data.index(APC) + len(APC):data.index(ST)].decode("ascii")
        self.assertEqual(control, "a=p,q=2,i=1,p=1,z=-5,C=1,X=0,Y=0")

    def test_row_and_column_are_clamped(self):
        self.assertIn(b"\x1b[1;1H", graphics.place(1, 1, 0, 0, 0, 0, 10))
        self.assertIn(b"\x1b[1;1H", graphics.place(1, 1, -4, -9, 0, 0, 10))

    def test_quiet_and_no_cursor_move(self):
        data = graphics.place(1, 2, 3, 4, 0, 0, 10)
        control = data[data.index(APC) + len(APC):data.index(ST)].decode("ascii")
        self.assertIn("q=2", control)
        self.assertIn("C=1", control)

    def test_invalid_ids(self):
        with self.assertRaises(ValueError):
            graphics.place(2 ** 32, 1, 1, 1, 0, 0, 10)
        with self.assertRaises(ValueError):
            graphics.place(1, -1, 1, 1, 0, 0, 10)
        with self.assertRaises(ValueError):
            graphics.place(1, 1, 1, 1, 0, 0, 2 ** 31)


@unittest.skipIf(graphics is None, "the terminal client graphics module is not available")
class TestPatch(unittest.TestCase):

    def test_golden(self):
        self.assertEqual(graphics.patch(1, 0, 0, 1, 1, PIXEL),
                         b"\x1b_Ga=f,q=2,i=1,r=1,x=0,y=0,s=1,v=1,X=1;AAAAAA==\x1b\\")

    def test_offset_golden(self):
        self.assertEqual(graphics.patch(4, 16, 32, 1, 1, PIXEL),
                         b"\x1b_Ga=f,q=2,i=4,r=1,x=16,y=32,s=1,v=1,X=1;AAAAAA==\x1b\\")

    def test_compressed(self):
        pixels = b"\0" * 4096
        deflated = zlib.compress(pixels)
        control, payload = split_escapes(graphics.patch(4, 1, 2, 32, 32, pixels))[0]
        self.assertEqual(control, "a=f,q=2,i=4,r=1,x=1,y=2,s=32,v=32,o=z,X=1")
        self.assertEqual(payload, b64encode(deflated))

    def test_replace_flag_is_always_set(self):
        for compress in (True, False):
            control = split_escapes(graphics.patch(4, 0, 0, 1, 1, PIXEL, compress=compress))[0][0]
            self.assertIn("X=1", control)
            self.assertIn("q=2", control)
            self.assertIn("r=1", control)

    def test_invalid_image_id(self):
        with self.assertRaises(ValueError):
            graphics.patch(2 ** 32, 0, 0, 1, 1, PIXEL)


@unittest.skipIf(graphics is None, "the terminal client graphics module is not available")
class TestDelete(unittest.TestCase):

    def test_delete_placement_golden(self):
        self.assertEqual(graphics.delete_placement(1, 2), b"\x1b_Ga=d,d=i,i=1,p=2,q=2\x1b\\")

    def test_delete_image_golden(self):
        self.assertEqual(graphics.delete_image(1), b"\x1b_Ga=d,d=I,i=1,q=2\x1b\\")

    def test_lowercase_keeps_the_data(self):
        # `d=i` keeps the image data, `d=I` frees it:
        self.assertIn("d=i,", split_escapes(graphics.delete_placement(6, 7))[0][0])
        self.assertIn("d=I,", split_escapes(graphics.delete_image(6))[0][0])

    def test_quiet(self):
        self.assertIn("q=2", split_escapes(graphics.delete_placement(6, 7))[0][0])
        self.assertIn("q=2", split_escapes(graphics.delete_image(6))[0][0])

    def test_no_payload(self):
        self.assertEqual(split_escapes(graphics.delete_placement(6, 7))[0][1], b"")
        self.assertEqual(split_escapes(graphics.delete_image(6))[0][1], b"")

    def test_invalid_ids(self):
        with self.assertRaises(ValueError):
            graphics.delete_image(2 ** 32)
        with self.assertRaises(ValueError):
            graphics.delete_placement(1, 2 ** 32)


@unittest.skipIf(graphics is None, "the terminal client graphics module is not available")
class TestProbe(unittest.TestCase):

    def test_golden(self):
        self.assertEqual(graphics.probe(31), b"\x1b_Ga=q,i=31,f=32,s=1,v=1,t=d;AAAAAA==\x1b\\")

    def test_not_quieted(self):
        # the probe is the one command we want a reply from:
        control, payload = split_escapes(graphics.probe(31))[0]
        self.assertNotIn("q=", control)
        self.assertEqual(payload, b64encode(b"\0\0\0\0"))

    def test_invalid_image_id(self):
        with self.assertRaises(ValueError):
            graphics.probe(-1)


@unittest.skipIf(graphics is None, "the terminal client graphics module is not available")
class TestProbeFrameEdit(unittest.TestCase):

    def test_golden(self):
        self.assertEqual(graphics.probe_frame_edit(31),
                         b"\x1b_Ga=f,i=31,r=1,x=0,y=0,s=1,v=1,X=1;AAAA/w==\x1b\\")

    def test_not_quieted(self):
        # like the transmission probe, we want the terminal's reply:
        control, payload = split_escapes(graphics.probe_frame_edit(31))[0]
        self.assertNotIn("q=", control)
        self.assertEqual(payload, b64encode(b"\0\0\0\xff"))

    def test_edits_frame_one_in_place(self):
        control = split_escapes(graphics.probe_frame_edit(31))[0][0]
        for key in ("a=f", "r=1", "X=1", "s=1", "v=1"):
            self.assertIn(key, control)

    def test_invalid_image_id(self):
        with self.assertRaises(ValueError):
            graphics.probe_frame_edit(-1)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
