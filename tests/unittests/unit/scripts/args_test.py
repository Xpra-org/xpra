# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.scripts.args import (
    shellquote,
    strip_defaults_start_child,
    is_display_arg,
    split_display_arg,
    is_connection_arg,
    strip_attach_extra_positional_args,
    find_mode_pos,
)
from xpra.scripts.config import InitException


class TestShellquote(unittest.TestCase):
    def test_plain_string(self):
        self.assertEqual(shellquote("hello"), '"hello"')

    def test_empty_string(self):
        self.assertEqual(shellquote(""), '""')

    def test_string_with_double_quotes(self):
        self.assertEqual(shellquote('say "hi"'), '"say \\"hi\\""')

    def test_string_with_spaces(self):
        self.assertEqual(shellquote("hello world"), '"hello world"')

    def test_string_with_backslash(self):
        self.assertEqual(shellquote("a\\b"), '"a\\b"')


class TestStripDefaultsStartChild(unittest.TestCase):
    def test_removes_defaults(self):
        start_child = ["xterm", "xeyes"]
        defaults = ["xterm"]
        result = strip_defaults_start_child(start_child, defaults)
        self.assertEqual(result, ["xeyes"])

    def test_empty_start_child(self):
        result = strip_defaults_start_child([], ["xterm"])
        self.assertEqual(result, [])

    def test_empty_defaults(self):
        result = strip_defaults_start_child(["xterm"], [])
        self.assertEqual(result, ["xterm"])

    def test_none_start_child(self):
        result = strip_defaults_start_child(None, ["xterm"])
        self.assertIsNone(result)

    def test_none_defaults(self):
        result = strip_defaults_start_child(["xterm"], None)
        self.assertEqual(result, ["xterm"])

    def test_removes_only_once(self):
        # same item appears twice in start_child but only once in defaults
        start_child = ["xterm", "xterm"]
        defaults = ["xterm"]
        result = strip_defaults_start_child(start_child, defaults)
        self.assertEqual(result, ["xterm"])

    def test_no_overlap(self):
        result = strip_defaults_start_child(["xeyes"], ["xterm"])
        self.assertEqual(result, ["xeyes"])


class TestIsDisplayArg(unittest.TestCase):
    def test_colon_prefix(self):
        self.assertTrue(is_display_arg(":0"))
        self.assertTrue(is_display_arg(":10"))

    def test_wayland_prefix(self):
        self.assertTrue(is_display_arg("wayland-0"))
        self.assertTrue(is_display_arg("wayland-1"))

    def test_socket_type_prefix(self):
        self.assertTrue(is_display_arg("tcp://localhost:10000"))
        self.assertTrue(is_display_arg("ssl://host:443"))

    def test_bare_integer(self):
        self.assertTrue(is_display_arg("0"))
        self.assertTrue(is_display_arg("42"))

    def test_negative_integer(self):
        self.assertFalse(is_display_arg("-1"))

    def test_hostname(self):
        self.assertFalse(is_display_arg("localhost"))

    def test_option_flag(self):
        self.assertFalse(is_display_arg("--some-option"))

    def test_empty_string(self):
        self.assertFalse(is_display_arg(""))


class TestSplitDisplayArg(unittest.TestCase):
    def test_empty_list(self):
        self.assertEqual(split_display_arg([]), ([], []))

    def test_display_first(self):
        self.assertEqual(split_display_arg([":0", "--some-opt"]), ([":0"], ["--some-opt"]))

    def test_no_display(self):
        self.assertEqual(split_display_arg(["--opt", "val"]), ([], ["--opt", "val"]))

    def test_single_display(self):
        self.assertEqual(split_display_arg([":0"]), ([":0"], []))

    def test_integer_display(self):
        self.assertEqual(split_display_arg(["5", "extra"]), (["5"], ["extra"]))


class TestIsConnectionArg(unittest.TestCase):
    def test_socket_url(self):
        self.assertTrue(is_connection_arg("tcp://localhost:10000"))
        self.assertTrue(is_connection_arg("ssl://host:443"))
        self.assertTrue(is_connection_arg("ssh://user@host"))

    def test_socket_colon_form(self):
        self.assertTrue(is_connection_arg("tcp:localhost:10000"))

    def test_socket_slash_form(self):
        self.assertTrue(is_connection_arg("tcp/localhost"))

    def test_host_display_pair(self):
        self.assertTrue(is_connection_arg("somehost:0"))
        self.assertTrue(is_connection_arg("somehost:10"))

    def test_plain_option(self):
        self.assertFalse(is_connection_arg("--option"))

    def test_plain_word(self):
        self.assertFalse(is_connection_arg("start"))

    def test_colon_prefix_posix(self):
        with patch("xpra.scripts.args.POSIX", True):
            self.assertTrue(is_connection_arg(":0"))

    def test_wayland_posix(self):
        with patch("xpra.scripts.args.POSIX", True):
            self.assertTrue(is_connection_arg("wayland-0"))


class TestStripAttachExtraPositionalArgs(unittest.TestCase):
    def test_no_attach(self):
        cmdline = ["xpra", "seamless", ":0"]
        self.assertEqual(strip_attach_extra_positional_args(cmdline), cmdline)

    def test_attach_no_extra(self):
        cmdline = ["xpra", "attach", ":0"]
        self.assertEqual(strip_attach_extra_positional_args(cmdline), cmdline)

    def test_strips_extra_positional(self):
        cmdline = ["xpra", "attach", ":0", "xterm"]
        result = strip_attach_extra_positional_args(cmdline)
        self.assertEqual(result, ["xpra", "attach", ":0"])

    def test_keeps_options_after_display(self):
        cmdline = ["xpra", "attach", ":0", "--clipboard=yes", "xterm"]
        result = strip_attach_extra_positional_args(cmdline)
        self.assertEqual(result, ["xpra", "attach", ":0", "--clipboard=yes"])

    def test_keeps_option_values(self):
        cmdline = ["xpra", "attach", ":0", "--compress", "lz4", "xterm"]
        result = strip_attach_extra_positional_args(cmdline)
        self.assertEqual(result, ["xpra", "attach", ":0", "--compress", "lz4"])

    def test_no_display_after_attach(self):
        # no display arg found — return as-is
        cmdline = ["xpra", "attach", "--some-option"]
        result = strip_attach_extra_positional_args(cmdline)
        self.assertEqual(result, cmdline)

    def test_tcp_url_as_display(self):
        cmdline = ["xpra", "attach", "tcp://host:10000", "xterm"]
        result = strip_attach_extra_positional_args(cmdline)
        self.assertEqual(result, ["xpra", "attach", "tcp://host:10000"])


class TestFindModePos(unittest.TestCase):
    def test_finds_seamless_as_start(self):
        # "seamless" maps to "start-seamless" in REVERSE_MODE_ALIAS,
        # but also adds "start" as a fallback
        args = ["xpra", "start", "--some-opt"]
        pos = find_mode_pos(args, "seamless")
        self.assertEqual(pos, 1)

    def test_finds_desktop(self):
        args = ["xpra", "start-desktop", "--opt"]
        pos = find_mode_pos(args, "desktop")
        self.assertEqual(pos, 1)

    def test_finds_short_form(self):
        # "start-desktop" -> also tries "desktop"
        args = ["xpra", "desktop", "--opt"]
        pos = find_mode_pos(args, "desktop")
        self.assertEqual(pos, 1)

    def test_finds_shadow(self):
        args = ["xpra", "start-shadow", "--opt"]
        pos = find_mode_pos(args, "shadow")
        self.assertEqual(pos, 1)

    def test_not_found_raises(self):
        args = ["xpra", "--opt"]
        with self.assertRaises(InitException):
            find_mode_pos(args, "desktop")

    def test_unknown_mode_raises(self):
        args = ["xpra", "start"]
        with self.assertRaises(InitException):
            find_mode_pos(args, "nonexistent-mode")


if __name__ == "__main__":
    unittest.main()
