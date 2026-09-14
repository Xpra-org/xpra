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

# These run in a subprocess: `GTKClipboardProxy` needs a GDK display, and binding
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

# the paths which now answer from a GTK callback instead of from a nested main loop:
ASYNC_CHECKS = r"""
import sys
from time import monotonic
from xpra.gtk.util import open_gdk_display

open_gdk_display(sys.argv[1])

from xpra.os_util import gi_import
from xpra.gtk.clipboard import GTKClipboardProxy, REQUEST_TIMEOUT

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GLib = gi_import("GLib")

SELECTION = sys.argv[2]
TEXT = "hello clipboard"
failures = []


def check(name, condition, message):
    if not condition:
        failures.append("%s: %s" % (name, message))


def run_until(condition, timeout=5000):
    # give the GTK callbacks and timers a main loop to be dispatched from:
    if condition():
        return True
    loop = GLib.MainLoop()
    deadline = monotonic() + timeout / 1000

    def poll():
        if condition() or monotonic() >= deadline:
            loop.quit()
            return False
        return True

    GLib.timeout_add(20, poll)
    loop.run()
    return condition()


def make_proxy(selection, greedy=False):
    proxy = GTKClipboardProxy(selection)
    proxy.set_enabled(True)
    proxy.set_direction(True, True)
    proxy.set_greedy_client(greedy)
    proxy.set_want_targets(greedy)
    tokens = []
    proxy.connect("send-clipboard-token", lambda _proxy, token: tokens.append(token))
    return proxy, tokens


# a selection nobody owns: the answer can only come back from the X server,
# so this is the one case which is guaranteed not to be answered inline
unowned, _ = make_proxy(SELECTION + "_UNOWNED")
replies = []
unowned.get_contents("TARGETS", lambda *args: replies.append(args))
check("async", not replies, "an unowned selection should not be answered before the main loop runs")
run_until(lambda: bool(replies))
check("async", len(replies) == 1, "expected exactly one answer, got %i" % len(replies))
if replies:
    dtype, dformat, data = replies[0]
    check("async", (dtype, dformat) == ("ATOM", 32), "expected an empty ATOM reply, got %s" % (replies[0], ))
    check("async", not data, "an unowned selection has no targets, got %s" % (data, ))
unowned.cleanup()

# now take the selection, so that there is something real to fetch:
clipboard = Gtk.Clipboard.get(Gdk.Atom.intern(SELECTION, False))
clipboard.set_text(TEXT, -1)
proxy, tokens = make_proxy(SELECTION, greedy=True)

targets = []
proxy.get_contents("TARGETS", lambda *args: targets.append(args))
run_until(lambda: bool(targets))
check("targets", len(targets) == 1, "expected exactly one TARGETS answer, got %i" % len(targets))
if targets:
    dtype, dformat, names = targets[0]
    check("targets", (dtype, dformat) == ("ATOM", 32), "TARGETS should be atoms, got %s / %s" % (dtype, dformat))
    check("targets", "UTF8_STRING" in names, "text on the clipboard should offer UTF8_STRING, got %s" % (names, ))

text = []
proxy.get_contents("UTF8_STRING", lambda *args: text.append(args))
run_until(lambda: bool(text))
check("contents", len(text) == 1, "expected exactly one answer, got %i" % len(text))
if text:
    dtype, dformat, data = text[0]
    check("contents", dformat == 8, "text should use format 8, got %s" % dformat)
    check("contents", data == TEXT.encode(), "expected %r, got %r" % (TEXT, data))

# a target nobody offers is answered once, with nothing:
missing = []
proxy.get_contents("application/x-xpra-does-not-exist", lambda *args: missing.append(args))
run_until(lambda: bool(missing))
check("missing", len(missing) == 1, "a missing target should be answered exactly once, got %i" % len(missing))
if missing:
    check("missing", missing[0][1] == 0, "a missing target should use format 0, got %s" % (missing[0], ))

# a greedy peer gets the contents collected and shipped with the token:
proxy.emit_token()
run_until(lambda: bool(tokens))
check("greedy", len(tokens) == 1, "expected exactly one token, got %i" % len(tokens))
if tokens:
    token = tokens[0]
    check("greedy", "UTF8_STRING" in token["targets"], "the token should advertise the targets, got %s" % (token, ))
    data = token["data"]
    check("greedy", bool(data), "a greedy peer should get the contents with the token")
    utf8 = data.get("UTF8_STRING")
    check("greedy", utf8 is not None, "expected UTF8_STRING data, got %s" % (tuple(data.keys()), ))
    if utf8:
        check("greedy", utf8[2] == TEXT.encode(), "expected %r with the token, got %r" % (TEXT, utf8[2]))
proxy.cleanup()

# the watchdog and a late reply must not both answer:
watchdog, _ = make_proxy(SELECTION + "_WATCHDOG")
answers = []
answer = watchdog.answer_once("STRING", lambda *args: answers.append(args))
check("watchdog", len(watchdog._local_requests) == 1, "the request should be registered until it is answered")
run_until(lambda: bool(answers), timeout=REQUEST_TIMEOUT * 10)
check("watchdog", len(answers) == 1, "the watchdog should answer the request, got %i" % len(answers))
check("watchdog", not watchdog._local_requests, "the watchdog should take the request out")
answer("STRING", 8, b"late")
check("watchdog", len(answers) == 1, "a reply after the watchdog should be dropped, got %i" % len(answers))
watchdog.cleanup()

# a request outstanding when the proxy goes away leaves no timer behind,
# and the answer which arrives afterwards is dropped:
gone, gone_tokens = make_proxy(SELECTION + "_CLEANUP")
generation = gone._selection_generation
late = []
late_answer = gone.answer_once("STRING", lambda *args: late.append(args))
gone.cleanup()
check("cleanup", not gone._local_requests, "cleanup should cancel every pending request")
check("cleanup", gone.is_stale(generation), "a disabled proxy should treat its callbacks as stale")
late_answer("STRING", 8, b"late")
check("cleanup", not late, "an answer after cleanup should be dropped, got %s" % (late, ))
check("cleanup", not gone_tokens, "nothing should be advertised after cleanup")

for failure in failures:
    print("FAIL %s" % failure)
print("done")
"""


class GTKClipboardTest(ServerTestUtil):

    def run_checks(self, checks: str, **env_options) -> None:
        display = self.find_free_display()
        xvfb = self.start_Xvfb(display)
        try:
            env = os.environ.copy()
            env["DISPLAY"] = display
            env["GDK_BACKEND"] = "x11"
            env.update(env_options)
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

    def test_the_clipboard_is_read_without_blocking(self):
        # short enough to keep the watchdog check quick,
        # long enough for the requests which do get an answer:
        self.run_checks(ASYNC_CHECKS, XPRA_CLIPBOARD_GTK_REQUEST_TIMEOUT="300")


def main():
    # can only work with an X11 server
    if POSIX and not OSX:
        unittest.main()


if __name__ == '__main__':
    main()
