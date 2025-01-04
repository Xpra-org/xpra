#!/usr/bin/env python3

# This file is part of Xpra.
# Copyright (C) 2009 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import avahi  # @UnresolvedImport
import dbus
from typing import Any

from xpra.net.mdns import XPRA_TCP_MDNS_TYPE, XPRA_UDP_MDNS_TYPE
from xpra.dbus.common import init_system_bus
from xpra.dbus.helper import dbus_to_native
from xpra.log import Logger

log = Logger("network", "mdns")


class Avahilistener:

    def __init__(self, service_type=XPRA_TCP_MDNS_TYPE,
                 mdns_found=None, mdns_add=None, mdns_remove=None, mdns_update=None):
        log("Avahilistener%s", (service_type, mdns_found, mdns_add, mdns_remove, mdns_update))
        try:
            self.bus = init_system_bus()
            assert self.bus
        except Exception as e:
            log.warn("failed to connect to the system dbus: %s", e)
            log.warn(" either start a dbus session or disable mdns support")
            return
        self.sdref = None
        self.readers = []
        self.resolvers = []
        self.signal_match = []
        self.service_type = service_type
        self.mdns_found = mdns_found
        self.mdns_add = mdns_add
        self.mdns_remove = mdns_remove
        # self.mdns_update = mdns_update
        self.server: Any = None
        self.sbrowser: Any = None

    @staticmethod
    def resolve_error(*args) -> None:
        log.error("Avahilistener.resolve_error%s", args)

    def service_resolved(self, interface, protocol, name: str, stype: str,
                         domain: str, host: str, x, address, port: int, text_array, v) -> None:
        log("Avahilistener.service_resolved%s",
            (interface, protocol, name, stype, domain, host, x, address, port, "..", v))
        if self.mdns_add:
            # parse text data:
            text = {}
            with log.trap_error("Error parsing text record"):
                for text_line in text_array:
                    line = ""
                    for b in text_line:
                        line += chr(b.real)
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        text[parts[0]] = parts[1]
                log(" text=%s", text)
            nargs = (dbus_to_native(x) for x in (interface, protocol, name, stype, domain, host, address, port, text))
            self.mdns_add(*nargs)

    def service_found(self, interface, protocol, name: str, stype: str, domain: str, flags: int) -> None:
        log("service_found%s", (interface, protocol, name, stype, domain, flags))
        if flags & avahi.LOOKUP_RESULT_LOCAL:
            # local service, skip
            pass
        if self.mdns_found:
            self.mdns_found(dbus_to_native(interface), dbus_to_native(name))
        self.server.ResolveService(interface, protocol, name, stype,
                                   domain, avahi.PROTO_UNSPEC, dbus.UInt32(0),
                                   reply_handler=self.service_resolved, error_handler=self.resolve_error)

    def service_removed(self, interface, protocol, name: str, stype: str, domain, flags: int) -> None:
        log("service_removed%s", (interface, protocol, name, stype, domain, flags))
        if self.mdns_remove:
            nargs = (dbus_to_native(x) for x in (interface, protocol, name, stype, domain, flags))
            self.mdns_remove(*nargs)

    def start(self) -> None:
        self.server = dbus.Interface(self.bus.get_object(avahi.DBUS_NAME, '/'), 'org.freedesktop.Avahi.Server')
        log("Avahilistener.start() server=%s", self.server)

        self.sbrowser = dbus.Interface(
            self.bus.get_object(avahi.DBUS_NAME,
                                self.server.ServiceBrowserNew(avahi.IF_UNSPEC, avahi.PROTO_UNSPEC,
                                                              self.service_type, 'local', dbus.UInt32(0)
                                                              )
                                ),
            avahi.DBUS_INTERFACE_SERVICE_BROWSER)
        log("Avahilistener.start() service browser=%s", self.sbrowser)
        s = self.sbrowser.connect_to_signal("ItemNew", self.service_found)
        self.signal_match.append(s)
        s = self.sbrowser.connect_to_signal("ItemRemove", self.service_removed)
        self.signal_match.append(s)

    def stop(self) -> None:
        sm = self.signal_match
        self.signal_match = []
        for s in sm:
            try:
                s.remove()
            except Exception:
                log.warn("Warning: failed to remove signal", exc_info=True)


def main():
    def mdns_found(*args):
        print(f"mdns_found: {args}")

    def mdns_add(*args):
        print(f"mdns_add: {args}")

    def mdns_remove(*args):
        print(f"mdns_remove: {args}")

    # we must preserve the order here
    # (as dbus loop_init injects some magic)
    from xpra.dbus.common import loop_init
    loop_init()
    from xpra.os_util import gi_import
    glib = gi_import("GLib")
    listeners: list[Avahilistener] = []

    def add(service_type):
        listener = Avahilistener(service_type, mdns_found, mdns_add, mdns_remove)
        listeners.append(listener)
        glib.idle_add(listener.start)

    add(XPRA_TCP_MDNS_TYPE)
    add(XPRA_UDP_MDNS_TYPE)
    try:
        glib.MainLoop().run()
    finally:
        for listener in listeners:
            listener.stop()


if __name__ == "__main__":
    main()
