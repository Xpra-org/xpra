#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gc
import unittest

from xpra.os_util import POSIX

try:
    from xpra.x11.bindings.ximage import XImageWrapper
except ImportError:
    XImageWrapper = None


W = 64
H = 48
DEPTH = 24
BPP = 4
ROWSTRIDE = W * BPP


def make_pixels(w=W, h=H, rowstride=ROWSTRIDE):
    # each pixel byte is derived from the sum of its coordinates (modulo 256),
    # so we can verify that a sub-image lines up with the parent region:
    buf = bytearray(rowstride * h)
    for y in range(h):
        for x in range(w):
            v = (x + y) % 256
            for i in range(BPP):
                buf[y * rowstride + x * BPP + i] = v
    return bytes(buf)


def make_image():
    img = XImageWrapper(0, 0, W, H, 0, "BGRX", DEPTH, ROWSTRIDE)
    img.set_pixels(make_pixels())
    return img


def verify_region(sub, x_off, y_off):
    # the sub-image pixel (sx, sy) must match the parent pixel (x_off+sx, y_off+sy):
    w = sub.get_width()
    h = sub.get_height()
    rowstride = sub.get_rowstride()
    pixels = sub.get_pixels()
    assert len(pixels) == sub.get_size()
    for sy in range(h):
        for sx in range(w):
            v = ((x_off + sx) + (y_off + sy)) % 256
            for i in range(BPP):
                av = pixels[sy * rowstride + sx * BPP + i]
                if av != v:
                    raise AssertionError(
                        f"expected {v:#x} at sub pixel ({sx}, {sy}) [parent ({x_off+sx}, {y_off+sy})], got {av:#x}")


@unittest.skipUnless(POSIX and XImageWrapper is not None, "no XImageWrapper binding")
class XImageWrapperTest(unittest.TestCase):

    def test_parent_attributes(self):
        img = make_image()
        assert img.get_width() == W
        assert img.get_height() == H
        assert img.get_depth() == DEPTH
        assert img.get_rowstride() == ROWSTRIDE
        assert img.get_size() == ROWSTRIDE * H
        assert img.has_pixels()
        assert len(img.get_pixels()) == ROWSTRIDE * H
        img.free()

    def test_zerocopy_sub_image(self):
        # a region that does not reach the bottom row is a zero-copy view:
        # it keeps the parent rowstride and its pixels alias the parent buffer.
        img = make_image()
        sub = img.get_sub_image(1, 0, 8, 6)
        assert sub.get_rowstride() == ROWSTRIDE, "zero-copy sub should keep the parent rowstride"
        assert sub.get_size() == ROWSTRIDE * 6
        assert sub.get_x() == 1
        verify_region(sub, 1, 0)
        sub.free()
        img.free()

    def test_bottom_edge_copy(self):
        # a region reaching the bottom row at x>0 would over-read the parent
        # buffer in a zero-copy view, so it must be a tightly packed copy:
        SW, SH = 5, 4
        img = make_image()
        x_off = 3
        y_off = H - SH
        sub = img.get_sub_image(x_off, y_off, SW, SH)
        assert sub.get_rowstride() == SW * BPP, "bottom-edge sub should be re-strided to a tight copy"
        assert sub.get_size() == SW * BPP * SH
        assert len(sub.get_pixels()) == SW * BPP * SH
        verify_region(sub, x_off, y_off)
        # the copy is independent: freeing the parent must not affect it
        img.free()
        verify_region(sub, x_off, y_off)
        sub.free()

    def test_bottom_edge_at_x0_is_zerocopy(self):
        # bottom row but x==0: no over-read, so it stays a zero-copy view:
        SH = 4
        img = make_image()
        sub = img.get_sub_image(0, H - SH, W, SH)
        assert sub.get_rowstride() == ROWSTRIDE
        verify_region(sub, 0, H - SH)
        sub.free()
        img.free()

    def test_parent_kept_alive(self):
        # a zero-copy sub-image holds a reference to its parent, so the parent
        # (and its pixel buffer) must survive garbage collection:
        img = make_image()
        sub = img.get_sub_image(2, 1, 8, 8)
        del img
        gc.collect()
        verify_region(sub, 2, 1)
        sub.free()

    def test_access_after_parent_freed_fails(self):
        # explicitly freeing the parent invalidates a zero-copy sub-image:
        # accessing its pixels must fail loudly rather than read freed memory.
        img = make_image()
        sub = img.get_sub_image(2, 1, 8, 8)
        img.free()
        try:
            sub.get_pixels()
        except AssertionError:
            pass
        else:
            raise AssertionError("accessing a sub-image after its parent was freed should fail")

    def test_invalid_sub_image(self):
        img = make_image()
        for x, y, w, h in (
            (0, 0, 0, 1),
            (0, 0, 1, 0),
            (1, 0, W, 1),
            (0, 1, 1, H),
        ):
            try:
                img.get_sub_image(x, y, w, h)
            except ValueError:
                pass
            else:
                raise AssertionError(f"sub-image with coords {(x, y, w, h)} should have failed")
        img.free()


def main():
    unittest.main()


if __name__ == "__main__":
    main()
