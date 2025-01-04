#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from xpra.os_util import WIN32
from xpra.util.io import pollwait
from unit.server_test_util import ServerTestUtil, log


class ProxyServerTest(ServerTestUtil):

    def test_proxy_start_stop(self):
        display = self.find_free_display()
        log(f"using free display={display}")
        cmd = ["proxy", display, "--no-daemon"]
        cmdstr = " ".join(f"'{c}'" for c in cmd)
        proxy = self.run_xpra(cmd)
        r = pollwait(proxy, 5)
        if r is not None:
            self.show_proc_pipes(proxy)
        assert r is None, f"proxy failed to start with cmd={cmdstr}, exit code={r}"
        displays = self.dotxpra.displays()
        assert display in displays, f"proxy display {display!r} not found in {displays}"
        self.check_stop_server(proxy, "stop", display)

    def stop_server(self, server_proc, subcommand, *connect_args):
        if WIN32:
            super().stop_server(server_proc, subcommand, *connect_args)
            return
        log("stop_server%s", (server_proc, subcommand, connect_args))
        if server_proc.poll() is not None:
            return
        server_proc.terminate()
        assert pollwait(server_proc) is not None, f"server process {server_proc} failed to exit"


def main():
    unittest.main()


if __name__ == '__main__':
    main()
