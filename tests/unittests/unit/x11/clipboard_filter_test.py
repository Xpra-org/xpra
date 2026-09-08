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

# a selection of our own, so that a real clipboard is never touched:
SELECTION = "XPRA_CLIPBOARD_FILTER_TEST"

# On a gtk client, `X11Clipboard` only ever sees an X11 event because the shared GDK event
# filter routes it, so it has to hold a reference of its own: the other subsystems which
# install that filter (xsettings, window stacking, xi2..) are all optional.
#
# This runs in a subprocess: binding the X11 bindings to GDK's display is process-global
# and cannot be undone, so doing it in the test process would leave every later test with
# a pointer to a display we are about to kill.
GTK_CHECKS = r"""
import sys
from xpra.os_util import gi_import
from xpra.gtk.util import open_gdk_display

open_gdk_display(sys.argv[1])
# the bindings must share GDK's connection, or the XFixes events we select for
# would be delivered to a connection GDK never reads:
from xpra.x11.gtk.display_source import init_gdk_display_source
init_gdk_display_source()

from xpra.x11.gtk.bindings import init_x11_filter, cleanup_x11_filter
from xpra.x11.selection.clipboard import X11Clipboard

SELECTION = sys.argv[2]
failures = []


def check(name, condition, message):
    if not condition:
        failures.append("%s: %s" % (name, message))


def no_filter_installed() -> bool:
    # `init_x11_filter` returns True only when it actually installs the filter,
    # so this both answers the question and leaves the count as it found it:
    installed_by_us = init_x11_filter()
    cleanup_x11_filter()
    return installed_by_us


def make_helper():
    return X11Clipboard(lambda *_args: None)


# the clipboard holds a reference for as long as it is alive:
check("reference", no_filter_installed(), "something else already holds the filter")
helper = make_helper()
check("reference", not no_filter_installed(), "the clipboard must hold a filter reference")
helper.cleanup()
check("reference", no_filter_installed(), "the reference must be released on cleanup")

# and it must not remove a filter another subsystem still needs:
check("shared", init_x11_filter(), "the filter should not be installed at this point")
helper = make_helper()
helper.cleanup()
check("shared", not init_x11_filter(), "the clipboard released a reference it did not own")
cleanup_x11_filter()
check("shared", cleanup_x11_filter(), "our own reference should have been the last one")

# releasing more than we took would break the other users of the filter:
helper = make_helper()
helper.cleanup()
helper.cleanup()
check("idempotent", no_filter_installed(), "cleanup released more than it took")

# and the point of all of it: the events actually arrive.
# Nothing else installs the filter here, so this only works
# because the clipboard took a reference of its own.
GLib = gi_import("GLib")
Gtk = gi_import("Gtk")
from xpra.x11.bindings.core import constants
from xpra.x11.bindings.window import X11WindowBindings
from xpra.x11.error import xsync

check("events", no_filter_installed(), "nothing else may hold the filter for this check")
helper = make_helper()
helper.init_proxies([SELECTION])
events = []
helper.connect("x11-xfixes-selection-notify-event", lambda _h, event: events.append(event))

X11Window = X11WindowBindings()
with xsync:
    root = X11Window.get_root_xid()
    owner = X11Window.CreateWindow(root, -1, -1, event_mask=0, inputoutput=constants["InputOnly"])


def take_ownership() -> bool:
    with xsync:
        X11Window.XSetSelectionOwner(owner, SELECTION)
    return False


GLib.timeout_add(100, take_ownership)
GLib.timeout_add(3000, Gtk.main_quit)
Gtk.main()
check("events", events, "no xfixes selection event was delivered to the clipboard")
helper.cleanup()

for failure in failures:
    print("FAIL %s" % failure)
print("done")
"""


# Servers route their own X11 events from `x11.bindings.loop` and forbid the gtk modules,
# so the clipboard must not reach for the gtk bindings there: importing `xpra.x11.gtk`
# replaces `xpra.x11.common.get_pywindow` with a version which cannot work in that process.
NO_GTK_CHECKS = r"""
import sys
from xpra.scripts.main import no_gi_gtk_modules
from xpra.x11.bindings.display_source import init_display_source
from xpra.x11.bindings.loop import register_glib_source
from xpra.os_util import gi_import

GLib = gi_import("GLib")
init_display_source()
register_glib_source(GLib.MainContext.default())
# this is what `X11Init.setup()` does once the event loop is routing:
no_gi_gtk_modules()

import xpra.x11.common as common
from xpra.x11.selection.clipboard import X11Clipboard, x11_event_loop_running

failures = []


def check(name, condition, message):
    if not condition:
        failures.append("%s: %s" % (name, message))


check("loop", x11_event_loop_running(), "the X11 event loop should be routing events")

lookup = common.get_pywindow
helper = X11Clipboard(lambda *_args: None)
helper.init_proxies([sys.argv[1]])
check("no gtk", "xpra.x11.gtk" not in sys.modules,
      "the clipboard imported the gtk bindings on a server")
check("no gtk", common.get_pywindow is lookup,
      "importing the gtk bindings replaced `get_pywindow`")
helper.cleanup()

for failure in failures:
    print("FAIL %s" % failure)
print("done")
"""


class X11ClipboardFilterTest(ServerTestUtil):

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

    def test_clipboard_owns_its_filter_reference(self):
        self.run_checks(GTK_CHECKS)

    def test_clipboard_leaves_gtk_alone_on_a_server(self):
        self.run_checks(NO_GTK_CHECKS)


def main():
    # can only work with an X11 server
    if POSIX and not OSX:
        unittest.main()


if __name__ == '__main__':
    main()
