#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import subprocess
import unittest

from xpra.os_util import OSX, POSIX
from unit.process_test_util import ProcessTestUtil

# a selection of our own, so that a real clipboard is never touched:
SELECTION = "XPRAINCRTEST"

# An owner which cannot fit its answer in a single property switches to `INCR`
# and delivers it one chunk at a time. Nothing says the rest of the clipboard
# stops while it does: another target can be converted at the same time, and its
# answer lands on a property of its own.
#
# This runs in a subprocess: binding the X11 bindings to a display is process-global
# and cannot be undone, so doing it in the test process would leave every later test
# with a pointer to a display we are about to kill.
CHECKS = r"""
import os, sys, struct
from time import monotonic, sleep
import gi
gi.require_version("Gdk", "3.0"); gi.require_version("Gtk", "3.0")
from gi.repository import GLib, GObject, Gdk
from xpra.x11.gtk3.gdk_display_source import init_gdk_display_source
init_gdk_display_source()
from xpra.x11.gtk3.gdk_bindings import init_x11_filter, add_event_receiver, remove_event_receiver
init_x11_filter()
from xpra.gtk_common.gobject_util import one_arg_signal
from xpra.gtk_common.error import xsync, xswallow
from xpra.gtk_common.gtk_util import get_default_root_window
from xpra.x11.gtk_x11 import GDKX11Window
from xpra.x11.bindings.window import X11WindowBindings
from xpra.x11.gtk_x11.clipboard import X11Clipboard

SELECTION = sys.argv[1]
BIG = "BIGTARGET"
SMALL = "SMALLTARGET"
CHUNKS = [b"first-half-", b"second-half"]
X11Window = X11WindowBindings()
failures = []

def check(name, condition, message):
    if not condition:
        failures.append("%s: %s" % (name, message))

class Owner(GObject.GObject):
    __gsignals__ = {
        "xpra-selection-request": one_arg_signal,
        "xpra-property-notify-event": one_arg_signal,
    }
    def __init__(self, xid):
        super().__init__()
        self.xid = xid
        self.incr = {}
    def do_xpra_selection_request(self, event):
        target = str(event.target)
        prop = str(event.property)
        with xsync:
            if target == BIG:
                total = sum(len(chunk) for chunk in CHUNKS)
                self.incr[prop] = list(CHUNKS) + [b""]
                X11Window.XChangeProperty(event.requestor, prop, "INCR", 32, struct.pack("@L", total))
            else:
                X11Window.XChangeProperty(event.requestor, prop, "STRING", 8, b"small-value")
            X11Window.sendSelectionNotify(event.requestor, event.selection, target, prop, event.time)
    def do_xpra_property_notify_event(self, event):
        chunks = self.incr.get(str(event.atom))
        if not chunks:
            return
        with xswallow:
            X11Window.GetWindowPropertyType(event.window, event.atom, False)
            # still there: this notification is our own write, not the acknowledgement
            return
        with xsync:
            X11Window.XChangeProperty(event.window, event.atom, "STRING", 8, chunks.pop(0))
        if not chunks:
            del self.incr[str(event.atom)]
GObject.type_register(Owner)

def pump(predicate, timeout=5):
    context = GLib.MainContext.default()
    deadline = monotonic() + timeout
    while monotonic() < deadline and not predicate():
        context.iteration(False)
        sleep(0.005)
    return predicate()

owin = GDKX11Window(get_default_root_window(), width=1, height=1, title="owner", wclass=Gdk.WindowWindowClass.INPUT_ONLY)
owin.set_events(Gdk.EventMask.PROPERTY_CHANGE_MASK | owin.get_events())
oxid = owin.get_xid()
owner = Owner(oxid)
add_event_receiver(oxid, owner)
with xsync:
    X11Window.XSetSelectionOwner(oxid, SELECTION)
    check("owner", X11Window.XGetSelectionOwner(SELECTION) == oxid, "could not take the selection")

helper = X11Clipboard(lambda *_args: None)
helper.init_proxies([SELECTION])
proxy = helper._clipboard_proxies[SELECTION]
proxy.set_enabled(True)
add_event_receiver(proxy.xid, owner)

big, small = [], []
proxy.get_contents(BIG, lambda *args: big.append(args))
proxy.get_contents(SMALL, lambda *args: small.append(args))
pump(lambda: bool(big) and bool(small))
check("small", small == [("STRING", 8, b"small-value")], "the single-property conversion got %r" % (small, ))
check("big", big == [("STRING", 8, b"".join(CHUNKS))], "the incremental conversion got %r" % (big, ))
# let any leftover incremental timer fire:
pump(lambda: False, 1.5)
check("incr", not proxy.incr_transfers, "an incremental transfer was left behind")
helper.cleanup()
remove_event_receiver(proxy.xid, owner)
remove_event_receiver(oxid, owner)
for f in failures:
    print("FAIL %s" % f)
print("done")
"""


class X11ClipboardIncrTest(ProcessTestUtil):

    def test_a_concurrent_conversion_is_not_swallowed_by_an_incremental_one(self):
        display = self.find_free_display()
        xvfb = self.start_Xvfb(display)
        try:
            env = os.environ.copy()
            env["DISPLAY"] = display
            # the default conversion timeout is very short,
            # don't let a slow test environment turn into a failure:
            env["XPRA_CLIPBOARD_CONVERT_TIMEOUT"] = "3000"
            proc = subprocess.run(
                (sys.executable, "-c", CHECKS, SELECTION),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, check=False, env=env, timeout=120,
            )
        finally:
            xvfb.terminate()
        self.assertEqual(proc.returncode, 0, f"checks did not run:\n{proc.stderr}")
        self.assertIn("done", proc.stdout, f"checks did not complete:\n{proc.stderr}")
        failures = [line for line in proc.stdout.splitlines() if line.startswith("FAIL ")]
        self.assertFalse(failures, "\n".join(failures))
        self.assertNotIn("timed out", proc.stderr, f"a conversion timed out:\n{proc.stderr}")
        # a transfer which is retired properly takes its timer with it:
        self.assertNotIn("incremental data timeout", proc.stderr, f"an incremental transfer was left behind:\n{proc.stderr}")


def main():
    # can only work with an X11 server
    if POSIX and not OSX:
        unittest.main()


if __name__ == '__main__':
    main()
