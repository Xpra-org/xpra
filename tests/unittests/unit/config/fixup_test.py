#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from xpra.config import InitExit, InitInfo, fixup
from xpra.config.defaults import build_defaults
from xpra.config.types import dict_to_config
from unit.config.defaults_test import supplied_context


class FixupTest(unittest.TestCase):

    def test_debug_and_csv_values(self):
        for value, expected in (("", ""), ("False", ""), ("True", "all"), ("yes", "all"), ("off", ""), ("network,util", "network,util")):
            self.assertEqual(fixup.fixup_debug_option(value), expected)
        self.assertEqual(fixup.csvstr([" one ", "", "two"]), "one,two")
        self.assertEqual(fixup.csvstrl(" ONE,TWO "), "one,two")
        self.assertEqual(fixup.nodupes(" ONE,two,one "), ["one", "two"])
        with self.assertRaises(ValueError):
            fixup.csvstr(1)

    def test_ping_values(self):
        for value, expected in ((True, True), (15, 15), ("yes", 5), ("no", 0), ("12", 12), ("invalid", 5)):
            options = SimpleNamespace(pings=value)
            fixup.fixup_pings(options)
            self.assertEqual(options.pings, expected)

    def test_encoding_aliases_and_exclusions(self):
        options = SimpleNamespace(encoding="jpg", encodings="pngl,pngp,rgb,jpg,no-jpeg", video=False)
        fixup.fixup_encodings(options)
        self.assertEqual(options.encoding, "jpeg")
        self.assertEqual(options.encodings, ("png/L", "png/P", "rgb", "no-jpeg", "rgb24", "rgb32"))
        self.assertEqual(options.video_encoders, ["none"])
        self.assertEqual(options.video_decoders, ["none"])
        self.assertEqual(options.csc_modules, ["none"])
        options.encodings = "-scroll,no-jpeg"
        fixup.fixup_encodings(options)
        self.assertNotIn("jpeg", options.encodings)
        self.assertNotIn("scroll", options.encodings)
        self.assertIn("png", options.encodings)
        options.encodings = "unknown"
        with self.assertRaises(InitExit):
            fixup.fixup_encodings(options)

    def test_video_module_options_and_help(self):
        options = SimpleNamespace(encoding="auto", encodings="all", video=True, csc_modules={"libyuv"}, video_encoders=[], video_decoders=[])
        fixup.fixup_encodings(options)
        self.assertEqual(options.csc_modules, ["libyuv"])
        options.csc_modules = ["help"]
        with self.assertRaises(InitInfo):
            fixup.fixup_encodings(options)

    def test_compression_and_packet_encoders(self):
        options = SimpleNamespace(compressors="all", packet_encoders="all")
        fixup.fixup_compression(options)
        fixup.fixup_packetencoding(options)
        self.assertTrue(options.compressors)
        self.assertTrue(options.packet_encoders)
        options.compressors = "none"
        options.packet_encoders = "none"
        fixup.fixup_compression(options)
        fixup.fixup_packetencoding(options)
        self.assertEqual(options.compressors, [])
        self.assertEqual(list(options.packet_encoders), ["none"])
        options.compressors = "lz4,zlib,unknown"
        options.packet_encoders = "rencodeplus,bencode,unknown"
        with patch("xpra.config.warn") as warn:
            fixup.fixup_compression(options)
            fixup.fixup_packetencoding(options)
        self.assertEqual(options.compressors, ["lz4"])
        self.assertEqual(options.packet_encoders, ["rencodeplus"])
        self.assertEqual(warn.call_count, 2)

    def test_clipboard_and_backend_platform_policy(self):
        options = SimpleNamespace(clipboard="auto", backend="native")
        with patch.object(fixup, "WIN32", True):
            fixup.fixup_backend(options)
            self.assertEqual(options.backend, "win32")
            for value, expected in (("toserver", "to-server"), ("toclient", "to-client"), ("both", "both"), ("none", "disabled")):
                options.clipboard_direction = value
                fixup.fixup_clipboard(options)
                self.assertEqual(options.clipboard_direction, expected)
        self.assertEqual(options.clipboard, "all")
        options.clipboard_direction = "invalid"
        with patch("xpra.config.warn") as warn:
            fixup.fixup_clipboard(options)
        self.assertEqual(options.clipboard_direction, "disabled")
        self.assertEqual(warn.call_count, 2)

    def test_invalid_keyboard_sequence(self):
        options = SimpleNamespace(keyboard_backend="auto", keyboard_raw="yes", keyboard_layouts=[object()], keyboard_variants=None)
        fixup.fixup_keyboard(options)
        self.assertEqual(options.keyboard_layouts, [])
        self.assertEqual(options.keyboard_variants, ["None"])
        self.assertTrue(options.keyboard_raw)

    def test_path_normalization(self):
        options = dict_to_config(build_defaults(supplied_context()))
        options.exec_wrapper = "wrapper --flag"
        options.log_dir = "relative-logs"
        options.download_path = "~/Downloads"
        options.ssl_key = "$PRIVATE_KEY"
        with patch.object(fixup, "which", return_value="/supplied/wrapper"):
            fixup.abs_paths(options)
        self.assertEqual(options.exec_wrapper, "/supplied/wrapper --flag")
        self.assertEqual(options.log_dir, os.path.abspath("relative-logs"))
        self.assertEqual(options.download_path, "~/Downloads")
        self.assertEqual(options.ssl_key, "$PRIVATE_KEY")
        self.assertEqual(options.ssl_ca_certs, "default")

    def test_complete_option_normalization(self):
        options = dict_to_config(build_defaults(supplied_context()))
        options.remote_xpra = "custom-xpra"
        options.video = False
        options.socket_dirs = os.pathsep.join(("/first", "/second"))
        fixup.fixup_options(options)
        self.assertEqual(options.remote_xpra, ["custom-xpra"])
        self.assertEqual(options.socket_dirs, ["/first", "/second"])
        self.assertEqual(options.landlock, "no")


if __name__ == "__main__":
    unittest.main()
