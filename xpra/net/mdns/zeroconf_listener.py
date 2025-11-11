#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket
from zeroconf import ServiceBrowser, Zeroconf

from xpra.common import noop, noerr
from xpra.log import Logger

log = Logger("network", "mdns")


class ZeroconfListener:

    def __init__(self, service_type, mdns_add=noop, mdns_remove=noop, mdns_update=noop):
        log("ZeroconfListener%s", (service_type, mdns_add, mdns_remove, mdns_update))
        self.zeroconf = Zeroconf()
        self.browser: ServiceBrowser | None = None
        if not service_type.endswith("local."):
            service_type += "local."
        self.service_type = service_type
        self.mdns_add = mdns_add
        self.mdns_remove = mdns_remove
        self.mdns_update = mdns_update

    def __repr__(self):
        return "ZeroconfListener(%s)" % self.service_type

    def update_service(self, zeroconf, stype: str, name: str) -> None:
        log("update_service%s", (zeroconf, stype, name))
        self.mdns_update(name, stype)

    def remove_service(self, zeroconf, stype: str, name: str) -> None:
        log("remove_service%s", (zeroconf, stype, name))
        domain = "local"
        self.mdns_remove(0, 0, name, stype, domain, 0)

    def add_service(self, zeroconf, stype: str, name: str) -> None:
        log("add_service%s", (zeroconf, stype, name))
        info = zeroconf.get_service_info(stype, name)
        log("service info: %s", info)
        if info:
            interface = None
            protocol = 0
            name = info.name
            stype = info.type
            domain = "local"
            server = info.server
            try:
                addresses = info.addresses
            except AttributeError:
                addresses = [info.address]
            port = info.port
            props = info.properties
            for address in addresses:
                saddress = socket.inet_ntoa(address)
                self.mdns_add(interface, protocol, name, stype, domain, server, saddress, port, props)

    def start(self) -> None:
        self.browser = ServiceBrowser(self.zeroconf, self.service_type, listener=self)
        log("ServiceBrowser%s=%s", (self.zeroconf, self.service_type, self), self.browser)

    def stop(self) -> None:
        b = self.browser
        if b:
            self.browser = None
            noerr(b.cancel)
        zc = self.zeroconf
        if zc:
            self.zeroconf = None
            noerr(zc.close)


def main() -> None:
    def mdns_add(*args):
        print(f"mdns_add: {args}")

    def mdns_remove(*args):
        print(f"mdns_remove: {args}")

    def mdns_update(*args):
        print(f"mdns_update: {args}")

    from xpra.os_util import gi_import
    GLib = gi_import("GLib")
    loop = GLib.MainLoop()

    from xpra.platform import program_context
    with program_context("zeroconf-listener", "zeroconf-listener"):
        listeners: list[ZeroconfListener] = []
        from xpra.net.mdns import XPRA_TCP_MDNS_TYPE, XPRA_UDP_MDNS_TYPE

        def add(service_type: str) -> None:
            listener = ZeroconfListener(service_type + "local.", mdns_add, mdns_remove, mdns_update)
            log(f"{listener=}")
            listener.start()

        add(XPRA_TCP_MDNS_TYPE)
        add(XPRA_UDP_MDNS_TYPE)
        try:
            loop.run()
        finally:
            for listener in listeners:
                listener.stop()


if __name__ == "__main__":
    main()
