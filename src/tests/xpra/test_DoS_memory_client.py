#!/usr/bin/env python
# This file is part of Parti.
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject

from wimpiggy.log import Logger
log = Logger()

from xpra.client_base import XpraClientBase, GLibXpraClient

class TestMemoryClient(GLibXpraClient):
    """
        Try to exhaust server memory without authenticating by sending an overly large packet.
    """

    def __init__(self, conn, opts):
        GLibXpraClient.__init__(self, conn, opts)
        def check_connection_dead(*args):
            self.send("irrelevant")
        gobject.timeout_add(1000, check_connection_dead)
        def check_connection_timeout(*args):
            log.error("BUG: packet size failsafe did not fire: we are still connected!")
            self.quit()
        gobject.timeout_add(20*1000, check_connection_timeout)

    def make_hello(self, challenge_response=None):
        capabilities = XpraClientBase.make_hello(self, challenge_response)
        capabilities["waste_of_space"] = "\0" * (32*1024)
        return capabilities

    def quit(self, *args):
        log.info("server correctly terminated the connection")
        GLibXpraClient.quit(self)

def main():
    import sys
    from tests.xpra.test_DoS_client import test_DoS
    test_DoS(TestMemoryClient, sys.argv)


if __name__ == "__main__":
    main()
