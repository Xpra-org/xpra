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
SELECTION = "XPRA_SELECTION_NOTIFY_TEST"

# `SelectionNotify` is how a selection owner - or the X server itself, when there is
# no owner - answers `XConvertSelection`. A refusal carries no property, so unless the
# event reaches the window which asked for the conversion, it cannot be told apart
# from an owner which never answers at all.
#
# This runs in a subprocess: binding the X11 bindings to a display is process-global
# and cannot be undone, so doing it in the test process would leave every later test
# with a pointer to a display we are about to kill.
CHECKS = r"""
import sys
from time import monotonic, sleep

from xpra.os_util import gi_import
from xpra.x11.bindings.display_source import init_display_source
from xpra.x11.bindings.loop import register_glib_source

GObject = gi_import("GObject")
GLib = gi_import("GLib")

init_display_source()
register_glib_source(GLib.MainContext.default())

from xpra.util.gobject import one_arg_signal
from xpra.x11.bindings.core import constants
from xpra.x11.bindings.window import X11WindowBindings
from xpra.x11.dispatch import add_event_receiver, remove_event_receiver
from xpra.x11.error import xsync

SELECTION = sys.argv[1]
TARGET = "TARGETS"
CurrentTime = constants["CurrentTime"]
X11Window = X11WindowBindings()
failures = []


def check(name, condition, message):
    if not condition:
        failures.append("%s: %s" % (name, message))


class Requestor(GObject.GObject):
    __gsignals__ = {
        "x11-selection-notify": one_arg_signal,
    }

    def __init__(self):
        super().__init__()
        self.events = []

    def do_x11_selection_notify(self, event) -> None:
        self.events.append(event)


GObject.type_register(Requestor)


def wait_for(requestor, count, timeout=5) -> int:
    context = GLib.MainContext.default()
    deadline = monotonic() + timeout
    while len(requestor.events) < count and monotonic() < deadline:
        context.iteration(False)
        sleep(0.01)
    return len(requestor.events)


with xsync:
    xid = X11Window.CreateWindow(X11Window.get_root_xid(), -1, -1,
                                 event_mask=constants["PropertyChangeMask"],
                                 inputoutput=constants["InputOnly"])
requestor = Requestor()
add_event_receiver(xid, requestor)

# nobody owns this selection, so the X server answers the conversion itself:
with xsync:
    X11Window.ConvertSelection(SELECTION, TARGET, "%s-%s" % (SELECTION, TARGET), xid, time=CurrentTime)
check("server refusal", wait_for(requestor, 1) == 1, "the X server's refusal never reached the requestor")
if requestor.events:
    event = requestor.events[0]
    check("server refusal", event.requestor == xid,
          "delivered to %#x instead of %#x" % (event.requestor, xid))
    check("server refusal", event.window == event.requestor,
          "window is %#x, requestor is %#x" % (event.window, event.requestor))
    check("server refusal", event.selection == SELECTION, "selection is %r" % (event.selection, ))
    check("server refusal", event.target == TARGET, "target is %r" % (event.target, ))
    check("server refusal", not event.property, "a refusal carries no property, got %r" % (event.property, ))
    check("server refusal", not event.send_event, "the X server's own reply is not synthetic")

# a real owner answers with `XSendEvent`, so its reply is synthetic:
with xsync:
    X11Window.sendSelectionNotify(xid, SELECTION, TARGET, "", CurrentTime)
check("owner refusal", wait_for(requestor, 2) == 2, "an owner's refusal never reached the requestor")
if len(requestor.events) > 1:
    event = requestor.events[1]
    check("owner refusal", event.send_event, "an owner's reply is sent with `XSendEvent`")
    check("owner refusal", event.requestor == xid,
          "delivered to %#x instead of %#x" % (event.requestor, xid))
    check("owner refusal", not event.property, "a refusal carries no property, got %r" % (event.property, ))

remove_event_receiver(xid, requestor)
with xsync:
    X11Window.DestroyWindow(xid)

for failure in failures:
    print("FAIL %s" % failure)
print("done")
"""


class X11SelectionNotifyTest(ServerTestUtil):

    def test_selection_notify_reaches_the_requestor(self):
        display = self.find_free_display()
        xvfb = self.start_Xvfb(display)
        try:
            env = os.environ.copy()
            env["DISPLAY"] = display
            proc = subprocess.run(
                (sys.executable, "-c", CHECKS, SELECTION),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, check=False, env=env, timeout=120,
            )
        finally:
            xvfb.terminate()
        self.assertEqual(proc.returncode, 0, f"checks did not run:\n{proc.stderr}")
        self.assertIn("done", proc.stdout, f"checks did not complete:\n{proc.stderr}")
        failures = [line for line in proc.stdout.splitlines() if line.startswith("FAIL ")]
        self.assertFalse(failures, "\n".join(failures))


def main():
    # can only work with an X11 server
    if POSIX and not OSX:
        unittest.main()


if __name__ == '__main__':
    main()
