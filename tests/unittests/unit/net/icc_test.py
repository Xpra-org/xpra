#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.net import icc


def make_icc_profile(size: int = 128) -> bytes:
    profile = bytearray(size)
    profile[:4] = size.to_bytes(4, "big")
    profile[36:40] = b"acsp"
    return bytes(profile)


class ICCValidationTest(unittest.TestCase):

    def test_valid_profile_is_canonicalized(self):
        profile = make_icc_profile()
        result = icc.validate_icc_profile({
            "source": "OS\nprofile\N{RIGHT-TO-LEFT OVERRIDE}",
            "data": bytearray(profile),
            "version": 1,
            "supports-output": True,
        })
        self.assertEqual(result["source"], "OS profile")
        self.assertEqual(result["data"], profile)
        self.assertIsInstance(result["data"], bytes)
        self.assertEqual(result["version"], 1)
        self.assertTrue(result["supports-output"])

    def test_valid_envelope_is_detached(self):
        profile = {"data": make_icc_profile()}
        displays = {0: profile}
        raw = {"global": profile, "display": displays}
        result = icc.validate_icc_data(raw)
        self.assertEqual(result, raw)
        self.assertIsNot(result, raw)
        self.assertIsNot(result["global"], profile)
        self.assertIsNot(result["display"], displays)
        self.assertIsNot(result["display"][0], profile)

    def test_invalid_profile_container_and_fields(self):
        for value in (None, (), [], "profile"):
            with self.subTest(value=value), self.assertRaises(TypeError):
                icc.validate_icc_profile(value)
        for profile in ({"unknown": "value"}, {1: "value"}):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                icc.validate_icc_profile(profile)

    def test_invalid_field_types(self):
        invalid = (
            {"data": 1},
            {"source": 1},
            {"version": True},
            {"version": -1},
            {"version": 2**31},
            {"supports-output": 1},
        )
        for profile in invalid:
            with self.subTest(profile=profile), self.assertRaises((TypeError, ValueError)):
                icc.validate_icc_profile(profile)

    def test_profile_header_validation(self):
        bad_size = bytearray(make_icc_profile())
        bad_size[:4] = (127).to_bytes(4, "big")
        bad_signature = bytearray(make_icc_profile())
        bad_signature[36:40] = b"nope"
        for data in (b"short", bytes(bad_size), bytes(bad_signature)):
            with self.subTest(data=data[:40]), self.assertRaises(ValueError):
                icc.validate_icc_profile({"data": data})
        self.assertEqual(icc.validate_icc_profile({"data": b""}), {"data": b""})

    def test_profile_and_text_limits(self):
        with patch.object(icc, "MAX_ICC_PROFILE_SIZE", 128):
            with self.assertRaises(ValueError):
                icc.validate_icc_profile({"data": make_icc_profile(129)})
        with patch.object(icc, "MAX_ICC_PROFILE_SIZE", 200):
            with self.assertRaises(ValueError):
                icc.validate_icc_profile({"data": make_icc_profile(), "icc-data": make_icc_profile()})
        with patch.object(icc, "MAX_ICC_TEXT_SIZE", 4):
            with self.assertRaises(ValueError):
                icc.validate_icc_profile({"name": "12345"})

    def test_invalid_envelope(self):
        for value in (None, (), [], "icc"):
            with self.subTest(value=value), self.assertRaises(TypeError):
                icc.validate_icc_data(value)
        with self.assertRaises(ValueError):
            icc.validate_icc_data({"unknown": {}})
        with self.assertRaises(TypeError):
            icc.validate_icc_data({"display": []})

    def test_display_indices_and_limit(self):
        profile = {"data": make_icc_profile()}
        for display in (True, -1, icc.MAX_ICC_DISPLAYS, "0"):
            with self.subTest(display=display), self.assertRaises(ValueError):
                icc.validate_icc_data({"display": {display: profile}})
        with patch.object(icc, "MAX_ICC_DISPLAYS", 1):
            with self.assertRaises(ValueError):
                icc.validate_icc_data({"display": {0: profile, 1: profile}})

    def test_aggregate_limit(self):
        profile = {"data": make_icc_profile()}
        with patch.object(icc, "MAX_ICC_TOTAL_SIZE", 255):
            with self.assertRaises(ValueError):
                icc.validate_icc_data({"global": profile, "display": {0: profile}})


def main():
    unittest.main()


if __name__ == "__main__":
    main()
