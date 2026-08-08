#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Tests for the `scroll` paint of the win32 GDI backing.
All tests are skipped on non-Windows platforms.
"""

import sys
import unittest

WIN32 = sys.platform == "win32"


def make_backing(width=16, height=16, alpha=False):
    from xpra.client.win32.gdi_backing import GDIBacking
    from xpra.platform.win32.common import CreateCompatibleDC, DeleteDC
    hdc = CreateCompatibleDC(None)
    backing = GDIBacking(1, hdc, 0, width, height, alpha)

    def cleanup() -> None:
        backing.close()
        DeleteDC(hdc)

    return backing, cleanup


def get_pixels(backing) -> bytes:
    """the whole DIB section, as bytes"""
    from ctypes import string_at
    bw, bh = backing.size
    return string_at(backing.pixels, bw * bh * 4)


def set_pixels(backing, data: bytes) -> None:
    from ctypes import memmove
    bw, bh = backing.size
    assert len(data) == bw * bh * 4
    memmove(backing.pixels, data, len(data))


def row_pattern(width: int, height: int) -> bytes:
    """one distinct byte value per row, so scrolls are easy to verify"""
    return b"".join(bytes([y & 0xFF]) * (width * 4) for y in range(height))


def get_row(backing, y: int) -> bytes:
    bw = backing.size[0]
    return get_pixels(backing)[y * bw * 4:(y + 1) * bw * 4]


class ClipSpanTest(unittest.TestCase):
    """`clip_span` is pure python, it can be tested anywhere"""

    def test_no_clipping_needed(self):
        from xpra.client.win32.gdi_backing import clip_span
        self.assertEqual(clip_span(10, 20, 5, 100), (10, 20))
        self.assertEqual(clip_span(10, 20, -5, 100), (10, 20))

    def test_destination_overflows_end(self):
        from xpra.client.win32.gdi_backing import clip_span
        # [90, 100) moved by +5 would end at 105:
        self.assertEqual(clip_span(90, 10, 5, 100), (90, 5))

    def test_destination_overflows_start(self):
        from xpra.client.win32.gdi_backing import clip_span
        # [0, 10) moved by -5 would start at -5:
        self.assertEqual(clip_span(0, 10, -5, 100), (5, 5))

    def test_source_overflows(self):
        from xpra.client.win32.gdi_backing import clip_span
        # the source itself is out of bounds:
        self.assertEqual(clip_span(95, 20, -5, 100), (95, 5))
        self.assertEqual(clip_span(-5, 20, 5, 100), (0, 15))

    def test_nothing_left(self):
        from xpra.client.win32.gdi_backing import clip_span
        self.assertEqual(clip_span(0, 10, -100, 100)[1], 0)
        self.assertEqual(clip_span(0, 10, 100, 100)[1], 0)
        self.assertEqual(clip_span(200, 10, 0, 100)[1], 0)


@unittest.skipUnless(WIN32, "the GDI backing is only available on MS Windows")
class GDIScrollTest(unittest.TestCase):

    def make(self, width=16, height=16, alpha=False):
        backing, cleanup = make_backing(width, height, alpha)
        self.addCleanup(cleanup)
        set_pixels(backing, row_pattern(width, height))
        return backing

    def callbacks(self):
        results = []
        return results, [lambda success, message="": results.append((success, message))]

    def scroll(self, backing, scrolls):
        from xpra.util.objects import typedict
        results, cbs = self.callbacks()
        backing.paint_scroll(b"", typedict({"scroll": scrolls}), cbs)
        self.assertTrue(results, "the paint callbacks were not fired")
        self.assertEqual(len(results), 1, f"expected a single callback, got {results}")
        return results[0]

    def test_scroll_up(self):
        backing = self.make(16, 16)
        # move rows 4..16 up by 4:
        success, message = self.scroll(backing, ((0, 4, 16, 12, 0, -4), ))
        self.assertTrue(success, message)
        for y in range(12):
            self.assertEqual(get_row(backing, y), bytes([y + 4]) * 64, f"row {y}")
        # the rows below were not touched:
        for y in range(12, 16):
            self.assertEqual(get_row(backing, y), bytes([y]) * 64, f"row {y}")

    def test_scroll_down(self):
        backing = self.make(16, 16)
        # move rows 0..12 down by 4:
        success, message = self.scroll(backing, ((0, 0, 16, 12, 0, 4), ))
        self.assertTrue(success, message)
        for y in range(4):
            self.assertEqual(get_row(backing, y), bytes([y]) * 64, f"row {y}")
        for y in range(4, 16):
            self.assertEqual(get_row(backing, y), bytes([y - 4]) * 64, f"row {y}")

    def test_scroll_horizontal(self):
        backing = self.make(16, 16)
        # every row holds a single value, so use a column pattern instead:
        pixels = bytes(x & 0xFF for _ in range(16) for x in range(16) for _ in range(4))
        set_pixels(backing, pixels)
        # move columns 0..12 right by 4:
        success, message = self.scroll(backing, ((0, 0, 12, 16, 4, 0), ))
        self.assertTrue(success, message)
        row = get_row(backing, 0)
        for x in range(4):
            self.assertEqual(row[x * 4], x, f"column {x} should be untouched")
        for x in range(4, 16):
            self.assertEqual(row[x * 4], x - 4, f"column {x}")

    def test_swap_uses_a_snapshot(self):
        """
        two rectangles swapping places can only be painted correctly
        from a snapshot taken before either of them was applied
        """
        backing = self.make(16, 16)
        before = get_pixels(backing)
        # swap the top and bottom halves:
        success, message = self.scroll(backing, ((0, 0, 16, 8, 0, 8), (0, 8, 16, 8, 0, -8)))
        self.assertTrue(success, message)
        for y in range(8):
            self.assertEqual(get_row(backing, y), bytes([y + 8]) * 64, f"row {y}")
            self.assertEqual(get_row(backing, y + 8), bytes([y]) * 64, f"row {y + 8}")
        # scrolling back must restore the original contents:
        self.scroll(backing, ((0, 0, 16, 8, 0, 8), (0, 8, 16, 8, 0, -8)))
        self.assertEqual(get_pixels(backing), before)

    def test_overlapping_source_and_destination(self):
        """the source of the second rectangle is the destination of the first"""
        backing = self.make(16, 16)
        success, message = self.scroll(backing, ((0, 0, 16, 4, 0, 4), (0, 4, 16, 4, 0, 8)))
        self.assertTrue(success, message)
        for y in range(4, 8):
            # rows 4..8 come from rows 0..4:
            self.assertEqual(get_row(backing, y), bytes([y - 4]) * 64, f"row {y}")
        for y in range(12, 16):
            # rows 12..16 come from rows 4..8 *before* the first rectangle was applied:
            self.assertEqual(get_row(backing, y), bytes([y - 8]) * 64, f"row {y}")

    def test_partial_width_scroll(self):
        backing = self.make(16, 16)
        # only scroll the left half, so the rows are not contiguous:
        success, message = self.scroll(backing, ((0, 4, 8, 12, 0, -4), ))
        self.assertTrue(success, message)
        for y in range(12):
            row = get_row(backing, y)
            self.assertEqual(row[:32], bytes([y + 4]) * 32, f"left half of row {y}")
            self.assertEqual(row[32:], bytes([y]) * 32, f"right half of row {y}")

    def test_diagonal_offset_scroll(self):
        """the snapshot does not start at (0, 0), so its origin must be taken into account"""
        backing = self.make(16, 16)
        # give every pixel a value that depends on both coordinates:
        pixels = bytes((x * 16 + y) & 0xFF for y in range(16) for x in range(16) for _ in range(4))
        set_pixels(backing, pixels)
        # move the (4, 4, 8, 8) square by (2, 3):
        success, message = self.scroll(backing, ((4, 4, 8, 8, 2, 3), ))
        self.assertTrue(success, message)
        data = get_pixels(backing)

        def pixel(x, y):
            return data[(y * 16 + x) * 4]

        for y in range(4, 12):
            for x in range(4, 12):
                self.assertEqual(pixel(x + 2, y + 3), (x * 16 + y) & 0xFF, f"pixel {(x + 2, y + 3)}")
        # a pixel outside of the destination square is untouched:
        self.assertEqual(pixel(0, 0), 0)
        self.assertEqual(pixel(15, 0), 15 * 16)

    def test_clipped_scroll(self):
        backing = self.make(16, 16)
        # the destination overflows the bottom of the backing by 4 rows:
        success, message = self.scroll(backing, ((0, 0, 16, 16, 0, 4), ))
        self.assertTrue(success, message)
        for y in range(4, 16):
            self.assertEqual(get_row(backing, y), bytes([y - 4]) * 64, f"row {y}")

    def test_no_delta_is_skipped(self):
        backing = self.make(16, 16)
        before = get_pixels(backing)
        success, _ = self.scroll(backing, ((0, 0, 16, 16, 0, 0), ))
        self.assertFalse(success)
        self.assertEqual(get_pixels(backing), before)

    def test_out_of_range_delta_fails(self):
        backing = self.make(16, 16)
        before = get_pixels(backing)
        success, _ = self.scroll(backing, ((0, 0, 16, 16, 0, 100), ))
        self.assertFalse(success)
        self.assertEqual(get_pixels(backing), before)

    def test_partial_failure_is_reported(self):
        backing = self.make(16, 16)
        # the first rectangle is valid, the second one is not:
        success, _ = self.scroll(backing, ((0, 4, 16, 12, 0, -4), (0, 0, 16, 16, 0, 100)))
        self.assertFalse(success)
        # the valid rectangle was still applied:
        self.assertEqual(get_row(backing, 0), bytes([4]) * 64)

    def test_empty_scroll_list(self):
        backing = self.make(16, 16)
        before = get_pixels(backing)
        success, message = self.scroll(backing, ())
        self.assertTrue(success, message)
        self.assertEqual(get_pixels(backing), before)

    def test_closed_backing(self):
        backing = self.make(16, 16)
        backing.close()
        success, _ = self.scroll(backing, ((0, 4, 16, 12, 0, -4), ))
        self.assertFalse(success)

    def test_scroll_data_from_img_data(self):
        """older servers overload the packet's image data"""
        from xpra.util.objects import typedict
        backing = self.make(16, 16)
        results, cbs = self.callbacks()
        backing.paint_scroll(((0, 4, 16, 12, 0, -4), ), typedict(), cbs)
        self.assertTrue(results and results[0][0], results)
        self.assertEqual(get_row(backing, 0), bytes([4]) * 64)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
