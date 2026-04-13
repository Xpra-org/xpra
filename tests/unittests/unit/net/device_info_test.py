#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

from xpra.net.device_info import (
    guess_adapter_type,
    jitter_for_adapter_type,
    guess_bandwidth_limit,
    get_device_value,
)


class TestGuessAdapterType(unittest.TestCase):

    def test_wireless_names(self):
        for name in ("wlan0", "wlp3s0", "wireless0", "wlan1"):
            self.assertEqual(guess_adapter_type(name), "wireless", name)

    def test_loopback_names(self):
        for name in ("lo", "loopback0", "localhost"):
            result = guess_adapter_type(name)
            self.assertIn(result, ("loopback", "local", "ethernet"), name)

    def test_lo_is_loopback(self):
        self.assertEqual(guess_adapter_type("lo"), "loopback")

    def test_ethernet_names(self):
        for name in ("ethernet0", "veth0"):
            self.assertEqual(guess_adapter_type(name), "ethernet", name)

    def test_wan_name(self):
        self.assertEqual(guess_adapter_type("wan0"), "wan")

    def test_local_names(self):
        for name in ("tun0", "tap0", "vlan1"):
            self.assertEqual(guess_adapter_type(name), "local", name)

    def test_unknown_name(self):
        result = guess_adapter_type("xyz999")
        self.assertEqual(result, "")

    def test_case_insensitive(self):
        self.assertEqual(guess_adapter_type("WLAN0"), "wireless")
        self.assertEqual(guess_adapter_type("VETH0"), "ethernet")


class TestJitterForAdapterType(unittest.TestCase):

    def test_empty_returns_minus_one(self):
        self.assertEqual(jitter_for_adapter_type(""), -1)

    def test_loopback_is_zero(self):
        self.assertEqual(jitter_for_adapter_type("loopback"), 0)

    def test_ethernet_is_non_negative(self):
        self.assertGreaterEqual(jitter_for_adapter_type("ethernet"), 0)

    def test_local_is_non_negative(self):
        self.assertGreaterEqual(jitter_for_adapter_type("local"), 0)

    def test_wireless_is_positive(self):
        self.assertGreater(jitter_for_adapter_type("wireless"), 0)

    def test_wifi_is_positive(self):
        self.assertGreater(jitter_for_adapter_type("wifi"), 0)

    def test_wan_returns_value(self):
        self.assertGreaterEqual(jitter_for_adapter_type("wan"), 0)

    def test_unknown_returns_minus_one(self):
        self.assertEqual(jitter_for_adapter_type("unknown-xyz"), -1)


class TestGuessBandwidthLimit(unittest.TestCase):

    def test_wireless_returns_wifi_limit(self):
        from xpra.net.device_info import WIFI_LIMIT
        self.assertEqual(guess_bandwidth_limit("wireless"), WIFI_LIMIT)

    def test_wifi_returns_wifi_limit(self):
        from xpra.net.device_info import WIFI_LIMIT
        self.assertEqual(guess_bandwidth_limit("wifi"), WIFI_LIMIT)

    def test_adsl_returns_adsl_limit(self):
        from xpra.net.device_info import ADSL_LIMIT
        self.assertEqual(guess_bandwidth_limit("adsl"), ADSL_LIMIT)

    def test_ppp_returns_adsl_limit(self):
        from xpra.net.device_info import ADSL_LIMIT
        self.assertEqual(guess_bandwidth_limit("ppp0"), ADSL_LIMIT)

    def test_ethernet_returns_zero(self):
        self.assertEqual(guess_bandwidth_limit("ethernet"), 0)

    def test_unknown_returns_zero(self):
        self.assertEqual(guess_bandwidth_limit("unknown"), 0)


class TestGetDeviceValue(unittest.TestCase):

    def test_env_var_takes_priority(self):
        os.environ["XPRA_NETWORK_TESTATTR"] = "42"
        try:
            result = get_device_value(
                {"socket.testattr": "from-coptions"},
                {"testattr": "from-device"},
                "testattr",
                int,
                0,
            )
            self.assertEqual(result, 42)
        finally:
            del os.environ["XPRA_NETWORK_TESTATTR"]

    def test_coptions_second_priority(self):
        result = get_device_value(
            {"socket.myattr": "100"},
            {"myattr": "200"},
            "myattr",
            int,
            0,
        )
        self.assertEqual(result, 100)

    def test_device_info_fallback(self):
        result = get_device_value(
            {},
            {"speed": "5000"},
            "speed",
            int,
            0,
        )
        self.assertEqual(result, 5000)

    def test_default_when_missing(self):
        result = get_device_value({}, {}, "nonexistent", str, "default")
        self.assertEqual(result, "default")

    def test_invalid_conversion_returns_default(self):
        result = get_device_value({}, {"count": "notanumber"}, "count", int, 99)
        self.assertEqual(result, 99)

    def test_string_conversion(self):
        result = get_device_value({}, {"name": "eth0"}, "name", str, "")
        self.assertEqual(result, "eth0")

    def test_hyphen_in_attr_name(self):
        os.environ["XPRA_NETWORK_MY_ATTR"] = "hello"
        try:
            result = get_device_value({}, {}, "my-attr", str, "")
            self.assertEqual(result, "hello")
        finally:
            del os.environ["XPRA_NETWORK_MY_ATTR"]


if __name__ == "__main__":
    unittest.main()
