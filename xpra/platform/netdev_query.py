# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket
from typing import Any

from xpra.platform import platform_import


def get_interface_info(*_args) -> dict[str, Any]:
    return {}


def get_tcp_info(_sock) -> dict[str, Any]:  # pylint: disable=unused-argument
    return {}


platform_import(globals(), "netdev_query", False,
                "get_tcp_info",
                "get_interface_info",
                )


def print_address(iface, addr, defs) -> None:
    from xpra.os_util import POSIX
    from xpra.util.str_fn import print_nested_dict
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
                        print_nested_dict(info, prefix="    ", lchar="-")
                finally:
                    if sock:
                        sock.close()


def print_iface(iface):
    from xpra.os_util import POSIX
    from xpra.net.net_util import import_netifaces
    netifaces = import_netifaces()
    addresses = netifaces.ifaddresses(iface)  # @UndefinedVariable pylint: disable=no-member
    for addr, defs in addresses.items():
        if addr in (socket.AF_INET, socket.AF_INET6):
            print_address(iface, addr, defs)
    if not POSIX:
        info = get_interface_info(0, iface)
        if info:
            print(f"  {info}")


def main() -> None:
    # pylint: disable=import-outside-toplevel
    import sys
    from xpra.net.net_util import get_interfaces
    from socket import if_nametoindex
    from xpra.platform import program_context
    from xpra.log import enable_color, consume_verbose_argv
    with program_context("Network-Device-Info", "Network Device Info"):
        enable_color()
        consume_verbose_argv(sys.argv, "network")
        print("Network interfaces found:")
        for iface in get_interfaces():
            try:
                print("* %s (index=%s)" % (iface.ljust(20), if_nametoindex(iface)))
            except OSError:
                print(f"* {iface}")
            print_iface(iface)


if __name__ == "__main__":
    main()
