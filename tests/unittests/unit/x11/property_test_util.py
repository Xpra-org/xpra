# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""An in-memory Xlib boundary; property encoding and decoding remain real."""

import unittest
from unittest.mock import patch

from xpra.x11 import prop, xroot_props
from xpra.x11.bindings.window import PropertyError

ROOT_XID = 0x1234


class PropertyWindow:
    def __init__(self):
        self.properties = {}
        self.atoms = {}
        self.event_mask = 4

    def XChangeProperty(self, xid, key, dtype, dformat, data):
        self.properties[xid, key] = dtype, dformat, data

    def XGetWindowProperty(self, xid, key, dtype, buffer_size=65536):
        value = self.properties.get((xid, key))
        if value is None:
            return None
        actual_type, _dformat, data = value
        if dtype != actual_type:
            raise PropertyError(f"expected {dtype}, found {actual_type}")
        return data[:buffer_size]

    def GetWindowPropertyType(self, xid, key):
        value = self.properties.get((xid, key))
        return value[:2] if value else None

    def XDeleteProperty(self, xid, key):
        self.properties.pop((xid, key), None)

    def get_xatom(self, name):
        if isinstance(name, int):
            return name
        if name not in self.atoms:
            self.atoms[name] = len(self.atoms) + 1
        return self.atoms[name]

    def get_atom_name(self, atom):
        return next((name for name, value in self.atoms.items() if value == atom), "")

    def get_root_size(self):
        return 3840, 2160

    def getEventMask(self, xid):
        assert xid == ROOT_XID
        return self.event_mask

    def setEventMask(self, xid, mask):
        assert xid == ROOT_XID
        self.event_mask = mask


class PropertyTestCase(unittest.TestCase):
    def setUp(self):
        self.window = PropertyWindow()
        for p in (
            patch.object(prop, "X11WindowBindings", return_value=self.window),
            patch.object(xroot_props, "X11WindowBindings", return_value=self.window),
            patch.object(xroot_props, "get_root_xid", return_value=ROOT_XID),
            patch("xpra.x11.error.Xenter"),
            patch("xpra.x11.error.Xexit", return_value=0),
        ):
            self.enterContext(p)
