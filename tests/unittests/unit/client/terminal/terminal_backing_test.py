#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Yan Shoshitaishvili <yans@pwn.college>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.constants import Gravity
from xpra.util.objects import typedict

try:
    from xpra.client.terminal import backing as terminal_backing
except ImportError:
    terminal_backing = None

RGB_MODES = ("BGRA", "BGRX", "RGBA", "RGBX", "RGB", "BGR")


def make_pixels(width: int, height: int, bpp: int, rowstride: int, seed: int = 7) -> bytes:
    """ deterministic pixel data, the padding bytes are filled with a recognizable value """
    data = bytearray(b"\xAA" * (rowstride * height))
    state = seed
    for row in range(height):
        for i in range(width * bpp):
            state = (state * 1103515245 + 12345) & 0x7FFFFFFF
            data[row * rowstride + i] = (state >> 16) & 0xFF
    return bytes(data)


def reference_rgba(rgb_format: str, data: bytes, width: int, height: int, rowstride: int) -> bytes:
    """ the obvious, slow conversion to RGBA - `X` is padding and becomes opaque alpha """
    bpp = len(rgb_format)
    out = bytearray()
    for row in range(height):
        base = row * rowstride
        for col in range(width):
            pixel = data[base + col * bpp:base + (col + 1) * bpp]
            components = dict(zip(rgb_format, pixel))
            out += bytes((components["R"], components["G"], components["B"], components.get("A", 255)))
    return bytes(out)


def reference_scroll(pixels: bytes, width: int, scrolls) -> bytes:
    """
    Reference `scroll` implementation: every rectangle is copied
    from the same reference image, the contents before any of them was applied.
    """
    snapshot = bytes(pixels)
    out = bytearray(pixels)
    for x, y, w, h, xdelta, ydelta in scrolls:
        for row in range(h):
            src = ((y + row) * width + x) * 4
            dst = ((y + row + ydelta) * width + x + xdelta) * 4
            out[dst:dst + w * 4] = snapshot[src:src + w * 4]
    return bytes(out)


def make_callbacks():
    """ returns the paint callbacks list and the list recording every call made to them """
    calls = []

    def record(success, message="") -> None:
        calls.append((success, message))

    return [record], calls


@unittest.skipIf(terminal_backing is None, "the terminal client is not installed")
class TerminalBackingTest(unittest.TestCase):

    def make_backing(self, width=64, height=32, alpha=True):
        class InlineBacking(terminal_backing.TerminalBacking):
            """ run the deferred paints inline instead of on the GLib main loop """

            def with_gfx_context(self, function, *args) -> None:
                function(None, *args)

        b = InlineBacking(1, alpha)
        b.init(width, height, width, height)
        return b

    def fill(self, b, value: int = 0) -> None:
        b.pixels = bytearray(bytes((value,)) * len(b.pixels))

    ######################################################################
    # to_rgba

    def test_to_rgba_every_mode(self):
        width, height = 5, 3
        for rgb_format in RGB_MODES:
            bpp = len(rgb_format)
            for extra in (0, 1, 7):
                rowstride = width * bpp + extra
                data = make_pixels(width, height, bpp, rowstride)
                rgba = terminal_backing.to_rgba(rgb_format, data, width, height, rowstride)
                expected = reference_rgba(rgb_format, data, width, height, rowstride)
                self.assertEqual(rgba, expected, f"{rgb_format} with rowstride={rowstride}")
                self.assertEqual(len(rgba), width * height * 4)

    def test_to_rgba_padding_is_opaque(self):
        # the `X` byte is zero, the alpha channel must still be fully opaque:
        data = bytes((1, 2, 3, 0)) * 4
        rgba = terminal_backing.to_rgba("BGRX", data, 4, 1, 16)
        self.assertEqual(rgba, bytes((3, 2, 1, 255)) * 4)
        rgba = terminal_backing.to_rgba("RGBX", data, 4, 1, 16)
        self.assertEqual(rgba, bytes((1, 2, 3, 255)) * 4)

    def test_to_rgba_alpha_preserved(self):
        data = bytes((1, 2, 3, 4)) * 4
        self.assertEqual(terminal_backing.to_rgba("BGRA", data, 4, 1, 16), bytes((3, 2, 1, 4)) * 4)
        self.assertEqual(terminal_backing.to_rgba("RGBA", data, 4, 1, 16), data)

    def test_to_rgba_zero_rowstride_defaults(self):
        data = bytes((1, 2, 3)) * 4
        self.assertEqual(terminal_backing.to_rgba("RGB", data, 4, 1, 0), bytes((1, 2, 3, 255)) * 4)

    def test_to_rgba_invalid_format(self):
        for rgb_format in ("", "R", "RG", "RGBAX", "YUV"):
            with self.assertRaises(ValueError):
                terminal_backing.to_rgba(rgb_format, b"\0" * 64, 2, 2, 8)

    def test_to_rgba_short_buffer(self):
        with self.assertRaises(ValueError):
            terminal_backing.to_rgba("RGBA", b"\0" * 15, 2, 2, 8)

    ######################################################################
    # init / close

    def test_init_allocates_on_size_change(self):
        b = self.make_backing(10, 5)
        self.assertEqual(b.size, (10, 5))
        self.assertEqual(b.render_size, (10, 5))
        self.assertEqual(len(b.pixels), 10 * 5 * 4)
        serial = b.buffer_serial
        # same buffer size, different render size: no reallocation
        b.init(20, 10, 10, 5)
        self.assertEqual(b.buffer_serial, serial)
        self.assertEqual(b.render_size, (20, 10))
        b.init(20, 10, 20, 10)
        self.assertEqual(b.buffer_serial, serial + 1)
        self.assertEqual(len(b.pixels), 20 * 10 * 4)

    def test_init_keeps_the_contents_when_growing(self):
        b = self.make_backing(4, 2)
        self.fill(b, 0xEE)
        b.init(6, 4, 6, 4)
        # the old 4x2 area is preserved at the top left, the rest is transparent:
        self.assertEqual(b.pixels_for(0, 0, 4, 2), bytes((0xEE, )) * (4 * 2 * 4))
        self.assertEqual(b.pixels_for(4, 0, 2, 4), bytes(2 * 4 * 4))
        self.assertEqual(b.pixels_for(0, 2, 6, 2), bytes(6 * 2 * 4))

    def test_init_keeps_the_contents_when_shrinking(self):
        b = self.make_backing(8, 8)
        self.fill(b, 0x11)
        b.init(4, 4, 4, 4)
        self.assertEqual(b.pixels_for(0, 0, 4, 4), bytes((0x11, )) * (4 * 4 * 4))

    def test_init_copy_honours_the_window_gravity(self):
        b = self.make_backing(2, 2)
        b.gravity = Gravity.SouthEast
        b.blit(bytes((1, 2, 3, 4)) * 4, 0, 0, 2, 2)
        b.init(4, 4, 4, 4)
        # the old contents are anchored to the bottom right corner:
        self.assertEqual(b.pixels_for(2, 2, 2, 2), bytes((1, 2, 3, 4)) * 4)
        self.assertEqual(b.pixels_for(0, 0, 4, 2), bytes(4 * 2 * 4))

    def test_close_is_idempotent(self):
        b = self.make_backing()
        b.close()
        self.assertIsNone(b._backing)
        self.assertEqual(len(b.pixels), 0)
        b.close()
        self.assertIsNone(b._backing)

    def test_paint_on_closed_backing_is_skipped(self):
        b = self.make_backing()
        b.close()
        callbacks, calls = make_callbacks()
        b.do_paint_rgb(None, "rgb32", "BGRA", b"\0" * 64, 0, 0, 4, 4, 4, 4, 16, typedict(), callbacks)
        self.assertEqual(calls, [(-1, "this backing is closed")])

    ######################################################################
    # do_paint_rgb

    def paint(self, b, rgb_format, data, x, y, width, height, rowstride, options=None):
        callbacks, calls = make_callbacks()
        b.do_paint_rgb(None, "rgb32", rgb_format, data, x, y, width, height, width, height, rowstride,
                       typedict(options or {}), callbacks)
        return calls

    def test_paint_every_mode(self):
        width, height = 6, 4
        for rgb_format in RGB_MODES:
            bpp = len(rgb_format)
            for extra in (0, 3, 11):
                b = self.make_backing(32, 16)
                rowstride = width * bpp + extra
                data = make_pixels(width, height, bpp, rowstride)
                calls = self.paint(b, rgb_format, data, 3, 2, width, height, rowstride)
                self.assertEqual(calls, [(True, "")], f"{rgb_format} rowstride={rowstride}")
                expected = reference_rgba(rgb_format, data, width, height, rowstride)
                self.assertEqual(b.pixels_for(3, 2, width, height), expected)
                # the rest of the buffer is untouched:
                self.assertEqual(b.pixels_for(0, 0, 3, 1), b"\0" * 12)

    def test_paint_records_damage(self):
        b = self.make_backing(32, 16)
        self.paint(b, "RGBA", b"\0" * 64, 1, 2, 4, 4, 16)
        self.assertEqual(b.get_damage(), [(1, 2, 4, 4)])
        # the damage has been drained:
        self.assertEqual(b.get_damage(), [])

    def test_paint_clipped_to_backing(self):
        b = self.make_backing(8, 8)
        data = bytes((1, 2, 3, 4)) * 16
        calls = self.paint(b, "RGBA", data, 6, 6, 4, 4, 16)
        self.assertEqual(calls, [(True, "")])
        self.assertEqual(b.get_damage(), [(6, 6, 2, 2)])
        self.assertEqual(b.pixels_for(6, 6, 2, 2), data[:8] + data[:8])

    def test_paint_outside_backing_is_skipped(self):
        b = self.make_backing(8, 8)
        calls = self.paint(b, "RGBA", b"\0" * 64, 20, 20, 4, 4, 16)
        self.assertEqual(calls, [(-1, "paint rectangle is outside of the backing")])
        self.assertEqual(b.get_damage(), [])

    def test_paint_rowstride_overflow_rejected(self):
        b = self.make_backing(32, 16)
        # 4 rows of 4 pixels need 3*rowstride + 16 bytes:
        data = b"\x11" * (3 * 32 + 15)
        calls = self.paint(b, "RGBA", data, 0, 0, 4, 4, 32)
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0][0])
        self.assertIn("not enough pixel data", calls[0][1])
        # nothing was painted:
        self.assertEqual(b.pixels_for(0, 0, 4, 4), b"\0" * 64)
        self.assertEqual(b.get_damage(), [])

    def test_paint_rowstride_too_small_rejected(self):
        b = self.make_backing(32, 16)
        data = b"\x11" * 1024
        calls = self.paint(b, "RGBA", data, 0, 0, 8, 4, 8)
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0][0])

    def test_paint_unsupported_format(self):
        b = self.make_backing()
        calls = self.paint(b, "r210", b"\0" * 64, 0, 0, 4, 4, 16)
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0][0])
        self.assertIn("unsupported pixel format", calls[0][1])

    def test_paint_scaling_not_supported(self):
        b = self.make_backing()
        callbacks, calls = make_callbacks()
        b.do_paint_rgb(None, "rgb32", "RGBA", b"\0" * 64, 0, 0, 4, 4, 8, 8, 16, typedict(), callbacks)
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0][0])
        self.assertIn("scaling", calls[0][1])

    def test_paint_disabled_still_fires(self):
        b = self.make_backing()
        calls = self.paint(b, "RGBA", b"\xff" * 64, 0, 0, 4, 4, 16, {"paint": False})
        self.assertEqual(calls, [(True, "")])
        self.assertEqual(b.pixels_for(0, 0, 4, 4), b"\0" * 64)

    def test_paint_callbacks_fire_exactly_once(self):
        # every path through do_paint_rgb must fire each callback exactly once:
        cases = (
            ("RGBA", b"\xff" * 64, 0, 0, 4, 4, 16, {}),
            ("RGBA", b"\xff" * 64, 0, 0, 4, 4, 16, {"paint": False}),
            ("RGBA", b"\xff" * 8, 0, 0, 4, 4, 16, {}),
            ("r210", b"\xff" * 64, 0, 0, 4, 4, 16, {}),
            ("RGBA", b"\xff" * 64, 100, 100, 4, 4, 16, {}),
            ("RGB", b"\xff" * 48, 0, 0, 4, 4, 12, {}),
        )
        for rgb_format, data, x, y, w, h, rowstride, options in cases:
            b = self.make_backing()
            callbacks = []
            counts = [0, 0, 0]

            def make_cb(index):
                def cb(success, message="") -> None:
                    counts[index] += 1
                return cb

            for i in range(3):
                callbacks.append(make_cb(i))
            b.do_paint_rgb(None, "rgb32", rgb_format, data, x, y, w, h, w, h, rowstride,
                           typedict(options), callbacks)
            self.assertEqual(counts, [1, 1, 1], f"{rgb_format} {(x, y, w, h)} {options}")

    def test_paint_error_fires_once(self):
        class BadData:
            """ claims to be big enough, but does not support the buffer protocol """

            def __len__(self) -> int:
                return 1024

        b = self.make_backing()
        callbacks, calls = make_callbacks()
        b.do_paint_rgb(None, "rgb32", "RGBA", BadData(), 0, 0, 4, 4, 4, 4, 16, typedict(), callbacks)
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0][0])
        self.assertIn("paint error", calls[0][1])

    ######################################################################
    # damage

    def test_damage_merge_overlapping(self):
        b = self.make_backing(100, 100)
        b.add_damage(0, 0, 10, 10)
        b.add_damage(5, 5, 10, 10)
        b.add_damage(50, 50, 4, 4)
        self.assertEqual(b.get_damage(), [(0, 0, 15, 15), (50, 50, 4, 4)])

    def test_damage_merge_chain(self):
        b = self.make_backing(100, 100)
        b.add_damage(0, 0, 10, 10)
        b.add_damage(40, 40, 10, 10)
        # this one overlaps both, so all three collapse into one:
        b.add_damage(5, 5, 40, 40)
        self.assertEqual(b.get_damage(), [(0, 0, 50, 50)])

    def test_damage_touching_not_merged(self):
        b = self.make_backing(100, 100)
        b.add_damage(0, 0, 10, 10)
        b.add_damage(10, 0, 10, 10)
        self.assertEqual(b.get_damage(), [(0, 0, 10, 10), (10, 0, 10, 10)])

    def test_damage_empty_rectangles_dropped(self):
        b = self.make_backing()
        b.add_damage(0, 0, 0, 10)
        b.add_damage(0, 0, 10, 0)
        self.assertEqual(b.get_damage(), [])

    def test_realloc_clears_damage(self):
        b = self.make_backing(10, 10)
        b.add_damage(0, 0, 5, 5)
        b.init(20, 20, 20, 20)
        self.assertEqual(b.get_damage(), [])

    ######################################################################
    # pixels_for

    def test_pixels_for_full_width(self):
        b = self.make_backing(4, 4)
        b.pixels = bytearray(range(64))
        self.assertEqual(b.pixels_for(0, 1, 4, 2), bytes(range(16, 48)))

    def test_pixels_for_sub_rect(self):
        b = self.make_backing(4, 4)
        b.pixels = bytearray(range(64))
        self.assertEqual(b.pixels_for(1, 0, 2, 2), bytes(range(4, 12)) + bytes(range(20, 28)))

    def test_pixels_for_invalid_rect(self):
        b = self.make_backing(4, 4)
        for rect in ((-1, 0, 2, 2), (0, -1, 2, 2), (3, 0, 2, 2), (0, 3, 2, 2), (0, 0, 0, 2), (0, 0, 2, 0)):
            with self.assertRaises(ValueError):
                b.pixels_for(*rect)

    def test_clip(self):
        b = self.make_backing(10, 10)
        self.assertEqual(b.clip(0, 0, 10, 10), (0, 0, 10, 10))
        self.assertEqual(b.clip(-5, -5, 10, 10), (0, 0, 5, 5))
        self.assertEqual(b.clip(8, 8, 10, 10), (8, 8, 2, 2))
        self.assertEqual(b.clip(20, 20, 5, 5), (10, 10, 0, 0))

    ######################################################################
    # scroll

    def scroll(self, b, scrolls):
        callbacks, calls = make_callbacks()
        b.paint_scroll(None, typedict({"scroll": tuple(scrolls)}), callbacks)
        return calls

    def test_scroll_matches_reference(self):
        for scrolls in (
                ((0, 0, 8, 8, 0, 4),),
                ((0, 0, 16, 8, 0, 8), (0, 8, 16, 8, 0, -8)),          # two areas swapping places
                ((0, 0, 10, 10, 4, 4), (4, 4, 10, 10, -4, -4)),       # overlapping source/destination
                ((0, 0, 16, 16, 0, 0),),                              # no delta: dropped
        ):
            b = self.make_backing(16, 16)
            b.pixels = bytearray(make_pixels(16, 16, 4, 64))
            before = bytes(b.pixels)
            self.scroll(b, scrolls)
            valid = tuple(s for s in scrolls if s[4] or s[5])
            expected = reference_scroll(before, 16, valid)
            self.assertEqual(bytes(b.pixels), expected, f"{scrolls}")

    def test_scroll_swap_is_not_applied_in_place(self):
        b = self.make_backing(4, 4)
        # 2 rows of one value, 2 rows of another:
        b.pixels = bytearray(b"\x11" * 32 + b"\x22" * 32)
        self.scroll(b, ((0, 0, 4, 2, 0, 2), (0, 2, 4, 2, 0, -2)))
        self.assertEqual(bytes(b.pixels), b"\x22" * 32 + b"\x11" * 32)

    def test_scroll_records_damage(self):
        b = self.make_backing(16, 16)
        self.scroll(b, ((0, 0, 8, 8, 0, 8),))
        self.assertEqual(b.get_damage(), [(0, 8, 8, 8)])

    def test_scroll_fires_callbacks_once(self):
        for scrolls, expected in (
                ((), True),
                (((0, 0, 8, 8, 0, 4),), True),
                (((0, 0, 8, 8, 0, 0),), False),                # no delta at all
                (((0, 0, 8, 8, 0, 100),), False),              # does not fit
                (((0, 0, 8, 8, 0, 4), (0, 0, 8, 8, 0, 100)), False),
        ):
            b = self.make_backing(16, 16)
            calls = self.scroll(b, scrolls)
            self.assertEqual(len(calls), 1, f"{scrolls}")
            self.assertEqual(bool(calls[0][0]), expected, f"{scrolls}")

    def test_scroll_from_img_data(self):
        # older servers overload the packet's image data instead of using the option:
        b = self.make_backing(16, 16)
        b.pixels = bytearray(make_pixels(16, 16, 4, 64))
        before = bytes(b.pixels)
        callbacks, calls = make_callbacks()
        b.paint_scroll(((0, 0, 16, 8, 0, 8),), typedict(), callbacks)
        self.assertEqual(calls, [(True, "")])
        self.assertEqual(bytes(b.pixels), reference_scroll(before, 16, ((0, 0, 16, 8, 0, 8),)))

    def test_scroll_on_closed_backing(self):
        b = self.make_backing(16, 16)
        b.close()
        callbacks, calls = make_callbacks()
        b.do_scroll_paints(None, ((0, 0, 8, 8, 0, 4),), callbacks)
        self.assertEqual(calls, [(-1, "this backing is closed")])

    ######################################################################
    # misc

    def test_rgb_modes_and_encoding_properties(self):
        b = self.make_backing()
        self.assertEqual(tuple(b.RGB_MODES), RGB_MODES)
        self.assertEqual(tuple(b.get_rgb_formats()), RGB_MODES)
        props = b.get_encoding_properties()
        self.assertEqual(tuple(props["encodings.rgb_formats"]), RGB_MODES)
        self.assertTrue(props["encoding.transparency"])

    def test_no_alpha_removes_alpha_modes(self):
        b = self.make_backing(alpha=False)
        self.assertEqual(tuple(b.get_rgb_formats()), ("BGRX", "RGBX", "RGB", "BGR"))

    def test_backing_sentinel_is_truthy(self):
        # `WindowBackingBase.draw_region` asserts on this attribute:
        b = self.make_backing()
        self.assertTrue(b._backing)

    def test_draw_region_dispatches_to_rgb(self):
        b = self.make_backing(16, 16)
        callbacks, calls = make_callbacks()
        data = bytes((1, 2, 3, 4)) * 16
        b.draw_region(0, 0, 4, 4, "rgb32", data, 16, typedict({"rgb_format": "RGBA"}), callbacks)
        self.assertEqual(calls, [(True, "")])
        self.assertEqual(b.pixels_for(0, 0, 4, 4), data)

    def test_get_info(self):
        b = self.make_backing(8, 4)
        info = b.get_info()
        self.assertEqual(info["type"], "terminal")
        self.assertEqual(info["size"], (8, 4))
        self.assertEqual(info["buffer-serial"], 1)

    def test_update_fps_buffer_is_a_noop(self):
        b = self.make_backing()
        b.update_fps_buffer(10, 10, b"\0" * 400)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
