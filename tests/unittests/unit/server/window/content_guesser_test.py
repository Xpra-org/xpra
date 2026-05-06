#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest
from unittest.mock import patch

from xpra.os_util import POSIX
from xpra.server.window import content_guesser
from xpra.server.window.content_guesser import (
    _load_dict_dirs,
    parse_content_types,
    parse_content_categories_file,
    guess_content_type_from_defs,
    _merge_defs,
)


class TestContentGuesser(unittest.TestCase):

    def test_merge_defs_nested_preserves_both_sides(self):
        # nested {prop: {key: value}} dicts must merge inner dicts,
        # not replace them — otherwise rules from one file/dir wipe another.
        target = {"class-instance": {"r1": "a", "r2": "b"}}
        source = {"class-instance": {"r3": "c"}}
        _merge_defs(target, source)
        self.assertEqual(target, {"class-instance": {"r1": "a", "r2": "b", "r3": "c"}})

    def test_merge_defs_inner_key_collision_source_wins(self):
        # when both sides define the same inner key, source replaces target —
        # this matches plain dict.update() semantics within a single tier (e.g. all files in /etc).
        target = {"class-instance": {"r1": "system"}}
        source = {"class-instance": {"r1": "user"}}
        _merge_defs(target, source)
        self.assertEqual(target, {"class-instance": {"r1": "user"}})

    def test_load_dict_dirs_preserves_system_prop_name_order(self):
        # regression: a user adding e.g. class-instance:kitty=text must not promote
        # class-instance ahead of system's title/role properties.
        # guess_content_type_from_defs iterates by property in dict order and stops
        # at the first match, so a Firefox Gmail window (matched by title=Gmail) must
        # still classify as text, not as browser via class-instance=firefox.
        with tempfile.TemporaryDirectory() as sysdir, tempfile.TemporaryDirectory() as userdir:
            os.makedirs(os.path.join(sysdir, "content-type"))
            os.makedirs(os.path.join(userdir, "content-type"))
            with open(os.path.join(sysdir, "content-type", "30_title.conf"), "w") as f:
                f.write("title:- Gmail -=text\n")
            with open(os.path.join(sysdir, "content-type", "50_class.conf"), "w") as f:
                f.write("class-instance:firefox=browser\n")
            with open(os.path.join(userdir, "content-type", "50.conf"), "w") as f:
                f.write("class-instance:kitty=text\n")

            with patch.object(content_guesser, "get_system_conf_dirs", return_value=[sysdir]), \
                    patch.object(content_guesser, "get_user_conf_dirs", return_value=[userdir]), \
                    patch.object(content_guesser, "POSIX", False):
                defs = _load_dict_dirs("content-type", parse_content_types)

            self.assertEqual(list(defs.keys()), ["title", "class-instance"])

            class FakeWindow:
                def get_property_names(self):
                    return ("title", "class-instance")

                def get_property(self, name):
                    return {"title": "Inbox - Gmail - user@gmail.com", "class-instance": "firefox"}[name]

            with patch.object(content_guesser, "content_type_defs", defs):
                self.assertEqual(guess_content_type_from_defs(FakeWindow()), "text")

    def test_merge_defs_flat_dict_replaces(self):
        # flat dicts (e.g. content-categories) keep simple update semantics.
        target = {"k1": "v1", "k2": "v2"}
        source = {"k2": "v2'", "k3": "v3"}
        _merge_defs(target, source)
        self.assertEqual(target, {"k1": "v1", "k2": "v2'", "k3": "v3"})

    def test_load_dict_dirs_merges_system_and_user_class_instance(self):
        # regression: a user class-instance file must not wipe the system class-instance file.
        with tempfile.TemporaryDirectory() as sysdir, tempfile.TemporaryDirectory() as userdir:
            os.makedirs(os.path.join(sysdir, "content-type"))
            os.makedirs(os.path.join(userdir, "content-type"))
            with open(os.path.join(sysdir, "content-type", "50_class.conf"), "w") as f:
                f.write("class-instance:xterm=text\n")
                f.write("class-instance:jetbrains.*=text\n")
            with open(os.path.join(userdir, "content-type", "50_extras.conf"), "w") as f:
                f.write("class-instance:kitty=text\n")

            with patch.object(content_guesser, "get_system_conf_dirs", return_value=[sysdir]), \
                    patch.object(content_guesser, "get_user_conf_dirs", return_value=[userdir]), \
                    patch.object(content_guesser, "POSIX", False):
                defs = _load_dict_dirs("content-type", parse_content_types)

            patterns = {regex_str for regex_str, _ in defs["class-instance"].values()}
            self.assertIn("xterm", patterns)
            self.assertIn("jetbrains.*", patterns)
            self.assertIn("kitty", patterns)

    def test_load_dict_dirs_later_system_dir_overrides_earlier(self):
        # regression: later system conf dirs (e.g. /etc/xdg/xpra) must be able to
        # override the same regex/key from earlier ones (e.g. /etc/xpra).
        # This matches the pre-fix behavior where the system-tier loop used dict.update.
        with tempfile.TemporaryDirectory() as sysdir1, tempfile.TemporaryDirectory() as sysdir2:
            os.makedirs(os.path.join(sysdir1, "content-type"))
            os.makedirs(os.path.join(sysdir2, "content-type"))
            with open(os.path.join(sysdir1, "content-type", "50.conf"), "w") as f:
                f.write("class-instance:foo=text\n")
            with open(os.path.join(sysdir2, "content-type", "50.conf"), "w") as f:
                f.write("class-instance:foo=video\n")

            with patch.object(content_guesser, "get_system_conf_dirs", return_value=[sysdir1, sysdir2]), \
                    patch.object(content_guesser, "get_user_conf_dirs", return_value=[]), \
                    patch.object(content_guesser, "POSIX", False):
                defs = _load_dict_dirs("content-type", parse_content_types)

            content_types = {ct for _, ct in defs["class-instance"].values()}
            self.assertEqual(content_types, {"video"})

    def test_load_dict_dirs_merges_two_system_files_with_same_prop(self):
        # regression: 90_fallback.conf's role rule must not wipe 10_role.conf's role rules.
        with tempfile.TemporaryDirectory() as sysdir:
            os.makedirs(os.path.join(sysdir, "content-type"))
            with open(os.path.join(sysdir, "content-type", "10_role.conf"), "w") as f:
                f.write("role:gimp-dock=text\n")
                f.write("role:gimp-toolbox=text\n")
            with open(os.path.join(sysdir, "content-type", "90_fallback.conf"), "w") as f:
                f.write("role:browser=browser\n")

            with patch.object(content_guesser, "get_system_conf_dirs", return_value=[sysdir]), \
                    patch.object(content_guesser, "get_user_conf_dirs", return_value=[]), \
                    patch.object(content_guesser, "POSIX", False):
                defs = _load_dict_dirs("content-type", parse_content_types)

            patterns = {regex_str for regex_str, _ in defs["role"].values()}
            self.assertEqual(patterns, {"gimp-dock", "gimp-toolbox", "browser"})

    @unittest.skipUnless(POSIX, "do_get_user_conf_dirs only returns literal '~' paths on POSIX")
    def test_load_dict_dirs_expands_tilde_in_user_dirs(self):
        # regression: do_get_user_conf_dirs returns paths with literal '~' (so multi-user
        # callers can osexpand against the target user). _load_dict_dir must expand '~'
        # against $HOME for the same-user case, otherwise os.path.exists silently rejects it.
        with tempfile.TemporaryDirectory() as homedir:
            os.makedirs(os.path.join(homedir, ".config", "xpra", "content-type"))
            with open(os.path.join(homedir, ".config", "xpra", "content-type", "50.conf"), "w") as f:
                f.write("class-instance:kitty=text\n")

            # patch getuid so the user-dirs branch is taken even when tests run as root
            with patch.dict(os.environ, {"HOME": homedir}, clear=False), \
                    patch.object(content_guesser, "get_system_conf_dirs", return_value=[]), \
                    patch.object(content_guesser, "get_user_conf_dirs", return_value=["~/.config/xpra"]), \
                    patch.object(content_guesser, "getuid", return_value=1000):
                defs = _load_dict_dirs("content-type", parse_content_types)

            patterns = {regex_str for regex_str, _ in defs["class-instance"].values()}
            self.assertEqual(patterns, {"kitty"})

    def test_load_dict_dirs_user_rule_overrides_broad_system_regex(self):
        # regression: a user override must take precedence over a broader system regex
        # earlier in iteration order. guess_content_type_from_defs stops on the first
        # match, so user rules must iterate before system rules.
        with tempfile.TemporaryDirectory() as sysdir, tempfile.TemporaryDirectory() as userdir:
            os.makedirs(os.path.join(sysdir, "content-type"))
            os.makedirs(os.path.join(userdir, "content-type"))
            with open(os.path.join(sysdir, "content-type", "50.conf"), "w") as f:
                # broad pattern first, specific second — file order matters
                f.write("class-instance:.*terminal.*=text\n")
                f.write("class-instance:gnome-terminal.*=text\n")
            with open(os.path.join(userdir, "content-type", "50.conf"), "w") as f:
                # user wants gnome-terminal classified as video
                f.write("class-instance:gnome-terminal.*=video\n")

            with patch.object(content_guesser, "get_system_conf_dirs", return_value=[sysdir]), \
                    patch.object(content_guesser, "get_user_conf_dirs", return_value=[userdir]), \
                    patch.object(content_guesser, "POSIX", False):
                defs = _load_dict_dirs("content-type", parse_content_types)

            class FakeWindow:
                def get_property_names(self):
                    return ("class-instance",)

                def get_property(self, name):
                    return "gnome-terminal-server"

            with patch.object(content_guesser, "content_type_defs", defs):
                ctype = guess_content_type_from_defs(FakeWindow())
            self.assertEqual(ctype, "video")

    def test_load_dict_dirs_flat_parser_unaffected(self):
        # content-categories parser produces a flat {category: type} dict; merge must still work.
        with tempfile.TemporaryDirectory() as sysdir, tempfile.TemporaryDirectory() as userdir:
            os.makedirs(os.path.join(sysdir, "content-categories"))
            os.makedirs(os.path.join(userdir, "content-categories"))
            with open(os.path.join(sysdir, "content-categories", "50.conf"), "w") as f:
                f.write("audio:audio\n")
                f.write("video:video\n")
            with open(os.path.join(userdir, "content-categories", "50.conf"), "w") as f:
                f.write("video:audio+video\n")
                f.write("game:video\n")

            with patch.object(content_guesser, "get_system_conf_dirs", return_value=[sysdir]), \
                    patch.object(content_guesser, "get_user_conf_dirs", return_value=[userdir]), \
                    patch.object(content_guesser, "POSIX", False):
                defs = _load_dict_dirs("content-categories", parse_content_categories_file)

            self.assertEqual(defs, {"audio": "audio", "video": "audio+video", "game": "video"})


def main():
    unittest.main()


if __name__ == "__main__":
    main()
