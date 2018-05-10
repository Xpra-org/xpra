#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("network", "mdns")

import socket
from xpra.util import csv
from xpra.net.net_util import get_interfaces_addresses
from xpra.net.mdns import XPRA_MDNS_TYPE, SHOW_INTERFACE
from zeroconf import ServiceInfo, Zeroconf        #@UnresolvedImport

from xpra.net.net_util import get_iface

def get_interface_index(host):
    #we don't use interface numbers with zeroconf,
    #so just return the interface name,
    #which is also unique
    return get_iface(host)

class ZeroconfPublishers(object):
    """
    Expose services via python zeroconf
    """

    def __init__(self, listen_on, service_name, service_type=XPRA_MDNS_TYPE, text_dict={}):
        log("ZeroconfPublishers%s", (listen_on, service_name, service_type, text_dict))
        self.services = []
        self.registered = []
        errs = 0
        hostname = socket.gethostname()+".local."
        all_listen_on = []
        for host_str, port in listen_on:
            if host_str=="":
                hosts = ["127.0.0.1", "::"]
            else:
                hosts = [host_str]
            for host in hosts:
                if host in ("0.0.0.0", "::", ""):
                    #annoying: we have to enumerate all interfaces
                    for iface, addresses in get_interfaces_addresses().items():
                        for af in (socket.AF_INET, socket.AF_INET6):
                            for defs in addresses.get(af, []):
                                addr = defs.get("addr")
                                if addr:
                                    try:
                                        addr_str = addr.split("%", 1)[0]
                                        address = socket.inet_pton(af, addr_str)
                                    except OSError as e:
                                        log("socket.inet_pton '%s'", addr_str, exc_info=True)
                                        log.error("Error: cannot parse IP address '%s'", addr_str)
                                        log.error(" %s", e)
                                        continue
                                    all_listen_on.append((addr_str, port, address))
                    continue
                try:
                    if host.find(":")>=0:
                        address = socket.inet_pton(socket.AF_INET6, host)
                    else:
                        address = socket.inet_pton(socket.AF_INET, host)
                except OSError as e:
                    log("socket.inet_pton '%s'", host, exc_info=True)
                    log.error("Error: cannot parse IP address '%s'", host)
                    log.error(" %s", e)
                    continue
                all_listen_on.append((host, port, address))
        log("will listen on: %s", all_listen_on)
        for host, port, address in all_listen_on:
            td = text_dict
            iface = get_iface(host)
            if iface is not None and SHOW_INTERFACE:
                td = text_dict.copy()
                td["iface"] = iface
            try:
                service = ServiceInfo(service_type+"local.", service_name+"."+service_type+"local.",
                                      address, port, 0, 0,
                                      td, hostname)
                self.services.append(service)
            except Exception as e:
                log("zeroconf ServiceInfo", exc_info=True)
                if errs==0:
                    log.error("Error: zeroconf failed to create service")
                log.error(" for host '%s' and port %i", host, port)
                log.error(" %s", e)
                errs += 1

    def start(self):
        self.zeroconf = Zeroconf()
        self.registered = []
        for service in self.services:
            try:
                self.zeroconf.register_service(service)
            except Exception:
                log("start failed on %s", service, exc_info=True)
            else:
                self.registered.append(service)

    def stop(self):
        registered = self.registered
        log("ZeroConfPublishers.stop(): %s" % csv(registered))
        self.registered = []
        for reg in registered:
            self.zeroconf.unregister_service(reg)
        self.zeroconf = None


def main():
    import random
    port = int(20000*random.random())+10000
    #host = "127.0.0.1"
    host = "0.0.0.0"
    host_ports = [(host, port)]
    ID = "test %s" % int(random.random()*100000)
    publisher = ZeroconfPublishers(host_ports, ID, XPRA_MDNS_TYPE, {"somename":"somevalue"})
    from xpra.gtk_common.gobject_compat import import_glib
    glib = import_glib()
    glib.idle_add(publisher.start)
    loop = glib.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        publisher.stop()
        loop.quit()


if __name__ == "__main__":
    main()
