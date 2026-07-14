#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import subprocess
import sys
import textwrap
import unittest
from unittest.mock import patch

from xpra import seccomp
from xpra.client.subsystem import encoding
from xpra.seccomp import draw as seccomp_draw
from xpra.seccomp import menu as seccomp_menu
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

    def test_install_menu_thread_noop_when_disabled(self):
        with patch.object(seccomp_menu, "is_enabled", return_value=False):
            self.assertFalse(seccomp_menu.install_thread())

    def test_install_menu_thread_uses_masked_rules(self):
        with patch.object(seccomp_menu, "is_enabled", return_value=True), \
             patch("xpra.seccomp._native.install_filter") as install_filter:
            self.assertTrue(seccomp_menu.install_thread())
        install_filter.assert_called_once_with(
            seccomp_menu.MENU_SYSCALLS,
            seccomp_menu.get_action(),
            seccomp_menu.MENU_MASKED_RULES,
        )

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

    def test_menu_allows_only_masked_file_opens(self):
        self.assertNotIn("open", seccomp_menu.MENU_SYSCALLS)
        self.assertNotIn("openat", seccomp_menu.MENU_SYSCALLS)
        masked_syscalls = {rule[0] for rule in seccomp_menu.MENU_MASKED_RULES}
        self.assertEqual(masked_syscalls, {"open", "openat", "write", "writev"})
        for syscall in ("clone", "clone3", "mkdir", "rename", "unlink", "ftruncate", "write"):
            self.assertNotIn(syscall, seccomp_menu.MENU_SYSCALLS)

    @unittest.skipUnless(seccomp.is_available(), "native seccomp module is unavailable")
    def test_menu_native_read_only_policy(self):
        code = textwrap.dedent("""
            import os
            import subprocess
            import tempfile
            import threading

            from xpra.seccomp import _native
            from xpra.seccomp.menu import MENU_MASKED_RULES, MENU_SYSCALLS

            writable = tempfile.TemporaryFile()
            _native.install_filter(MENU_SYSCALLS, "errno", MENU_MASKED_RULES)
            with open("/etc/hosts", encoding="utf8") as stream:
                assert stream.read(1)

            def denied(fn):
                try:
                    fn()
                except (OSError, RuntimeError):
                    return
                raise AssertionError("operation unexpectedly allowed")

            denied(lambda: open("/tmp/xpra-seccomp-menu-write-test", "w"))
            denied(lambda: os.write(writable.fileno(), b"x"))
            denied(lambda: os.mkdir("/tmp/xpra-seccomp-menu-mkdir-test"))
            denied(lambda: subprocess.run(("true",), check=True))
            denied(lambda: threading.Thread(target=lambda: None).start())
        """)
        subprocess.run((sys.executable, "-c", code), check=True)

    def test_parse_blocks_file_syscalls(self):
        # every file/exec packet handler now runs off the parse thread, so the parse
        # filter drops file access too (see docs/Usage/Seccomp.md):
        for syscall in seccomp_draw.FILE_SYSCALLS:
            self.assertNotIn(syscall, seccomp_parse.PARSE_SYSCALLS)
        # parse is exactly the draw list plus the socket read syscalls:
        self.assertEqual(set(seccomp_parse.PARSE_SYSCALLS),
                         set(seccomp_draw.DRAW_SYSCALLS) | set(seccomp_parse.SOCKET_SYSCALLS))

    def test_rfb_keeps_file_syscalls(self):
        # the rfb read thread has not been walked, so it keeps file access for now:
        self.assertIn("openat", seccomp_rfb.RFB_SYSCALLS)
        self.assertIn("open", seccomp_rfb.RFB_SYSCALLS)
        # rfb is the full baseline (with files) plus the socket read syscalls:
        self.assertEqual(set(seccomp_rfb.RFB_SYSCALLS),
                         set(seccomp_draw.BASE_SYSCALLS) | set(seccomp_parse.SOCKET_SYSCALLS))

    def test_install_rfb_read_thread_noop_when_disabled(self):
        with patch.object(seccomp_rfb, "is_enabled", return_value=False):
            self.assertFalse(seccomp_rfb.install_thread())

    def test_rfb_is_superset_of_parse(self):
        # rfb keeps everything parse has, plus the file syscalls parse dropped:
        self.assertTrue(set(seccomp_parse.PARSE_SYSCALLS).issubset(set(seccomp_rfb.RFB_SYSCALLS)))
        self.assertTrue(set(seccomp_draw.FILE_SYSCALLS).issubset(set(seccomp_rfb.RFB_SYSCALLS)))

    def test_parse_seccomp_option(self):
        from xpra.scripts.main import parse_seccomp_option as p
        self.assertEqual(p(""), {})
        self.assertEqual(p("auto"), {})
        self.assertEqual(p("no"), {
            "XPRA_SECCOMP": "0",
            "XPRA_SECCOMP_DRAW": "0", "XPRA_SECCOMP_PARSE": "0", "XPRA_SECCOMP_RFB": "0",
            "XPRA_SECCOMP_MENU": "0",
        })
        self.assertEqual(p("default"), {
            "XPRA_SECCOMP_DRAW": "1", "XPRA_SECCOMP_DRAW_ACTION": "errno",
            "XPRA_SECCOMP_PARSE": "1", "XPRA_SECCOMP_PARSE_ACTION": "errno",
            "XPRA_SECCOMP_RFB": "1", "XPRA_SECCOMP_RFB_ACTION": "errno",
            "XPRA_SECCOMP_MENU": "1", "XPRA_SECCOMP_MENU_ACTION": "errno",
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
        self.assertEqual(env["XPRA_SECCOMP_MENU"], "0")
        for bad in ("draw,bogus", "draw:nope", "xxx"):
            with self.assertRaises(ValueError):
                p(bad)

    def test_configure_seccomp_only_sets_unset_vars(self):
        from xpra.scripts import main
        keys = ("XPRA_SECCOMP", "XPRA_SECCOMP_DRAW", "XPRA_SECCOMP_DRAW_ACTION",
                "XPRA_SECCOMP_PARSE", "XPRA_SECCOMP_PARSE_ACTION",
                "XPRA_SECCOMP_RFB", "XPRA_SECCOMP_RFB_ACTION")
        keys += ("XPRA_SECCOMP_MENU", "XPRA_SECCOMP_MENU_ACTION")
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
        # the decode thread and the `load-all-codecs` thread may both call this,
        # so it must load the codecs exactly once (see decode-thread seccomp ordering):
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

    def test_ensure_codecs_loaded_defers_to_decode_thread(self):
        # the invariant: when a decode thread exists, `ensure_codecs_loaded` must wait for
        # it rather than loading the codecs itself; without a decode thread, it loads them:
        from threading import Event

        class FakeEncodings:
            def __init__(self, decode_thread: bool):
                self._decode_thread = decode_thread
                self._codecs_loaded = Event()
                self.loads = 0

            def has_decode_thread(self) -> bool:
                return self._decode_thread

            def load_all_codecs(self) -> None:
                self.loads += 1
                self._codecs_loaded.set()

        # no decode thread: loads the codecs itself
        no_decode = FakeEncodings(decode_thread=False)
        encoding.Encodings.ensure_codecs_loaded(no_decode)
        self.assertEqual(no_decode.loads, 1)

        # decode thread present and codecs already loaded: returns without loading
        loaded = FakeEncodings(decode_thread=True)
        loaded._codecs_loaded.set()
        encoding.Encodings.ensure_codecs_loaded(loaded)
        self.assertEqual(loaded.loads, 0)

        # decode thread present but it never loads: falls back after the timeout
        with patch.object(encoding, "CODEC_LOAD_TIMEOUT", 0.01):
            stalled = FakeEncodings(decode_thread=True)
            encoding.Encodings.ensure_codecs_loaded(stalled)
            self.assertEqual(stalled.loads, 1)

    @staticmethod
    def _file_io_fake():
        # a minimal stand-in borrowing the real file I/O thread methods, so we can
        # verify received-file writes are handed off to the "file-io" thread:
        from queue import SimpleQueue
        from xpra.net import file_transfer as ft

        class Fake:
            schedule_file_io = ft.FileTransferHandler.schedule_file_io
            _ensure_file_io_thread = ft.FileTransferHandler._ensure_file_io_thread
            _file_io_loop = ft.FileTransferHandler._file_io_loop
            stop_file_io_thread = ft.FileTransferHandler.stop_file_io_thread

            def __init__(self):
                self._file_io_queue = SimpleQueue()
                self._file_io_thread = None
                self.ran: list = []

        return ft, Fake()

    def test_file_io_runs_off_the_parse_thread(self):
        import threading
        ft, fake = self._file_io_fake()

        def work(tag: str) -> None:
            fake.ran.append((tag, threading.current_thread().name))

        with patch.object(ft, "FILE_IO_THREAD", True), \
                patch.object(ft.GLib, "idle_add", side_effect=lambda fn, *a: fn(*a)) as idle_add:
            def parse() -> None:
                fake.schedule_file_io(work, "a")
                fake.schedule_file_io(work, "b")
            t = threading.Thread(target=parse, name="parse")
            t.start()
            t.join()
            fake.stop_file_io_thread()

        # thread creation was deferred to the main loop (idle_add), not the parse thread:
        self.assertTrue(idle_add.called)
        # both writes ran, in order, on the dedicated file-io thread (never "parse"):
        self.assertEqual([tag for tag, _ in fake.ran], ["a", "b"])
        for _, tname in fake.ran:
            self.assertEqual(tname, "file-io")
        # cleanly stopped:
        self.assertIsNone(fake._file_io_thread)

    def test_file_io_disabled_runs_inline(self):
        import threading
        ft, fake = self._file_io_fake()

        def work(tag: str) -> None:
            fake.ran.append((tag, threading.current_thread().name))

        with patch.object(ft, "FILE_IO_THREAD", False):
            def parse() -> None:
                fake.schedule_file_io(work, "a")
            t = threading.Thread(target=parse, name="parse")
            t.start()
            t.join()

        # disabled: the write runs inline on the calling (parse) thread, no thread spawned:
        self.assertEqual(fake.ran, [("a", "parse")])
        self.assertIsNone(fake._file_io_thread)

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
