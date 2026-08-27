#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.os_util import get_hex_uuid
from xpra.util.env import osexpand
from xpra.util.io import pollwait
from unit.server_test_util import ServerTestUtil, log


class X11ClientTestUtil(ServerTestUtil):
    uq = 0

    def terminate_and_wait(self, proc, timeout=5) -> None:
        # a bare `proc.terminate()` only sends the signal and returns immediately:
        # the next test's `find_free_display()` can then race this process's own
        # display/socket cleanup and end up reusing a display it hasn't released yet:
        if proc.poll() is None:
            proc.terminate()
            if pollwait(proc, timeout) is None:
                proc.kill()
                pollwait(proc, timeout)

    def run_client(self, *args):
        client_display = self.find_free_display()
        xvfb = self.start_Xvfb(client_display)
        xvfb.display = client_display
        return xvfb, self.do_run_client(client_display, *args)

    def do_run_client(self, client_display, *args):
        from xpra.x11.vfb_util import xauth_add

        xauth_data = get_hex_uuid()
        xauthority = self.default_env.get("XAUTHORITY", osexpand("~/.Xauthority"))
        xauth_add(xauthority, client_display, xauth_data, os.getuid(), os.getgid())
        env = self.get_run_env()
        env["DISPLAY"] = client_display
        env["XPRA_LOG_PREFIX"] = "client %i: " % X11ClientTestUtil.uq
        X11ClientTestUtil.uq += 1
        log("starting test client on Xvfb %s", client_display)
        return self.run_xpra(["attach"] + list(args), env=env)
