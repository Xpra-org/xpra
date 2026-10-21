#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct
import unittest
from unittest.mock import patch

from xpra.x11 import prop
from xpra.x11.bindings.window import PropertyError
from xpra.x11.error import XError
from unit.x11.property_test_util import PropertyTestCase, ROOT_XID


class TestProperties(PropertyTestCase):

    def test_scalar_roundtrips(self):
        for etype, value, xtype, fmt in (
            ("utf8", "café λ", "UTF8_STRING", 8),
            ("latin1", "café", "STRING", 8),
            ("u8", 255, "CARDINAL", 8),
            ("u16", 65535, "CARDINAL", 16),
            ("u32", 0xffffffff, "CARDINAL", 32),
            ("integer", 42, "INTEGER", 32),
            ("window", ROOT_XID, "WINDOW", 32),
            ("atom", "_NET_WM_NAME", "ATOM", 32),
        ):
            with self.subTest(etype=etype):
                prop.prop_set(ROOT_XID, "value", etype, value)
                self.assertEqual(prop.prop_type_get(ROOT_XID, "value"), (xtype, fmt))
                self.assertEqual(prop.prop_get(ROOT_XID, "value", etype), value)
        prop.prop_del(ROOT_XID, "value")
        self.assertIsNone(prop.prop_type_get(ROOT_XID, "value"))
        self.assertIsNone(prop.prop_get(ROOT_XID, "value", "utf8"))
        prop.prop_del(ROOT_XID, "value")

    def test_array_roundtrips(self):
        for etype, values in (
            ("utf8", ["Main", "λ"]), ("latin1", ["café", "other"]),
            ("u8", [0, 255]), ("u16", [0, 65535]), ("u32", [1, 2, 0xffffffff]),
            ("atom", ["_NET_WM_NAME", "_NET_SUPPORTED"]),
        ):
            with self.subTest(etype=etype):
                prop.array_set(ROOT_XID, "array", etype, values)
                self.assertEqual(prop.array_get(ROOT_XID, "array", etype), values)
        # Retain compatibility with the deprecated array form.
        with patch.object(prop, "log") as log:
            self.assertEqual(prop.prop_get(ROOT_XID, "array", ["atom"]), values)
            log.warn.assert_called_once()
        prop.array_set(ROOT_XID, "empty", "u32", [])
        self.assertEqual(prop.array_get(ROOT_XID, "empty", "u32"), [])
        self.assertIsNone(prop.array_get(ROOT_XID, "missing", "u32"))

    def test_invalid_window_ids(self):
        for xid in (None, "123", object()):
            with self.subTest(xid=xid):
                with self.assertRaises(TypeError):
                    prop.raw_prop_set(xid, "key", "STRING", 8, b"data")
                with self.assertRaises(TypeError):
                    prop.raw_prop_get(xid, "key", "STRING")
                with self.assertRaises(TypeError):
                    prop.prop_del(xid, "key")
        self.assertFalse(self.window.properties)

    def test_raw_read_size_and_missing_property(self):
        prop.raw_prop_set(ROOT_XID, "key", "STRING", 8, b"abcdef")
        self.assertEqual(prop.raw_prop_get(ROOT_XID, "key", "STRING", 3), b"abc")
        with patch.object(prop, "log") as log:
            self.assertIsNone(prop.raw_prop_get(ROOT_XID, "missing", "STRING", ignore_errors=True))
            log.assert_not_called()

    def test_property_errors(self):
        for ignore in (False, True):
            with self.subTest(ignore=ignore), patch.object(prop, "log") as log, \
                    patch.object(self.window, "XGetWindowProperty", side_effect=PropertyError("wrong type")):
                self.assertIsNone(prop.raw_prop_get(ROOT_XID, "key", "STRING", ignore_errors=ignore, raise_xerrors=True))
                self.assertEqual(log.info.call_count, 0 if ignore else 3)
        # Wrongly typed server properties take the same path through the native boundary.
        prop.prop_set(ROOT_XID, "key", "u32", 42)
        self.assertIsNone(prop.prop_get(ROOT_XID, "key", "utf8", ignore_errors=True))

    def test_xerrors(self):
        with patch.object(self.window, "XGetWindowProperty", side_effect=XError("window destroyed")), \
                patch.object(prop, "log"):
            self.assertIsNone(prop.raw_prop_get(ROOT_XID, "key", "STRING"))
            with self.assertRaises(XError):
                prop.raw_prop_get(ROOT_XID, "key", "STRING", raise_xerrors=True)
        with patch.object(self.window, "GetWindowPropertyType", side_effect=XError("window destroyed")):
            self.assertIsNone(prop.prop_type_get(ROOT_XID, "key"))

    def test_decode_errors(self):
        prop.raw_prop_set(ROOT_XID, "broken", "CARDINAL", 32, b"\x01")
        with patch.object(prop, "log") as log:
            self.assertIsNone(prop.prop_get(ROOT_XID, "broken", "u32", ignore_errors=True))
            log.warn.assert_not_called()
            with self.assertRaises(struct.error):
                prop.prop_get(ROOT_XID, "broken", "u32")
            self.assertTrue(log.warn.called)
            with self.assertRaises(struct.error):
                prop.do_prop_decode("broken", ["u32"], b"\x01")
            # Logging a malformed value must not hide the original decode error.
            with self.assertRaises(TypeError):
                prop.do_prop_decode("broken", "u32", None)

    def test_atom_validation(self):
        with patch.object(prop, "log") as log:
            self.assertIsNone(prop._get_atom(struct.pack("@L", 0)))
            log.warn.assert_called_once()
            self.assertIsNone(prop._get_atom(struct.pack("@L", 987)))
            log.error.assert_called_once()
        self.assertEqual(prop._get_xatom(42), 42)

    def test_python_types(self):
        expected = {"UTF8_STRING": "utf8", "STRING": "latin1", "ATOM": "atom", "CARDINAL": "u32",
                    "INTEGER": "integer", "VISUALID": "visual", "WINDOW": "window"}
        for xtype, etype in expected.items():
            self.assertEqual(prop.get_python_type(xtype), etype)
        self.assertEqual(prop.get_python_type("custom"), "custom")


if __name__ == '__main__':
    unittest.main()
