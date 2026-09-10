#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import subprocess
import sys
import unittest

from unit.server_test_util import ServerTestUtil
from xpra.os_util import OSX, POSIX

# selections of our own, so that a real clipboard is never touched:
SELECTION = "XPRA_GTK_CLIPBOARD_TEST"

# This runs in a subprocess: `GTKClipboardProxy` needs a GDK display, and binding
# to one is process-global, so opening it here would leave every later test with
# a pointer to a display we are about to kill.
CHECKS = r"""
import sys
from xpra.gtk.util import open_gdk_display

open_gdk_display(sys.argv[1])

from xpra.gtk.clipboard import GTKClipboardProxy

SELECTION = sys.argv[2]
failures = []


def check(name, condition, message):
    if not condition:
        failures.append("%s: %s" % (name, message))


def make_proxy(selection, can_send=True):
    # a peer which is neither greedy nor wants the targets gets a bare token,
    # which is the path that does not touch the real clipboard at all:
    proxy = GTKClipboardProxy(selection)
    proxy.set_enabled(True)
    proxy.set_direction(can_send, True)
    tokens = []
    proxy.connect("send-clipboard-token", lambda _proxy, token: tokens.append(token))
    return proxy, tokens


proxy, tokens = make_proxy(SELECTION)
proxy.do_owner_changed()
check("isolated", len(tokens) == 1, "an isolated owner change should be advertised at once, got %i" % len(tokens))
check("isolated", proxy._emit_token_timer == 0, "an isolated owner change should not arm a timer")
check("isolated", proxy._sent_token_events == 1, "the token should be counted, got %i" % proxy._sent_token_events)

for _ in range(50):
    proxy.do_owner_changed()
check("burst", len(tokens) == 1, "an owner burst should not be one packet per change, got %i" % len(tokens))
check("burst", proxy._emit_token_timer != 0, "the burst should leave one token scheduled")

# the peer taking the selection drops the token we had scheduled for the old owner:
proxy.got_token((), None, False)
check("cancel", proxy._emit_token_timer == 0, "a remote token should cancel the one we scheduled")
check("cancel", len(tokens) == 1, "no further token should have been sent, got %i" % len(tokens))
proxy.cleanup()

blocked, blocked_tokens = make_proxy(SELECTION + "_TO_CLIENT", can_send=False)
blocked.do_owner_changed()
check("direction", not blocked_tokens, "a proxy which cannot send should not advertise its owner")
blocked.cleanup()

for failure in failures:
    print("FAIL %s" % failure)
print("done")
"""


class GTKClipboardTest(ServerTestUtil):

    def run_checks(self, checks: str) -> None:
        display = self.find_free_display()
        xvfb = self.start_Xvfb(display)
        try:
            env = os.environ.copy()
            env["DISPLAY"] = display
            env["GDK_BACKEND"] = "x11"
            proc = subprocess.run(
                (sys.executable, "-c", checks, display, SELECTION),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, check=False, env=env, timeout=120,
            )
        finally:
            xvfb.terminate()
        self.assertEqual(proc.returncode, 0, f"checks did not run:\n{proc.stderr}")
        self.assertIn("done", proc.stdout, f"checks did not complete:\n{proc.stderr}")
        failures = [line for line in proc.stdout.splitlines() if line.startswith("FAIL ")]
        self.assertFalse(failures, "\n".join(failures))

    def test_the_token_goes_through_the_shared_scheduler(self):
        self.run_checks(CHECKS)


def main():
    # can only work with an X11 server
    if POSIX and not OSX:
        unittest.main()


if __name__ == '__main__':
    main()
