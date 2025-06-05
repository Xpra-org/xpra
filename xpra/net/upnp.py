# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket
from typing import Any

from xpra.util.str_fn import csv

from xpra.log import Logger
log = Logger("network", "upnp")

UPNP_IPV6 = False
INET = {
    "INET": socket.AF_INET,  # @UndefinedVariable
}
if UPNP_IPV6:
    INET["INET6"] = socket.AF_INET6  # @UndefinedVariable


def get_interface_address(addrs) -> str:
    for name, v in INET.items():
        # ie: inet=[{'addr': '192.168.0.111', 'netmask': '255.255.255.0', 'broadcast': '192.168.0.255'}]
        inet = addrs.get(v)
        log("addresses[%s]=%s", name, inet)
        if not inet:
            continue
        for a in inet:
            # ie: host = {'addr': '192.168.0.111', 'netmask': '255.255.255.0', 'broadcast': '192.168.0.255'}
            host = a.get("addr")
            if host:
                return host
    return ""


def get_device_interface(gateways: dict) -> str:
    default_gw = gateways.get("default")  # ie: {2: ('192.168.3.1', 'eth0')}
    if default_gw:
        for v in INET.values():  # ie: AF_INET
            inet = default_gw.get(v)  # ie: ('192.168.3.1', 'eth0')
            if inet and len(inet) >= 2:
                return inet[1]
    for v in INET.values():
        # ie: gws = [('192.168.3.1', 'eth0', True), ('192.168.0.1', 'wlan0', False)]}
        gws = gateways.get(v)
        if not gws:
            continue
        for inet in gws:
            if inet and len(inet) >= 2:
                return inet[1]
    return ""


def resolve_internal_host() -> str:
    # we need to figure out the specific IP
    # which is connected to this device
    import netifaces
    gateways = netifaces.gateways()  # @UndefinedVariable
    if not gateways:
        raise ValueError("internal host IP not found: no gateways")
    interface = get_device_interface(gateways)
    if not interface:
        raise ValueError("cannot identify the network interface")
    log("identified interface '%s'", interface)
    addrs = netifaces.ifaddresses(interface)  # @UndefinedVariable
    log("ifaddresses(%s)=%s", interface, addrs)
    # ie: {17: [{'addr': '30:52:cb:85:54:03', 'broadcast': 'ff:ff:ff:ff:ff:ff'}],
    #      2: [{'addr': '192.168.0.111', 'netmask': '255.255.255.0', 'broadcast': '192.168.0.255'}],
    #     10: [{'addr': 'fe80::1944:64a7:ab7b:9d67%wlan0', 'netmask': 'ffff:ffff:ffff:ffff::/64'}]}
    internal_host = get_interface_address(addrs)
    if not internal_host:
        raise ValueError("no address found for interface '%s'", interface)
    return internal_host


def find_device(upnp, value: str):
    try:
        devices = upnp.discover()
    except Exception as e:
        log("discover()", exc_info=True)
        raise ValueError(f"error discovering devices: {e}")
    if devices:
        log("find_device found %i devices:", len(devices))
        for device in devices:
            log(f" * {device!r}")
    if value == "igd":
        try:
            device = upnp.get_igd()
            if not device:
                raise ValueError("no igd device found")
            log("using IGD device %s", device)
        except Exception as e:
            raise ValueError(f"upnp failed to query igd device: {e}")
    else:
        try:
            # the device could be given as an index:
            no = int(value)
            try:
                device = devices[no]
                log("using device %i: %s", no, device)
            except IndexError:
                return ValueError(f"no device number {no}, only {len(devices)} devices found")
        except ValueError:
            # try using the value as a device name:
            device = getattr(upnp, value, None)
            if device is None:
                return ValueError(f"device name {value!r} not found")
            log("using device %s", device)
    log("device: %s", device.get_friendly_name())
    log("device address: %s", device.address)
    return device


def find_service(device, value: str):
    services = device.get_services()
    if not services:
        return ValueError("device %r does not have any services" % device)
    log("services=%s", csv(services))
    if value:
        try:
            # the service could be given as an index:
            no = int(value)
            try:
                service = services[no]
                log("using service %i: %s", no, service)
                return service
            except IndexError:
                raise ValueError("no service number %i on device %s" % (no, device),
                                 "%i services found" % len(services))
        except ValueError:
            # find the service by id
            matches = [v for v in services if v.id.split(":")[-1] == value]
            if len(matches) > 1:
                return ValueError(f"more than one service matches {value!r}")
            if len(matches) != 1:
                return ValueError(f"service {value!r} not found on {device}")
            service = matches[0]
            log("using service %s", service)
            return service
    # find the service with a "AddPortMapping" action:
    for service in services:
        if get_action(service, "AddPortMapping"):
            log("found a service with `AddPortMapping` function: %s", service)
            return service
    raise ValueError("device %r does not have a service with a port mapping action" % device)


def upnp_add(socktype: str, info, options: dict):
    log("upnp_add%s", (socktype, info, options))

    def err(*msgs) -> None:
        log("pnp_add%s", (info, options), exc_info=True)
        log.error("Error: cannot add UPnP port mapping")
        for msg in msgs:
            if msg:
                log.error(" %s", msg)
        return None

    # find the port number:
    try:
        internal_host, internal_port = info
    except (ValueError, TypeError):
        return err(f"cannot identify the host and port number from {info}")
    try:
        import upnpy
    except ImportError as e:
        return err(e)

    # prepare the port mapping attributes early:
    # (in case this causes errors)
    remote_host = options.get("upnp-remote-host", "")
    external_port = int(options.get("upnp-external-port", internal_port))
    protocol = "TCP"
    duration = int(options.get("upnp-duration", 600))

    try:
        upnp = upnpy.UPnP()
        log("upnp=%s", upnp)
        try:
            value = options.get("upnp-device", "igd")
            device = find_device(upnp, value)
        except ValueError as e:
            return err(str(e))

        if internal_host in ("0.0.0.0", "::/0", "::"):
            # we need to figure out the specific IP
            # which is connected to this device
            try:
                internal_host = resolve_internal_host()
            except ValueError as e:
                return err(str(e))

        try:
            value = options.get("upnp-service", "")
            service = find_service(device, value)
        except ValueError as e:
            return err(str(e))
        add = get_action(service, "AddPortMapping")
        delete = get_action(service, "DeletePortMapping")
        if not add:
            return err("service %s does not support 'AddPortMapping'")
        if not delete:
            return err("service %s does not support 'DeletePortMapping'")
        kwargs = {
            "NewRemoteHost": remote_host,
            "NewExternalPort": external_port,
            "NewProtocol": protocol,
            "NewInternalPort": internal_port,
            "NewInternalClient": internal_host,
            "NewEnabled": True,
            "NewPortMappingDescription": "Xpra-%s" % socktype,
            "NewLeaseDuration": duration,
        }
        log("%s%s", add, kwargs)
        add(**kwargs)
        log_upnp_info(service)
        external_ip = get_new_service_ip(service)
        if external_ip:
            log.info("UPnP port mapping added for %s:%s", external_ip, external_port)
            options["upnp-address"] = (external_ip, external_port)

        def cleanup() -> None:
            delete_service(service, protocol, socktype,
                           internal_port,
                           external_ip, external_port, remote_host)
        return cleanup
    except Exception as e:
        return err(e)


def delete_service(service, protocol: str, socktype: str,
                   internal_port: int,
                   external_ip: str, external_port: int, remote_host: str) -> None:
    delete = get_action(service, "DeletePortMapping")
    assert delete, "cannot find delete action"
    try:
        kwargs: dict[str, Any] = {
            "NewRemoteHost": remote_host,
            "NewExternalPort": external_port,
            "NewProtocol": protocol,
        }
        log("%s%s", delete, kwargs)
        delete(**kwargs)
        log.info("UPnP port mapping removed for %s:%s", external_ip, external_port)
    except Exception as e:
        log("%s", delete, exc_info=True)
        log.error("Error removing port UPnP port mapping")
        log.error(" for external port %i,", external_port)
        log.error(" internal port %i (%s):", internal_port, socktype)
        log.estr(e)


def get_action(service, action_name: str):
    actions = service.get_actions()
    for action in actions:
        if action.name == action_name:
            return action
    return None


def log_upnp_info(service) -> None:
    # UPNP_INFO = ("GetConnectionTypeInfo", "GetStatusInfo", "GetNATRSIPStatus")
    UPNP_INFO = ("GetConnectionTypeInfo", "GetStatusInfo")
    for action_name in UPNP_INFO:
        action = get_action(service, action_name)
        if action:
            try:
                r = action()
                log("%s=%s", action_name, r)
            except Exception:
                log("%s", action, exc_info=True)


def get_new_service_ip(service) -> str:
    getip = get_action(service, "GetExternalIPAddress")
    if not getip:
        return ""
    try:
        reply = getip()
        ip = (reply or {}).get("NewExternalIPAddress")
        if ip:
            return ip
    except Exception:
        log("%s", getip, exc_info=True)
    return ""
