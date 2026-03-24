#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# ABOUTME: Tests for the runtime HCURSOR offset probe used by the Win32 GL cursor fix.
# ABOUTME: Verifies the probe discovers a valid offset and extracts working HCURSOR handles.

import struct
import unittest
from ctypes import addressof, c_void_p, sizeof, create_string_buffer

from xpra.os_util import WIN32


def _make_fake_struct(fields):
    """Create a fake C struct in memory with pointer-sized fields.
    Returns (buffer, base_address)."""
    ptr_size = sizeof(c_void_p)
    buf = create_string_buffer(len(fields) * ptr_size)
    fmt = "P" * len(fields)
    struct.pack_into(fmt, buf, 0, *fields)
    return buf


class TestScanLogic(unittest.TestCase):
    """Test the offset-scanning algorithm independent of Win32 APIs."""

    def _scan_for_differing_valid_handles(self, ptr_a, ptr_b, scan_limit, is_valid_handle):
        """Reimplementation of the core scan logic from _probe_hcursor_offset
        for testing without Win32 dependencies."""
        ptr_size = sizeof(c_void_p)
        for offset in range(0, scan_limit, ptr_size):
            val_a = c_void_p.from_address(ptr_a + offset).value or 0
            val_b = c_void_p.from_address(ptr_b + offset).value or 0
            if not val_a or not val_b or val_a == val_b:
                continue
            if is_valid_handle(val_a) and is_valid_handle(val_b):
                return offset
        return -1

    def test_finds_differing_field(self):
        """Two structs with same layout, different values at one field."""
        ptr_size = sizeof(c_void_p)
        # Struct: [same, same, DIFFERENT, same]
        buf_a = _make_fake_struct([100, 200, 0xABCD, 400])
        buf_b = _make_fake_struct([100, 200, 0xDCBA, 400])
        valid = {0xABCD, 0xDCBA}
        offset = self._scan_for_differing_valid_handles(
            addressof(buf_a), addressof(buf_b),
            len(buf_a), lambda v: v in valid,
        )
        self.assertEqual(offset, 2 * ptr_size)

    def test_skips_same_values(self):
        """Fields with identical values are skipped."""
        buf_a = _make_fake_struct([100, 200, 300])
        buf_b = _make_fake_struct([100, 200, 300])
        offset = self._scan_for_differing_valid_handles(
            addressof(buf_a), addressof(buf_b),
            len(buf_a), lambda v: True,
        )
        self.assertEqual(offset, -1)

    def test_skips_zero_values(self):
        """Fields with zero values are skipped even if they differ."""
        buf_a = _make_fake_struct([0, 200])
        buf_b = _make_fake_struct([100, 200])
        offset = self._scan_for_differing_valid_handles(
            addressof(buf_a), addressof(buf_b),
            len(buf_a), lambda v: True,
        )
        # First field: val_a=0, skipped. Second field: same. No match.
        self.assertEqual(offset, -1)

    def test_skips_invalid_handles(self):
        """Fields that differ but fail validation are skipped."""
        buf_a = _make_fake_struct([0xAAAA, 0xBBBB])
        buf_b = _make_fake_struct([0xCCCC, 0xDDDD])
        valid = {0xBBBB, 0xDDDD}
        ptr_size = sizeof(c_void_p)
        offset = self._scan_for_differing_valid_handles(
            addressof(buf_a), addressof(buf_b),
            len(buf_a), lambda v: v in valid,
        )
        self.assertEqual(offset, 1 * ptr_size)

    def test_first_valid_match_wins(self):
        """When multiple fields differ and validate, the first offset wins."""
        buf_a = _make_fake_struct([0x1111, 0x3333])
        buf_b = _make_fake_struct([0x2222, 0x4444])
        ptr_size = sizeof(c_void_p)
        offset = self._scan_for_differing_valid_handles(
            addressof(buf_a), addressof(buf_b),
            len(buf_a), lambda v: True,
        )
        self.assertEqual(offset, 0)


@unittest.skipUnless(WIN32, "Win32-only: requires GDK Win32 backend")
class TestHCursorProbeWin32(unittest.TestCase):
    """End-to-end tests that run on Win32 with a real GDK display."""

    def test_probe_finds_offset(self):
        """The probe should discover a non-negative offset."""
        from xpra.platform.win32.gui import _probe_hcursor_offset
        offset = _probe_hcursor_offset()
        self.assertGreaterEqual(offset, 0, "probe failed to find HCURSOR offset")
        # Offset should be reasonable (within typical GObject struct sizes)
        self.assertLess(offset, 256)

    def test_extract_hcursor_from_arrow(self):
        """Extracting HCURSOR from an arrow cursor should return non-zero."""
        from xpra.platform.win32.gui import _get_hcursor_from_gdk_cursor
        from xpra.os_util import gi_import
        Gdk = gi_import("Gdk")
        display = Gdk.Display.get_default()
        if not display:
            self.skipTest("no display")
        cursor = Gdk.Cursor.new_for_display(display, Gdk.CursorType.ARROW)
        hcursor = _get_hcursor_from_gdk_cursor(cursor)
        self.assertNotEqual(hcursor, 0, "failed to extract HCURSOR from arrow cursor")

    def test_extract_hcursor_different_types(self):
        """Different cursor types should yield different HCURSOR values."""
        from xpra.platform.win32.gui import _get_hcursor_from_gdk_cursor
        from xpra.os_util import gi_import
        Gdk = gi_import("Gdk")
        display = Gdk.Display.get_default()
        if not display:
            self.skipTest("no display")
        arrow = Gdk.Cursor.new_for_display(display, Gdk.CursorType.ARROW)
        cross = Gdk.Cursor.new_for_display(display, Gdk.CursorType.CROSSHAIR)
        h_arrow = _get_hcursor_from_gdk_cursor(arrow)
        h_cross = _get_hcursor_from_gdk_cursor(cross)
        self.assertNotEqual(h_arrow, 0)
        self.assertNotEqual(h_cross, 0)
        self.assertNotEqual(h_arrow, h_cross,
                            "arrow and crosshair should have different HCURSOR handles")


if __name__ == "__main__":
    unittest.main()
