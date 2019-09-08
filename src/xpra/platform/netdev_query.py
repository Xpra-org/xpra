# This file is part of Xpra.
# Copyright (C) 2017-2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def get_interface_info(*_args):
    return {}


from xpra.platform import platform_import
platform_import(globals(), "netdev_query", False,
                "get_interface_info",
                )


def main():
    import sys
    import socket

    from xpra.os_util import POSIX
    from xpra.util import print_nested_dict
    from xpra.net.net_util import import_netifaces, get_interfaces, if_nametoindex
    from xpra.platform import program_context
    from xpra.log import Logger, enable_color, add_debug_category, enable_debug_for
    log = Logger("network")
    with program_context("Network-Device-Info", "Network Device Info"):
        enable_color()
        verbose = "-v" in sys.argv or "--verbose" in sys.argv
        if verbose:
            enable_debug_for("network")
            add_debug_category("network")
            log.enable_debug()

        print("Network interfaces found:")
        netifaces = import_netifaces()
        for iface in get_interfaces():
            if if_nametoindex:
                print("* %s (index=%s)" % (iface.ljust(20), if_nametoindex(iface)))
            else:
                print("* %s" % iface)
            addresses = netifaces.ifaddresses(iface)     #@UndefinedVariable
            for addr, defs in addresses.items():
                if addr in (socket.AF_INET, socket.AF_INET6):
                    for d in defs:
                        ip = d.get("addr")
                        if ip:
                            stype = {
                                socket.AF_INET  : "IPv4",
                                socket.AF_INET6 : "IPv6",
                                }[addr]
                            print(" * %s:     %s" % (stype, ip))
                            if POSIX:
                                from xpra.net.socket_util import create_tcp_socket
                                try:
                                    sock = create_tcp_socket(ip, 0)
                                    sockfd = sock.fileno()
                                    info = get_interface_info(sockfd, iface)
                                    if info:
                                        print_nested_dict(info, prefix="    ", lchar="-")
                                finally:
                                    sock.close()
            if not POSIX:
                info = get_interface_info(0, iface)
                if info:
                    print("  %s" % info)


if __name__ == "__main__":
    main()
