#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>

import unittest
from unittest.mock import Mock, patch

from xpra.util import objects
from xpra.util.objects import AtomicInteger, MutableInteger, typedict


class TypedictTest(unittest.TestCase):

    def test_nested_lookup_and_literal_key_precedence(self):
        values = typedict({"display": {"size": {"width": "1920"}}, "display.size.width": "800", "7": "3"})
        self.assertEqual(values.intget("display.size.width"), 800)
        del values["display.size.width"]
        self.assertEqual(values.intget("display.size.width"), 1920)
        self.assertEqual(values.get("display.size.width"), "1920")
        self.assertEqual(values.intget("7"), 3)
        self.assertEqual(values.intget("display.size.height", 12), 12)
        self.assertEqual(values.intget("display.size.width.extra", 12), 12)
        self.assertEqual(values.setdefault("new", 4), 4)
        self.assertEqual(values.setdefault("new", 5), 4)

    def test_wrapped_scalar_and_dictionary_values(self):
        values = typedict({"version": {"": b"8.0"}, "count": {"": "4"}, "nested": typedict({"a": 1}), "float": "1.25"})
        self.assertEqual(values.strget("version"), "8.0")
        self.assertEqual(values.intget("count"), 4)
        self.assertEqual(values.floatget("float"), 1.25)
        self.assertEqual(values.dictget("nested"), {"a": 1})
        self.assertIs(type(values.dictget("nested")), dict)

    def test_list_bounds_and_invalid_values(self):
        default = (9,)
        for value in (None, "1,2", 3, [1], [1, 2, 3], ["bad", 2]):
            with self.subTest(value=value), patch.object(typedict, "_warn"):
                values = typedict({"items": value})
                self.assertEqual(values.inttupleget("items", default, min_items=2, max_items=2), default)
        with patch.object(typedict, "_warn"):
            self.assertEqual(typedict({"items": [None]}).tupleget("items", default, item_type=(int, float)), default)

    def test_list_conversion_keeps_all_items_and_does_not_modify_input(self):
        original = ["1", b"2", 3]
        values = typedict({"items": original, "wrapped": {"": [b"one", "two"]}})
        self.assertEqual(values.inttupleget("items"), (1, 2, 3))
        self.assertEqual(original, ["1", b"2", 3])
        self.assertEqual(values.strtupleget("wrapped"), ("one", "two"))
        self.assertEqual(typedict({"pair": ["4", "5"]}).intpair("pair"), (4, 5))
        self.assertEqual(typedict({"pair": [1, 2, 3]}).intpair("pair", (8, 9)), (8, 9))


class ObjectHelpersTest(unittest.TestCase):

    def test_integer_values_and_comparisons(self):
        atomic = AtomicInteger()
        atomic.set(7)
        self.assertEqual(atomic.get(), 7)
        self.assertEqual(atomic, "7")
        self.assertNotEqual(atomic, "bad")
        value = MutableInteger(7)
        self.assertEqual(value, 7)
        self.assertNotEqual(value, 8)
        self.assertLess(value, 8)
        self.assertLessEqual(value, 7)
        self.assertGreater(value, 6)
        self.assertGreaterEqual(value, 7)

    def test_notypedict_converts_nested_values_in_place(self):
        value = {"plain": {"nested": typedict({"leaf": typedict({"x": 1})})}}
        with patch.object(objects, "get_util_logger"):
            result = objects.notypedict(value)
        self.assertIs(result, value)
        self.assertIs(type(result["plain"]["nested"]), dict)
        self.assertIs(type(result["plain"]["nested"]["leaf"]), dict)
        self.assertEqual(result, {"plain": {"nested": {"leaf": {"x": 1}}}})

    def test_factory_falls_back_after_failures_and_empty_results(self):
        broken = Mock(side_effect=ValueError("unavailable"))
        empty = Mock(return_value=None)
        success = Mock(return_value=object())
        unused = Mock()
        with patch.object(objects, "get_util_logger"):
            result = objects.make_instance([None, broken, empty, success, unused], "arg")
            self.assertIs(result, success.return_value)
            self.assertIsNone(objects.make_instance([None, empty], "arg"))
        broken.assert_called_once_with("arg")
        unused.assert_not_called()

    def test_dictionary_merge_reports_conflicting_path(self):
        with patch.dict("os.environ", {"XPRA_DICTMERGE_WARNINGS": "0"}):
            merged = objects.merge_dicts({"a": {"x": 1}}, {"a": {"x": 1, "y": 2}, "b": 3})
            self.assertEqual(merged, {"a": {"x": 1, "y": 2}, "b": 3})
            with self.assertRaisesRegex(ValueError, "'a'.'x'"):
                objects.merge_dicts(merged, {"a": {"x": 9}})


if __name__ == "__main__":
    unittest.main()
