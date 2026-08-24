#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Yan Shoshitaishvili <yans@pwn.college>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import zlib
import fcntl
import signal
import struct
import logging
import termios
import tempfile
import unittest
import subprocess
from io import BytesIO
from base64 import b64decode
from unittest.mock import patch
from collections.abc import Sequence

from xpra.exit_codes import ExitCode
from xpra.util.env import OSEnvContext
from xpra.util.objects import typedict, AdHocStruct
from xpra.client.base import client as base_client
from xpra.client.gui import ui_client_base
from unit.test_util import silence_info, silence_warn
from unit.client.terminal.terminal_test_util import (
    TERMINAL_SIZE,
    FakeWindow, FakeWindowSubsystem, FakePointerSubsystem, FakeDisplaySubsystem, FakeKeyboardSubsystem,
)

try:
    from xpra.client.terminal import graphics
    from xpra.client.terminal import client as terminal_client
    from xpra.client.terminal import tty as terminal_tty
    from xpra.client.terminal.tty import TerminalOutput
    from xpra.client.terminal.input import (
        KeyEvent, MouseEvent, GraphicsResponse, KeyboardFlagsResponse, TextReport,
    )
    from xpra.client.terminal.subsystem.display import TerminalDisplayClient
except ImportError:
    graphics = None
    terminal_client = None
    terminal_tty = None
    TerminalOutput = None
    KeyEvent = MouseEvent = GraphicsResponse = KeyboardFlagsResponse = TextReport = None
    TerminalDisplayClient = None

# `GLib.IO_IN`, spelled out so that this test package never imports `gi`:
IO_IN = 1

# what `xpra.scripts.main.make_client` must end up with for `--backend=terminal`,
# run in a subprocess because it poisons the `gi.repository` Gtk modules process wide:
MAKE_CLIENT_SCRIPT = """
from xpra.scripts.config import make_defaults_struct
from xpra.scripts.main import make_client
opts = make_defaults_struct()
opts.backend = "terminal"
client = make_client(opts)
client.init(opts)
client.init_ui(opts)
from xpra.client.base import features
print("RESULT opengl=%s systray=%s progress=%s subsystems=,%s,"
      % (features.opengl, features.systray, features.progress, ",".join(sorted(client.subsystems))))
print("OPTIONS opengl=%r system_tray=%r splash=%r" % (opts.opengl, opts.system_tray, opts.splash))
client.cleanup()
"""


class FakeEncodingSubsystem:
    def __init__(self, encodings=("png", "rgb")):
        self.encodings = encodings

    def get_encodings(self):
        return self.encodings


@unittest.skipIf(terminal_client is None, "the terminal client component is not available")
class TerminalClientTest(unittest.TestCase):
    """
    Composition test for `XpraTerminalClient`: the real client object, with the
    terminal size injected so that no tty is ever needed.
    """

    def setUp(self):
        super().setUp()
        # the terminal client never has an X11 display source, and the platform
        # queries used when the client starts up must not go looking for one:
        env_context = OSEnvContext(XPRA_NOX11="1")
        env_context.__enter__()
        self.addCleanup(env_context.__exit__)

    def make_client(self, terminal_size=TERMINAL_SIZE):
        with silence_info(ui_client_base):
            client = terminal_client.XpraTerminalClient()
        self.addCleanup(client.cleanup)
        client.terminal_size = terminal_size
        # the mouse coordinate base is detected from the terminal the client runs in,
        # which must not decide what these tests assert:
        client.mouse_base = 1
        return client

    def make_output(self, client):
        buf = BytesIO()
        client.terminal_output = TerminalOutput(buf)
        return buf

    ######################################################################
    # composition

    def test_subsystem_substitution(self):
        client = self.make_client()
        display = client.get_subsystem("display")
        self.assertIsNotNone(display, "no `display` subsystem composed")
        self.assertIsInstance(display, TerminalDisplayClient)
        # every substitution must keep the subsystem prefix:
        self.assertEqual(type(display).PREFIX, "display")
        if clipboard := client.get_subsystem("clipboard"):
            from xpra.client.terminal.subsystem.clipboard import TerminalClipboardClient
            self.assertIsInstance(clipboard, TerminalClipboardClient)
            self.assertEqual(type(clipboard).PREFIX, "clipboard")

    def test_keyboard_helper_class_is_installed(self):
        client = self.make_client()
        from xpra.client.terminal.keyboard import TerminalKeyboardHelper
        kb = client.get_subsystem("keyboard")
        self.assertIsNotNone(kb, "no `keyboard` subsystem composed")
        # it must be set before `init_ui` instantiates it:
        self.assertIs(kb.helper_class, TerminalKeyboardHelper)

    def test_client_identity(self):
        client = self.make_client()
        self.assertEqual(client.client_toolkit(), "terminal")
        self.assertEqual(client.client_type, "terminal")
        self.assertEqual(repr(client), "XpraTerminalClient")

    def test_scheduler_is_the_glib_one(self):
        client = self.make_client()
        # the base class' stubs return `None` silently, which would hang the client:
        for name in ("idle_add", "timeout_add", "source_remove"):
            self.assertTrue(callable(getattr(client, name)))
        timer = client.timeout_add(10000, print)
        self.assertTrue(timer)
        client.source_remove(timer)

    ######################################################################
    # display subsystem

    def test_display_real_values(self):
        client = self.make_client()
        display = client.get_subsystem("display")
        self.assertEqual(display.get_root_size(), (1000, 600))
        self.assertEqual(tuple(display.get_screen_sizes()), ((1000, 600), ))
        self.assertEqual(tuple(display.get_screen_sizes(2, 2)), ((500, 300), ))
        monitors = display.get_monitors_info()
        self.assertIsInstance(monitors, dict)
        self.assertEqual(monitors[0]["geometry"], (0, 0, 1000, 600))
        self.assertEqual(monitors[0]["name"], "terminal")
        self.assertTrue(display.has_transparency())

    def test_default_terminal_geometry(self):
        # a terminal which does not report its pixel size:
        client = self.make_client((80, 24, 0, 0))
        self.assertEqual(client.cell_size(),
                         (terminal_client.DEFAULT_CELL_WIDTH, terminal_client.DEFAULT_CELL_HEIGHT))
        self.assertEqual(client.terminal_pixel_size(),
                         (80 * terminal_client.DEFAULT_CELL_WIDTH, 24 * terminal_client.DEFAULT_CELL_HEIGHT))
        # nothing known at all:
        client.terminal_size = (0, 0, 0, 0)
        self.assertEqual(client.get_subsystem("display").get_root_size(),
                         (terminal_client.DEFAULT_COLUMNS * terminal_client.DEFAULT_CELL_WIDTH,
                          terminal_client.DEFAULT_ROWS * terminal_client.DEFAULT_CELL_HEIGHT))

    def test_cell_size(self):
        client = self.make_client()
        self.assertEqual(client.cell_size(), (10, 20))
        self.assertEqual(client.terminal_pixel_size(), (1000, 600))

    def test_the_pixel_size_is_taken_from_the_terminal_reports(self):
        # a pty which only forwards rows and columns (`docker exec` and friends):
        client = self.make_client((80, 24, 0, 0))
        display = client.subsystems["display"] = FakeDisplaySubsystem()
        # `CSI 16 t` is answered with `CSI 6 ; <height> ; <width> t`:
        client.process_input_events([TextReport(6, (20, 10))])
        self.assertEqual(client.terminal_size, (80, 24, 800, 480))
        self.assertEqual(client.cell_size(), (10, 20))
        self.assertEqual(client.terminal_pixel_size(), (800, 480))
        self.assertEqual(display.screen_changes, 1)
        # and the pixel size we now have wins over any later report:
        client.process_input_events([TextReport(6, (40, 20))])
        self.assertEqual(client.terminal_size, (80, 24, 800, 480))
        self.assertEqual(display.screen_changes, 1)

    def test_the_text_area_report_is_used_too(self):
        client = self.make_client((80, 24, 0, 0))
        # `CSI 14 t` is answered with `CSI 4 ; <height> ; <width> t`:
        client.process_input_events([TextReport(4, (480, 800))])
        self.assertEqual(client.terminal_size, (80, 24, 800, 480))

    def test_unusable_terminal_reports_are_ignored(self):
        client = self.make_client((80, 24, 0, 0))
        display = client.subsystems["display"] = FakeDisplaySubsystem()
        for report in (TextReport(6, ()), TextReport(6, (0, 10)), TextReport(4, (10, 10)),
                       TextReport(8, (20, 10))):
            client.process_input_events([report])
            self.assertEqual(client.terminal_size, (80, 24, 0, 0), f"{report} was used")
        # and a report which arrives when nothing is known cannot be used either:
        client.terminal_size = (0, 0, 0, 0)
        client.process_input_events([TextReport(6, (20, 10))])
        self.assertEqual(client.terminal_size, (0, 0, 0, 0))
        self.assertEqual(display.screen_changes, 0)

    ######################################################################
    # encodings

    def test_get_encodings(self):
        client = self.make_client()
        # `xpra.scripts.main.handle_client_encoding_option` calls this:
        self.assertIsInstance(client.get_encodings(), Sequence)
        client.subsystems["encoding"] = FakeEncodingSubsystem()
        self.assertEqual(tuple(client.get_encodings()), ("png", "rgb"))
        client.subsystems.pop("encoding")
        self.assertEqual(tuple(client.get_encodings()), ())

    ######################################################################
    # the rest of the frontend contract

    def test_frontend_contract(self):
        client = self.make_client()
        self.assertIsNone(client.get_group_leader(1, typedict(), False))
        self.assertEqual(tuple(client.get_notifier_classes()), ())
        self.assertEqual(tuple(client.get_tray_classes()), ())
        self.assertEqual(tuple(client.get_system_tray_classes()), ())
        self.assertIsNone(client.get_menu_helper())
        self.assertIsNone(client.get_menu_helper_class())
        self.assertEqual(client.get_gl_client_window_module("yes"), ({}, None))
        self.assertEqual(client.get_xdpi(), 96)
        self.assertEqual(client.get_ydpi(), 96)
        self.assertEqual(client.get_mouse_position(), (0, 0))
        self.assertEqual(client.get_raw_mouse_position(), (0, 0))
        self.assertEqual(tuple(client.get_current_modifiers()), ())

    def test_the_system_tray_is_turned_off_before_the_subsystems_are_initialized(self):
        client = self.make_client()
        opts = AdHocStruct()
        opts.system_tray = True
        seen = []
        # `UIXpraClient.init` initializes every composed subsystem, which needs a full
        # options object: record what it would have been given instead of running it
        saved = ui_client_base.UIXpraClient.init
        ui_client_base.UIXpraClient.init = lambda self, o: seen.append(o.system_tray)
        try:
            client.init(opts)
        finally:
            ui_client_base.UIXpraClient.init = saved
        self.assertEqual(seen, [False], "the system tray was still enabled when the subsystems were initialized")
        self.assertFalse(opts.system_tray)
        self.assertEqual(client.headerbar, "no")

    def test_keyboard_sync_is_turned_off_before_the_subsystems_are_initialized(self):
        # with sync enabled the server holds each key down between our press and
        # release packets, and the rollover of ordinary fast typing then collapses
        # repeated letters and mispairs the releases:
        client = self.make_client()
        opts = AdHocStruct()
        opts.keyboard_sync = True
        seen = []
        saved = ui_client_base.UIXpraClient.init
        ui_client_base.UIXpraClient.init = lambda self, o: seen.append(o.keyboard_sync)
        try:
            client.init(opts)
        finally:
            ui_client_base.UIXpraClient.init = saved
        self.assertEqual(seen, [False], "keyboard sync was still enabled when the subsystems were initialized")

    def test_desktop_metadata_is_requested(self):
        # the server only sends the window metadata a client declares support
        # for, and the default list does not include the "desktop" flag which
        # marks the whole-display windows of `start-desktop` sessions
        # (`fit_to_terminal` resizes those to track the terminal):
        client = self.make_client()
        supported = client.hello_extra.get("metadata.supported", ())
        self.assertIn("desktop", supported)
        self.assertIn("title", supported)

    def test_tray_windows_are_ignored(self):
        client = self.make_client()
        window_sub = client.get_subsystem("window")
        if window_sub is None:
            self.skipTest("no `window` subsystem composed")
        # the client has no way of creating a tray, so it must not claim it has:
        self.assertFalse(getattr(window_sub, "client_supports_system_tray", False))
        self.assertFalse(window_sub.get_caps().get("system_tray", False))
        # and a tray window sent by a server anyway is ignored rather than fatal:
        from xpra.net.common import Packet
        from xpra.client.subsystem.window import manager as window_manager
        metadata = {"tray": True, "title": "nm-applet"}
        with silence_warn(window_manager):
            self.assertIsNone(window_sub._process_window_create(
                Packet("window-create", 10, 0, 0, 24, 24, metadata)))

    def test_make_client_never_looks_at_the_x11_display(self):
        # this is what `xpra.scripts.main.make_client` calls, and the only thing
        # keeping the display subsystem's probes away from the X11 bindings:
        with OSEnvContext():
            os.environ.pop("XPRA_NOX11", None)
            os.environ["DISPLAY"] = ":0"
            with silence_info(ui_client_base):
                client = terminal_client.make_client(None)
            self.addCleanup(client.cleanup)
            self.assertIsInstance(client, terminal_client.XpraTerminalClient)
            self.assertEqual(os.environ.get("XPRA_NOX11"), "1")

    def test_main_make_client_composes_no_gui_only_subsystem(self):
        # `make_client` poisons the `gi.repository` Gtk modules process wide,
        # and the OpenGL warning this pins is emitted on the terminal we run in:
        proc = subprocess.run([sys.executable, "-c", MAKE_CLIENT_SCRIPT],
                              capture_output=True, text=True, check=False, timeout=120)
        output = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, output)
        self.assertIn("RESULT opengl=False systray=False progress=False", output)
        self.assertIn("OPTIONS opengl='no' system_tray=False splash=False", output)
        subsystems = output.split("subsystems=")[1].split("\n")[0]
        for name in ("opengl", "progress"):
            self.assertNotIn(f",{name},", subsystems, f"the {name!r} subsystem was composed")
        # nothing may be printed on the terminal before the client even starts:
        self.assertNotIn("OpenGL", output)

    def test_client_window_classes(self):
        client = self.make_client()
        from xpra.client.terminal.window import ClientWindow
        self.assertEqual(tuple(client.get_client_window_classes((0, 0, 1, 1), typedict(), False)),
                         (ClientWindow, ))

    def test_grabs_are_recorded_only(self):
        client = self.make_client()
        window = client.subsystems["window"] = FakeWindowSubsystem()
        client.window_grab(5, None)
        self.assertEqual(window._window_with_grab, 5)
        client.window_ungrab()
        self.assertEqual(window._window_with_grab, 0)

    def test_get_info(self):
        client = self.make_client()
        # `merge_dicts` warns because two composed subsystems both use a "network" key,
        # which is a pre-existing quirk of `XpraClientBase.get_info`, not of this client:
        from xpra.util import io as util_io
        util_io.get_util_logger()
        with silence_warn(util_io, "util_logger"):
            info = client.get_info()
        self.assertEqual(info["terminal"]["size"], TERMINAL_SIZE)
        self.assertEqual(info["terminal"]["cell-size"], (10, 20))
        self.assertEqual(info["terminal"]["mouse-coordinate-base"], 1)
        self.assertFalse(info["terminal"]["graphics"])

    ######################################################################
    # the terminal is left alone until we enter terminal mode

    def test_terminal_untouched_before_terminal_mode(self):
        client = self.make_client()
        self.assertIsNone(client.terminal_output)
        self.assertIsNone(client.terminal_context)
        # nothing may be written, and nothing may raise:
        client.write_terminal(b"hello")
        client.write_osc52(b"hello")
        client.window_bell(None, 0, 0, 0, 0, 0, 0, "")
        client.update_cursor()

    def test_write_osc52_and_bell(self):
        client = self.make_client()
        buf = self.make_output(client)
        client.write_osc52(b"\x1b]52;c;YQ==\x07")
        client.window_bell(None, 0, 100, 1000, 100, 0, 0, "TerminalBell")
        self.assertEqual(buf.getvalue(), b"\x1b]52;c;YQ==\x07\x07")

    ######################################################################
    # the kitty graphics protocol probe

    def _pin_shm(self, value: int):
        saved = terminal_client.SHM
        terminal_client.SHM = value
        self.addCleanup(setattr, terminal_client, "SHM", saved)

    def test_shm_probe_follows_the_graphics_probe(self):
        from xpra.client.terminal.shm import ShmWriter
        if not ShmWriter.available():
            self.skipTest("no writable shared memory directory")
        self._pin_shm(-1)
        client = self.make_client()
        buf = self.make_output(client)
        client.handle_graphics_response(GraphicsResponse(terminal_client.PROBE_IMAGE_ID, True, "OK"))
        self.assertTrue(client.shm_probe_sent)
        self.assertFalse(client.shm_ok)
        data = buf.getvalue()
        self.assertIn(b"a=q,i=%i,f=32,s=1,v=1,t=s,S=4" % terminal_client.PROBE_SHM_IMAGE_ID, data)
        # the probe object holds the single test pixel:
        writer = client.shm_writer
        self.assertEqual(len(writer.pending), 1)
        path = writer.path(writer.pending[0])
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"\x00\x00\x00\x00")
        # the terminal read (and unlinked) the object and answers OK:
        os.unlink(path)
        client.handle_graphics_response(GraphicsResponse(terminal_client.PROBE_SHM_IMAGE_ID, True, "OK"))
        self.assertTrue(client.shm_ok)
        self.assertFalse(client.shm_probe_sent)
        # pixels now go through shared memory:
        name = client.shm_transfer(b"\x01\x02\x03\x04")
        self.assertTrue(name)
        with open(writer.path(name), "rb") as f:
            self.assertEqual(f.read(), b"\x01\x02\x03\x04")

    def test_shm_probe_rejection_cleans_up(self):
        from xpra.client.terminal.shm import ShmWriter
        if not ShmWriter.available():
            self.skipTest("no writable shared memory directory")
        self._pin_shm(-1)
        client = self.make_client()
        self.make_output(client)
        client.handle_graphics_response(GraphicsResponse(terminal_client.PROBE_IMAGE_ID, True, "OK"))
        writer = client.shm_writer
        path = writer.path(writer.pending[0])
        # a terminal on another machine cannot open our shared memory:
        client.handle_graphics_response(GraphicsResponse(terminal_client.PROBE_SHM_IMAGE_ID, False, "EBADF"))
        self.assertFalse(client.shm_ok)
        self.assertIsNone(client.shm_writer)
        self.assertFalse(os.path.exists(path))
        self.assertEqual(client.shm_transfer(b"data"), "")

    def test_shm_can_be_forced_off(self):
        self._pin_shm(0)
        client = self.make_client()
        buf = self.make_output(client)
        client.handle_graphics_response(GraphicsResponse(terminal_client.PROBE_IMAGE_ID, True, "OK"))
        self.assertFalse(client.shm_probe_sent)
        self.assertFalse(client.shm_ok)
        self.assertNotIn(b"t=s", buf.getvalue())

    def test_full_retransmits_are_the_default(self):
        # kitty drops chunked `a=f` frame edits which directly follow another
        # chunked graphics command (accepted, never rendered), so out of the
        # box every update re-sends the whole image:
        client = self.make_client()
        buf = self.make_output(client)
        client.handle_graphics_response(GraphicsResponse(terminal_client.PROBE_IMAGE_ID, True, "OK"))
        self.assertTrue(client.graphics_ok)
        self.assertFalse(client.frame_probe_sent)
        self.assertFalse(client.frame_edits)
        # no frame edit probe went out, the test image is freed straight away:
        data = buf.getvalue()
        self.assertNotIn(b"a=f", data)
        self.assertIn(b"a=d,d=I", data)

    def _force_frame_edit_probe(self):
        saved = terminal_client.FRAME_EDITS
        terminal_client.FRAME_EDITS = -1
        self.addCleanup(setattr, terminal_client, "FRAME_EDITS", saved)

    def test_graphics_probe_accepted(self):
        # pin the probe mode, regardless of the XPRA_TERMINAL_FRAME_EDITS environment:
        self._force_frame_edit_probe()
        client = self.make_client()
        buf = self.make_output(client)
        window_sub = FakeWindowSubsystem()
        client.subsystems["window"] = window_sub
        window = FakeWindow(1, (0, 0), (100, 100))
        window_sub.windows[1] = window
        client.handle_graphics_response(GraphicsResponse(terminal_client.PROBE_IMAGE_ID, True, "OK"))
        self.assertTrue(client.graphics_ok)
        # the client then probes for `a=f` frame edit support:
        # a real 1x1 image is stored under the probe id and a frame edit is attempted on it:
        probe_id = terminal_client.PROBE_IMAGE_ID
        data = buf.getvalue()
        self.assertIn(b"a=t,q=2,i=%i" % probe_id, data)
        self.assertIn(b"a=f,i=%i" % probe_id, data)
        self.assertTrue(client.frame_probe_sent)
        # every window mapped before the terminal answered is placed again:
        self.assertEqual(window.placements, 1)
        # the terminal answers the frame edit probe:
        client.handle_graphics_response(GraphicsResponse(probe_id, True, "OK"))
        self.assertTrue(client.frame_edits)
        self.assertFalse(client.frame_probe_sent)
        # the test image is freed again:
        self.assertIn(b"a=d,d=I", buf.getvalue())

    def test_frame_edits_rejected(self):
        # pin the probe mode, regardless of the XPRA_TERMINAL_FRAME_EDITS environment:
        self._force_frame_edit_probe()
        client = self.make_client()
        buf = self.make_output(client)
        probe_id = terminal_client.PROBE_IMAGE_ID
        client.handle_graphics_response(GraphicsResponse(probe_id, True, "OK"))
        self.assertTrue(client.frame_probe_sent)
        # a terminal without `a=f` support rejects the frame edit:
        client.handle_graphics_response(GraphicsResponse(probe_id, False, "ENOTSUP"))
        self.assertFalse(client.frame_edits)
        self.assertFalse(client.frame_probe_sent)
        self.assertIn(b"a=d,d=I", buf.getvalue())

    def test_frame_edit_probe_timeout(self):
        # pin the probe mode, regardless of the XPRA_TERMINAL_FRAME_EDITS environment:
        self._force_frame_edit_probe()
        client = self.make_client()
        self.make_output(client)
        probe_id = terminal_client.PROBE_IMAGE_ID
        client.handle_graphics_response(GraphicsResponse(probe_id, True, "OK"))
        self.assertTrue(client.frame_probe_sent)
        # a terminal which ignores the frame edit never answers:
        client.frame_probe_timeout()
        self.assertFalse(client.frame_edits)
        self.assertFalse(client.frame_probe_sent)

    def test_graphics_response_for_another_image_is_ignored(self):
        client = self.make_client()
        self.make_output(client)
        client.handle_graphics_response(GraphicsResponse(1, True, "OK"))
        self.assertFalse(client.graphics_ok)

    def test_graphics_probe_timeout_quits(self):
        client = self.make_client()
        self.make_output(client)
        client.probe_timer = 0
        with silence_warn(base_client):
            client.graphics_probe_timeout()
        self.assertEqual(client.exit_code, ExitCode.UNSUPPORTED)
        self.assertFalse(client.graphics_ok)
        # quitting restores the terminal:
        self.assertIsNone(client.terminal_output)

    def test_graphics_probe_rejected_quits(self):
        client = self.make_client()
        self.make_output(client)
        with silence_warn(base_client):
            client.handle_graphics_response(GraphicsResponse(terminal_client.PROBE_IMAGE_ID, False, "ENOTSUP:nope"))
        self.assertEqual(client.exit_code, ExitCode.UNSUPPORTED)

    ######################################################################
    # input routing

    def test_keyboard_flags_response(self):
        client = self.make_client()
        self.assertFalse(client.kitty_keyboard)
        client.process_input_events([KeyboardFlagsResponse(15)])
        self.assertTrue(client.kitty_keyboard)
        client.process_input_events([KeyboardFlagsResponse(1)])
        self.assertFalse(client.kitty_keyboard)

    def make_input_client(self):
        client = self.make_client()
        self.make_output(client)
        window_sub = FakeWindowSubsystem()
        client.subsystems["window"] = window_sub
        client.subsystems["pointer"] = FakePointerSubsystem()
        client.subsystems["keyboard"] = FakeKeyboardSubsystem()
        return client, window_sub

    def add_window(self, client, window_sub, wid, pos, size, override_redirect=False):
        window = FakeWindow(wid, pos, size, override_redirect)
        window_sub.windows[wid] = window
        client._new_window(None, window)
        # a real `ClientWindow` calls this right after sending `map-window`:
        client.window_mapped(window)
        return window

    def test_input_flush_is_only_armed_for_a_lone_byte(self):
        # a stalled multi-byte sequence must be waited for, not flushed:
        # flushing it drops the key and mistypes its remainder as garbage
        # (this is what broke fast typing over a congested link):
        client, _ = self.make_input_client()
        client.input_parser.feed(b"\x1b[")
        client.schedule_input_flush()
        self.assertEqual(client.input_flush_timer, 0)
        # the sequence completes and parses as one event, nothing was lost:
        events = client.input_parser.feed(b"97u")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].code, ord("a"))
        # a lone `ESC` is the one case the timer is for:
        client.input_parser.feed(b"\x1b")
        client.schedule_input_flush()
        self.assertNotEqual(client.input_flush_timer, 0)
        client.source_remove(client.input_flush_timer)
        client.input_flush_timer = 0

    def test_input_flush_does_nothing_for_a_partial_sequence(self):
        client, window_sub = self.make_input_client()
        self.add_window(client, window_sub, 1, (0, 0), (100, 100))
        kb = client.subsystems["keyboard"]
        client.input_parser.feed(b"\x1b[9")
        client.flush_terminal_input()
        self.assertEqual(kb.actions, [])
        self.assertEqual(client.input_parser.pending, 3)

    def test_input_flush_converts_a_lone_escape(self):
        client, window_sub = self.make_input_client()
        self.add_window(client, window_sub, 1, (0, 0), (100, 100))
        kb = client.subsystems["keyboard"]
        # the client samples `terminal_fd` from stdin at construction time,
        # and the test runner's stdin must not decide whether the flush runs:
        client.terminal_fd = -1
        client.input_parser.feed(b"\x1b")
        client.flush_terminal_input()
        # legacy mode synthesizes the release, so press + release:
        self.assertEqual([(a[1], a[2]) for a in kb.actions], [("Escape", True), ("Escape", False)])
        self.assertEqual(client.input_parser.pending, 0)

    def test_input_flush_defers_to_pending_terminal_input(self):
        # when the rest of the sequence is already waiting on the fd,
        # the timer must not flush the `ESC` out from under it:
        client, window_sub = self.make_input_client()
        self.add_window(client, window_sub, 1, (0, 0), (100, 100))
        kb = client.subsystems["keyboard"]
        rfd, wfd = os.pipe()
        try:
            client.terminal_fd = rfd
            os.write(wfd, b"[97u")
            client.input_parser.feed(b"\x1b")
            client.flush_terminal_input()
            self.assertEqual(kb.actions, [])
            self.assertEqual(client.input_parser.pending, 1)
        finally:
            client.terminal_fd = -1
            os.close(rfd)
            os.close(wfd)

    def test_lost_modifier_release_is_synthesized(self):
        # replay of a real kitty-on-Wayland trace: ctrl pressed, its release
        # swallowed by the compositor (alt-tab), then plain letters - without
        # the reconciliation every letter becomes a control chord on the server
        # (`a` = beginning-of-line, `p` = previous-history: mangled typing):
        client, window_sub = self.make_input_client()
        self.add_window(client, window_sub, 1, (0, 0), (100, 100))
        kb = client.subsystems["keyboard"]
        client.kitty_keyboard = True
        client.process_input_events([KeyEvent(57442, mods=4, event_type=1)])       # Control_L press
        self.assertEqual(client._mod_keys_down, {57442: 4})
        # a chorded letter while ctrl is genuinely held is left alone:
        client.process_input_events([KeyEvent(ord("c"), mods=4, event_type=1, text=""),
                                     KeyEvent(ord("c"), mods=4, event_type=3)])
        self.assertNotIn(("Control_L", False), [(a[1], a[2]) for a in kb.actions])
        # the release never arrives, the next letter reports ctrl as gone:
        kb.actions.clear()
        client.process_input_events([KeyEvent(ord("a"), event_type=1, text="a")])
        names = [(a[1], a[2]) for a in kb.actions]
        self.assertEqual(names[0], ("Control_L", False), names)
        self.assertEqual(names[1], ("a", True), names)
        self.assertEqual(client._mod_keys_down, {})

    def test_modifier_repeat_without_press_is_tracked(self):
        # kitty can send repeat events for a modifier whose press we never saw:
        client, window_sub = self.make_input_client()
        self.add_window(client, window_sub, 1, (0, 0), (100, 100))
        kb = client.subsystems["keyboard"]
        client.kitty_keyboard = True
        client.process_input_events([KeyEvent(57443, mods=2, event_type=2)])       # Alt_L repeat
        self.assertEqual(client._mod_keys_down, {57443: 2})
        kb.actions.clear()
        client.process_input_events([KeyEvent(ord("x"), event_type=1, text="x")])
        self.assertEqual([(a[1], a[2]) for a in kb.actions], [("Alt_L", False), ("x", True)])

    def test_both_control_keys_held(self):
        client, window_sub = self.make_input_client()
        self.add_window(client, window_sub, 1, (0, 0), (100, 100))
        kb = client.subsystems["keyboard"]
        client.kitty_keyboard = True
        client.process_input_events([KeyEvent(57442, mods=4, event_type=1),
                                     KeyEvent(57448, mods=4, event_type=1)])
        # releasing one of them keeps the bit set - nothing must be synthesized:
        client.process_input_events([KeyEvent(57442, mods=4, event_type=3)])
        self.assertEqual(client._mod_keys_down, {57448: 4})
        kb.actions.clear()
        client.process_input_events([KeyEvent(ord("y"), mods=4, event_type=1, text="")])
        self.assertNotIn(("Control_R", False), [(a[1], a[2]) for a in kb.actions])
        # once the bit clears, the remaining key is released:
        client.process_input_events([KeyEvent(ord("y"), event_type=3)])
        self.assertIn(("Control_R", False), [(a[1], a[2]) for a in kb.actions])

    def test_held_modifiers_are_released_on_the_way_out(self):
        client, window_sub = self.make_input_client()
        self.add_window(client, window_sub, 1, (0, 0), (100, 100))
        kb = client.subsystems["keyboard"]
        client.kitty_keyboard = True
        client.process_input_events([KeyEvent(57442, mods=4, event_type=1)])
        kb.actions.clear()
        client.stop_terminal_mode()
        self.assertEqual([(a[1], a[2]) for a in kb.actions], [("Control_L", False)])
        self.assertEqual(client._mod_keys_down, {})

    def test_std_streams_are_sealed(self):
        # anything writing to fd 1 or fd 2 during terminal mode corrupts the
        # escape stream and the terminal drops the graphics command it was
        # parsing - both fds must point away from the tty while sealed:
        client = self.make_client()
        sink = tempfile.NamedTemporaryFile(delete=False)
        self.addCleanup(os.unlink, sink.name)
        handler = AdHocStruct()
        handler.baseFilename = sink.name
        client.log_handler = handler
        saved = terminal_client.is_a_tty
        terminal_client.is_a_tty = lambda *_: True
        self.addCleanup(setattr, terminal_client, "is_a_tty", saved)
        client.seal_std_streams()
        try:
            self.assertIsNotNone(client._sealed_fds)
            os.write(1, b"STRAY-STDOUT\n")
            os.write(2, b"STRAY-STDERR\n")
        finally:
            client.unseal_std_streams()
        self.assertIsNone(client._sealed_fds)
        with open(sink.name, "rb") as f:
            data = f.read()
        self.assertIn(b"STRAY-STDOUT", data)
        self.assertIn(b"STRAY-STDERR", data)
        # sealing twice and unsealing twice must be safe:
        client.unseal_std_streams()

    def test_type_refresh_is_off_by_default(self):
        client, window_sub = self.make_input_client()
        self.add_window(client, window_sub, 1, (0, 0), (100, 100))
        client.kitty_keyboard = True
        client.process_input_events([KeyEvent(ord("a"), event_type=1, text="a")])
        self.assertEqual(client.type_refresh_timer, 0)

    def test_typing_burst_requests_a_refresh(self):
        # one refresh request per typing burst (`TYPE_REFRESH_DELAY`, off by default):
        client, window_sub = self.make_input_client()
        self.add_window(client, window_sub, 1, (0, 0), (100, 100))
        client.kitty_keyboard = True
        with patch.object(terminal_client, "TYPE_REFRESH_DELAY", 750):
            client.process_input_events([KeyEvent(ord("a"), event_type=1, text="a")])
            self.assertNotEqual(client.type_refresh_timer, 0)
            first_timer = client.type_refresh_timer
            # more typing re-arms the timer instead of stacking requests:
            client.process_input_events([KeyEvent(ord("b"), event_type=1, text="b")])
            self.assertNotEqual(client.type_refresh_timer, first_timer)
            # a key release on its own does not arm it:
            client.source_remove(client.type_refresh_timer)
            client.type_refresh_timer = 0
            client.process_input_events([KeyEvent(ord("b"), event_type=3)])
            self.assertEqual(client.type_refresh_timer, 0)
        # when the timer fires, the focused window is refreshed:
        client.type_refresh()
        self.assertEqual(window_sub.refreshes, [1])

    def test_key_events_go_to_the_focused_window(self):
        client, window_sub = self.make_input_client()
        kb = client.subsystems["keyboard"]
        # no window exists yet, so the event is dropped:
        client.process_input_events([KeyEvent(ord("a"), text="a")])
        self.assertEqual(kb.actions, [])
        # the first regular window takes the focus as soon as it is created,
        # so the keyboard works without requiring a click first:
        window = self.add_window(client, window_sub, 1, (0, 0), (100, 100))
        self.assertEqual(client._focused, 1)
        client.kitty_keyboard = True
        client.process_input_events([KeyEvent(ord("a"), mods=4, event_type=1, text="a")])
        self.assertEqual(kb.actions, [(window, "a", True, ("control", ))])
        # the modifiers reported with the event are cached for the subsystems:
        self.assertEqual(tuple(client.get_current_modifiers()), ("control", ))

    def test_legacy_key_press_synthesizes_a_release(self):
        client, window_sub = self.make_input_client()
        window = self.add_window(client, window_sub, 1, (0, 0), (100, 100))
        client.focus_window(1)
        kb = client.subsystems["keyboard"]
        # the terminal does not report key releases (no kitty keyboard protocol):
        self.assertFalse(client.kitty_keyboard)
        client.process_input_events([KeyEvent(ord("a"), text="a")])
        self.assertEqual(kb.actions, [(window, "a", True, ()), (window, "a", False, ())])
        # with the protocol enabled, the terminal sends the release itself:
        kb.actions = []
        client.kitty_keyboard = True
        client.process_input_events([KeyEvent(ord("a"), event_type=1, text="a"),
                                     KeyEvent(ord("a"), event_type=3, text="a")])
        self.assertEqual([a[2] for a in kb.actions], [True, False])

    def test_mouse_coordinate_base(self):
        with OSEnvContext():
            os.environ.pop("KITTY_WINDOW_ID", None)
            # every terminal but kitty reports mode 1016 coordinates 1-based:
            os.environ["TERM"] = "xterm-256color"
            self.assertEqual(terminal_client.mouse_coordinate_base(), 1)
            os.environ["TERM"] = "xterm-kitty"
            self.assertEqual(terminal_client.mouse_coordinate_base(), 0)
            os.environ["TERM"] = "screen"
            os.environ["KITTY_WINDOW_ID"] = "1"
            self.assertEqual(terminal_client.mouse_coordinate_base(), 0)
            # and the tunable wins over the detection:
            saved = terminal_client.MOUSE_COORDINATE_BASE
            terminal_client.MOUSE_COORDINATE_BASE = 1
            try:
                self.assertEqual(terminal_client.mouse_coordinate_base(), 1)
            finally:
                terminal_client.MOUSE_COORDINATE_BASE = saved

    def test_the_client_picks_up_the_mouse_coordinate_base(self):
        with OSEnvContext():
            os.environ.pop("KITTY_WINDOW_ID", None)
            os.environ["TERM"] = "xterm-kitty"
            with silence_info(ui_client_base):
                client = terminal_client.XpraTerminalClient()
            self.addCleanup(client.cleanup)
            self.assertEqual(client.mouse_base, 0)

    def test_zero_based_mouse_reports(self):
        # a terminal which reports mode 1016 coordinates 0-based (kitty):
        client, window_sub = self.make_input_client()
        client.mouse_base = 0
        self.add_window(client, window_sub, 1, (100, 100), (100, 100))
        # the top left pixel of the window must hit that window, not the background:
        client.process_input_events([MouseEvent(100, 100, 1, "press", 0)])
        self.assertEqual(client.get_raw_mouse_position(), (100, 100))
        self.assertEqual([(b[1], b[2], b[3]) for b in window_sub.buttons], [(1, 1, True)])

    def test_focus_parks_the_pointer_until_real_mouse_input(self):
        # without this, a fresh session has a dead keyboard until the first click:
        # when `XSetInputFocus` does not take effect the X focus stays on
        # `PointerRoot` and keys are routed to the window under the pointer,
        # which starts wherever the vfb put it
        client, window_sub = self.make_input_client()
        pointer = client.subsystems["pointer"]
        self.add_window(client, window_sub, 1, (0, 0), (100, 100))
        self.assertEqual(pointer.positions, [(-1, 1, (50, 50, 50, 50), (), ())])
        # a real mouse event ends the parking:
        client.process_input_events([MouseEvent(11, 21, 0, "motion", 0)])
        self.assertTrue(client._pointer_synced)
        pointer.positions.clear()
        self.add_window(client, window_sub, 2, (0, 0), (50, 50))
        client.focus_window(2)
        self.assertEqual(pointer.positions, [])

    def test_mouse_motion(self):
        client, window_sub = self.make_input_client()
        self.add_window(client, window_sub, 1, (20, 40), (100, 100))
        pointer = client.subsystems["pointer"]
        # focusing the new window parked the pointer at its center:
        self.assertEqual(pointer.positions.pop(0), (-1, 1, (70, 90, 50, 50), (), ()))
        # SGR pixel coordinates are 1-based on this terminal:
        self.assertEqual(client.mouse_base, 1)
        client.process_input_events([MouseEvent(31, 51, 0, "motion", 0)])
        self.assertEqual(client.get_raw_mouse_position(), (30, 50))
        self.assertEqual(pointer.positions, [(-1, 1, (30, 50, 10, 10), (), ())])

    def test_mouse_motion_outside_any_window(self):
        client, window_sub = self.make_input_client()
        self.add_window(client, window_sub, 1, (20, 40), (10, 10))
        pointer = client.subsystems["pointer"]
        pointer.positions.clear()      # drop the focus-time pointer parking
        client.process_input_events([MouseEvent(500, 500, 0, "motion", 0)])
        self.assertEqual(pointer.positions, [(-1, 0, (499, 499, 499, 499), (), ())])

    def test_mouse_buttons_are_paired_and_focus(self):
        client, window_sub = self.make_input_client()
        self.add_window(client, window_sub, 1, (0, 0), (100, 100))
        client.process_input_events([MouseEvent(11, 21, 1, "press", 0)])
        self.assertEqual(client._buttons, [1])
        self.assertEqual(window_sub.focus_events, [(1, True)])
        client.process_input_events([MouseEvent(11, 21, 1, "release", 0)])
        self.assertEqual(client._buttons, [])
        self.assertEqual([(b[2], b[3]) for b in window_sub.buttons], [(1, True), (1, False)])
        # the held buttons are reported with the press:
        self.assertEqual(window_sub.buttons[0][6], (1, ))
        self.assertEqual(window_sub.buttons[1][6], ())

    def test_mouse_press_outside_any_window_is_dropped(self):
        client, window_sub = self.make_input_client()
        self.add_window(client, window_sub, 1, (0, 0), (10, 10))
        client.process_input_events([MouseEvent(500, 500, 1, "press", 0)])
        self.assertEqual(window_sub.buttons, [])
        self.assertEqual(client._buttons, [])

    def test_mouse_release_outside_any_window_is_still_sent(self):
        # dragging out of a window and releasing there must not leave the button held down
        client, window_sub = self.make_input_client()
        self.add_window(client, window_sub, 1, (0, 0), (100, 100))
        client.process_input_events([MouseEvent(11, 21, 1, "press", 0),
                                     MouseEvent(501, 501, 1, "release", 0)])
        self.assertEqual(client._buttons, [])
        self.assertEqual([(b[1], b[2], b[3]) for b in window_sub.buttons],
                         [(1, 1, True), (0, 1, False)])
        # the release is reported at the root window position:
        self.assertEqual(window_sub.buttons[1][4], (500, 500, 500, 500))
        # and the next press is delivered normally:
        client.process_input_events([MouseEvent(11, 21, 1, "press", 0)])
        self.assertEqual(client._buttons, [1])
        self.assertEqual([(b[1], b[2], b[3]) for b in window_sub.buttons][-1:], [(1, 1, True)])

    def test_wheel(self):
        client, window_sub = self.make_input_client()
        self.add_window(client, window_sub, 1, (0, 0), (100, 100))
        client.process_input_events([MouseEvent(11, 21, 4, "wheel", 0),
                                     MouseEvent(11, 21, 5, "wheel", 0),
                                     MouseEvent(11, 21, 6, "wheel", 0),
                                     MouseEvent(11, 21, 7, "wheel", 0)])
        self.assertEqual([(w[2], w[3]) for w in window_sub.wheels],
                         [(0, 1), (0, -1), (-1, 0), (1, 0)])
        # an unknown wheel button is dropped rather than sent as a delta of 0:
        window_sub.wheels = []
        client.process_input_events([MouseEvent(11, 21, 9, "wheel", 0)])
        self.assertEqual(window_sub.wheels, [])
        # and so is a wheel event which is not over any window:
        client.process_input_events([MouseEvent(500, 500, 4, "wheel", 0)])
        self.assertEqual(window_sub.wheels, [])

    def test_unknown_events_are_ignored(self):
        client = self.make_client()
        client.process_input_events([object(), None])

    ######################################################################
    # cursor

    def cursor_data(self, width=4, height=4, xhot=1, yhot=2, serial=77):
        pixels = bytes((1, 2, 3, 255)) * (width * height)
        return ("raw", 0, 0, width, height, xhot, yhot, serial, pixels, "default")

    def transmitted_pixels(self, data: bytes) -> bytes:
        """ decode the payload of the `a=t` image transmission found in what we wrote """
        start = data.index(b"\x1b_Ga=t")
        end = data.index(b"\x1b\\", start)
        control, _, payload = data[start + 3:end].partition(b";")
        pixels = b64decode(payload)
        if b",o=z" in control:
            pixels = zlib.decompress(pixels)
        return pixels

    def test_cursor_is_transmitted_and_placed_at_the_hotspot(self):
        client = self.make_client()
        buf = self.make_output(client)
        client._pointer_pos = (105, 63)
        client.set_windows_cursor((), self.cursor_data())
        data = buf.getvalue()
        image_id = graphics.CURSOR_IMAGE_ID
        self.assertIn(b"a=t,q=2,i=%i,f=32,s=4,v=4" % image_id, data)
        # the cursor pixels are RGBA on the wire and the terminal expects RGBA:
        self.assertEqual(self.transmitted_pixels(data), bytes((1, 2, 3, 255)) * 16)
        # (105-1, 63-2) with 10x20 cells: row 4, column 11, offsets (4, 1)
        self.assertIn(b"\x1b[4;11H", data)
        self.assertIn(b"a=p,q=2,i=%i,p=1,z=%i,C=1,X=4,Y=1" % (image_id, graphics.CURSOR_Z), data)

    def test_cursor_follows_the_pointer_without_a_new_image(self):
        client = self.make_client()
        buf = self.make_output(client)
        client.set_windows_cursor((), self.cursor_data())
        buf.seek(0)
        buf.truncate()
        client._pointer_pos = (200, 100)
        client.update_cursor()
        data = buf.getvalue()
        # the image is already in the terminal, only the placement moves:
        self.assertNotIn(b"a=t", data)
        self.assertIn(b"\x1b[5;20H", data)

    def test_new_cursor_shapes_swap_image_ids(self):
        # a new shape must be placed before the old image is deleted, or the
        # pointer blinks on every shape change (retransmitting under a single
        # id deletes the visible image and its placement first):
        client = self.make_client()
        buf = self.make_output(client)
        client.set_windows_cursor((), self.cursor_data())
        self.assertEqual(client._cursor_image_id, graphics.CURSOR_IMAGE_ID)
        buf.seek(0)
        buf.truncate()
        new_shape = list(self.cursor_data())
        new_shape[7] = int(new_shape[7]) + 1
        client.set_windows_cursor((), tuple(new_shape))
        data = buf.getvalue()
        back_id = terminal_client.CURSOR_BACK_IMAGE_ID
        self.assertEqual(client._cursor_image_id, back_id)
        transmit = data.index(b"a=t,q=2,i=%i" % back_id)
        place = data.index(b"a=p,q=2,i=%i" % back_id)
        delete = data.index(b"a=d,d=I,i=%i" % graphics.CURSOR_IMAGE_ID)
        self.assertLess(transmit, place)
        self.assertLess(place, delete)

    def test_empty_cursor_removes_the_placement(self):
        client = self.make_client()
        buf = self.make_output(client)
        client.set_windows_cursor((), self.cursor_data())
        buf.seek(0)
        buf.truncate()
        client.set_windows_cursor((), ())
        self.assertIn(b"a=d,d=i,i=%i,p=1" % graphics.CURSOR_IMAGE_ID, buf.getvalue())
        # and nothing is emitted for a cursor which is already gone:
        buf.seek(0)
        buf.truncate()
        client.update_cursor()
        self.assertEqual(buf.getvalue(), b"")

    def test_invalid_cursor_data_is_dropped(self):
        client = self.make_client()
        buf = self.make_output(client)
        # the pixel buffer is too small for the size claimed:
        with silence_warn(terminal_client, "cursorlog"):
            client.set_windows_cursor((), ("raw", 0, 0, 40, 40, 0, 0, 1, b"\0" * 16, "default"))
        self.assertEqual(client._cursor_data, ())
        buf.seek(0)
        buf.truncate()
        client.update_cursor()
        self.assertEqual(buf.getvalue(), b"")

    def test_cursor_is_recorded_on_the_cursor_subsystem(self):
        client = self.make_client()
        self.make_output(client)
        cursor = client.get_subsystem("cursor")
        if cursor is None:
            self.skipTest("no `cursor` subsystem composed")
        window = FakeWindow(1)
        data = self.cursor_data()
        client.set_windows_cursor((window, ), data)
        self.assertEqual(cursor._cursors[window], data)
        client.set_windows_cursor((window, ), ())
        self.assertNotIn(window, cursor._cursors)

    ######################################################################
    # cleanup

    def test_cleanup_twice(self):
        client = self.make_client()
        client.cleanup()
        client.cleanup()

    def test_cleanup_after_terminal_output(self):
        client = self.make_client()
        buf = self.make_output(client)
        client._zorder = {1: 10, 2: 12}
        client.cleanup()
        # every image we uploaded is freed:
        self.assertIn(b"a=d,d=I,i=1", buf.getvalue())
        self.assertIn(b"a=d,d=I,i=2", buf.getvalue())
        self.assertIsNone(client.terminal_output)
        client.cleanup()

    def test_quit_before_run(self):
        client = self.make_client()
        # `GObjectClientAdapter.quit` would dereference a main loop which does not exist yet:
        client.quit(ExitCode.OK)
        self.assertEqual(client.exit_code, ExitCode.OK)


@unittest.skipIf(terminal_client is None, "the terminal client component is not available")
class TerminalModeTest(unittest.TestCase):
    """
    Enters and leaves terminal mode for real, on a pty created by this test:
    the terminal modes, the escape sequences we emit and the input we read back
    all go through the same code paths as on a real terminal.
    """

    def setUp(self):
        super().setUp()
        log_dir = tempfile.TemporaryDirectory()
        self.addCleanup(log_dir.cleanup)
        # the client redirects its own log output away from the terminal,
        # keep whatever it writes inside the temporary directory:
        env_context = OSEnvContext(XPRA_NOX11="1", XPRA_LOG_DIRS=log_dir.name)
        env_context.__enter__()
        self.addCleanup(env_context.__exit__)
        self.master, self.slave = os.openpty()
        self.outputs: list = []
        # registered before the client, so it runs after `client.cleanup()`:
        self.addCleanup(self.close_pty)
        # so that reading what the client wrote never blocks:
        flags = fcntl.fcntl(self.master, fcntl.F_GETFL)
        fcntl.fcntl(self.master, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        self.saved_mode = termios.tcgetattr(self.slave)
        with silence_info(ui_client_base):
            self.client = terminal_client.XpraTerminalClient()
        self.addCleanup(self.client.cleanup)
        self.client.terminal_fd = self.slave
        self.client.terminal_size = TERMINAL_SIZE
        # the tests must not depend on the terminal they are running in:
        self.client.mouse_base = 1
        self.client.make_terminal_output = self.make_terminal_output

    def make_terminal_output(self):
        # the client owns the terminal device, the test plays the terminal emulator:
        fileobj = os.fdopen(os.dup(self.slave), "wb", buffering=0)
        self.outputs.append(fileobj)
        return TerminalOutput(fileobj)

    def close_pty(self) -> None:
        for fileobj in self.outputs:
            fileobj.close()
        for fd in (self.master, self.slave):
            try:
                os.close(fd)
            except OSError:
                pass

    def read_terminal(self) -> bytes:
        data = b""
        while True:
            try:
                chunk = os.read(self.master, 65536)
            except BlockingIOError:
                return data
            except OSError:
                return data
            if not chunk:
                return data
            data += chunk

    def write_terminal(self, data: bytes) -> None:
        os.write(self.master, data)
        self.client.handle_terminal_input(None, IO_IN)

    def test_enter_and_leave_terminal_mode(self):
        client = self.client
        client.start_terminal_mode()
        self.assertIsNotNone(client.terminal_output)
        self.assertTrue(client.terminal_context.active)
        # the terminal is now in raw mode:
        self.assertFalse(termios.tcgetattr(self.slave)[3] & termios.ECHO)
        data = self.read_terminal()
        for expected in (
            b"\x1b[?1049h",         # alternate screen
            b"\x1b[?25l",           # hide the cursor
            b"\x1b[>",              # push the kitty keyboard flags
            b"\x1b[?1016h",         # SGR pixel mouse reports
            b"\x1b[?u",             # query the keyboard flags
            b"a=q,i=%i" % terminal_client.PROBE_IMAGE_ID,   # the graphics probe
        ):
            self.assertIn(expected, data)
        # the log output has been redirected away from the terminal:
        self.assertIsNotNone(client.saved_log_handlers)
        # and the terminal resizes are watched:
        self.assertTrue(client.sigwinch_watch or signal.getsignal(signal.SIGWINCH) == client.handle_sigwinch)

        client.cleanup()
        data = self.read_terminal()
        for expected in (
            b"\x1b[?1016l",         # mouse reports off
            b"\x1b[<u",             # pop the keyboard flags
            b"\x1b[?25h",           # show the cursor
            b"\x1b[?1049l",         # back to the main screen
        ):
            self.assertIn(expected, data)
        self.assertIsNone(client.terminal_output)
        self.assertIsNone(client.terminal_context)
        self.assertIsNone(client.saved_log_handlers)
        # the terminal modes have been restored:
        self.assertEqual(termios.tcgetattr(self.slave), self.saved_mode)

    def test_start_terminal_mode_is_idempotent(self):
        client = self.client
        client.start_terminal_mode()
        output = client.terminal_output
        self.read_terminal()
        client.start_terminal_mode()
        self.assertIs(client.terminal_output, output)
        self.assertEqual(self.read_terminal(), b"")

    def test_input_is_parsed_from_the_terminal(self):
        client = self.client
        client.start_terminal_mode()
        self.read_terminal()
        window_sub = FakeWindowSubsystem()
        client.subsystems["window"] = window_sub
        client.subsystems["pointer"] = FakePointerSubsystem()
        client.subsystems["keyboard"] = FakeKeyboardSubsystem()
        window = FakeWindow(1, (0, 0), (500, 500))
        window_sub.windows[1] = window
        client._new_window(None, window)
        client.focus_window(1)
        # the terminal answers our two queries:
        self.write_terminal(b"\x1b[?15u")
        self.assertTrue(client.kitty_keyboard)
        self.write_terminal(b"\x1b_Gi=%i;OK\x1b\\" % terminal_client.PROBE_IMAGE_ID)
        self.assertTrue(client.graphics_ok)
        # a key press, then a mouse move:
        self.write_terminal(b"\x1b[97;1:1u")
        self.assertEqual(client.subsystems["keyboard"].actions,
                         [(window, "a", True, ())])
        self.write_terminal(b"\x1b[<35;101;51M")
        self.assertEqual(client.get_raw_mouse_position(), (100, 50))
        self.assertEqual(client.subsystems["pointer"].positions[-1],
                         (-1, 1, (100, 50, 100, 50), (), ()))

    def test_terminal_resize_updates_the_geometry(self):
        client = self.client
        client.start_terminal_mode()
        self.read_terminal()
        display = FakeDisplaySubsystem()
        client.subsystems["display"] = display
        # `struct winsize`: rows, columns, width and height in pixels
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 132, 1584, 1100))
        self.assertTrue(client.terminal_size_changed())
        self.assertEqual(client.terminal_size, (132, 50, 1584, 1100))
        self.assertEqual(client.cell_size(), (12, 22))
        self.assertEqual(client.terminal_pixel_size(), (1584, 1100))
        self.assertEqual(display.screen_changes, 1)
        # a `SIGWINCH` which does not change the size costs nothing:
        self.assertFalse(client.update_terminal_size())
        self.assertTrue(client.terminal_size_changed())
        self.assertEqual(display.screen_changes, 1)
        # the terminal reports its pixel size, so there is nothing to ask it:
        self.assertEqual(self.read_terminal(), b"")

    def test_a_resize_without_a_pixel_size_queries_the_terminal(self):
        client = self.client
        # a pty which only forwards rows and columns (`docker exec` and friends)
        # never had a pixel size to begin with:
        client.terminal_size = (120, 40, 0, 0)
        client.start_terminal_mode()
        self.read_terminal()
        client.subsystems["display"] = FakeDisplaySubsystem()
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 132, 0, 0))
        self.assertTrue(client.terminal_size_changed())
        self.assertEqual(client.terminal_size, (132, 50, 0, 0))
        data = self.read_terminal()
        self.assertIn(b"\x1b[14t", data)
        self.assertIn(b"\x1b[16t", data)
        # and the terminal's answer gives us the cell size:
        self.write_terminal(b"\x1b[6;22;12t")
        self.assertEqual(client.terminal_size, (132, 50, 132 * 12, 50 * 22))
        self.assertEqual(client.cell_size(), (12, 22))

    def test_a_pixel_less_reading_is_quarantined(self):
        # the terminal reported pixels before: a sudden pixel-less 80x24 reading
        # is what a transient glitch looks like - adopting it instantly would
        # shrink the whole session to a guessed size (and some vfbs cannot grow
        # back), so it must be confirmed by a second reading first:
        client = self.client
        client.start_terminal_mode()
        self.read_terminal()
        display = FakeDisplaySubsystem()
        client.subsystems["display"] = display
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        with silence_warn(terminal_client):
            self.assertTrue(client.terminal_size_changed())
        # nothing is adopted yet:
        self.assertEqual(client.terminal_size, TERMINAL_SIZE)
        self.assertEqual(display.screen_changes, 0)
        self.assertEqual(client._pending_size, (80, 24))
        self.assertNotEqual(client.size_confirm_timer, 0)
        # the terminal is asked for its geometry again:
        data = self.read_terminal()
        self.assertIn(b"\x1b[14t", data)
        self.assertIn(b"\x1b[16t", data)
        # a stable second reading is adopted:
        client.source_remove(client.size_confirm_timer)
        client.size_confirm_timer = 0
        client._pending_size = (80, 24)
        self.assertFalse(client.confirm_terminal_size())
        self.assertEqual(client.terminal_size, (80, 24, 0, 0))
        self.assertEqual(display.screen_changes, 1)

    def test_a_transient_size_glitch_is_ignored(self):
        client = self.client
        client.start_terminal_mode()
        self.read_terminal()
        display = FakeDisplaySubsystem()
        client.subsystems["display"] = display
        rows, cols = TERMINAL_SIZE[1], TERMINAL_SIZE[0]
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        with silence_warn(terminal_client):
            self.assertTrue(client.terminal_size_changed())
        self.assertEqual(client.terminal_size, TERMINAL_SIZE)
        # the terminal recovers before the confirmation runs:
        fcntl.ioctl(self.master, termios.TIOCSWINSZ,
                    struct.pack("HHHH", rows, cols, TERMINAL_SIZE[2], TERMINAL_SIZE[3]))
        client.source_remove(client.size_confirm_timer)
        client.size_confirm_timer = 0
        self.assertFalse(client.confirm_terminal_size())
        # the glitch never reached the server:
        self.assertEqual(client.terminal_size, TERMINAL_SIZE)
        self.assertEqual(display.screen_changes, 0)

    def test_sigwinch_is_handled_on_the_main_loop(self):
        client = self.client
        scheduled: list = []
        # a signal handler must not touch the terminal itself:
        client.idle_add = lambda fn, *args: scheduled.append((fn, args))
        client.handle_sigwinch(signal.SIGWINCH, None)
        self.assertEqual(scheduled, [(client.terminal_size_changed, ())])

    def test_a_fatal_error_is_reported_after_the_terminal_is_restored(self):
        client = self.client
        records: list[str] = []

        class RecordingHandler(logging.Handler):
            def emit(self, record) -> None:
                records.append(record.getMessage())

        handler = RecordingHandler()
        logging.root.addHandler(handler)
        self.addCleanup(logging.root.removeHandler, handler)
        client.start_terminal_mode()
        self.read_terminal()
        # while the terminal is in graphics mode, our own output goes to the log file:
        self.assertNotIn(handler, logging.root.handlers)
        client.probe_timer = 0
        client.graphics_probe_timeout()
        self.assertEqual(client.exit_code, ExitCode.UNSUPPORTED)
        # the terminal (and the logging) is restored before the reason is given,
        # or the user would never see it:
        self.assertIsNone(client.terminal_output)
        self.assertIn(b"\x1b[?1049l", self.read_terminal())
        self.assertIn(handler, logging.root.handlers)
        self.assertTrue([r for r in records if "kitty graphics protocol" in r],
                        f"the failure was not reported to the user: {records}")

    def test_closed_terminal_quits(self):
        client = self.client
        client.start_terminal_mode()
        self.read_terminal()
        os.close(self.master)
        # writing to a pty whose other end is gone fails, which is the point:
        with silence_warn(base_client), silence_warn(terminal_tty):
            self.assertFalse(client.handle_terminal_input(None, IO_IN))
        self.assertEqual(client.input_watch, 0)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
