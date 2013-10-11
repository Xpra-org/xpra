#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject

from xpra.log import Logger
log = Logger()

from xpra.client.gobject_client_base import CommandConnectClient


class TestMemoryClient(CommandConnectClient):
    """
        Try to exhaust server memory without authenticating by sending an overly large packet.
    """

    def __init__(self, conn, opts):
        CommandConnectClient.__init__(self, conn, opts)
        def check_connection_dead(*args):
            self.send("irrelevant")
        gobject.timeout_add(1000, check_connection_dead)
        def check_connection_timeout(*args):
            log.error("BUG: packet size failsafe did not fire: we are still connected!")
            self.quit()
        gobject.timeout_add(20*1000, check_connection_timeout)

    def make_hello(self, challenge_response=None):
        capabilities = CommandConnectClient.make_hello(self, challenge_response)
        capabilities["waste_of_space"] = "\0" * (1024*1024)
        return capabilities

    def quit(self, *args):
        log.info("OK: server correctly terminated the connection")
        CommandConnectClient.quit(self, 0)

def main():
    import sys
    from tests.xpra.clients.test_DoS_client import test_DoS
    test_DoS(TestMemoryClient, sys.argv)


if __name__ == "__main__":
    main()
