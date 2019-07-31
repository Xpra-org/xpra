#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket
from zeroconf import ServiceInfo, Zeroconf        #@UnresolvedImport

from xpra.log import Logger
from xpra.util import csv
from xpra.net.net_util import get_interfaces_addresses
from xpra.net.mdns import XPRA_MDNS_TYPE, SHOW_INTERFACE
from xpra.net.net_util import get_iface

log = Logger("network", "mdns")


def get_interface_index(host):
    #we don't use interface numbers with zeroconf,
    #so just return the interface name,
    #which is also unique
    return get_iface(host)


def inet_ton(af, addr):
    if af==socket.AF_INET:
        return socket.inet_aton(addr)
    inet_pton = getattr(socket, "inet_pton", None)
    if not inet_pton:
        #no ipv6 support with python2 on win32:
        return None
    return inet_pton(af, addr)   #@UndefinedVariable


class ZeroconfPublishers(object):
    """
    Expose services via python zeroconf
    """

    def __init__(self, listen_on, service_name, service_type=XPRA_MDNS_TYPE, text_dict=None):
        log("ZeroconfPublishers%s", (listen_on, service_name, service_type, text_dict))
        self.zeroconf = None
        self.services = []
        self.registered = []
        errs = 0
        hostname = socket.gethostname()+".local."
        all_listen_on = []
        for host_str, port in listen_on:
            if host_str=="":
                hosts = ("127.0.0.1", "::")
            else:
                hosts = (host_str,)
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
                                        address = inet_ton(af, addr_str)
                                        if address:
                                            all_listen_on.append((addr_str, port, address))
                                    except OSError as e:
                                        log("socket.inet_pton '%s'", addr_str, exc_info=True)
                                        log.error("Error: cannot parse IP address '%s'", addr_str)
                                        log.error(" %s", e)
                                        continue
                    continue
                try:
                    if host.find(":")>=0:
                        af = socket.AF_INET6
                    else:
                        af = socket.AF_INET
                    address = inet_ton(af, host)
                    if address:
                        all_listen_on.append((host, port, address))
                except OSError as e:
                    log("socket.inet_pton '%s'", host, exc_info=True)
                    log.error("Error: cannot parse IP address '%s'", host)
                    log.error(" %s", e)
                    continue
        log("will listen on: %s", all_listen_on)
        for host, port, address in all_listen_on:
            td = text_dict or {}
            iface = get_iface(host)
            if iface is not None and SHOW_INTERFACE:
                td = text_dict.copy()
                td["iface"] = iface
            td = self.txt_rec(td)
            try:
                #ie: service_name = localhost.localdomain :2 (ssl)
                st = service_type+"local."
                parts = service_name.split(" ", 1)
                regname = parts[0].split(".")[0]
                if len(parts)==2:
                    regname += parts[1]
                regname = regname.replace(" ", "-")
                regname = regname.replace("(", "")
                regname = regname.replace(")", "")
                #ie: regname = localhost:2-ssl
                regname += "."+service_type+"local."
                args = (st, regname, address, port, 0, 0, td, hostname)
                service = ServiceInfo(*args)
                ServiceInfo.args = args
                log("ServiceInfo%s=%s", args, service)
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


    def txt_rec(self, text_dict):
        #prevent zeroconf from mangling our ints into booleans:
        from collections import OrderedDict
        new_dict = OrderedDict()
        for k,v in text_dict.items():
            if isinstance(v, int):
                new_dict[k] = str(v)
            else:
                new_dict[k] = v
        return new_dict

    def update_txt(self, txt):
        for service in tuple(self.registered):
            args = list(service.args)
            args[6] = self.txt_rec(txt)
            si = ServiceInfo(*args)
            self.zeroconf.update_service(si)


def main():
    import random
    port = int(20000*random.random())+10000
    #host = "127.0.0.1"
    host = "0.0.0.0"
    host_ports = [(host, port)]
    service_name = "test %s" % int(random.random()*100000)
    publisher = ZeroconfPublishers(host_ports, service_name, XPRA_MDNS_TYPE, {"somename":"somevalue"})
    from xpra.gtk_common.gobject_compat import import_glib
    glib = import_glib()
    glib.idle_add(publisher.start)
    loop = glib.MainLoop()
    def update_rec():
        log("update_rec()")
        from zeroconf import DNSText, _CLASS_ANY, _DNS_OTHER_TTL, current_time_millis
        import struct
        int2byte = struct.Struct(">B").pack
        item = b"key=value"
        txt_data = b"".join((int2byte(len(item)), item))
        for service in publisher.services:
            rec = DNSText(service.name, service.type, _CLASS_ANY, _DNS_OTHER_TTL, txt_data)
            #service.update_record(time.time(), rec)
            #service._set_properties({"hello" : "world"})
            publisher.zeroconf.update_record(current_time_millis(), rec)
        #publisher.zeroconf.notify_all()
        return False
    glib.timeout_add(10*1000, update_rec)
    try:
        loop.run()
    except KeyboardInterrupt:
        publisher.stop()
        loop.quit()


if __name__ == "__main__":
    main()
