#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2017-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket
from zeroconf import ServiceBrowser, Zeroconf        #@UnresolvedImport

from xpra.log import Logger

log = Logger("network", "mdns")


class ZeroconfListener:

    def __init__(self, service_type, mdns_found=None, mdns_add=None, mdns_remove=None):
        log("ZeroconfListener%s", (service_type, mdns_found, mdns_add, mdns_remove))
        self.zeroconf = Zeroconf()
        self.browser = None
        if not service_type.endswith("local."):
            service_type += "local."
        self.service_type = service_type
        self.mdns_found = mdns_found
        self.mdns_add = mdns_add
        self.mdns_remove = mdns_remove

    def __repr__(self):
        return "ZeroconfListener(%s)" % self.service_type

    def remove_service(self, zeroconf, stype, name):
        log("remove_service%s", (zeroconf, stype, name))
        if self.mdns_remove:
            domain = "local"
            self.mdns_remove(0, 0, name, stype, domain, 0)

    def add_service(self, zeroconf, stype, name):
        log("add_service%s", (zeroconf, stype, name))
        info = zeroconf.get_service_info(stype, name)
        log("service info: %s", info)
        if self.mdns_add and info:
            interface = 0
            protocol = 0
            name = info.name
            stype = info.type
            domain = "local"
            server = info.server
            address = socket.inet_ntoa(info.address)
            port = info.port
            props = info.properties
            self.mdns_add(interface, protocol, name, stype, domain, server, address, port, props)

    def start(self):
        self.browser = ServiceBrowser(self.zeroconf, self.service_type, listener=self)
        log("ServiceBrowser%s=%s", (self.zeroconf, self.service_type, self), self.browser)

    def stop(self):
        b = self.browser
        if b:
            self.browser = None
            try:
                b.cancel()
            except Exception:
                pass
        zc = self.zeroconf
        if zc:
            self.zeroconf = None
            try:
                zc.close()
            except Exception:
                pass


def main():
    def mdns_found(*args):
        print("mdns_found: %s" % (args, ))
    def mdns_add(*args):
        print("mdns_add: %s" % (args, ))
    def mdns_remove(*args):
        print("mdns_remove: %s" % (args, ))

    from gi.repository import GLib
    loop = GLib.MainLoop()

    from xpra.platform import program_context
    with program_context("zeroconf-listener", "zeroconf-listener"):
        from xpra.net.mdns import XPRA_MDNS_TYPE
        listener = ZeroconfListener(XPRA_MDNS_TYPE+"local.", mdns_found, mdns_add, mdns_remove)
        log("listener=%s" % listener)
        listener.start()
        try:
            loop.run()
        finally:
            listener.stop()


if __name__ == "__main__":
    main()
