#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from xpra.auth.ratelimit import Authenticator, get_peer_ip, get_ip_key
from xpra.util.objects import typedict


def make_connection(ip: str, port: int = 54321):
    return SimpleNamespace(remote=(ip, port), options={})


class FakeClock:

    def __init__(self, now: float = 1000):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestRateLimitAuthenticator(unittest.TestCase):

    def setUp(self):
        Authenticator.reset()
        self.clock = FakeClock()
        self.slept: list[float] = []
        for p in (
            patch("xpra.auth.ratelimit.monotonic", self.clock),
            patch("xpra.auth.ratelimit.sleep", self.slept.append),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(Authenticator.reset)

    def auth(self, ip: str = "1.2.3.4", **kwargs) -> Authenticator:
        return Authenticator(connection=make_connection(ip), username="foo", **kwargs)

    def failed_attempt(self, ip: str = "1.2.3.4", **kwargs) -> Authenticator:
        # a connection that gets past the gate, then fails a later authentication module:
        a = self.auth(ip, **kwargs)
        assert a.authenticate(typedict()) is True
        a.auth_failed()
        return a

    def recorded(self, ip: str = "1.2.3.4", ipv4_prefix: int = 32, ipv6_prefix: int = 128) -> int:
        key = get_ip_key(ip, ipv4_prefix, ipv6_prefix)
        return len(Authenticator.FAILURES.get(key, ()))

    def test_peer_ip(self):
        assert get_peer_ip(make_connection("1.2.3.4")) == "1.2.3.4"
        # unix sockets, named pipes and the fake connections used by the other tests:
        assert get_peer_ip(SimpleNamespace(remote="")) == ""
        assert get_peer_ip("fake-connection-data") == ""
        assert get_peer_ip(None) == ""

    def test_ip_key(self):
        assert get_ip_key("1.2.3.4", 32, 128) == "1.2.3.4/32"
        assert get_ip_key("1.2.3.4", 24, 128) == "1.2.3.0/24"
        assert get_ip_key("2001:db8::1", 32, 64) == "2001:db8::/64"
        # an IPv4 mapped address is grouped with the plain IPv4 address:
        assert get_ip_key("::ffff:1.2.3.4", 32, 128) == "1.2.3.4/32"
        # loopback is never rate limited:
        assert get_ip_key("127.0.0.1", 32, 128) == ""
        assert get_ip_key("::1", 32, 128) == ""
        # unparsable addresses are ignored rather than fatal:
        assert get_ip_key("not-an-ip", 32, 128) == ""
        assert get_ip_key("", 32, 128) == ""

    def test_first_attempt_passes_without_delay(self):
        a = self.auth()
        assert a.requires_challenge() is False
        assert a.authenticate(typedict()) is True
        assert not self.slept

    def test_blocks_after_max_failures(self):
        for _ in range(3):
            self.failed_attempt(**{"max-failures": 3})
        assert self.recorded() == 3
        a = self.auth(**{"max-failures": 3})
        assert a.authenticate(typedict()) is False
        assert a.rejected is True

    def test_delay_grows_then_rejects(self):
        opts = {"max-failures": 5, "delay": 1, "max-delay": 8}
        for _ in range(5):
            self.failed_attempt(**opts)
        # 8 rather than 16: capped by `max-delay`
        assert self.slept == [1, 2, 4, 8]
        assert self.auth(**opts).authenticate(typedict()) is False

    def test_delay_can_be_disabled(self):
        opts = {"max-failures": 5, "delay": 0}
        for _ in range(4):
            self.failed_attempt(**opts)
        assert not self.slept

    def test_window_expiry_unblocks(self):
        opts = {"max-failures": 2, "window": 60}
        for _ in range(2):
            self.failed_attempt(**opts)
        assert self.auth(**opts).authenticate(typedict()) is False
        self.clock.advance(61)
        assert self.auth(**opts).authenticate(typedict()) is True

    def test_rejection_does_not_extend_the_block(self):
        opts = {"max-failures": 2, "window": 60}
        for _ in range(2):
            self.failed_attempt(**opts)
        # a blocked client keeps hammering: the server rejects it,
        # and fires the `auth_failed` callback for that rejection too
        self.clock.advance(30)
        for _ in range(5):
            a = self.auth(**opts)
            assert a.authenticate(typedict()) is False
            a.auth_failed()
        assert self.recorded() == 2
        # the block still lifts one window after the *real* failures:
        self.clock.advance(31)
        assert self.auth(**opts).authenticate(typedict()) is True

    def test_success_clears_the_failures(self):
        opts = {"max-failures": 3}
        for _ in range(2):
            self.failed_attempt(**opts)
        assert self.recorded() == 2
        a = self.auth(**opts)
        assert a.authenticate(typedict()) is True
        a.auth_succeeded()
        assert self.recorded() == 0

    def test_addresses_are_tracked_separately(self):
        opts = {"max-failures": 2}
        for _ in range(2):
            self.failed_attempt("1.2.3.4", **opts)
        assert self.auth("1.2.3.4", **opts).authenticate(typedict()) is False
        assert self.auth("5.6.7.8", **opts).authenticate(typedict()) is True

    def test_ipv6_addresses_can_be_grouped_by_prefix(self):
        opts = {"max-failures": 2, "ipv6-prefix": 64}
        for ip in ("2001:db8::1", "2001:db8::2"):
            self.failed_attempt(ip, **opts)
        # both addresses count against the same /64:
        assert self.auth("2001:db8::3", **opts).authenticate(typedict()) is False
        # a different /64 is unaffected:
        assert self.auth("2001:db9::1", **opts).authenticate(typedict()) is True

    def test_ipv6_addresses_are_exact_by_default(self):
        opts = {"max-failures": 2}
        for ip in ("2001:db8::1", "2001:db8::2"):
            self.failed_attempt(ip, **opts)
        assert self.auth("2001:db8::3", **opts).authenticate(typedict()) is True

    def test_loopback_is_not_rate_limited(self):
        opts = {"max-failures": 1}
        for _ in range(5):
            self.failed_attempt("127.0.0.1", **opts)
        assert not Authenticator.FAILURES
        assert self.auth("127.0.0.1", **opts).authenticate(typedict()) is True

    def test_connections_without_an_address_are_not_rate_limited(self):
        # ie: unix domain sockets
        a = Authenticator(connection=SimpleNamespace(remote=""), username="foo", **{"max-failures": 1})
        assert a.authenticate(typedict()) is True
        a.auth_failed()
        assert not Authenticator.FAILURES
        assert a.authenticate(typedict()) is True

    def test_tracked_addresses_are_bounded(self):
        opts = {"max-tracked": 2}
        for i in range(5):
            self.failed_attempt(f"1.2.3.{i}", **opts)
        assert len(Authenticator.FAILURES) == 2
        # the oldest records are the ones that get evicted:
        assert self.recorded("1.2.3.0") == 0
        assert self.recorded("1.2.3.4") == 1

    def test_expired_records_are_dropped(self):
        opts = {"window": 60}
        self.failed_attempt("1.2.3.4", **opts)
        self.clock.advance(61)
        self.failed_attempt("5.6.7.8", **opts)
        assert "1.2.3.4/32" not in Authenticator.FAILURES

    def test_invalid_options_are_rejected(self):
        for opts in (
            {"max-failures": "not-a-number"},
            {"max-failures": 0},
            {"window": -1},
            {"ipv6-prefix": 129},
            {"delay": "x"},
        ):
            with self.assertRaises(ValueError):
                self.auth(**opts)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
