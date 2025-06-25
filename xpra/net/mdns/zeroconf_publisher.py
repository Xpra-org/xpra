#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket
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


LOOPBACK_AFAM = {
    "0.0.0.0": socket.AF_INET,
    "::": socket.AF_INET6,
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


class ZeroconfPublishers:
    """
    Expose services via python zeroconf
    """

    def __init__(self, listen_on, service_name: str, service_type: str = XPRA_TCP_MDNS_TYPE, text_dict=None):
        log("ZeroconfPublishers%s", (listen_on, service_name, service_type, text_dict))
        self.services: list[ZeroconfPublisher] = []
        self.ports: dict[str, set[int]] = {}

        def add_address(host: str, port: int, af=socket.AF_INET):
            try:
                if af == socket.AF_INET6 and host.find("%"):
                    host = host.split("%")[0]
                try:
                    host = socket.gethostbyname(host)
                except Exception:
                    pass
                address = inet_ton(af, host)
            except Exception as e:
                log("inet_aton(%s)", host, exc_info=True)
                log.warn(f"Warning: cannot publish {service_name} records on {host!r}:")
                log.warn(" %s", e)
                return
            sn = service_name
            ports = set(self.ports.get(service_name, ()))
            log("add_address(%s, %s, %s) ports=%s", host, port, af, ports)
            ports.add(port)
            if len(ports) > 1:
                sn += f"-{len(ports)}"
            try:
                zp = ZeroconfPublisher(address, host, port, sn, service_type, text_dict)
            except Exception as e:
                log.warn(f"Warning: zeroconf API error for {service_name} on {host!r}:{port}:")
                log.warn(" %s", e)
            else:
                self.services.append(zp)
                self.ports[service_name] = ports

        for host, port in listen_on:
            if host.startswith("[") and host.endswith("]"):
                host = host[1:-1]
            if host in ("0.0.0.0", "::"):
                af = LOOPBACK_AFAM.get(host)
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

    def start(self) -> None:
        for s in self.services:
            s.start()

    def stop(self) -> None:
        for s in self.services:
            s.stop()

    def update_txt(self, txt) -> None:
        for s in self.services:
            try:
                s.update_txt(txt)
            except TimeoutError:
                log(f"update_txt({txt})", exc_info=True)


class ZeroconfPublisher:
    def __init__(self, address, host: str, port: int,
                 service_name: str, service_type=XPRA_TCP_MDNS_TYPE,
                 text_dict=None):
        log("ZeroconfPublisher%s", (address, host, port, service_name, service_type, text_dict))
        self.address = address
        self.host = host
        self.port = port
        self.zeroconf = None
        self.service = None
        self.kwargs = {}
        self.registered = False
        try:
            # ie: service_name = localhost.localdomain :2 (ssl)
            parts = service_name.split(" ", 1)
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
            td = txt_rec(text_dict or {})
            self.kwargs = {
                "type_": st,  # "_xpra._tcp.local."
                "name": regname,
                "server": regname,
                "port": port,
                "properties": td,
                "addresses": [self.address],
            }
            service = ServiceInfo(**self.kwargs)
            log("ServiceInfo(%s)=%s", self.kwargs, service)
            self.service = service
        except Exception as e:
            log("zeroconf ServiceInfo", exc_info=True)
            log.error(" for port %i", port)
            log.estr(e)

    def start(self) -> None:
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

    def stop(self) -> None:
        log("ZeroConfPublishers.stop(): %s", self.service)
        if self.registered:
            self.zeroconf.unregister_service(self.service)
        self.zeroconf = None

    def update_txt(self, txt) -> None:
        if not hasattr(self.zeroconf, "update_service"):
            log("no update_service with zeroconf version %s", zeroconf_version)
            return
        props = txt_rec(txt)
        self.kwargs["properties"] = props
        si = ServiceInfo(**self.kwargs)
        try:
            self.zeroconf.update_service(si)
            self.service = si
        except KeyError as e:
            # probably a race condition with cleanup
            log("update_txt(%s)", txt, exc_info=True)
            log.warn("Warning: failed to update service")
            log.warn(" %s", e)
        except Exception:
            log.error("Error: failed to update service", exc_info=True)


def main():
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
        publisher = ZeroconfPublishers(host_ports, service_name, service_type, {"somename": "somevalue"})
        GLib.idle_add(publisher.start)
        publishers.append(publisher)

        def update_rec():
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
