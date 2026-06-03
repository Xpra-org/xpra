#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket
from dataclasses import dataclass, field
from zeroconf import ServiceInfo, Zeroconf, __version__ as zeroconf_version

from xpra.log import Logger
from xpra.util.env import envbool, envint, first_time
from xpra.net.net_util import get_interfaces_addresses
from xpra.net.mdns import XPRA_TCP_MDNS_TYPE, XPRA_UDP_MDNS_TYPE
from xpra.net.net_util import get_iface

log = Logger("network", "mdns")
log("python-zeroconf version %s", zeroconf_version)

IPV6 = envbool("XPRA_ZEROCONF_IPV6", True)
IPV6_LO = envbool("XPRA_ZEROCONF_IPV6_LOOPBACK", False)
IPV4_LO = envint("XPRA_ZEROCONF_IPV4_LOOPBACK", 1)

LOOPBACK_AFAM: dict[str, socket.AddressFamily] = {
    "0.0.0.0": socket.AddressFamily.AF_INET,
    "::": socket.AddressFamily.AF_INET6,
}


def get_interface_index(host: str) -> str:
    # we don't use interface numbers with zeroconf,
    # so just return the interface name,
    # which is also unique
    return get_iface(host)


def inet_ton(af, addr):
    if af == socket.AF_INET:
        return socket.inet_aton(addr)
    return socket.inet_pton(af, addr)  # @UndefinedVariable


def txt_rec(text_dict) -> dict:
    # prevent zeroconf from mangling our ints into booleans:
    new_dict = {}
    for k, v in text_dict.items():
        if isinstance(v, int):
            new_dict[k] = str(v)
        else:
            new_dict[k] = v
    return new_dict


@dataclass
class Service:
    """
    A single mDNS record, which may advertise more than one address
    (ie: one per interface for a wildcard listen address),
    with the `Zeroconf` instance created when it is started.
    """
    hosts: list[str]
    kwargs: dict
    service: ServiceInfo
    zeroconf: Zeroconf | None = field(default=None)
    registered: bool = field(default=False)


class ZeroconfMulticast:
    """
    Expose services via python zeroconf.

    A single ``listen_on`` entry using a wildcard address (``0.0.0.0`` / ``::``)
    is expanded into one `Service` record per interface address.
    """

    def __init__(self, listen_on, service_name: str, service_type: str = XPRA_TCP_MDNS_TYPE, text_dict=None):
        log("ZeroconfMulticast%s", (listen_on, service_name, service_type, text_dict))
        self.services: list[Service] = []
        self.ports: dict[str, set[int]] = {}
        # group addresses that only differ by their interface into a single record:
        self.services_by_name: dict[str, Service] = {}

        def add_address(host: str, port: int, af: socket.AddressFamily) -> None:
            self.add_address(host, port, af, service_name, service_type, text_dict)

        for host, port in listen_on:
            if host.startswith("[") and host.endswith("]"):
                host = host[1:-1]
            if host in ("0.0.0.0", "::"):
                af: socket.AddressFamily = LOOPBACK_AFAM[host]
                if af == socket.AF_INET6 and not IPV6_LO:
                    if first_time(f"zeroconf-{host}"):
                        log.info(f"python-zeroconf: {host!r} IPv6 loopback address is not supported")
                        mode = (text_dict or {}).get("mode")
                        if mode:
                            log.info(f" unable to publish mDNS record for {mode} connections")
                        log("try XPRA_ZEROCONF_IPV6_LOOPBACK=1 to enable it at your own risk")
                    # means that IPV6 is False and "::" is not supported
                    # at time of writing, https://pypi.org/project/zeroconf/ says:
                    # _listening on localhost (::1) does not work. Help with understanding why is appreciated._
                    continue

                # annoying: we have to enumerate all interfaces
                iaddr = get_interfaces_addresses()

                def add_iface(iface: str, addresses: dict) -> None:
                    log("%r %s: %s", iface, af, addresses.get(af, {}))
                    for defs in addresses.get(af, ()):
                        addr = defs.get("addr")
                        if addr:
                            add_address(addr, port, af)

                log(f"interface addresses: {iaddr!r}")
                # ensure loopback is done last, as it may conflict:
                loopback = iaddr.pop("lo", {})
                for iface, addresses in iaddr.items():
                    add_iface(iface, addresses)
                # with IPV4_LO=2, always publish loopback,
                # with IPV4_LO=1, only publish it if we don't have other addresses:
                if loopback and (IPV4_LO == 2) or (IPV4_LO == 1 and not iaddr):
                    add_iface("lo", loopback)
                continue
            if host == "":
                host = "127.0.0.1"
            af = socket.AF_INET
            if host.find(":") >= 0:
                if IPV6:
                    af = socket.AF_INET6
                else:
                    host = "127.0.0.1"
            add_address(host, port, af)

    def add_address(self, host: str, port: int, af: socket.AddressFamily,
                    service_name: str, service_type: str, text_dict):
        try:
            if af == socket.AF_INET6 and host.find("%"):
                host = host.split("%")[0]
            try:
                host = socket.gethostbyname(host)
            except OSError:
                pass
            address = inet_ton(af, host)
        except Exception as e:
            log("inet_aton(%s)", host, exc_info=True)
            log.warn(f"Warning: cannot publish {service_name} records on {host!r}:")
            log.warn(" %s", e)
            return
        ports = set(self.ports.get(service_name, ()))
        log("add_address(%s, %s, %s, %s) ports=%s", service_name, host, port, af, ports)
        ports.add(port)
        self.ports[service_name] = ports
        sn = service_name
        if len(ports) > 1:
            sn += f"-{len(ports)}"
        # ie: sn = localhost.localdomain :2 (ssl)
        parts = sn.split(" ", 1)
        regname = parts[0].split(".")[0]
        if len(parts) == 2:
            regname += parts[1]
        regname = regname.replace(":", "-")
        regname = regname.replace(" ", "-")
        regname = regname.replace("(", "")
        regname = regname.replace(")", "")
        # ie: regname = localhost-2-ssl
        st = service_type + "local."
        regname += "." + st

        # all the addresses for the same name are advertised by a single record:
        existing = self.services_by_name.get(regname)
        if existing:
            if address not in existing.kwargs["addresses"]:
                existing.kwargs["addresses"].append(address)
            if host not in existing.hosts:
                existing.hosts.append(host)
            existing.service = ServiceInfo(**existing.kwargs)
            log("updated %s: %s", regname, existing.service)
            return

        kwargs = {
            "type_": st,  # "_xpra._tcp.local."
            "name": regname,
            "server": regname,
            "port": port,
            "properties": txt_rec(text_dict or {}),
            "addresses": [address],
        }
        try:
            service = ServiceInfo(**kwargs)
            log("ServiceInfo(%s)=%s", kwargs, service)
        except Exception as e:
            log("zeroconf ServiceInfo", exc_info=True)
            log.warn(f"Warning: zeroconf API error for {service_name} on {host!r}:{port}:")
            log.warn(" %s", e)
            return
        s = Service([host], kwargs, service)
        self.services.append(s)
        self.services_by_name[regname] = s

    def start(self) -> None:
        for s in self.services:
            try:
                s.zeroconf = Zeroconf(interfaces=s.hosts)
            except OSError:
                log("start()", exc_info=True)
                log.error("Error: failed to create Zeroconf instance for addresses %s", s.hosts)
                continue
            try:
                s.zeroconf.register_service(s.service)
            except Exception:
                log("start failed on %s", s.service, exc_info=True)
            else:
                s.registered = True

    def stop(self) -> None:
        for s in self.services:
            log("ZeroconfMulticast.stop(): %s", s.service)
            if s.registered:
                s.zeroconf.unregister_service(s.service)
            s.zeroconf = None
            s.registered = False

    def update_txt(self, txt) -> None:
        props = txt_rec(txt)
        for s in self.services:
            zc = s.zeroconf
            if not zc:
                continue
            s.kwargs["properties"] = props
            si = ServiceInfo(**s.kwargs)
            try:
                zc.update_service(si)
                s.service = si
            except TimeoutError:
                log(f"update_txt({txt})", exc_info=True)
            except KeyError as e:
                # probably a race condition with cleanup
                log("update_txt(%s)", txt, exc_info=True)
                log.warn("Warning: failed to update service")
                log.warn(" %s", e)
            except Exception:
                log.error("Error: failed to update service", exc_info=True)


def main() -> None:
    import random
    port = int(20000 * random.random()) + 10000
    # host = "127.0.0.1"
    host = "0.0.0.0"
    host_ports = [(host, port)]
    service_name = "test %s" % int(random.random() * 100000)
    from xpra.os_util import gi_import
    GLib = gi_import("GLib")
    publishers = []

    def add(service_type):
        publisher = ZeroconfMulticast(host_ports, service_name, service_type, {"somename": "somevalue"})
        GLib.idle_add(publisher.start)
        publishers.append(publisher)

        def update_rec() -> None:
            publisher.update_txt({"somename": "someothervalue"})

        GLib.timeout_add(10 * 1000, update_rec)

    add(XPRA_TCP_MDNS_TYPE)
    add(XPRA_UDP_MDNS_TYPE)
    loop = GLib.MainLoop()
    log.info("python-zeroconf version %s", zeroconf_version)
    try:
        loop.run()
    except KeyboardInterrupt:
        for publisher in publishers:
            publisher.stop()
        loop.quit()


if __name__ == "__main__":
    main()
