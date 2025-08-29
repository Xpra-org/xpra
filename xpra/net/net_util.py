#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# taken from the code I wrote for winswitch

import os
import socket
import sys
from typing import Any
from collections.abc import Callable, Sequence
from importlib import import_module

from xpra.os_util import POSIX
from xpra.util.str_fn import print_nested_dict, csv, bytestostr
from xpra.util.version import parse_version
from xpra.net.bytestreams import get_socket_config
from xpra.common import FULL_INFO, BACKWARDS_COMPATIBLE
from xpra.log import Logger, enable_color, consume_verbose_argv

log = Logger("network", "util")

netifaces_version: Sequence[Any] = ()
_netifaces = None


def import_netifaces() -> object:
    global _netifaces, netifaces_version
    if _netifaces is None:
        try:
            import netifaces  # pylint: disable=import-outside-toplevel
            log("netifaces loaded successfully")
            _netifaces = netifaces
            netifaces_version = parse_version(netifaces.version)  # @UndefinedVariable
        except ImportError:
            _netifaces = False
            log.warn("Warning: the python netifaces package is missing")
            log.warn(" some networking functionality will be unavailable")
    return _netifaces


iface_ipmasks = {}
bind_IPs = None


def get_interfaces() -> Sequence[str]:
    netifaces = import_netifaces()
    if not netifaces:
        return []
    return netifaces.interfaces()  # @UndefinedVariable pylint: disable=no-member


def get_interfaces_addresses() -> dict[str, dict]:
    d = {}
    netifaces = import_netifaces()
    if netifaces:
        for iface in get_interfaces():
            d[iface] = netifaces.ifaddresses(iface)  # @UndefinedVariable pylint: disable=no-member
    return d


def get_interface(address) -> str:
    for iface, idefs in get_interfaces_addresses().items():
        # ie: {
        #    17: [{'broadcast': u'ff:ff:ff:ff:ff:ff', 'addr': u'00:e0:4c:68:46:a6'}],
        #    2: [{'broadcast': u'192.168.1.255', 'netmask': u'255.255.255.0', 'addr': u'192.168.1.7'}],
        #    10: [{'netmask': u'ffff:ffff:ffff:ffff::/64', 'addr': u'fe80::6c45:655:c59e:92a1%eth0'}]
        # }
        for _itype, defs in idefs.items():
            # ie: itype=2, defs=[{'broadcast': u'192.168.1.255', 'netmask': u'255.255.255.0', 'addr': u'192.168.1.7'}]
            for props in defs:
                if props.get("addr") == address:
                    return iface
    return ""


def get_all_ips() -> Sequence[str]:
    ips: list[str] = []
    for inet in get_interfaces_addresses().values():
        # ie: inet = {
        #    18: [{'addr': ''}],
        #    2: [{'peer': '127.0.0.1', 'netmask': '255.0.0.0', 'addr': '127.0.0.1'}],
        #    30: [{'peer': '::1', 'netmask': 'ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff', 'addr': '::1'},
        #         {'peer': '', 'netmask': 'ffff:ffff:ffff:ffff::', 'addr': 'fe80::1%lo0'}]
        #    }
        for v in (socket.AF_INET, socket.AF_INET6):
            addresses = inet.get(v, ())
            for addr in addresses:
                # ie: addr = {'peer': '127.0.0.1', 'netmask': '255.0.0.0', 'addr': '127.0.0.1'}]
                ip = addr.get("addr", "")
                if ip and ip not in ips:
                    ips.append(ip)
    return ips


def get_gateways() -> dict[str, dict]:
    netifaces = import_netifaces()
    if not netifaces:
        return {}
    try:
        d = netifaces.gateways()
        AF_NAMES = {}
        for k in dir(netifaces):
            if k.startswith("AF_"):
                v = getattr(netifaces, k)
                AF_NAMES[v] = k[3:]
        gateways: dict[str, dict] = {}
        for family, gws in d.items():
            if family == "default":
                continue
            gateways[AF_NAMES.get(family, str(family))] = gws
        return gateways
    except Exception:
        log("get_gateways() failed", exc_info=True)
        return {}


def get_bind_IPs() -> Sequence[str]:
    global bind_IPs
    if not bind_IPs:
        netifaces = import_netifaces()
        if netifaces:
            bind_IPs = do_get_bind_IPs()
        else:
            bind_IPs = ["127.0.0.1"]
    return bind_IPs


def do_get_bind_IPs() -> Sequence[str]:
    ips = []
    netifaces = import_netifaces()
    assert netifaces
    ifaces = netifaces.interfaces()  # @UndefinedVariable pylint: disable=no-member
    log("ifaces=%s", ifaces)
    for iface in ifaces:
        if_ipmasks = []
        try:
            ipmasks = do_get_bind_ifacemask(iface)
            for ipmask in ipmasks:
                (ip, _) = ipmask
                if ip not in ips:
                    ips.append(ip)
                if ipmask not in if_ipmasks:
                    if_ipmasks.append(ipmask)
        except Exception as e:
            log("do_get_bind_IPs()", exc_info=True)
            log.error("Error parsing network interface '%s':", iface)
            log.error(" %s", iface, e)
        iface_ipmasks[iface] = if_ipmasks
    log("do_get_bind_IPs()=%s", ips)
    log("iface_ipmasks=%s", iface_ipmasks)
    return ips


def do_get_bind_ifacemask(iface: str) -> Sequence[tuple[str, str]]:
    ipmasks = []
    netifaces = import_netifaces()
    assert netifaces
    address_types = netifaces.ifaddresses(iface)  # @UndefinedVariable pylint: disable=no-member
    for addresses in address_types.values():
        for address in addresses:
            if 'netmask' in address and 'addr' in address:
                addr = address['addr']
                mask = address['netmask']
                if addr != '::1' and addr != '0.0.0.0' and addr.find("%") < 0:
                    try:
                        fam = socket.AF_INET6 if len(addr.split(":")) > 2 else socket.AF_INET
                        b = socket.inet_pton(fam, addr)
                        log(f"socket.inet_pton(AF_INET%s, {addr}={b}", "6" if fam == socket.AF_INET6 else "")
                        ipmasks.append((addr, mask))
                    except Exception as e:
                        log(f"do_get_bind_ifacemask({iface})", exc_info=True)
                        log.error(f"Error converting address {addr!r} with mask {mask!r} to binary")
                        log.error(f" for interface {iface}:")
                        log.estr(e)
    log("do_get_bind_ifacemask(%s)=%s", iface, ipmasks)
    return ipmasks


def _parse_ip_part(s: str) -> int:
    if not s:
        return 0
    try:
        return int(s)
    except ValueError:
        return int(s, 16)


def get_iface(ip: str) -> str:
    log("get_iface(%s)", ip)
    if not ip:
        return ""
    if ip.find("%") >= 0:
        iface = ip.split("%", 1)[1]
        try:
            socket.if_nametoindex(iface)
            return iface
        except OSError:
            return ""
    ipv6 = ip.find(":") >= 0
    af = socket.AF_INET6 if ipv6 else socket.AF_INET
    ipchars = ".:0123456789"
    if ipv6:
        ipchars += "[]"
    if any(x for x in ip if ipchars.find(x) < 0):
        # extra characters, assume this is a hostname:
        sockaddr = ()
        try:
            v = socket.getaddrinfo(ip, None)
            assert len(v) > 0
        except Exception as e:
            log("socket.getaddrinfo(%s, None)", ip, exc_info=True)
            log.error(f"Error resolving {ip!r}: {e}")
            return ""
        for i, x in enumerate(v):
            family, socktype, proto, canonname, sockaddr = x
            log("get_iface(%s) [%i]=%s", ip, i, (family, socktype, proto, canonname, sockaddr))
            if family == af:
                break
        if sockaddr:
            log("get_iface(%s) sockaddr=%s", ip, sockaddr)
            ip = sockaddr[0]

    ipv6 = ip.find(":") >= 0
    if not ipv6:
        ip_parts = ip.split(".")
        if len(ip_parts) != 4:
            return ""

    best_match = ""
    get_bind_IPs()
    for iface, ipmasks in iface_ipmasks.items():
        for test_ip, mask in ipmasks:
            if test_ip == ip:
                # exact match
                log("get_iface(%s)=%s", iface, ip)
                return iface
            if ip_match(ip, test_ip, mask):
                best_match = iface
    log("get_iface(%s)=%s", ip, best_match)
    return best_match


def ip_match(ip: str, test_ip: str, mask: str) -> bool:
    ipv6 = ip.find(":") >= 0
    if ipv6:
        ip_parts = ip.split("/")[0].split(":")
    else:
        ip_parts = ip.split(".")
        if len(ip_parts) != 4:
            return False

    if len(test_ip.split(":")) > 2:
        # test_ip is ipv6
        test_ip_parts = test_ip.split("/")[0].split(":")
        mask_parts = mask.split("/")[0].split(":")
    else:
        test_ip_parts = test_ip.split(".")
        mask_parts = mask.split(".")
        if len(test_ip_parts) != 4 or len(mask_parts) != 4:
            log.error(f"Error: incorrect IP {test_ip} or mask {mask}")
            return False

    try:
        for i, test_ip_part in enumerate(test_ip_parts):
            if i >= len(mask_parts):
                # end of the mask
                break
            if i >= len(ip_parts):
                # end of the ip
                ip_val = 0
            else:
                ip_val = _parse_ip_part(ip_parts[i])

            test_ip_val = _parse_ip_part(test_ip_part)
            mask_val = _parse_ip_part(mask_parts[i])
            test_ip_val = test_ip_val & mask_val
            ip_val = ip_val & mask_val
            if test_ip_val != ip_val:
                return False
        return True
    except Exception as e:
        log("ip parsing error", exc_info=True)
        log.error(f"Error parsing IP {test_ip!r} or its mask {mask!r}: {e}")
        return False


net_sys_config: dict[str, Any] = {}


def get_net_sys_config() -> dict[str, Any]:
    global net_sys_config
    if net_sys_config or not os.path.exists("/proc"):
        return net_sys_config

    def stripnl(v) -> str:
        return str(v).rstrip("\r").rstrip("\n")

    def addproc(procpath: str, subsystem: str, name: str, conv: Callable = stripnl) -> None:
        assert name
        try:
            with open(procpath, encoding="latin1") as f:
                data = f.read()
                subdict = net_sys_config.setdefault(subsystem, {})
                if name.find("/") > 0:
                    sub, name = name.split("/", 1)
                    subdict = subdict.setdefault(sub, {})
                for sub in ("ip", "tcp", "ipfrag", "icmp", "igmp"):
                    if name.startswith(f"{sub}_"):
                        name = name[len(sub) + 1:]
                        subdict = subdict.setdefault(sub, {})
                        break
                subdict[name] = conv(data)
        except Exception as e:
            log("cannot read '%s': %s", procpath, e)

    for k in (
            "netdev_max_backlog", "optmem_max",
            "rmem_default", "rmem_max", "wmem_default", "wmem_max", "max_skb_frags",
            "busy_poll", "busy_read", "somaxconn",
    ):
        addproc(f"/proc/sys/net/core/{k}", "core", k, int)
    for k in ("default_qdisc",):
        addproc(f"/proc/sys/net/core/{k}", "core", k)
    for k in ("max_dgram_qlen",):
        addproc(f"/proc/sys/net/unix/{k}", "unix", k, int)
    for k in (
            "ip_forward", "ip_forward_use_pmtu",
            "tcp_abort_on_overflow", "fwmark_reflect", "tcp_autocorking", "tcp_dsack",
            "tcp_ecn_fallback", "tcp_fack",
            # "tcp_l3mdev_accept",
            "tcp_low_latency", "tcp_no_metrics_save", "tcp_recovery", "tcp_retrans_collapse", "tcp_timestamps",
            "tcp_workaround_signed_windows", "tcp_thin_linear_timeouts", "tcp_thin_dupack", "ip_nonlocal_bind",
            "ip_dynaddr", "ip_early_demux", "icmp_echo_ignore_all", "icmp_echo_ignore_broadcasts",
    ):
        addproc(f"/proc/sys/net/ipv4/{k}", "ipv4", k, bool)
    for k in (
            "tcp_allowed_congestion_control", "tcp_available_congestion_control",
            "tcp_congestion_control", "tcp_early_retrans",
            "tcp_moderate_rcvbuf", "tcp_rfc1337", "tcp_sack", "tcp_slow_start_after_idle", "tcp_stdurg",
            "tcp_syncookies", "tcp_tw_recycle", "tcp_tw_reuse", "tcp_window_scaling",
            "icmp_ignore_bogus_error_responses", "icmp_errors_use_inbound_ifaddr",
    ):
        addproc(f"/proc/sys/net/ipv4/{k}", "ipv4", k)

    def parsenums(v: str) -> Sequence[int]:
        return tuple(int(x.strip()) for x in v.split("\t") if len(x.strip()) > 0)

    for k in ("tcp_mem", "tcp_rmem", "tcp_wmem", "ip_local_port_range", "ip_local_reserved_ports",):
        addproc(f"/proc/sys/net/ipv4/{k}", "ipv4", k, parsenums)
    for k in (
            "ip_default_ttl", "ip_no_pmtu_disc", "route/min_pmtu",
            "route/mtu_expires", "route/min_adv_mss",
            "ipfrag_high_thresh", "ipfrag_low_thresh", "ipfrag_time", "ipfrag_max_dist",
            "tcp_adv_win_scale", "tcp_app_win", "tcp_base_mss", "tcp_ecn", "tcp_fin_timeout", "tcp_frto",
            "tcp_invalid_ratelimit", "tcp_keepalive_time", "tcp_keepalive_probes", "tcp_keepalive_intvl",
            "tcp_max_orphans", "tcp_max_syn_backlog", "tcp_max_tw_buckets",
            "tcp_min_rtt_wlen", "tcp_mtu_probing", "tcp_probe_interval",
            "tcp_probe_threshold", "tcp_orphan_retries",
            "tcp_reordering", "tcp_max_reordering", "tcp_retries1", "tcp_retries2", "tcp_synack_retries",
            "tcp_fastopen", "tcp_syn_retries", "tcp_min_tso_segs", "tcp_pacing_ss_ratio",
            "tcp_pacing_ca_ratio", "tcp_tso_win_divisor", "tcp_notsent_lowat",
            "tcp_limit_output_bytes", "tcp_challenge_ack_limit",
            "icmp_ratelimit", "icmp_msgs_per_sec", "icmp_msgs_burst", "icmp_ratemask",
            "igmp_max_memberships", "igmp_max_msf", "igmp_qrv",
    ):
        addproc(f"/proc/sys/net/ipv4/{k}", "ipv4", k, int)
    return net_sys_config


def get_ssl_info(show_constants=False) -> dict[str, Any]:
    try:
        import ssl  # pylint: disable=import-outside-toplevel
    except ImportError as e:  # pragma: no cover
        log("no ssl: %s", e)
        return {}
    info: dict[str, Any] = {}
    if show_constants:
        protocols = {k: int(getattr(ssl, k)) for k in dir(ssl) if k.startswith("PROTOCOL_")}
        ops = {k: int(getattr(ssl, k)) for k in dir(ssl) if k.startswith("OP_")}
        vers = {k: int(getattr(ssl, k)) for k in dir(ssl) if k.startswith("VERIFY_")}
        info |= {
            "protocols": protocols,
            "options": ops,
            "verify": vers,
        }
    for k, name in {
        "HAS_ALPN": "alpn",
        "HAS_ECDH": "ecdh",
        "HAS_SNI": "sni",
        "HAS_NPN": "npn",
        "CHANNEL_BINDING_TYPES": "channel-binding-types",
    }.items():
        v = getattr(ssl, k, None)
        if v is not None:
            info[name] = v

    vnum = getattr(ssl, "OPENSSL_VERSION_NUMBER", 0)
    if vnum:
        vparts = []
        for _ in range(4):
            vparts.append((vnum & 0xff) >> 4)
            vnum = vnum >> 8
        info["openssl-version"] = tuple(reversed(vparts))[:FULL_INFO+1]
    return info


def get_network_caps(full_info: int = 1) -> dict[str, Any]:
    # pylint: disable=import-outside-toplevel
    from xpra.net.compression import get_enabled_compressors, get_compression_caps
    from xpra.net.packet_encoding import get_enabled_encoders, get_packet_encoding_caps
    caps: dict[str, Any] = {
        "compressors": get_enabled_compressors(),
        "encoders": get_enabled_encoders(),
    }
    if BACKWARDS_COMPATIBLE:
        from xpra.util.env import envbool
        FLUSH_HEADER: bool = envbool("XPRA_FLUSH_HEADER", True)
        caps["flush"] = FLUSH_HEADER
    caps.update(get_compression_caps(full_info))
    caps.update(get_packet_encoding_caps(full_info))
    return caps


def get_paramiko_info() -> dict[str, Sequence[int]]:
    paramiko = sys.modules.get("paramiko")
    if paramiko:
        return {
            "version": paramiko.__version_info__,
        }
    return {}


def get_bcrypt_info() -> dict[str, str]:
    bcrypt = sys.modules.get("bcrypt")
    if bcrypt:
        return {
            "version": bcrypt.__version__,
        }
    return {}


def get_info() -> dict[str, Any]:
    i = get_network_caps()
    netifaces = import_netifaces()
    if netifaces:
        i["interfaces"] = get_interfaces()
        i["gateways"] = get_gateways()
    if "ssl" in sys.modules:
        ssli = get_ssl_info()
        ssli[""] = True
        i["ssl"] = ssli
    if FULL_INFO > 1:
        s = get_net_sys_config()
        if s:
            i["system"] = s
    i["config"] = get_socket_config()
    i["paramiko"] = get_paramiko_info()
    i["bcrypt"] = get_bcrypt_info()
    return i


def print_interface_info(iface: str) -> None:
    try:
        print("* %s (index=%s)" % (iface.ljust(20), socket.if_nametoindex(iface)))
    except OSError:
        print(f"* {iface}")
    from xpra.platform.netdev_query import get_interface_info
    from xpra.net.device_info import get_NM_adapter_type
    netifaces = import_netifaces()
    addresses = netifaces.ifaddresses(iface)  # @UndefinedVariable pylint: disable=no-member
    for addr, defs in addresses.items():
        if addr in (socket.AF_INET, socket.AF_INET6):
            for d in defs:
                ip = d.get("addr")
                if ip:
                    stype = {
                        socket.AF_INET: "IPv4",
                        socket.AF_INET6: "IPv6",
                    }[addr]
                    print(f" * {stype}:     {ip}")
                    if POSIX:
                        from xpra.net.socket_util import create_tcp_socket
                        sock = None
                        try:
                            sock = create_tcp_socket(ip, 0)
                            sockfd = sock.fileno()
                            info = get_interface_info(sockfd, iface)
                            if info:
                                print("  %s" % info)
                        finally:
                            if sock:
                                sock.close()
    info = get_interface_info(0, iface)
    dtype = get_NM_adapter_type(iface, ignore_inactive=False)
    if dtype:
        info["type"] = dtype
    if info:
        print(f"  {info}")


def pver(v) -> str:
    if isinstance(v, (tuple, list)):
        s = ""
        lastx = None
        for x in v:
            if lastx is not None:
                # dot separated numbers
                if isinstance(lastx, int):
                    s += "."
                else:
                    s += ", "
            s += bytestostr(x)
            lastx = x
        return s
    if isinstance(v, bytes):
        v = bytestostr(v)
    if isinstance(v, str) and v.startswith("v"):
        return v[1:]
    return str(v)


def main() -> int:  # pragma: no cover
    # pylint: disable=import-outside-toplevel
    from xpra.platform import program_context
    with program_context("Network-Info", "Network Info"):
        enable_color()
        consume_verbose_argv(sys.argv, "network")
        print("Network interfaces found:")
        netifaces = import_netifaces()
        for iface in get_interfaces():
            print_interface_info(iface)

        print("")
        print("Gateways found:")
        for gt, idefs in get_gateways().items():
            print(f"* {gt}")  # ie: "INET"
            for i, idef in enumerate(idefs):
                if isinstance(idef, (list, tuple)):
                    print(f" [{i}]           " + csv(idef))

        print("")
        print("Protocol Capabilities:")
        from xpra.net import compression
        compression.init_all()
        from xpra.net import packet_encoding
        packet_encoding.init_all()
        netcaps = get_network_caps()
        netif: dict[str, bool | Sequence] = {"": bool(netifaces)}
        if netifaces_version:
            netif["version"] = netifaces_version
        netcaps["netifaces"] = netif
        print_nested_dict(netcaps, vformat=pver)

        print("")
        print("Network Config:")
        print_nested_dict(get_socket_config())

        net_sys = get_net_sys_config()
        if net_sys:
            print("")
            print("Network System Config:")
            print_nested_dict(net_sys)

        print("")
        print("SSL:")
        print_nested_dict(get_ssl_info(True))

        print("")
        print("SSH:")
        try:
            import_module("paramiko")
        except ImportError:
            pass
        print_nested_dict(get_paramiko_info())

        print("")
        print("bcrypt:")
        try:
            import_module("bcrypt")
        except ImportError:
            pass
        print_nested_dict(get_bcrypt_info())

        try:
            from xpra.net.crypto import crypto_backend_init, get_crypto_caps
            crypto_backend_init()
            ccaps = get_crypto_caps()
            if ccaps:
                print("")
                print("Crypto Capabilities:")
                print_nested_dict(ccaps)
        except Exception as e:
            print("No Crypto:")
            print(f" {e}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    main()
