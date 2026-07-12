#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest
from unittest.mock import patch

from xpra import seccomp
from xpra.client.subsystem import encoding
from xpra.seccomp import draw as seccomp_draw
from xpra.seccomp import parse as seccomp_parse
from xpra.seccomp import rfb as seccomp_rfb


class SeccompTest(unittest.TestCase):

    @staticmethod
    def assert_decoder_exclusions(testcase: unittest.TestCase, filtered: tuple[str, ...]) -> None:
        testcase.assertGreaterEqual(len(filtered), 3)
        testcase.assertEqual(filtered[0], "all")
        testcase.assertEqual(set(filtered[1:]), {"no-nvdec", "no-vpl"})

    def test_filter_video_decoder_options(self):
        with patch.object(seccomp, "LINUX", True), \
             patch.object(seccomp, "ENABLED", True), \
             patch.object(seccomp, "is_available", return_value=True):
            filtered = encoding.Encodings.filter_video_decoder_options(type("C", (), {"video_decoders": ("all", "no-vpl")})())
        self.assert_decoder_exclusions(self, filtered)

    def test_install_draw_thread_noop_when_disabled(self):
        with patch.object(seccomp, "is_enabled", return_value=False):
            self.assertFalse(seccomp_draw.install_thread())

    def test_install_parse_thread_noop_when_disabled(self):
        with patch.object(seccomp_parse, "is_enabled", return_value=False):
            self.assertFalse(seccomp_parse.install_thread())

    def test_parse_syscalls_superset_of_draw(self):
        self.assertTrue(set(seccomp_draw.DRAW_SYSCALLS).issubset(set(seccomp_parse.PARSE_SYSCALLS)))
        self.assertIn("recvfrom", seccomp_parse.PARSE_SYSCALLS)

    def test_draw_blocks_file_syscalls(self):
        # the draw filter must not allow opening / creating / deleting files:
        for syscall in seccomp_draw.FILE_SYSCALLS:
            self.assertNotIn(syscall, seccomp_draw.DRAW_SYSCALLS)
        self.assertIn("openat", seccomp_draw.FILE_SYSCALLS)
        # the draw list is exactly the baseline minus the file syscalls:
        self.assertEqual(set(seccomp_draw.DRAW_SYSCALLS),
                         set(seccomp_draw.BASE_SYSCALLS) - set(seccomp_draw.FILE_SYSCALLS))

    def test_parse_and_rfb_keep_file_syscalls(self):
        # parse / rfb keep file access (larger lazy-import surface in packet handlers):
        for syscalls in (seccomp_parse.PARSE_SYSCALLS, seccomp_rfb.RFB_SYSCALLS):
            self.assertIn("openat", syscalls)
            self.assertIn("open", syscalls)

    def test_install_rfb_read_thread_noop_when_disabled(self):
        with patch.object(seccomp_rfb, "is_enabled", return_value=False):
            self.assertFalse(seccomp_rfb.install_thread())

    def test_rfb_syscalls_match_parse(self):
        self.assertEqual(seccomp_rfb.RFB_SYSCALLS, seccomp_parse.PARSE_SYSCALLS)

    def test_parse_seccomp_option(self):
        from xpra.scripts.main import parse_seccomp_option as p
        self.assertEqual(p(""), {})
        self.assertEqual(p("auto"), {})
        self.assertEqual(p("no"), {
            "XPRA_SECCOMP": "0",
            "XPRA_SECCOMP_DRAW": "0", "XPRA_SECCOMP_PARSE": "0", "XPRA_SECCOMP_RFB": "0",
        })
        self.assertEqual(p("default"), {
            "XPRA_SECCOMP_DRAW": "1", "XPRA_SECCOMP_DRAW_ACTION": "errno",
            "XPRA_SECCOMP_PARSE": "1", "XPRA_SECCOMP_PARSE_ACTION": "errno",
            "XPRA_SECCOMP_RFB": "1", "XPRA_SECCOMP_RFB_ACTION": "errno",
        })
        self.assertEqual(p("strict")["XPRA_SECCOMP_DRAW_ACTION"], "kill_process")
        # explicit thread list disables the unlisted threads and never sets the global flag:
        env = p("draw,parse:kill")
        self.assertNotIn("XPRA_SECCOMP", env)
        self.assertEqual(env["XPRA_SECCOMP_DRAW"], "1")
        self.assertNotIn("XPRA_SECCOMP_DRAW_ACTION", env)
        self.assertEqual(env["XPRA_SECCOMP_PARSE"], "1")
        self.assertEqual(env["XPRA_SECCOMP_PARSE_ACTION"], "kill")
        self.assertEqual(env["XPRA_SECCOMP_RFB"], "0")
        for bad in ("draw,bogus", "draw:nope", "xxx"):
            with self.assertRaises(ValueError):
                p(bad)

    def test_configure_seccomp_only_sets_unset_vars(self):
        from xpra.scripts import main
        keys = ("XPRA_SECCOMP", "XPRA_SECCOMP_DRAW", "XPRA_SECCOMP_DRAW_ACTION",
                "XPRA_SECCOMP_PARSE", "XPRA_SECCOMP_PARSE_ACTION",
                "XPRA_SECCOMP_RFB", "XPRA_SECCOMP_RFB_ACTION")
        with patch.dict(os.environ, {}, clear=False):
            for k in keys:
                os.environ.pop(k, None)
            # a value already present in the environment must be preserved:
            os.environ["XPRA_SECCOMP_DRAW_ACTION"] = "log"
            main.configure_seccomp("strict")
            self.assertEqual(os.environ["XPRA_SECCOMP_DRAW"], "1")
            self.assertEqual(os.environ["XPRA_SECCOMP_DRAW_ACTION"], "log")
            self.assertEqual(os.environ["XPRA_SECCOMP_PARSE_ACTION"], "kill_process")
            # empty value is a no-op:
            for k in keys:
                os.environ.pop(k, None)
            main.configure_seccomp("")
            self.assertNotIn("XPRA_SECCOMP_DRAW", os.environ)

    def test_load_all_codecs_runs_once(self):
        # the draw thread and the `load-all-codecs` thread may both call this,
        # so it must load the codecs exactly once (see draw-thread seccomp ordering):
        from threading import Event, Lock

        class FakeEncodings:
            def __init__(self):
                self._codecs_lock = Lock()
                self._codecs_loaded = Event()
                self.calls = 0

            def do_load_all_codecs(self) -> None:
                self.calls += 1

        fake = FakeEncodings()
        encoding.Encodings.load_all_codecs(fake)
        encoding.Encodings.load_all_codecs(fake)
        self.assertEqual(fake.calls, 1)
        self.assertTrue(fake._codecs_loaded.is_set())
        # a pre-set completion event short-circuits without loading:
        already = FakeEncodings()
        already._codecs_loaded.set()
        encoding.Encodings.load_all_codecs(already)
        self.assertEqual(already.calls, 0)

    def test_ensure_codecs_loaded_defers_to_draw_thread(self):
        # the invariant: when a draw thread exists, `ensure_codecs_loaded` must wait for
        # it rather than loading the codecs itself; without a draw thread, it loads them:
        from threading import Event

        class FakeEncodings:
            def __init__(self, draw_thread: bool):
                self._draw_thread = draw_thread
                self._codecs_loaded = Event()
                self.loads = 0

            def has_draw_thread(self) -> bool:
                return self._draw_thread

            def load_all_codecs(self) -> None:
                self.loads += 1
                self._codecs_loaded.set()

        # no draw thread: loads the codecs itself
        no_draw = FakeEncodings(draw_thread=False)
        encoding.Encodings.ensure_codecs_loaded(no_draw)
        self.assertEqual(no_draw.loads, 1)

        # draw thread present and codecs already loaded: returns without loading
        loaded = FakeEncodings(draw_thread=True)
        loaded._codecs_loaded.set()
        encoding.Encodings.ensure_codecs_loaded(loaded)
        self.assertEqual(loaded.loads, 0)

        # draw thread present but it never loads: falls back after the timeout
        with patch.object(encoding, "CODEC_LOAD_TIMEOUT", 0.01):
            stalled = FakeEncodings(draw_thread=True)
            encoding.Encodings.ensure_codecs_loaded(stalled)
            self.assertEqual(stalled.loads, 1)

    def test_get_save_to_file_gated_by_seccomp(self):
        from xpra.codecs import debug as codec_debug
        with patch.dict(os.environ, {"XPRA_SAVE_TO_FILE": "frame"}):
            with patch.object(seccomp, "is_enabled", return_value=True):
                self.assertEqual(codec_debug.get_save_to_file(), "")
            with patch.object(seccomp, "is_enabled", return_value=False):
                self.assertEqual(codec_debug.get_save_to_file(), "frame")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XPRA_SAVE_TO_FILE", None)
            with patch.object(seccomp, "is_enabled", return_value=True):
                self.assertEqual(codec_debug.get_save_to_file(), "")


if __name__ == "__main__":
    unittest.main()
