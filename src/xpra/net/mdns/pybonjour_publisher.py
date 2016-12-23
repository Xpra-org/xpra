#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 - 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# taken from the code I wrote for winswitch

from xpra.log import Logger
log = Logger("network", "mdns")

from xpra.util import csv
from xpra.os_util import WIN32
from xpra.net.net_util import if_indextoname, if_nametoindex, get_iface
try:
    from xpra.net.mdns import pybonjour
except OSError as e:
    log("failed to load pybonjour", exc_info=True)
    raise ImportError("cannot load pybonjour module: %s" % e.strerror)
from xpra.net.mdns import XPRA_MDNS_TYPE

SHOW_INTERFACE = True            #publishes the name of the interface we broadcast from


def get_interface_index(host):
    if host == "0.0.0.0" or host =="" or host=="*":
        return pybonjour.kDNSServiceInterfaceIndexAny
    if host=="127.0.0.1" or host=="::1":
        return pybonjour.kDNSServiceInterfaceIndexLocalOnly
    if not if_nametoindex:
        if not WIN32:
            log.error("Error: cannot convert interface to index (if_nametoindex is missing)")
            log.error(" pybonjour will publish on ALL interfaces")
        return pybonjour.kDNSServiceInterfaceIndexAny
    iface = get_iface(host)
    if not iface:
        return None
    return if_nametoindex(iface)


class BonjourPublishers:
    """
    Aggregates a number of BonjourPublisher(s).
    This takes care of constructing the appropriate BonjourPublisher with the interface index and port for the given list of (host,port)s to broadcast on.
    """

    def __init__(self, listen_on, service_name, service_type=XPRA_MDNS_TYPE, text_dict={}):
        log("BonjourPublishers%s", (listen_on, service_name, service_type, text_dict))
        self.publishers = []
        for host, port in listen_on:
            iface_index = get_interface_index(host)
            log("iface_index(%s)=%s", host, iface_index)
            td = text_dict
            if SHOW_INTERFACE and if_indextoname:
                td = text_dict.copy()
                td["iface"] = if_indextoname(iface_index)
            txt = pybonjour.TXTRecord(td)
            self.publishers.append(BonjourPublisher(iface_index, port, service_name, service_type, txt))

    def start(self):
        for publisher in self.publishers:
            publisher.start()

    def stop(self):
        log("BonjourPublishers.stop(): %s" % csv(self.publishers))
        for publisher in self.publishers:
            try:
                publisher.stop()
            except Exception as e:
                log.error("Error stopping publisher %s:", publisher)
                log.error(" %s" % publisher, e)


class BonjourPublisher:

    def __init__(self, iface_index, port, service_name, service_type, text_record):
        log("BonjourPublisher%s", (iface_index, port, service_name, service_type, text_record))
        self.sdref = None
        self.reader = None
        self.iface_index = iface_index
        self.port = port
        self.service_name = service_name
        self.service_type = service_type
        self.text_record = text_record

    def __repr__(self):
        return "BonjourPublisher(%s, %s)" % (self.iface_index, self.port)

    def broadcasting(self, args):
        log("broadcasting%s", args)
        self.sdref  = args[0]

    def failed(self, errorCode):
        log.error("Error: pybonjour failed with error code %i", errorCode)

    def start(self):
        log("BonjourPublisher.start()")
        #d = broadcast(reactor, "_daap._tcp", 3689, "DAAP Server")
        self.broadcast()

    def broadcast(self):
        def _callback(sdref, flags, errorCode, name, regtype, domain):
            log("_callback%s", (sdref, flags, errorCode, name, regtype, domain))
            if errorCode == pybonjour.kDNSServiceErr_NoError:
                self.broadcasting(sdref, name, regtype, domain)
            else:
                self.failed(errorCode)

        log("pybonjour broadcast() adding service for interface %s on %s", self.iface_index, self.port)
        try:
            self.sdref = pybonjour.DNSServiceRegister(name = self.service_name,
                                    regtype = self.service_type,
                                    port = self.port,
                                    txtRecord = self.text_record,
                                    callBack = _callback)
        except pybonjour.BonjourError as e:
            if e.errorCode==pybonjour.kDNSServiceErr_NameConflict:
                log.error("Error: another server is already claiming our service type '%s'!", self.service_type)
            else:
                log.error("Error: failed to broadcast mdns service %s on port %s", self.service_type, self.port)
                log.error(" ensure that mdns is installed and running")
            return None


    def stop(self):
        sdref = self.sdref
        log("stop() sdref=%s", sdref)
        if sdref:
            self.sdref = None
            sdref.close()


def main():
    import random, signal
    port = int(20000*random.random())+10000
    host = "0.0.0.0"
    host_ports = [(host, port)]
    ID = "test_%s" % int(random.random()*100000)
    publisher = BonjourPublishers(host_ports, ID, XPRA_MDNS_TYPE, {"somename":"somevalue"})
    signal.signal(signal.SIGTERM, exit)
    from xpra.gtk_common.gobject_compat import import_glib
    glib = import_glib()
    glib.idle_add(publisher.start)
    loop = glib.MainLoop()
    loop.run()


if __name__ == "__main__":
    main()
