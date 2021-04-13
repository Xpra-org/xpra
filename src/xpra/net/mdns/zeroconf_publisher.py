#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket
from zeroconf import ServiceInfo, Zeroconf, __version__ as zeroconf_version #@UnresolvedImport

from xpra.log import Logger
from xpra.util import envbool
from xpra.net.net_util import get_interfaces_addresses
from xpra.net.mdns import XPRA_MDNS_TYPE
from xpra.net.net_util import get_iface

log = Logger("network", "mdns")
log("python-zeroconf version %s", zeroconf_version)

IPV6 = envbool("XPRA_ZEROCONF_IPV6", False)


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
        self.services = []
        self.ports = {}
        def add_address(host, port, af=socket.AF_INET):
            try:
                if af==socket.AF_INET6 and host.find("%"):
                    host = host.split("%")[0]
                address = inet_ton(af, host)
                sn = service_name
                ports = set(self.ports.get(service_name, ()))
                log("add_address(%s, %s, %s) ports=%s", host, port, af, ports)
                ports.add(port)
                if len(ports)>1:
                    sn += "-%i" % len(ports)
                zp = ZeroconfPublisher(address, host, port, sn, service_type, text_dict)
            except Exception as e:
                log("inet_aton(%s)", host, exc_info=True)
                log.warn("Warning: cannot publish records on %s:", host)
                log.warn(" %s", e)
            else:
                self.services.append(zp)
                self.ports[service_name] = ports
        for host, port in listen_on:
            if host in ("0.0.0.0", "::"):
                #annoying: we have to enumerate all interfaces
                for iface, addresses in get_interfaces_addresses().items():
                    for af in (socket.AF_INET, socket.AF_INET6):
                        if af==socket.AF_INET6 and not IPV6:
                            continue
                        log("%s: %s", iface, addresses.get(socket.AF_INET, {}))
                        for defs in addresses.get(af, {}):
                            addr = defs.get("addr")
                            if addr:
                                add_address(addr, port, af)
                continue
            if host=="":
                host = "127.0.0.1"
            af = socket.AF_INET
            if host.find(":")>=0:
                if IPV6:
                    af = socket.AF_INET6
                else:
                    host = "127.0.0.1"
            add_address(host, port, af)

    def start(self):
        for s in self.services:
            s.start()

    def stop(self):
        for s in self.services:
            s.stop()

    def update_txt(self, txt):
        for s in self.services:
            s.update_txt(txt)


class ZeroconfPublisher(object):
    def __init__(self, address, host, port, service_name, service_type=XPRA_MDNS_TYPE, text_dict=None):
        log("ZeroconfPublisher%s", (address, host, port, service_name, service_type, text_dict))
        self.address = address
        self.host = host
        self.port = port
        self.zeroconf = None
        self.service = None
        self.args = ()
        self.kwargs = {}
        self.registered = False
        try:
            #ie: service_name = localhost.localdomain :2 (ssl)
            parts = service_name.split(" ", 1)
            regname = parts[0].split(".")[0]
            if len(parts)==2:
                regname += parts[1]
            regname = regname.replace(":", "-")
            regname = regname.replace(" ", "-")
            regname = regname.replace("(", "")
            regname = regname.replace(")", "")
            #ie: regname = localhost:2-ssl
            st = service_type+"local."
            regname += "."+st
            td = self.txt_rec(text_dict or {})
            if zeroconf_version<"0.23":
                self.args = (st, regname, self.address, port, 0, 0, td)
            else:
                self.kwargs = {
                    "type_"         : st,       #_xpra._tcp.local.
                    "name"          : regname,
                    "port"          : port,
                    "properties"    : td,
                    "addresses"     : [self.address],
                    }
            service = ServiceInfo(*self.args, **self.kwargs)
            log("ServiceInfo(%s, %s)=%s", self.args, self.kwargs, service)
            self.service = service
        except Exception as e:
            log("zeroconf ServiceInfo", exc_info=True)
            log.error(" for port %i", port)
            log.error(" %s", e)

    def start(self):
        try:
            self.zeroconf = Zeroconf(interfaces=[self.host])
        except OSError:
            log("start()", exc_info=True)
            log.error("Error: failed to create Zeroconf instance for address '%s'", self.host)
            return
        try:
            self.zeroconf.register_service(self.service)
        except Exception:
            log("start failed on %s", self.service, exc_info=True)
        else:
            self.registered = True

    def stop(self):
        log("ZeroConfPublishers.stop(): %s", self.service)
        if self.registered:
            self.zeroconf.unregister_service(self.service)
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
        if not hasattr(self.zeroconf, "update_service"):
            log("no update_service with zeroconf version %s", zeroconf_version)
            return
        props = self.txt_rec(txt)
        if self.args:
            args = list(self.args)
            args[6] = props
            self.args = tuple(args)
        else:
            self.kwargs["properties"] = props
        si = ServiceInfo(*self.args, **self.kwargs)
        try:
            self.zeroconf.update_service(si)
            self.service = si
        except KeyError as e:
            #probably a race condition with cleanup
            log("update_txt(%s)", txt, exc_info=True)
            log.warn("Warning: failed to update service")
            log.warn(" %s", e)
        except Exception:
            log.error("Error: failed to update service", exc_info=True)


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
    log.info("python-zeroconf version %s", zeroconf_version)
    def update_rec():
        publisher.update_txt({"somename": "someothervalue"})
        return False
    glib.timeout_add(10*1000, update_rec)
    try:
        loop.run()
    except KeyboardInterrupt:
        publisher.stop()
        loop.quit()


if __name__ == "__main__":
    main()
