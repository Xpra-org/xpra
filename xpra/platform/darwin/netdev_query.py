# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from SystemConfiguration import (
    SCNetworkInterfaceCopyAll,                      #@UnresolvedImport
    SCNetworkInterfaceGetBSDName,                   #@UnresolvedImport
    SCNetworkInterfaceGetHardwareAddressString,     #@UnresolvedImport
    SCNetworkInterfaceGetInterfaceType,             #@UnresolvedImport
    SCNetworkInterfaceGetSupportedProtocolTypes,    #@UnresolvedImport
    )


def get_interface_info(_fd, iface):
    r = SCNetworkInterfaceCopyAll()
    if iface:
        for scnetworkinterface in r:
            if str(SCNetworkInterfaceGetBSDName(scnetworkinterface))==iface:
                return do_get_interface_info(scnetworkinterface)
    elif len(r)==1:
        return do_get_interface_info(r[0])
    return {}

def do_get_interface_info(scnetworkinterface):
    info = {}
    bsdname = SCNetworkInterfaceGetBSDName(scnetworkinterface)
    if bsdname:
        info["name"] = str(bsdname)
    hw = SCNetworkInterfaceGetHardwareAddressString(scnetworkinterface)
    if hw:
        info["hardware-address"] = str(hw)
    t = SCNetworkInterfaceGetInterfaceType(scnetworkinterface)
    if t:
        info["adapter-type"] = str(t)
    #SCNetworkInterfaceGetLocalizedDisplayName
    p = SCNetworkInterfaceGetSupportedProtocolTypes(scnetworkinterface)
    if p:
        info["protocols"] = tuple(str(x) for x in p)
    return info

def get_socket_tcp_info(sock):
    from ctypes import c_int8, c_uint8, c_uint32, c_int32, c_int64
    MACOS_TCP_INFO_FIELDS = (
        ("state",           c_uint8),
        ("options",         c_uint8),
        ("snd_wscale",      c_uint8),
        ("rcv_wscale",      c_uint8),
        ("flags",           c_uint32),
        ("rto",             c_uint32),
        ("snd_mss",         c_uint32),
        ("rcv_mss",         c_uint32),
        ("rttcur",          c_uint32),
        ("srtt",            c_uint32),
        ("rttvar",          c_uint32),
        ("rttbest",         c_uint32),
        ("snd_ssthresh",    c_uint32),
        ("snd_cwnd",        c_uint32),
        ("rcv_space",       c_uint32),
        ("snd_wnd",         c_uint32),
        ("snd_nxt",         c_uint32),
        ("rcv_nxt",         c_uint32),
        ("last_outif",      c_int32),
        ("snd_sbbytes",     c_int32),
        ("padding",         c_int32),
        #aligned 8:
        ("txpackets",       c_int64),
        ("txbytes",         c_int64),
        ("txretransmitbytes", c_int64),
        ("txunacked",       c_int64),
        ("rxpackets",       c_int64),
        ("rxbytes",         c_int64),
        ("rxduplicatebytes", c_int64),
        ("rxoutoforderbytes", c_int64),
        ("snd_bw",          c_int64),
        ("synrexmits",      c_int8),
        ("unused1",         c_int8),
        ("unused2",         c_int8),
        ("cell_rxpackets",  c_int64),
        ("cell_rxbytes",    c_int64),
        ("cell_txpackets",  c_int64),
        ("cell_txbytes",    c_int64),
        ("wifi_rxpackets",  c_int64),
        ("wifi_rxbytes",    c_int64),
        ("wifi_txpackets",  c_int64),
        ("wifi_txbytes",    c_int64),
        ("wired_rxpackets",  c_int64),
        ("wired_rxbytes",    c_int64),
        ("wired_txpackets",  c_int64),
        ("wired_txbytes",    c_int64),
        )
    from xpra.net.socket_util import get_sockopt_tcp_info
    TCP_INFO = 0x200
    return get_sockopt_tcp_info(sock, TCP_INFO, MACOS_TCP_INFO_FIELDS)

def get_tcp_info(sock):
    info = get_socket_tcp_info(sock)
    try:
        import socket
        SO_NWRITE = 0x1024  #Get number of bytes currently in send socket buffer
        #actually gives the sum of (unsent data + sent-but-not-ACK-ed data)
        v = sock.getsockopt(socket.SOL_SOCKET, SO_NWRITE)
        info["sndbuf_unacked"] = v
    except OSError:
        from xpra.log import Logger
        Logger("network").error("failed to get SO_NWRITE on %s", sock, exc_info=True)
    return {}


def main():
    r = SCNetworkInterfaceCopyAll()
    print("%i interfaces:" % len(r))
    for scnetworkinterface in r:
        info = do_get_interface_info(scnetworkinterface)
        print(info)


if __name__ == "__main__":
    main()
