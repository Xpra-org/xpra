#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.parsing import split_dict_str, parse_simple_dict


class TestSplitDictStr(unittest.TestCase):

    def test_simple(self):
        self.assertEqual(split_dict_str("a=1,b=2"), ["a=1", "b=2"])

    def test_no_sep(self):
        self.assertEqual(split_dict_str("a=1"), ["a=1"])

    def test_empty(self):
        self.assertEqual(split_dict_str(""), [])

    def test_parens_not_split(self):
        self.assertEqual(
            split_dict_str("a=1,b=exec(x=2,y=3),c=4"),
            ["a=1", "b=exec(x=2,y=3)", "c=4"],
        )

    def test_nested_parens(self):
        self.assertEqual(
            split_dict_str("a=f(b=g(c=1,d=2),e=3),x=4"),
            ["a=f(b=g(c=1,d=2),e=3)", "x=4"],
        )

    def test_paren_only_at_boundary(self):
        # comma before opening paren should split
        self.assertEqual(split_dict_str("a=1,b=2(x=3)"), ["a=1", "b=2(x=3)"])


class TestParseSimpleDict(unittest.TestCase):

    def test_basic(self):
        self.assertEqual(parse_simple_dict("a=1,b=2"), {"a": "1", "b": "2"})

    def test_repeated_key_becomes_list(self):
        result = parse_simple_dict("auth=allow,auth=env")
        self.assertEqual(result, {"auth": ["allow", "env"]})

    def test_bracket_value_not_split(self):
        result = parse_simple_dict("auth=exec(command=/bin/echo,foo=bar),opt=x")
        self.assertEqual(result["auth"], "exec(command=/bin/echo,foo=bar)")
        self.assertEqual(result["opt"], "x")

    def test_empty(self):
        self.assertEqual(parse_simple_dict(""), {})

    def test_no_value(self):
        # entries without '=' are skipped
        result = parse_simple_dict("noequals,a=1")
        self.assertEqual(result, {"a": "1"})

    def test_three_auth_values(self):
        result = parse_simple_dict("auth=allow,auth=env,auth=file")
        self.assertEqual(result["auth"], ["allow", "env", "file"])


def main():
    unittest.main()


if __name__ == "__main__":
    main()
