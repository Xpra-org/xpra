#!/usr/bin/env python3

import unittest
from unittest.mock import patch

from dbus.exceptions import DBusException

try:
    from xpra.platform.posix.shadow.fd_portal import PortalShadow
    NO_PORTAL = ""
except DBusException as e:
    # the module connects to the session bus when it is imported:
    PortalShadow = None
    NO_PORTAL = f"cannot connect to the session bus: {e}"


class FakeCapture:
    def __init__(self):
        self.cleaned = 0

    def clean(self):
        self.cleaned += 1


@unittest.skipIf(PortalShadow is None, NO_PORTAL)
class PortalShadowCaptureTest(unittest.TestCase):
    def test_multi_stream_cleanup(self):
        server = PortalShadow.__new__(PortalShadow)
        first, second = FakeCapture(), FakeCapture()
        server.captures = {11: first, 12: second}
        server.stop_capture()
        server.stop_capture()
        self.assertEqual(server.captures, {})
        self.assertEqual((first.cleaned, second.cleaned), (1, 1))

    def test_stream_error_only_cleans_affected_node(self):
        server = PortalShadow.__new__(PortalShadow)
        first, second = FakeCapture(), FakeCapture()
        first.node_id = 11
        server.captures = {11: first, 12: second}
        server.get_window = lambda _wid: None
        with patch("xpra.platform.posix.shadow.fd_portal.get_sources_by_type", return_value=()):
            server.capture_error(first, "stream failed")
        self.assertEqual(first.cleaned, 1)
        self.assertEqual(server.captures, {12: second})


if __name__ == "__main__":
    unittest.main()
