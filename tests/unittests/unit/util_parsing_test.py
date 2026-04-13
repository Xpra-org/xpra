#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.parsing import (
    str_to_bool,
    parse_bool_or,
    parse_bool_or_int,
    parse_bool_or_number,
    parse_number,
    print_bool,
    print_number,
    from0to100,
    intrangevalidator,
    parse_encoded_bin_data,
    parse_scaling_value,
    split_dict_str,
    parse_simple_dict,
    parse_str_dict,
    parse_with_unit,
    parse_resolution,
    parse_resolutions,
    get_refresh_rate_for_value,
    adjust_monitor_refresh_rate,
    get_default_video_max_size,
    validated_monitor_data,
    TRUE_OPTIONS,
    FALSE_OPTIONS,
)


class TestStrToBool(unittest.TestCase):

    def test_true_options(self):
        for v in TRUE_OPTIONS:
            self.assertTrue(str_to_bool(v), f"expected True for {v!r}")

    def test_false_options(self):
        for v in FALSE_OPTIONS:
            self.assertFalse(str_to_bool(v), f"expected False for {v!r}")

    def test_string_case_insensitive(self):
        self.assertTrue(str_to_bool("YES"))
        self.assertTrue(str_to_bool("True"))
        self.assertTrue(str_to_bool("ON"))
        self.assertFalse(str_to_bool("NO"))
        self.assertFalse(str_to_bool("FALSE"))
        self.assertFalse(str_to_bool("OFF"))

    def test_whitespace_stripped(self):
        self.assertTrue(str_to_bool("  yes  "))
        self.assertFalse(str_to_bool("  no  "))

    def test_unknown_returns_default(self):
        self.assertTrue(str_to_bool("maybe", default=True))
        self.assertFalse(str_to_bool("maybe", default=False))
        self.assertTrue(str_to_bool("", default=True))


class TestParseBoolOr(unittest.TestCase):

    def test_true_options(self):
        for v in TRUE_OPTIONS:
            self.assertTrue(parse_bool_or("k", v))

    def test_false_options(self):
        for v in FALSE_OPTIONS:
            self.assertFalse(parse_bool_or("k", v))

    def test_auto_returns_auto_value(self):
        self.assertIsNone(parse_bool_or("k", "auto"))
        self.assertIsNone(parse_bool_or("k", None))
        self.assertTrue(parse_bool_or("k", "auto", auto=True))
        self.assertFalse(parse_bool_or("k", "auto", auto=False))

    def test_numeric_strings(self):
        self.assertTrue(parse_bool_or("k", "2"))
        self.assertFalse(parse_bool_or("k", "0"))

    def test_invalid_returns_auto(self):
        self.assertIsNone(parse_bool_or("k", "garbage"))
        self.assertTrue(parse_bool_or("k", "garbage", auto=True))


class TestPrintBool(unittest.TestCase):

    def test_true(self):
        self.assertEqual(print_bool("k", True), "yes")
        self.assertEqual(print_bool("k", True, true_str="enabled"), "enabled")

    def test_false(self):
        self.assertEqual(print_bool("k", False), "no")
        self.assertEqual(print_bool("k", False, false_str="disabled"), "disabled")

    def test_none_is_auto(self):
        self.assertEqual(print_bool("k", None), "auto")

    def test_non_bool_returns_empty(self):
        self.assertEqual(print_bool("k", "yes"), "")
        self.assertEqual(print_bool("k", 1), "")


class TestParseBoolOrInt(unittest.TestCase):

    def test_true_options_return_one(self):
        for v in TRUE_OPTIONS:
            self.assertEqual(parse_bool_or_int("k", v), 1)

    def test_false_options_return_zero(self):
        for v in FALSE_OPTIONS:
            self.assertEqual(parse_bool_or_int("k", v), 0)

    def test_numeric_strings(self):
        self.assertEqual(parse_bool_or_int("k", "5"), 5)
        self.assertEqual(parse_bool_or_int("k", "0"), 0)

    def test_auto_returns_default(self):
        self.assertEqual(parse_bool_or_number(int, "k", "auto"), 0)
        self.assertEqual(parse_bool_or_number(int, "k", "auto", auto=7), 7)

    def test_invalid_returns_auto(self):
        self.assertEqual(parse_bool_or_int("k", "notanumber"), 0)


class TestParseNumber(unittest.TestCase):

    def test_int(self):
        self.assertEqual(parse_number(int, "k", "42"), 42)
        self.assertEqual(parse_number(int, "k", 42), 42)

    def test_float(self):
        self.assertAlmostEqual(parse_number(float, "k", "3.14"), 3.14)

    def test_auto_returns_default(self):
        self.assertEqual(parse_number(int, "k", "auto"), 0)
        self.assertEqual(parse_number(int, "k", "auto", auto=99), 99)

    def test_invalid_returns_auto(self):
        self.assertEqual(parse_number(int, "k", "notanumber"), 0)
        self.assertEqual(parse_number(int, "k", "notanumber", auto=5), 5)


class TestPrintNumber(unittest.TestCase):

    def test_auto_value_prints_auto(self):
        self.assertEqual(print_number(0), "auto")
        self.assertEqual(print_number(5, auto_value=5), "auto")

    def test_non_auto_prints_value(self):
        self.assertEqual(print_number(10), "10")
        self.assertEqual(print_number(1, auto_value=0), "1")


class TestIntRangeValidator(unittest.TestCase):

    def test_valid_in_range(self):
        self.assertEqual(intrangevalidator(50, 0, 100), 50)
        self.assertEqual(intrangevalidator(0, 0, 100), 0)
        self.assertEqual(intrangevalidator(100, 0, 100), 100)

    def test_below_min_raises(self):
        with self.assertRaises(ValueError):
            intrangevalidator(-1, 0, 100)

    def test_above_max_raises(self):
        with self.assertRaises(ValueError):
            intrangevalidator(101, 0, 100)

    def test_no_bounds(self):
        self.assertEqual(intrangevalidator(9999), 9999)
        self.assertEqual(intrangevalidator(-9999), -9999)

    def test_from0to100(self):
        self.assertEqual(from0to100(0), 0)
        self.assertEqual(from0to100(100), 100)
        with self.assertRaises(ValueError):
            from0to100(-1)
        with self.assertRaises(ValueError):
            from0to100(101)


class TestParseEncodedBinData(unittest.TestCase):

    def test_empty(self):
        self.assertEqual(parse_encoded_bin_data(""), b"")

    def test_hex_prefix(self):
        self.assertEqual(parse_encoded_bin_data("0x48656c6c6f"), b"Hello")

    def test_b64_prefix(self):
        import base64
        encoded = "b64:" + base64.b64encode(b"Hello").decode()
        self.assertEqual(parse_encoded_bin_data(encoded), b"Hello")

    def test_base64_prefix(self):
        import base64
        encoded = "base64:" + base64.b64encode(b"World").decode()
        self.assertEqual(parse_encoded_bin_data(encoded), b"World")

    def test_bare_hex(self):
        self.assertEqual(parse_encoded_bin_data("48656c6c6f"), b"Hello")

    def test_bare_base64(self):
        import base64
        encoded = base64.b64encode(b"Hello").decode()
        self.assertEqual(parse_encoded_bin_data(encoded), b"Hello")

    def test_all_invalid_chars_returns_empty(self):
        # only non-base64, non-hex characters: stripped to empty before decoding
        self.assertEqual(parse_encoded_bin_data("!!!"), b"")


class TestParseScalingValue(unittest.TestCase):

    def test_empty(self):
        self.assertIsNone(parse_scaling_value(""))
        self.assertIsNone(parse_scaling_value(None))

    def test_percent(self):
        self.assertEqual(parse_scaling_value("50%"), (1, 2))
        self.assertEqual(parse_scaling_value("100%"), (1, 1))
        self.assertEqual(parse_scaling_value("25%"), (1, 4))

    def test_ratio_colon(self):
        self.assertEqual(parse_scaling_value("1:2"), (1, 2))
        self.assertEqual(parse_scaling_value("2:3"), (2, 3))

    def test_ratio_slash(self):
        self.assertEqual(parse_scaling_value("1/2"), (1, 2))

    def test_integer(self):
        # single value -> (1, value)
        self.assertEqual(parse_scaling_value("2"), (1, 2))

    def test_upscale_raises(self):
        with self.assertRaises((AssertionError, ValueError)):
            parse_scaling_value("3:2")

    def test_zero_raises(self):
        with self.assertRaises((AssertionError, ValueError)):
            parse_scaling_value("0:1")


class TestSplitDictStr(unittest.TestCase):

    def test_simple(self):
        self.assertEqual(split_dict_str("a=1,b=2,c=3"), ["a=1", "b=2", "c=3"])

    def test_nested_parens(self):
        result = split_dict_str("a=1,b=exec(x=2,y=3),c=4")
        self.assertEqual(result, ["a=1", "b=exec(x=2,y=3)", "c=4"])

    def test_empty_string(self):
        self.assertEqual(split_dict_str(""), [])

    def test_no_sep(self):
        self.assertEqual(split_dict_str("a=1"), ["a=1"])

    def test_custom_sep(self):
        self.assertEqual(split_dict_str("a=1;b=2", sep=";"), ["a=1", "b=2"])

    def test_deeply_nested(self):
        result = split_dict_str("a=f(g(1,2),3),b=4")
        self.assertEqual(result, ["a=f(g(1,2),3)", "b=4"])


class TestParseSimpleDict(unittest.TestCase):

    def test_basic(self):
        d = parse_simple_dict("a=1,b=2")
        self.assertEqual(d["a"], "1")
        self.assertEqual(d["b"], "2")

    def test_empty(self):
        self.assertEqual(parse_simple_dict(""), {})

    def test_comments_and_no_equals_ignored(self):
        d = parse_simple_dict("#comment,noequals,a=1")
        self.assertNotIn("#comment", d)
        self.assertNotIn("noequals", d)
        self.assertEqual(d["a"], "1")

    def test_nested_dict(self):
        # "a=b=c" -> {"a": {"b": "c"}}
        d = parse_simple_dict("a=b=c")
        self.assertIsInstance(d["a"], dict)
        self.assertEqual(d["a"]["b"], "c")

    def test_repeated_key_becomes_list(self):
        d = parse_simple_dict("a=1,a=2")
        self.assertIsInstance(d["a"], list)
        self.assertIn("1", d["a"])
        self.assertIn("2", d["a"])

    def test_whitespace_stripped(self):
        d = parse_simple_dict("  a = 1 , b = 2 ")
        self.assertEqual(d["a"], "1")
        self.assertEqual(d["b"], "2")

    def test_nested_parens_not_split(self):
        d = parse_simple_dict("a=1,b=exec(x=2,y=3),c=4")
        self.assertIn("b", d)
        self.assertIn("c", d)


class TestParseStrDict(unittest.TestCase):

    def test_basic(self):
        d = parse_str_dict("a=1,b=2")
        self.assertEqual(d, {"a": "1", "b": "2"})

    def test_empty(self):
        self.assertEqual(parse_str_dict(""), {})

    def test_no_equals_ignored(self):
        d = parse_str_dict("noequals,a=1")
        self.assertNotIn("noequals", d)
        self.assertEqual(d["a"], "1")

    def test_value_with_equals(self):
        # only split on first '='
        d = parse_str_dict("a=b=c")
        self.assertEqual(d["a"], "b=c")

    def test_whitespace_stripped(self):
        d = parse_str_dict("  a = 1 ,  b = 2 ")
        self.assertEqual(d["a"], "1")
        self.assertEqual(d["b"], "2")

    def test_custom_sep(self):
        d = parse_str_dict("a=1;b=2", sep=";")
        self.assertEqual(d, {"a": "1", "b": "2"})


class TestParseWithUnit(unittest.TestCase):

    def test_int_passthrough(self):
        self.assertEqual(parse_with_unit("bandwidth", 1000000), 1000000)

    def test_plain_number(self):
        self.assertEqual(parse_with_unit("bandwidth", "1000000"), 1000000)

    def test_kilobits(self):
        self.assertEqual(parse_with_unit("bandwidth", "1000kbps"), 1000000)

    def test_megabits(self):
        self.assertEqual(parse_with_unit("bandwidth", "10mbps"), 10000000)

    def test_gigabits(self):
        self.assertEqual(parse_with_unit("bandwidth", "1gbps"), 1000000000)

    def test_auto_returns_none(self):
        self.assertIsNone(parse_with_unit("bandwidth", "auto"))

    def test_false_option_returns_zero(self):
        self.assertEqual(parse_with_unit("bandwidth", "0"), 0)
        self.assertEqual(parse_with_unit("bandwidth", "no"), 0)

    def test_too_low_raises(self):
        with self.assertRaises(ValueError):
            parse_with_unit("bandwidth", "1bps", min_value=250000)

    def test_unknown_unit_raises(self):
        with self.assertRaises(ValueError):
            parse_with_unit("bandwidth", "10xbps")


class TestParseResolution(unittest.TestCase):

    def test_explicit_dimensions(self):
        w, h, _ = parse_resolution("1920x1080")
        self.assertEqual((w, h), (1920, 1080))

    def test_with_refresh_rate(self):
        self.assertEqual(parse_resolution("1920x1080@60"), (1920, 1080, 60))

    def test_alias_4k(self):
        w, h, _ = parse_resolution("4K")
        self.assertEqual((w, h), (3840, 2160))

    def test_alias_1080p(self):
        w, h, _ = parse_resolution("1080P")
        self.assertEqual((w, h), (1920, 1080))

    def test_alias_with_refresh(self):
        w, h, hz = parse_resolution("4K@30")
        self.assertEqual((w, h), (3840, 2160))
        self.assertEqual(hz, 30)

    def test_empty_returns_none(self):
        self.assertIsNone(parse_resolution(""))
        self.assertIsNone(parse_resolution(None))

    def test_invalid_raises(self):
        with self.assertRaises(ValueError):
            parse_resolution("notaresolution")


class TestParseResolutions(unittest.TestCase):

    def test_false_options_return_none(self):
        self.assertIsNone(parse_resolutions("no"))
        self.assertIsNone(parse_resolutions("false"))
        self.assertIsNone(parse_resolutions(""))
        self.assertIsNone(parse_resolutions(None))

    def test_none_default_returns_empty(self):
        self.assertEqual(parse_resolutions("none"), ())
        self.assertEqual(parse_resolutions("default"), ())

    def test_single(self):
        result = parse_resolutions("1920x1080")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][:2], (1920, 1080))

    def test_multiple(self):
        result = parse_resolutions("1920x1080,1280x720")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][:2], (1920, 1080))
        self.assertEqual(result[1][:2], (1280, 720))


class TestGetRefreshRateForValue(unittest.TestCase):

    def test_auto_passthrough(self):
        self.assertEqual(get_refresh_rate_for_value("auto", 60), 60)
        self.assertEqual(get_refresh_rate_for_value("none", 60), 60)

    def test_exact_value(self):
        self.assertEqual(get_refresh_rate_for_value("60", 30), 60)

    def test_clamped_to_max(self):
        result = get_refresh_rate_for_value("200", 30)
        self.assertLessEqual(result, 144)

    def test_clamped_to_min(self):
        result = get_refresh_rate_for_value("1", 30)
        self.assertGreaterEqual(result, 5)

    def test_range_clamps(self):
        # "10-50": invalue=30 should stay at 30
        self.assertEqual(get_refresh_rate_for_value("10-50", 30), 30)
        # invalue=5 should clamp to minimum 10
        self.assertEqual(get_refresh_rate_for_value("10-50", 5), 10)
        # invalue=60 should clamp to maximum 50
        self.assertEqual(get_refresh_rate_for_value("10-50", 60), 50)

    def test_range_min_gt_max_raises(self):
        with self.assertRaises(ValueError):
            get_refresh_rate_for_value("50-10", 30)

    def test_percent(self):
        result = get_refresh_rate_for_value("50%", 60)
        self.assertEqual(result, 30)


class TestAdjustMonitorRefreshRate(unittest.TestCase):

    def test_auto_unchanged(self):
        mdef = {0: {"refresh-rate": 60000}}
        result = adjust_monitor_refresh_rate("auto", mdef)
        self.assertEqual(result[0]["refresh-rate"], 60000)

    def test_explicit_rate(self):
        mdef = {0: {"refresh-rate": 60000}}
        result = adjust_monitor_refresh_rate("30", mdef)
        # 30 * 1000 = 30000
        self.assertEqual(result[0]["refresh-rate"], 30000)

    def test_does_not_modify_original(self):
        mdef = {0: {"refresh-rate": 60000}}
        adjust_monitor_refresh_rate("30", mdef)
        self.assertEqual(mdef[0]["refresh-rate"], 60000)

    def test_multiple_monitors(self):
        mdef = {0: {"refresh-rate": 60000}, 1: {"refresh-rate": 60000}}
        result = adjust_monitor_refresh_rate("30", mdef)
        self.assertIn(0, result)
        self.assertIn(1, result)


class TestGetDefaultVideoMaxSize(unittest.TestCase):

    def test_default(self):
        from xpra.util.env import OSEnvContext
        with OSEnvContext():
            import os
            os.environ.pop("XPRA_VIDEO_MAX_SIZE", None)
            w, h = get_default_video_max_size()
            self.assertEqual((w, h), (4096, 4096))

    def test_env_override(self):
        from xpra.util.env import OSEnvContext
        with OSEnvContext():
            import os
            os.environ["XPRA_VIDEO_MAX_SIZE"] = "1920x1080"
            w, h = get_default_video_max_size()
            self.assertEqual(w, 1920)


class TestValidatedMonitorData(unittest.TestCase):

    def test_basic(self):
        monitors = {
            0: {
                "geometry": (0, 0, 1920, 1080),
                "primary": True,
                "refresh-rate": 60000,
                "manufacturer": "ACME",
                "model": "Monitor1",
            }
        }
        result = validated_monitor_data(monitors)
        self.assertIn(0, result)
        m = result[0]
        self.assertEqual(m["geometry"], (0, 0, 1920, 1080))
        self.assertTrue(m["primary"])
        self.assertEqual(m["refresh-rate"], 60000)

    def test_name_generated_from_manufacturer_model(self):
        monitors = {0: {"manufacturer": "DEL", "model": "DELL P2715Q"}}
        result = validated_monitor_data(monitors)
        # model already starts with manufacturer abbrev — should use model
        self.assertEqual(result[0]["name"], "DELL P2715Q")

    def test_name_generated_combined(self):
        monitors = {0: {"manufacturer": "ACME", "model": "ViewPlus"}}
        result = validated_monitor_data(monitors)
        self.assertEqual(result[0]["name"], "ACME ViewPlus")

    def test_name_fallback_to_index(self):
        monitors = {0: {}}
        result = validated_monitor_data(monitors)
        self.assertEqual(result[0]["name"], "0")

    def test_string_key_coerced(self):
        monitors = {"0": {"refresh-rate": 60000}}
        result = validated_monitor_data(monitors)
        self.assertIn(0, result)

    def test_empty(self):
        self.assertEqual(validated_monitor_data({}), {})


def main():
    unittest.main()


if __name__ == '__main__':
    main()
