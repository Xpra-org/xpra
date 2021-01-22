#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010, 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject

from xpra.log import Logger
log = Logger()

from xpra.client.gobject_client_base import CommandConnectClient


class TestIllegalCommandClient(CommandConnectClient):
    """
        Sending an illegal command should get us kicked out
    """

    def __init__(self, conn, opts):
        CommandConnectClient.__init__(self, conn, opts)
        def check_kicked_out(*args):
            log.error("BUG: illegal command did not get us kicked out: we are still connected!")
            self.quit()
        gobject.timeout_add(5*1000, check_kicked_out)

    def send_hello(self, challenge_response=None):
        #we should not be able to do this before hello:
        for i in range(1, 10):
            self.send("close-window", i)

    def quit(self, *args):
        log.info("OK: server correctly terminated the connection")
        CommandConnectClient.quit(self)

def main():
    import sys
    from tests.xpra.clients.test_DoS_client import test_DoS
    test_DoS(TestIllegalCommandClient, sys.argv)


if __name__ == "__main__":
    main()
