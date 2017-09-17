#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013, 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# taken from the code I wrote for winswitch

import avahi
import dbus
try:
    from dbus.exceptions import DBusException
except:
    #not available in all versions of the bindings?
    DBusException = Exception
from xpra.net.mdns import XPRA_MDNS_TYPE

from xpra.log import Logger
log = Logger("network", "mdns")

from xpra.dbus.common import init_system_bus
from xpra.net.net_util import get_iface, if_nametoindex, if_indextoname

SHOW_INTERFACE = True            #publishes the name of the interface we broadcast from


def get_interface_index(host):
    log("get_interface_index(%s)", host)
    if host == "0.0.0.0" or host =="" or host=="*":
        return avahi.IF_UNSPEC

    if not if_nametoindex:
        log.error("cannot convert interface to index (if_nametoindex is missing), so returning 'IF_UNSPEC', avahi will publish on ALL interfaces")
        return avahi.IF_UNSPEC

    iface = get_iface(host)
    log("get_iface(%s)=%s", host, iface)
    if iface is None:
        return avahi.IF_UNSPEC

    index = if_nametoindex(iface)
    log("if_nametoindex(%s)=%s", iface, index)
    if iface is None:
        return avahi.IF_UNSPEC
    return index


class AvahiPublishers:
    """
    Aggregates a number of AvahiPublisher(s).
    This takes care of constructing the appropriate AvahiPublisher
    with the interface index and port for the given list of (host,port)s to broadcast on,
    and to convert the text dict into a TXT string.
    """

    def __init__(self, listen_on, service_name, service_type=XPRA_MDNS_TYPE, text_dict={}):
        log("AvahiPublishers%s", (listen_on, service_name, service_type, text_dict))
        self.publishers = []
        try:
            bus = init_system_bus()
        except Exception as e:
            log.warn("failed to connect to the system dbus: %s", e)
            log.warn(" either start a dbus session or disable mdns support")
            return
        for host, port in listen_on:
            iface_index = get_interface_index(host)
            log("iface_index(%s)=%s", host, iface_index)
            td = text_dict
            if SHOW_INTERFACE and if_indextoname and iface_index is not None:
                td = text_dict.copy()
                td["iface"] = if_indextoname(iface_index)
            txt = []
            if text_dict:
                for k,v in text_dict.items():
                    txt.append("%s=%s" % (k,v))
            fqdn = host
            if host=="0.0.0.0":
                fqdn = ""
            elif host:
                try:
                    import socket
                    fqdn = socket.gethostbyaddr(host)[0]
                    log("gethostbyaddr(%s)=%s", host, fqdn)
                    if fqdn.find(".")<0:
                        fqdn = socket.getfqdn(host)
                        log("getfqdn(%s)=%s", host, fqdn)
                    if fqdn.find(".")<0:
                        if fqdn:
                            fqdn += ".local"
                        log("cannot find a fully qualified domain name for '%s', using: %s", host, fqdn)
                except:
                    pass
            self.publishers.append(AvahiPublisher(bus, service_name, port, service_type, domain="", host=fqdn, text=txt, interface=iface_index))

    def start(self):
        log("avahi:starting: %s", self.publishers)
        if not self.publishers:
            return
        all_err = True
        for publisher in self.publishers:
            if publisher.start():
                all_err = False
        if all_err:
            log.warn(" to avoid this warning, disable mdns support ")
            log.warn(" using the 'mdns=no' option")

    def stop(self):
        log("stopping: %s", self.publishers)
        for publisher in self.publishers:
            publisher.stop()


class AvahiPublisher:

    def __init__(self, bus, name, port, stype=XPRA_MDNS_TYPE, domain="", host="", text=[], interface=avahi.IF_UNSPEC):
        log("AvahiPublisher%s", (bus, name, port, stype, domain, host, text, interface))
        self.bus = bus
        self.name = name
        self.stype = stype
        self.domain = domain
        self.host = host
        self.port = port
        self.text = avahi.string_array_to_txt_array(text)
        self.interface = interface
        self.server = None
        self.group = None

    def get_info(self):
        def iface():
            if self.interface>0:
                return "interface %i" % self.interface
            return "all interfaces"
        return "%s %s:%s on %s" % (self.name, self.host, self.port, iface())

    def __repr__(self):
        return "AvahiPublisher(%s)" % self.get_info()

    def start(self):
        try:
            self.server = dbus.Interface(self.bus.get_object(avahi.DBUS_NAME, avahi.DBUS_PATH_SERVER), avahi.DBUS_INTERFACE_SERVER)
            self.group = dbus.Interface(self.bus.get_object(avahi.DBUS_NAME, self.server.EntryGroupNew()), avahi.DBUS_INTERFACE_ENTRY_GROUP)
        except Exception as e:
            log.warn("failed to connect to avahi's dbus interface: %s", e)
            return False
        log("avahi dbus server=%s", self.server)
        log("avahi dbus group=%s", self.group)
        self.server.connect_to_signal("StateChanged", self.server_state_changed)
        return self.server_state_changed(self.server.GetState())

    def server_state_changed(self, state, error=None):
        log("server_state_changed(%s, %s) on %s", state, error, self.server)
        if state == avahi.SERVER_COLLISION:
            log.error("Error: mdns server name collision")
            if error:
                log.error(" %s", error)
            self.stop()
            return False
        elif state == avahi.SERVER_RUNNING:
            self.add_service()
            return True
        else:
            log.warn("Warning: unknown avahi server state '%s'", state)
            return False

    def add_service(self):
        if not self.group:
            return
        try:
            args = (self.interface, avahi.PROTO_UNSPEC, dbus.UInt32(0),
                         self.name, self.stype, self.domain, self.host,
                         dbus.UInt16(self.port), self.text)
            log("calling %s%s", self.group, args)
            self.group.AddService(*args)
            self.group.Commit()
            log("dbus service added")
        except DBusException as e:
            log("cannot add service", exc_info=True)
            #use try+except as older versions may not have those modules?
            message = e.get_dbus_message()
            dbus_error_name = e.get_dbus_name()
            log.error("Error starting publisher %s", self.get_info())
            if dbus_error_name=="org.freedesktop.Avahi.CollisionError":
                log.error(" another instance already claims this dbus name")
                log.error(" %s", e)
                log.error(" %s", message)
                return
            for l in str(e).splitlines():
                for x in l.split(":", 1):
                    if x:
                        log.error(" %s", x)

    def stop(self):
        group = self.group
        log("%s.stop() group=%s", self, group)
        if group:
            self.group = None
            try:
                group.Reset()
            except Exception as e:
                log.error("Error stopping avahi publisher %s:", self)
                log.error(" %s", e)
        self.server = None


def main():
    import glib
    import random, signal
    port = int(20000*random.random())+10000
    host = ""
    name = "test service"
    bus = init_system_bus()
    publisher = AvahiPublisher(bus, name, port, stype=XPRA_MDNS_TYPE, host=host, text=["somename:somevalue"])
    assert publisher
    glib.idle_add(publisher.start)
    signal.signal(signal.SIGTERM, exit)
    glib.MainLoop().run()


if __name__ == "__main__":
    main()
