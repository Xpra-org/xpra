# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util import csv


def upnp_add(socktype, info, options):
    from xpra.log import Logger
    log = Logger("network", "upnp")
    log("upnp_add%s", (socktype, info, options))
    def err(*msgs):
        log("pnp_add%s", (info, options), exc_info=True)
        log.error("Error: cannot add UPnP port mapping")
        for msg in msgs:
            if msg:
                log.error(" %s", msg)
        return None
    #find the port number:
    try:
        internal_host, internal_port = info
    except (ValueError, TypeError):
        return err("cannot identify the host and port number from %s" % (info,))
    try:
        import upnpy
    except ImportError as e:
        return err(e)
    try:
        #prepare the port mapping attributes early:
        #(in case this causes errors)
        remote_host = options.get("upnp-remote-host", "")
        external_port = int(options.get("upnp-external-port", internal_port))
        protocol = "UDP" if socktype=="udp" else "TCP"
        duration = int(options.get("upnp-duration", 600))

        upnp = upnpy.UPnP()
        log("upnp=%s", upnp)
        #find the device to use:
        try:
            devices = upnp.discover()
        except Exception as e:
            log("discover()", exc_info=True)
            return err("error discovering devices", e)
        d = options.get("upnp-device", "igd")
        if d=="igd":
            try:
                device = upnp.get_igd()
                log("using IGD device %s", device)
            except Exception as e:
                dstr = ()
                if devices:
                    dstr = (
                        "%i devices:" % len(devices),
                        ": %s" % devices,
                        )
                return err(e, *dstr)
        else:
            try:
                #the device could be given as an index:
                no = int(d)
                try:
                    device = devices[no]
                except IndexError:
                    return err("no device number %i" % no,
                               "%i devices found" % len(devices))
                log("using device %i: %s", no, device)
            except ValueError:
                #try using the value as a device name:
                device = getattr(upnp, d, None)
                if device is None:
                    return err("device name '%s' not found" % d)
                log("using device %s", device)
        log("device: %s", device.get_friendly_name())
        log("device address: %s", device.address)
        if internal_host in ("0.0.0.0", "::/0", "::"):
            #we need to figure out the specific IP
            #which is connected to this device
            import netifaces
            gateways = netifaces.gateways()
            if not gateways:
                return err("internal host IP not found: no gateways")
            UPNP_IPV6 = False
            INET = {
                "INET"  : netifaces.AF_INET,
                }
            if UPNP_IPV6:
                INET["INET6"] = netifaces.AF_INET6
            def get_device_interface():
                default_gw = gateways.get("default")    #ie: {2: ('192.168.3.1', 'eth0')}
                if default_gw:
                    for v in INET.values():             #ie: AF_INET
                        inet = default_gw.get(v)        #ie: ('192.168.3.1', 'eth0')
                        if inet and len(inet)>=2:
                            return inet[1]
                for v in INET.values():
                    #ie: gws = [('192.168.3.1', 'eth0', True), ('192.168.0.1', 'wlan0', False)]}
                    gws = gateways.get(v)
                    if not gws:
                        continue
                    for inet in gws:
                        if inet and len(inet)>=2:
                            return inet[1]
            interface = get_device_interface()
            if not interface:
                return err("cannot identify the network interface for '%s'" % (device.address,))
            log("identified interface '%s' for device address %s", interface, device.address)
            addrs = netifaces.ifaddresses(interface)
            log("ifaddresses(%s)=%s", interface, addrs)
            #ie: {17: [{'addr': '30:52:cb:85:54:03', 'broadcast': 'ff:ff:ff:ff:ff:ff'}],
            #      2: [{'addr': '192.168.0.111', 'netmask': '255.255.255.0', 'broadcast': '192.168.0.255'}],
            #     10: [{'addr': 'fe80::1944:64a7:ab7b:9d67%wlan0', 'netmask': 'ffff:ffff:ffff:ffff::/64'}]}
            def get_interface_address():
                for name, v in INET.items():
                    #ie: inet=[{'addr': '192.168.0.111', 'netmask': '255.255.255.0', 'broadcast': '192.168.0.255'}]
                    inet = addrs.get(v)
                    log("addresses[%s]=%s", name, inet)
                    if not inet:
                        continue
                    for a in inet:
                        #ie: host = {'addr': '192.168.0.111', 'netmask': '255.255.255.0', 'broadcast': '192.168.0.255'}
                        host = a.get("addr")
                        if host:
                            return host
                return None
            internal_host = get_interface_address()
            if not internal_host:
                return err("no address found for interface '%s'", interface)

        #find the service:
        services = device.get_services()
        if not services:
            return err("device %s does not have any services" % device)
        log("services=%s", csv(services))
        s = options.get("upnp-service", "")
        if s:
            try:
                #the service could be given as an index:
                no = int(s)
                try:
                    service = services[no]
                except IndexError:
                    return err("no service number %i on device %s" % (no, device),
                               "%i services found" % len(services))
                log("using service %i: %s", no, service)
            except ValueError:
                #find the service by id
                matches = [v for v in services if v.id.split(":")[-1]==s]
                if len(matches)>1:
                    return err("more than one service matches '%s'" % (s,))
                if len(matches)!=1:
                    return err("service '%s' not found on %s" % (s, device))
                service = matches[0]
                log("using service %s", service)
        else:
            #find the service with a "AddPortMapping" action:
            service = None
            for v in services:
                if get_action(v, "AddPortMapping"):
                    service = v
                    break
            if not service:
                return err("device %s does not have a service with a port mapping action" % device)
        add = get_action(service, "AddPortMapping")
        delete = get_action(service, "DeletePortMapping")
        if not add:
            return err("service %s does not support 'AddPortMapping'")
        if not delete:
            return err("service %s does not support 'DeletePortMapping'")
        kwargs = {
            "NewRemoteHost"     : remote_host,
            "NewExternalPort"   : external_port,
            "NewProtocol"       : protocol,
            "NewInternalPort"   : internal_port,
            "NewInternalClient" : internal_host,
            "NewEnabled"        : True,
            "NewPortMappingDescription" : "Xpra-%s" % socktype,
            "NewLeaseDuration"  : duration,
            }
        log("%s%s", add, kwargs)
        add(**kwargs)
        #UPNP_INFO = ("GetConnectionTypeInfo", "GetStatusInfo", "GetNATRSIPStatus")
        UPNP_INFO = ("GetConnectionTypeInfo", "GetStatusInfo")
        for action_name in UPNP_INFO:
            action = get_action(service, action_name)
            if action:
                try:
                    r = action()
                    log("%s=%s", action_name, r)
                except Exception:
                    log("%s", action, exc_info=True)
        getip = get_action(service, "GetExternalIPAddress")
        if getip:
            try:
                reply = getip()
                ip = (reply or {}).get("NewExternalIPAddress")
                if ip:
                    log.info("UPnP port mapping added for %s:%s", ip, external_port)
                    options["upnp-address"] = (ip, external_port)
            except Exception as e:
                log("%s", getip, exc_info=True)
        def cleanup():
            try:
                kwargs = {
                    "NewRemoteHost"     : remote_host,
                    "NewExternalPort"   : external_port,
                    "NewProtocol"       : protocol,
                    }
                log("%s%s", delete, kwargs)
                delete(**kwargs)
                log.info("UPnP port mapping removed for %s:%s", ip, external_port)
            except Exception as e:
                log("%s", delete, exc_info=True)
                log.error("Error removing port UPnP port mapping")
                log.error(" for external port %i,", external_port)
                log.error(" internal port %i (%s):", internal_port, socktype)
                log.error(" %s", e)
        return cleanup
    except Exception as e:
        return err(e)

def get_action(service, action_name):
    actions = service.get_actions()
    for action in actions:
        if action.name==action_name:
            return action
    return None
