#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
from subprocess import PIPE

from unit.client.x11_client_test_util import X11ClientTestUtil
from xpra.util.env import envbool
from xpra.os_util import get_hex_uuid
from xpra.util.io import pollwait, which
from xpra.log import Logger

log = Logger("clipboard")

SANITY_CHECKS = envbool("XPRA_CLIPBOARD_SANITY_CHECKS", True)


def has_xclip():
    return bool(which("xclip"))


class X11ClipboardTestUtil(X11ClientTestUtil):

    @staticmethod
    def proc_output(proc) -> str:
        """
        What a command wrote before it failed.
        `class_run_command` redirects to temporary files unless pipes are asked for,
        so this has to be read back from them - we cannot use pipes for `xclip -i`,
        which forks and holds them open for as long as it owns the selection.
        """
        msgs = []
        for name, f in (("stdout", proc.stdout_file), ("stderr", proc.stderr_file)):
            if not f:
                #ie: XPRA_TEST_DEBUG sends the output to the terminal instead
                continue
            try:
                with open(f.name, "rb") as fd:
                    data = fd.read().decode("utf8", "replace").strip()
            except OSError as e:
                data = "cannot be read: %s" % e
            if data:
                msgs.append("%s=%r" % (name, data))
        return ", ".join(msgs) or "no output"

    def get_clipboard_value(self, display, selection="clipboard"):
        """
        Returns the contents of the selection, and what `xclip` complained about.
        `xclip -o` fails whenever the selection has no owner, which is a legitimate
        outcome here, so the error is handed back instead of raising - already
        formatted so that the caller can append it to its assertion message.
        """
        cmd = "xclip -display %s -selection %s -o" % (display, selection)
        proc = self.class_run_command(cmd, shell=True, stdout=PIPE, stderr=PIPE)
        out, err = proc.communicate()
        error = ""
        if proc.returncode != 0:
            error = " ('%s' returned %s: %s)" % (
                cmd, proc.returncode, err.decode("utf8", "replace").strip() or "no error output")
        return out.decode(), error

    def set_clipboard_value(self, display, value, selection="clipboard"):
        cmd = "echo -n '%s' | xclip -display %s -selection %s -i" % (value, display, selection)
        xclip = self.run_command(cmd, shell=True)
        r = pollwait(xclip, 5)
        assert r==0, "xclip command '%s' returned %s (%s)" % (cmd, r, self.proc_output(xclip))

    def copy_and_verify(self, display1, display2, synced=True, wait=1, selection="clipboard"):
        log("copy_and_verify%s", (display1, display2, synced, wait, selection))
        value = get_hex_uuid()
        self.set_clipboard_value(display1, value, selection)
        #wait for synchronization to occur:
        time.sleep(wait)
        new_value, error = self.get_clipboard_value(display2, selection)
        if synced:
            assert new_value==value, "clipboard contents for %s do not match, expected '%s' but got '%s'%s" % (
                selection, value, new_value, error)
        else:
            assert new_value!=value, "clipboard contents for %s match but synchronization was not expected: value='%s'" % (selection, value)
        if SANITY_CHECKS and display2!=display1:
            #verify that the value has not changed on the original display:
            new_value, error = self.get_clipboard_value(display1, selection)
            assert new_value==value, "clipboard contents for %s changed on the display we copied from, expected '%s' but got '%s'%s" % (
                selection, value, new_value, error)
        return value

    def do_test_copy_selection(self, selection="clipboard", direction="both"):
        log("do_test_copy(%s, %s)", selection, direction)
        server = self.run_server()
        server_display = server.display
        #connect a client:
        xvfb, client = self.run_client(server_display,
                                       "--clipboard-direction=%s" % direction, "--remote-logging=no")
        assert pollwait(client, 2) is None, "client has exited with return code %s" % client.poll()
        client_display = xvfb.display

        #wait for client to own the clipboard:
        cmd = self.get_xpra_cmd()+["info", server_display]
        for _ in range(10):
            out = X11ClientTestUtil.get_command_output(cmd)
            if out.find(b"clipboard.client=")>0:
                break
            time.sleep(1)

        if SANITY_CHECKS:
            log("sanity checks")
            #xclip sanity check: retrieve from the same display.
            #these copies are synchronized to the other display just like any other one,
            #so they have to be given the time to land there before the next one is made:
            #otherwise this check ends up reading the value the other display has just sent us
            self.copy_and_verify(client_display, client_display, True, selection=selection)
            self.copy_and_verify(server_display, server_display, True, selection=selection)

        log("copy client %s to server %s", client_display, server_display)
        for _ in range(2):
            self.copy_and_verify(client_display, server_display, direction in ("both", "to-server"), selection=selection)
        log("copy server %s to client %s", server_display, client_display)
        for _ in range(2):
            self.copy_and_verify(server_display, client_display, direction in ("both", "to-client"), selection=selection)
        log("copy client %s to server %s", client_display, server_display)
        for _ in range(2):
            self.copy_and_verify(client_display, server_display, direction in ("both", "to-server"), selection=selection)

        client.terminate()
        xvfb.terminate()
        server.terminate()

    def do_test_copy(self, direction="both"):
        from xpra.clipboard.common import get_local_selections
        for selection in get_local_selections():
            self.do_test_copy_selection(selection, direction)
