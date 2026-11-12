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
SELECTION = "XPRA_CLIPBOARD_ATOMS_TEST"

# X11 atoms are never freed, so the clipboard peer must not be able to make us create
# as many as it likes: every target and type name it sends us may become one.
#
# This runs in a subprocess: binding the X11 bindings to a display is process-global
# and cannot be undone, so doing it in the test process would leave every later test
# with a pointer to a display we are about to kill.
CHECKS = r"""
import sys
from xpra.os_util import gi_import
from xpra.x11.bindings.display_source import init_display_source
from xpra.x11.bindings.loop import register_glib_source

GLib = gi_import("GLib")
init_display_source()
register_glib_source(GLib.MainContext.default())

from xpra.net.common import Packet
from xpra.x11.bindings.core import X11CoreBindings
from xpra.x11.error import xsync
from xpra.x11.selection import clipboard
from xpra.x11.selection.clipboard import X11Clipboard

SELECTION = sys.argv[1]
LIMIT = 4
clipboard.MAX_CLIPBOARD_ATOMS = LIMIT
X11Core = X11CoreBindings()
failures = []


def check(name, condition, message):
    if not condition:
        failures.append("%s: %s" % (name, message))


def exists(*names) -> set:
    with xsync:
        return set(X11Core.get_existing_atoms(names))


packets = []
helper = X11Clipboard(lambda *packet: packets.append(packet), **{"clipboards.local": (SELECTION, )})
helper.init_proxies([SELECTION])
helper._clipboard_proxies[SELECTION].set_enabled(True)

# only the core protocol's atoms are predefined on a bare Xvfb:
check("lookup", exists("STRING", "XPRA_TEST_NO_SUCH_ATOM") == {"STRING"},
      "get_existing_atoms must find existing atoms only")
check("lookup", not exists("XPRA_TEST_NO_SUCH_ATOM"), "get_existing_atoms must not create atoms")

# atoms which already exist are free:
check("existing", helper.accept_names(("STRING", "ATOM")) == {"STRING", "ATOM"},
      "existing atoms should be accepted")
check("existing", not helper._peer_atoms, "existing atoms must not use the budget")

new_names = tuple("text/x-xpra-test-%i" % i for i in range(LIMIT + 2))
targets = helper.local_targets(("STRING", ) + new_names)
check("budget", targets == ("STRING", ) + new_names[:LIMIT], "unexpected targets: %s" % (targets, ))
check("budget", len(helper._peer_atoms) == LIMIT, "budget not used: %s" % (helper._peer_atoms, ))
# names we have accepted remain usable, and become real atoms once used:
with xsync:
    X11Core.intern_atoms(new_names[:LIMIT])
check("budget", helper.may_intern(new_names[0]), "an accepted name should remain usable")
check("budget", not helper.may_intern(new_names[-1]), "the budget is exhausted")
check("budget", not exists(*new_names[LIMIT:]), "rejected names must not become atoms")

# a request also converts the selection into a property named after the target:
helper.process_clipboard_packet(Packet("clipboard-request", 1, SELECTION, "text/x-xpra-test-request"))
check("request", packets == [("clipboard-contents-none", 1, SELECTION)], "unexpected reply: %s" % (packets, ))
check("request", not exists("text/x-xpra-test-request", SELECTION + "-text/x-xpra-test-request"),
      "a refused request must not create atoms")
helper.cleanup()

for failure in failures:
    print("FAIL %s" % failure)
print("done")
"""


class X11ClipboardAtomsTest(ServerTestUtil):

    def test_atom_budget(self):
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
