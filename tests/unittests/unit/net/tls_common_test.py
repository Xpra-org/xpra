#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import io
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.exit_codes import ExitCode
from xpra.net.tls import common
from xpra.scripts.config import InitExit


class TLSCommonTest(unittest.TestCase):

    def test_remote_proxy_validation_and_read(self):
        options = object()
        with self.assertRaises(InitExit):
            common.get_remote_proxy_command_output(options, (), [])
        with patch("xpra.scripts.parsing.parse_display_name", return_value={"type": "tcp"}):
            with self.assertRaises(InitExit):
                common.get_remote_proxy_command_output(options, ("tcp://host",), [])
        conn = Mock()
        conn.read.side_effect = (b"one", b"two", b"")
        display = {"type": "ssh", "host": "host"}
        with patch("xpra.scripts.parsing.parse_display_name", return_value=display), \
                patch("xpra.net.connect.connect_to_ssh", return_value=conn):
            result, data = common.get_remote_proxy_command_output(options, ("ssh://host",), [])
        self.assertEqual(data, b"onetwo")
        self.assertEqual(result["proxy_command"], ["setup-ssl"])
        conn.close.assert_called_once()

    def test_setup_remote_and_missing_data(self):
        display = {"host": "host"}
        save = Mock()
        with patch.object(common, "get_remote_proxy_command_output", return_value=(display, b"certificate")), \
                patch("xpra.net.tls.file.strip_cert", return_value=b"stripped"), \
                patch("xpra.net.tls.file.save_ssl_config_file", save):
            self.assertEqual(common.setup_ssl(object(), ("ssh://host",), []), ExitCode.OK)
        save.assert_called_once_with("host", port=0, filename="cert.pem", fileinfo="certificate", filedata=b"stripped")
        with patch.object(common, "get_remote_proxy_command_output", return_value=(display, b"")):
            with self.assertRaises(InitExit):
                common.setup_ssl(object(), ("ssh://host",), [])

    def test_setup_and_show_local(self):
        stdout = io.StringIO()
        with patch("xpra.net.tls.file.gen_ssl_cert", return_value=("key", "cert")), \
                patch("xpra.util.io.load_binary_file", return_value=b"CERT"), \
                patch.object(common.sys, "stdout", stdout):
            self.assertEqual(common.setup_ssl(object(), (), []), 0)
        self.assertEqual(stdout.getvalue(), "CERT")

        stdout = io.StringIO()
        with patch("xpra.net.tls.file.find_ssl_cert", side_effect=("key", "cert")), \
                patch("xpra.util.io.load_binary_file", return_value=b"CERT"), \
                patch.object(common.sys, "stdout", stdout):
            self.assertEqual(common.show_ssl(object(), (), []), ExitCode.OK)
        self.assertEqual(stdout.getvalue(), "CERT")
        with patch("xpra.net.tls.file.find_ssl_cert", return_value=""):
            self.assertEqual(common.show_ssl(object(), (), []), ExitCode.NO_DATA)

    def test_show_remote(self):
        stdout = io.StringIO()
        with patch.object(common, "get_remote_proxy_command_output", return_value=({}, b"junkCERT")), \
                patch("xpra.net.tls.file.strip_cert", return_value=b"CERT"), patch.object(common.sys, "stdout", stdout):
            self.assertEqual(common.show_ssl(SimpleNamespace(), ("ssh://host",), []), ExitCode.OK)
        self.assertEqual(stdout.getvalue(), "CERT")


if __name__ == "__main__":
    unittest.main()
