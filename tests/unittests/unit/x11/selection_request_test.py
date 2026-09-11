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
SELECTION = "XPRASELECTIONREQUESTTEST"

# What a local application does when it pastes from the clipboard we hold for the
# remote end: it converts the selection, and we answer once the peer has sent the
# data over. Nothing in this path is optional - an application which is not
# answered waits forever, which is what `xclip -o` does.
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
from xpra.x11.selection.clipboard import X11Clipboard

SELECTION = sys.argv[1]
TARGET = "UTF8_STRING"
PROPERTY = "XCLIP_OUT"
VALUE = b"what the peer sent us"
X11Window = X11WindowBindings()
failures = []


def check(name, condition, message):
    if not condition:
        failures.append("%s: %s" % (name, message))


# an application pasting from the clipboard:
class Application(GObject.GObject):
    __gsignals__ = {
        "x11-selection-notify": one_arg_signal,
    }

    def __init__(self, xid: int):
        super().__init__()
        self.xid = xid
        self.answers = []

    def do_x11_selection_notify(self, event) -> None:
        self.answers.append(event)


GObject.type_register(Application)


def pump(predicate, timeout=5) -> bool:
    context = GLib.MainContext.default()
    deadline = monotonic() + timeout
    while monotonic() < deadline and not predicate():
        context.iteration(False)
        sleep(0.005)
    return predicate()


helper = X11Clipboard(lambda *_args: None)
helper.init_proxies([SELECTION])
proxy = helper._clipboard_proxies[SELECTION]
proxy.set_enabled(True)
proxy.set_direction(True, True)

# the remote end owns the clipboard, and we hold the selection on its behalf:
requests = []
proxy.connect("send-clipboard-request", lambda _proxy, _selection, target: requests.append(target))
proxy.got_token((TARGET, ), claim=True)
check("owner", proxy.owned, "the proxy did not take the selection")

with xsync:
    axid = X11Window.CreateWindow(X11Window.get_root_xid(), -1, -1,
                                  event_mask=constants["PropertyChangeMask"],
                                  inputoutput=constants["InputOnly"])
application = Application(axid)
add_event_receiver(axid, application)

with xsync:
    X11Window.ConvertSelection(SELECTION, TARGET, PROPERTY, axid, time=constants["CurrentTime"])
check("request", pump(lambda: TARGET in requests), "the request never reached the peer: %s" % (requests, ))

# the peer answers, and the application gets its data:
proxy.got_contents(TARGET, TARGET, 8, VALUE)
check("answer", pump(lambda: bool(application.answers)), "the application was never answered")
if application.answers:
    event = application.answers[0]
    check("answer", event.property == PROPERTY, "answered on %r instead of %r" % (event.property, PROPERTY))
    with xsync:
        data = X11Window.XGetWindowProperty(axid, PROPERTY, TARGET)
    check("answer", data == VALUE, "got %r instead of %r" % (data, VALUE))

helper.cleanup()
remove_event_receiver(axid, application)
with xsync:
    X11Window.DestroyWindow(axid)

for failure in failures:
    print("FAIL %s" % failure)
print("done")
"""


class X11SelectionRequestTest(ServerTestUtil):

    def test_a_local_paste_is_answered(self):
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
        # the handler runs from the event dispatcher, which turns an error into a log entry:
        self.assertNotIn("Traceback", proc.stderr, f"the selection request raised:\n{proc.stderr}")


def main():
    # can only work with an X11 server
    if POSIX and not OSX:
        unittest.main()


if __name__ == '__main__':
    main()
