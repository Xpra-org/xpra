#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
import os
import sys
from dataclasses import replace
from unittest.mock import patch

from xpra.config import defaults
from xpra.config.defaults import DefaultsContext, build_defaults, dict_to_validated_config, get_defaults, make_defaults_struct


def supplied_context() -> DefaultsContext:
    return DefaultsContext(
        win32=False, osx=False, posix=True, wm_name="Test", border="auto,5:off", postscript_printer="printer",
        pulseaudio=None, systemd_run="auto", system_proxy_socket="/supplied/proxy", xvfb="supplied Xvfb", xdummy="supplied Xorg",
        sessions_dir="/supplied/sessions", download_dir="/supplied/downloads", seccomp="default", uid=123, gid=456,
        audio_support=True, socket_dirs=["/supplied/sockets"], client_socket_dirs=["/supplied/client"],
        remote_xpra=["supplied-xpra"], key_shortcuts=["Control+F1:quit"], start_env=["FIRST=1"], env=["SECOND=2"],
    )


class DefaultsTest(unittest.TestCase):

    def test_supplied_defaults_without_discovery(self):
        with patch.object(defaults, "collect_defaults_context", side_effect=AssertionError("host discovery")):
            values = build_defaults(supplied_context())
        for key, expected in (("uid", 123), ("gid", 456), ("xvfb", "supplied Xvfb"), ("wm-name", "Test"),
                              ("socket-dirs", ["/supplied/sockets"]), ("env", ["SECOND=2"]), ("start-env", ["FIRST=1"]),
                              ("download-path", "/supplied/downloads"), ("speaker", "on"), ("microphone", "off")):
            with self.subTest(key=key):
                self.assertEqual(values[key], expected)

    def test_platform_defaults(self):
        platforms = ((False, False, True, "/usr/bin/xdg-open"), (True, False, False, "start ''"), (False, True, True, "open"))
        for win32, osx, posix, command in platforms:
            values = build_defaults(replace(supplied_context(), win32=win32, osx=osx, posix=posix, audio_support=False))
            with self.subTest(win32=win32, osx=osx):
                self.assertEqual(values["open-command"], command)
                self.assertEqual(values["daemon"], not (win32 or osx))
                self.assertEqual(values["dbus"], "yes" if posix and not osx else "no")
                self.assertEqual(values["source"], ("/etc/profile",) if posix else ())
                self.assertEqual(values["speaker"], "disabled")
                self.assertEqual(values["microphone"], "disabled")

    def test_cached_discovery(self):
        with patch.object(defaults, "GLOBAL_DEFAULTS", None), \
             patch.object(defaults, "collect_defaults_context", return_value=supplied_context()) as collect:
            first = get_defaults()
            self.assertIs(get_defaults(), first)
            collect.assert_called_once_with()
            first["title"] = "cached mutation"
            self.assertEqual(get_defaults()["title"], "cached mutation")

    def test_builder_creates_independent_builtin_lists(self):
        first = build_defaults(supplied_context())
        second = build_defaults(supplied_context())
        first["start"].append("xterm")
        self.assertEqual(second["start"], [])

    def test_configuration_precedence(self):
        values = build_defaults(supplied_context())
        with patch.object(defaults, "GLOBAL_DEFAULTS", values):
            options = dict_to_validated_config({"quality": "72", "title": "file"}, extras_defaults={"quality": 60, "title": "extra"})
        self.assertEqual(options.quality, 72)
        self.assertEqual(options.title, "file")
        self.assertEqual(values["quality"], 0)

    def test_user_defaults_and_extra_validation(self):
        values = build_defaults(supplied_context())
        with patch.object(defaults, "GLOBAL_DEFAULTS", values), \
             patch("xpra.config.io.read_xpra_defaults", return_value={"extra": "3", "title": "file"}) as read:
            options = make_defaults_struct(extras_defaults={"extra": 1}, extras_types={"extra": int}, username="tester", uid=123, gid=456)
        read.assert_called_once_with("tester", 123, 456)
        self.assertEqual(options.extra, 3)
        self.assertEqual(options.title, "file")

    def test_username_resolution(self):
        with patch.object(defaults, "GLOBAL_DEFAULTS", build_defaults(supplied_context())), \
             patch.object(defaults, "get_username_for_uid", return_value="resolved"), \
             patch("xpra.config.io.read_xpra_defaults", return_value={}) as read:
            make_defaults_struct(uid=123, gid=456)
        read.assert_called_once_with("resolved", 123, 456)

    def test_clone_alias(self):
        with patch.object(defaults, "GLOBAL_DEFAULTS", build_defaults(supplied_context())), \
             patch.dict(defaults.CLONES, {"quality": "quality-alias"}):
            self.assertEqual(dict_to_validated_config({"quality": "81"}).quality_alias, 81)

    def test_context_collection_uses_supplied_paths_and_commands(self):
        with patch.dict(os.environ, {"XPRA_CONF_DIR": "/supplied/config", "RPM_BUILD_ROOT": "/supplied/build"}), \
             patch.object(sys, "argv", ["/opt/xpra/bin/xpra"]), \
             patch.object(defaults.os.path, "exists", side_effect=lambda p: p == "/supplied/config"), \
             patch.object(defaults, "detect_xvfb_command", return_value=["test-vfb", "--flag"]) as xvfb, \
             patch.object(defaults, "detect_xdummy_command", return_value=["test-xdummy"]), \
             patch.object(defaults, "has_audio_support", return_value=False), \
             patch("xpra.platform.paths.get_download_dir", return_value="/supplied/downloads"):
            context = defaults.collect_defaults_context()
        self.assertEqual(context.xvfb, "test-vfb --flag")
        self.assertEqual(context.xdummy, "test-xdummy")
        self.assertEqual(context.download_dir, "/supplied/downloads")
        self.assertFalse(context.audio_support)
        self.assertEqual(xvfb.call_args.args, ("/supplied/config", "/opt/xpra/bin"))

    def test_missing_cwd_during_context_collection(self):
        with patch.object(defaults.os, "getcwd", side_effect=FileNotFoundError), \
             patch.object(defaults, "detect_xvfb_command", return_value=[]), \
             patch.object(defaults, "detect_xdummy_command", return_value=[]):
            self.assertEqual(defaults.collect_defaults_context().xvfb, "")

    def test_platform_helpers_and_unexpanded_paths(self):
        with patch.object(defaults, "POSIX", True), patch.object(defaults, "WIN32", False), patch.object(defaults, "OSX", False), \
             patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/run/test", "HOME": "/home/test"}):
            self.assertEqual(defaults.unexpand_all(["/run/test/xpra", "/home/test/.xpra", "/other"]),
                             ["$XDG_RUNTIME_DIR/xpra", "~/.xpra", "/other"])
            self.assertEqual(defaults.get_default_systemd_run(), "auto")
            self.assertIn("NO_AT_BRIDGE=1", defaults.get_default_env())
        for win32, osx in ((True, False), (False, True)):
            with patch.object(defaults, "WIN32", win32), patch.object(defaults, "OSX", osx):
                self.assertEqual(defaults.get_default_env(), ())
                self.assertEqual(defaults.get_default_start_env(), ())
                self.assertEqual(defaults.get_default_systemd_run(), "no")
        with patch.object(defaults.sys, "platform", "other"):
            self.assertEqual(defaults.get_default_seccomp(), "no")

    def test_audio_discovery_is_cached_and_handles_missing_parents(self):
        with patch.object(defaults, "_has_audio_support", None), patch("importlib.util.find_spec", side_effect=ImportError) as find:
            self.assertFalse(defaults.has_audio_support())
            self.assertFalse(defaults.has_audio_support())
        find.assert_called_once_with("xpra.audio")


if __name__ == "__main__":
    unittest.main()
