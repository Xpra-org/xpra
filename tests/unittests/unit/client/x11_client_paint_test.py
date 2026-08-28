#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

from xpra.util.env import envint, OSEnvContext
from xpra.exit_codes import exit_str
from xpra.os_util import OSX, POSIX
from xpra.util.io import pollwait
from unit.client.x11_client_test_util import X11ClientTestUtil, log

CLIENT_TIMEOUT = envint("XPRA_TEST_CLIENT_TIMEOUT", 20)

# colors-plain quadrants, see xpra/gtk/examples/colors_plain.py:
RED = (255, 0, 0)
GREEN = (0, 254, 0)
BLUE = (0, 0, 253)
GREY = (128, 128, 128)


class X11ClientPaintTest(X11ClientTestUtil):

    def _quadrant_centers(self, cw, ch):
        # sample near a corner of each quadrant, away from the "R"/"G"/"B"
        # text labels colors-plain draws at the center of the red/green/blue
        # quadrants (the grey quadrant has no label):
        return {
            "red": ((cw // 8, ch // 8), RED),
            "green": ((5 * cw // 8, ch // 8), GREEN),
            "blue": ((cw // 8, 5 * ch // 8), BLUE),
            "grey": ((5 * cw // 8, 5 * ch // 8), GREY),
        }

    def _colors_start_arg(self):
        # spawn "xpra example colors-plain" as the server's start child.
        # use the `xpra` wrapper script (via get_xpra_cmd) rather than
        # `python -m xpra.scripts.main`: `-m` cannot execute `xpra.scripts.main`
        # when it is a compiled extension module (ie: cythonize_more builds),
        # it fails with "No code object available for xpra.scripts.main":
        return " ".join(self.get_xpra_cmd() + ["example", "colors-plain"])

    def _check_colors_pattern(self, server_args, client_args, tolerance):
        server_display = self.find_free_display()
        server = xvfb = client = None
        try:
            server = self.check_fast_start_server(
                server_display, "--windows=yes", "--start=%s" % self._colors_start_arg(), *server_args)
            xvfb, client = self.run_client(server_display, "--desktop-scaling=1", *client_args)
            r = pollwait(client, CLIENT_TIMEOUT)
            if r is not None:
                raise RuntimeError("client exited with code %s" % exit_str(r))
            xid, _cx, _cy, cw, ch = self.find_client_window(xvfb.display, title="Colors")
            assert cw >= 300 and ch >= 300, "unexpected colors-plain window size %ix%i" % (cw, ch)
            for name, (point, expected) in self._quadrant_centers(cw, ch).items():
                x, y = point
                self.wait_for_client_pixel(xvfb.display, xid, x, y, expected, tolerance=tolerance)
                log("colors-plain %s quadrant OK at (%i, %i)", name, x, y)
        finally:
            if client:
                self.terminate_and_wait(client)
            if xvfb:
                self.terminate_and_wait(xvfb)
            if server:
                self.check_stop_server(server, "exit", server_display)

    def test_colors_png(self):
        self._check_colors_pattern(
            server_args=("--encodings=png",),
            client_args=("--encoding=png",),
            tolerance=0,
        )

    def test_colors_webp(self):
        self._check_colors_pattern(
            server_args=("--encodings=webp",),
            client_args=("--encoding=webp", "--quality=100"),
            tolerance=6,
        )

    def test_colors_opengl(self):
        client_display = self.find_free_display()
        xvfb = self.start_Xvfb(client_display)
        try:
            with OSEnvContext():
                os.environ["DISPLAY"] = client_display
                from xpra.scripts.glprobe import run_opengl_probe
                message, props = run_opengl_probe()
            # a real GL context could be created ("success" in props) even when the
            # unforced probe's `message` reports the driver as disabled by policy
            # (eg: llvmpipe is greylisted) - `--opengl=force` bypasses exactly that
            # policy check, so only skip when GL is genuinely unusable:
            if not props.get("success"):
                self.skipTest("OpenGL not usable on this Xvfb: %s (%s)" % (message, props))

            server_display = self.find_free_display()
            server = client = None
            try:
                server = self.check_fast_start_server(
                    server_display, "--windows=yes", "--encodings=png",
                    "--start=%s" % self._colors_start_arg())
                client = self.do_run_client(
                    client_display, server_display, "--desktop-scaling=1",
                    "--encoding=png", "--opengl=force")
                r = pollwait(client, CLIENT_TIMEOUT)
                if r is not None:
                    raise RuntimeError("client exited with code %s" % exit_str(r))
                xid, _cx, _cy, cw, ch = self.find_client_window(client_display, title="Colors")
                assert cw >= 300 and ch >= 300, "unexpected colors-plain window size %ix%i" % (cw, ch)
                for name, (point, expected) in self._quadrant_centers(cw, ch).items():
                    x, y = point
                    self.wait_for_client_pixel(client_display, xid, x, y, expected, tolerance=4)
                    log("colors-plain %s quadrant OK at (%i, %i)", name, x, y)
            finally:
                if client:
                    self.terminate_and_wait(client)
                if server:
                    self.check_stop_server(server, "exit", server_display)
        finally:
            self.terminate_and_wait(xvfb)

    def test_xterm_position_and_color(self):
        server_display = self.find_free_display()
        server = xvfb = client = None
        try:
            # xterm's `-geometry WxH` is in character CELLS, not pixels (80x24 is a
            # normal-sized terminal, not a tiny one):
            # run a plain shell (not the user's default $SHELL) so no prompt escape
            # sequence overwrites the `-T` title once it starts:
            start_xterm = "xterm -geometry 80x24+120+90 -T testxterm -bg #101820 -fg #f0e0c0 -e sh -c 'sleep 60'"
            server = self.check_fast_start_server(
                server_display, "--windows=yes", "--sync-xvfb=50", "--start=%s" % start_xterm)
            xvfb, client = self.run_client(server_display, "--desktop-scaling=1")
            r = pollwait(client, CLIENT_TIMEOUT)
            if r is not None:
                raise RuntimeError("client exited with code %s" % exit_str(r))
            xid, cx, cy, cw, ch = self.find_client_window(xvfb.display, title="testxterm")
            assert cw > 50 and ch > 50, "xterm window too small: %ix%i" % (cw, ch)
            # placed via `-geometry +120+90`, no window manager on either side:
            assert abs(cx - 120) <= 2 and abs(cy - 90) <= 2, "unexpected xterm position (%i, %i)" % (cx, cy)
            # no text is printed, so the whole cell area stays a uniform -bg fill:
            self.wait_for_client_pixel(xvfb.display, xid, cw // 2, ch // 2, (0x10, 0x18, 0x20), tolerance=0)
        finally:
            if client:
                self.terminate_and_wait(client)
            if xvfb:
                self.terminate_and_wait(xvfb)
            if server:
                self.check_stop_server(server, "exit", server_display)


def main():
    if POSIX and not OSX:
        unittest.main()


if __name__ == '__main__':
    main()
