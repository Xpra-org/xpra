#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Tests for xpra/server/window/metadata.py
"""

import os
import unittest

from xpra.server.window.metadata import (
    make_window_metadata, _make_window_metadata,
    DEFAULT_VALUES,
)
from xpra.constants import WORKSPACE_UNSET


class _Window:
    """Minimal mock window that stores properties."""

    def __init__(self, **props):
        self._props = props

    def get_property(self, name):
        return self._props.get(name)


class TestDefaultValues(unittest.TestCase):
    """Verify that DEFAULT_VALUES covers the properties we know about."""

    def test_known_keys_present(self):
        for key in ("title", "pid", "iconic", "fullscreen", "has-alpha", "class-instance"):
            self.assertIn(key, DEFAULT_VALUES)

    def test_workspace_default_is_unset(self):
        self.assertEqual(DEFAULT_VALUES["workspace"], WORKSPACE_UNSET)

    def test_boolean_defaults_are_false(self):
        for key in ("iconic", "fullscreen", "maximized", "above", "below",
                    "focused", "has-alpha", "override-redirect", "tray"):
            self.assertIs(DEFAULT_VALUES[key], False, f"{key} default should be False")

    def test_numeric_defaults(self):
        self.assertEqual(DEFAULT_VALUES["pid"], 0)
        self.assertEqual(DEFAULT_VALUES["depth"], 24)
        self.assertEqual(DEFAULT_VALUES["opacity"], -1)


class TestMakeWindowMetadata(unittest.TestCase):

    # ------------------------------------------------------------------
    # Properties from DEFAULT_VALUES
    # ------------------------------------------------------------------

    def test_title(self):
        w = _Window(title="My Window")
        result = make_window_metadata(w, "title")
        self.assertEqual(result, {"title": "My Window"})

    def test_pid(self):
        w = _Window(pid=1234)
        result = make_window_metadata(w, "pid")
        self.assertEqual(result, {"pid": 1234})

    def test_boolean_prop_true(self):
        w = _Window(iconic=True)
        result = make_window_metadata(w, "iconic")
        self.assertEqual(result, {"iconic": True})

    def test_boolean_prop_false(self):
        w = _Window(iconic=False)
        result = make_window_metadata(w, "iconic")
        self.assertEqual(result, {"iconic": False})

    def test_tuple_prop(self):
        w = _Window(**{"class-instance": ("xterm", "XTerm")})
        result = make_window_metadata(w, "class-instance")
        self.assertEqual(result, {"class-instance": ("xterm", "XTerm")})

    def test_dict_prop_shape(self):
        shape = {"x": 0, "y": 0}
        w = _Window(shape=shape)
        result = make_window_metadata(w, "shape")
        self.assertEqual(result, {"shape": shape})

    def test_size_constraints(self):
        sc = {"min-size": (100, 50)}
        w = _Window(**{"size-constraints": sc})
        result = make_window_metadata(w, "size-constraints")
        self.assertEqual(result, {"size-constraints": sc})

    # ------------------------------------------------------------------
    # skip_defaults=True behaviour
    # ------------------------------------------------------------------

    def test_skip_defaults_omits_default_value(self):
        w = _Window(title="")          # "" is the default for title
        result = make_window_metadata(w, "title", skip_defaults=True)
        self.assertEqual(result, {})

    def test_skip_defaults_keeps_non_default(self):
        w = _Window(title="Something")
        result = make_window_metadata(w, "title", skip_defaults=True)
        self.assertEqual(result, {"title": "Something"})

    def test_skip_defaults_none_treated_as_default(self):
        # None is treated as the default value
        w = _Window(title=None)
        result = make_window_metadata(w, "title", skip_defaults=True)
        self.assertEqual(result, {})

    def test_skip_defaults_false_keeps_zero(self):
        # skip_defaults=False always returns the value
        w = _Window(pid=0)
        result = make_window_metadata(w, "pid", skip_defaults=False)
        self.assertEqual(result, {"pid": 0})

    # ------------------------------------------------------------------
    # group-leader / transient-for / parent
    # ------------------------------------------------------------------

    def test_group_leader_set(self):
        from xpra.net.common import BACKWARDS_COMPATIBLE
        w = _Window(**{"group-leader": 42})
        result = make_window_metadata(w, "group-leader")
        self.assertIn("group-leader", result)
        self.assertEqual(result["group-leader"], 42)
        if BACKWARDS_COMPATIBLE:
            self.assertIn("group-leader-xid", result)
            self.assertIn("group-leader-wid", result)

    def test_group_leader_absent(self):
        w = _Window(**{"group-leader": None})
        result = make_window_metadata(w, "group-leader")
        self.assertEqual(result, {})

    def test_transient_for_set(self):
        w = _Window(**{"transient-for": 99})
        result = make_window_metadata(w, "transient-for")
        self.assertIn("transient-for", result)
        self.assertEqual(result["transient-for"], 99)

    def test_transient_for_absent(self):
        w = _Window(**{"transient-for": 0})
        result = make_window_metadata(w, "transient-for")
        self.assertEqual(result, {})

    def test_parent_set(self):
        w = _Window(parent=7)
        result = make_window_metadata(w, "parent")
        self.assertIn("parent", result)

    def test_parent_absent(self):
        w = _Window(parent=None)
        result = make_window_metadata(w, "parent")
        self.assertEqual(result, {})

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    def test_unknown_property_raises_in_inner(self):
        w = _Window()
        with self.assertRaises(ValueError):
            _make_window_metadata(w, "no-such-property")

    def test_unknown_property_returns_empty_in_outer(self):
        w = _Window()
        result = make_window_metadata(w, "no-such-property")
        self.assertEqual(result, {})

    def test_get_property_raises_returns_empty(self):
        class _BadWindow:
            def get_property(self, name):
                raise TypeError("boom")
        result = make_window_metadata(_BadWindow(), "title")
        self.assertEqual(result, {})

    # ------------------------------------------------------------------
    # SKIP_METADATA env-var support
    # ------------------------------------------------------------------

    def test_skip_metadata_env(self):
        original = os.environ.get("XPRA_SKIP_METADATA", "")
        try:
            # reload with skip-list containing "title"
            import xpra.server.window.metadata as mod
            os.environ["XPRA_SKIP_METADATA"] = "title"
            # patch the module-level SKIP_METADATA list directly
            mod.SKIP_METADATA = ["title"]
            w = _Window(title="Hello")
            result = mod.make_window_metadata(w, "title")
            self.assertEqual(result, {})
        finally:
            os.environ["XPRA_SKIP_METADATA"] = original
            mod.SKIP_METADATA = original.split(",")


def main():
    unittest.main()


if __name__ == "__main__":
    main()
