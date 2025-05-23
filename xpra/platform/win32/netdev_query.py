# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger, consume_verbose_argv

log = Logger("network", "util", "win32")


def get_interface_info(_fd, iface):
    from xpra.platform.win32.comtypes_util import CIMV2_Query
    query = "SELECT * FROM Win32_NetworkAdapter WHERE GUID='%s'" % iface
    try:
        with CIMV2_Query(query) as res:
            log("ExecQuery(%s) returned %i rows", query, res.Count)
            if res.Count == 1:
                for r in res:
                    props = {}
                    for k, ik, conv in (
                            ("AdapterType", "adapter-type", str),
                            ("Caption", "caption", str),
                            ("Description", "description", str),
                            ("DeviceID", "id", int),
                            ("GUID", "GUID", str),
                            ("Index", "index", int),
                            ("Name", "name", str),
                            ("ProductName", "product-name", str),
                            ("Speed", "speed", int),
                    ):
                        try:
                            v = conv(r.Properties_[k].Value)
                        except Exception as e:
                            log.error("Error retrieving '%s' from network adapter record:", k)
                            log.estr(e)
                        else:
                            props[ik] = v
                    log("get_interface_info(%s)=%s" % (iface, props))
                    return props
    except Exception as e:
        log("get_interface_info(%s)", iface, exc_info=True)
        from xpra.util.env import first_time
        if first_time("win32-network-query"):
            log.info("cannot query network interface:")
            log.info(" %s", e)
    return {}


def get_tcp_info(_sock):  # pylint: disable=unused-argument
    """
    #not implemented yet!
    #the functions below would require administrator privileges:
    from ctypes import WinDLL, POINTER, c_void_p, c_ubyte
    from ctypes.wintypes import ULONG, UINT
    PUCHAR = POINTER(c_ubyte)
    iphlpapi = WinDLL("Iphlpapi", use_last_error=True)
    TCP_ESTATS_TYPE = UINT
    PMIB_TCPROW = c_void_p
    SetPerTcpConnectionEStats = iphlpapi.SetPerTcpConnectionEStats
    SetPerTcpConnectionEStats.restype = ULONG
    SetPerTcpConnectionEStats.argtypes = (PMIB_TCPROW, TCP_ESTATS_TYPE,
                                          PUCHAR, ULONG, ULONG, ULONG)
    GetPerTcpConnectionEStats = iphlpapi.GetPerTcpConnectionEStats
    GetPerTcpConnectionEStats.restype = ULONG
    GetPerTcpConnectionEStats.argtypes = (PMIB_TCPROW, TCP_ESTATS_TYPE,
                                          PUCHAR, ULONG, ULONG,
                                          PUCHAR, ULONG, ULONG,
                                          PUCHAR, ULONG, ULONG)
    """
    return {}


def main() -> None:
    import sys
    from xpra.platform import program_context
    with program_context("Network-Speed", "Network Speed Query Tool"):
        consume_verbose_argv(sys.argv, "win32")
        from xpra.net.net_util import get_interfaces
        from xpra.util.stats import std_unit
        interfaces = get_interfaces()
        for iface in interfaces:
            speed = get_interface_info(0, iface).get("speed", 0)
            try:
                v = int(speed)
                s = "%sbps" % std_unit(v)
                print("%s : %s" % (iface, s))
            except ValueError:
                log.error("Error: parsing speed value '%s'", speed, exc_info=True)


if __name__ == "__main__":
    main()
