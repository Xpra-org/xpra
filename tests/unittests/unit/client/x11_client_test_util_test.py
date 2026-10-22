#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock, patch

from unit.client import x11_client_test_util as client_util


class TestX11ClientCookies(unittest.TestCase):

    def test_clients_share_a_cookie_only_on_the_same_display(self):
        first = client_util.X11ClientTestUtil()
        second = client_util.X11ClientTestUtil()
        for helper in (first, second):
            helper.default_env = {"XAUTHORITY": "/test/.Xauthority"}
            helper.get_run_env = Mock(side_effect=dict)
            helper.run_xpra = Mock()
        with patch.object(client_util.X11ClientTestUtil, "xauth_cookies", {}, create=True), \
                patch.object(client_util.X11ClientTestUtil, "uq", 0), \
                patch.object(client_util, "get_hex_uuid", side_effect=("cookie1", "cookie2", "cookie3")), \
                patch("xpra.x11.vfb_util.xauth_add") as add:
            first.do_run_client(":100")
            second.do_run_client(":100")
            first.do_run_client(":101")
        cookies = [(call[0][1], call[0][2]) for call in add.call_args_list]
        self.assertEqual(cookies, [(":100", "cookie1"), (":100", "cookie1"), (":101", "cookie3")])


if __name__ == '__main__':
    unittest.main()
