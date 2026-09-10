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


# A conversion which is refused has to complete straight away. The only thing which
# distinguishes the repair from the defect is that the request never reaches
# `CONVERT_TIMEOUT`: both end up calling the callback with an empty value.
CONVERSION_CHECKS = r"""
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
from xpra.x11.selection.clipboard import X11Clipboard

SELECTION = sys.argv[1]
X11Window = X11WindowBindings()
failures = []


def check(name, condition, message):
    if not condition:
        failures.append("%s: %s" % (name, message))


# an owner which turns down every representation it is asked for:
class RefusingOwner(GObject.GObject):
    __gsignals__ = {
        "x11-selection-request": one_arg_signal,
    }

    def __init__(self, xid: int):
        super().__init__()
        self.xid = xid
        self.requests = []

    def do_x11_selection_request(self, event) -> None:
        self.requests.append(event)
        with xsync:
            # no property: ICCCM's negative reply
            X11Window.sendSelectionNotify(event.requestor, event.selection, str(event.target), "", event.time)


GObject.type_register(RefusingOwner)


def pump(predicate, timeout=5) -> bool:
    context = GLib.MainContext.default()
    deadline = monotonic() + timeout
    while monotonic() < deadline and not predicate():
        context.iteration(False)
        sleep(0.005)
    return predicate()


with xsync:
    oxid = X11Window.CreateWindow(X11Window.get_root_xid(), -1, -1,
                                  event_mask=constants["PropertyChangeMask"],
                                  inputoutput=constants["InputOnly"])
owner = RefusingOwner(oxid)
add_event_receiver(oxid, owner)
with xsync:
    X11Window.XSetSelectionOwner(oxid, SELECTION)
    check("owner", X11Window.XGetSelectionOwner(SELECTION) == oxid, "could not take the selection")

helper = X11Clipboard(lambda *_args: None)
helper.init_proxies([SELECTION])
proxy = helper._clipboard_proxies[SELECTION]
proxy.set_enabled(True)

results = []
start = monotonic()
proxy.get_contents("TARGETS", lambda *args: results.append(args))
check("refusal", pump(lambda: bool(results)), "the refused conversion never completed")
elapsed = 1000 * (monotonic() - start)
check("refusal", bool(owner.requests), "the owner was never asked to convert anything")
if results:
    check("refusal", results[0] == ("ATOM", 32, b""), "got %r instead of an empty target list" % (results[0], ))
# `CONVERT_TIMEOUT` is 100ms, and the whole point is not to wait for it:
check("refusal", elapsed < 100, "the refusal took %ims, which is the conversion timeout" % elapsed)

# a second conversion for the same target must not be completed by the first answer:
results.clear()
proxy.get_contents("STRING", lambda *args: results.append(args))
proxy.get_contents("STRING", lambda *args: results.append(args))
check("two", pump(lambda: len(results) == 2), "only %i of the 2 refusals completed" % len(results))
check("two", results == [("", 0, b"")] * 2, "got %r" % (results, ))
check("two", not proxy.local_requests, "requests are still pending: %s" % (proxy.local_requests, ))

helper.cleanup()
remove_event_receiver(oxid, owner)
with xsync:
    X11Window.DestroyWindow(oxid)

for failure in failures:
    print("FAIL %s" % failure)
print("done")
"""


class X11SelectionNotifyTest(ServerTestUtil):

    def run_checks(self, checks: str) -> None:
        display = self.find_free_display()
        xvfb = self.start_Xvfb(display)
        try:
            env = os.environ.copy()
            env["DISPLAY"] = display
            proc = subprocess.run(
                (sys.executable, "-c", checks, SELECTION),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, check=False, env=env, timeout=120,
            )
        finally:
            xvfb.terminate()
        self.assertEqual(proc.returncode, 0, f"checks did not run:\n{proc.stderr}")
        self.assertIn("done", proc.stdout, f"checks did not complete:\n{proc.stderr}")
        failures = [line for line in proc.stdout.splitlines() if line.startswith("FAIL ")]
        self.assertFalse(failures, "\n".join(failures))
        # `timeout_get_contents` is the failure this is all about:
        self.assertNotIn("timed out", proc.stderr, f"a conversion timed out:\n{proc.stderr}")

    def test_selection_notify_reaches_the_requestor(self):
        self.run_checks(CHECKS)

    def test_a_refused_conversion_does_not_time_out(self):
        self.run_checks(CONVERSION_CHECKS)


def main():
    # can only work with an X11 server
    if POSIX and not OSX:
        unittest.main()


if __name__ == '__main__':
    main()
