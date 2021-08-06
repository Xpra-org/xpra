# This file is part of Xpra.
# Copyright (C) 2017-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: language_level=3

import os
import socket

from libc.stdint cimport uint32_t, uint16_t, uint8_t  #pylint: disable=syntax-error

from xpra.util import first_time, csv
from xpra.os_util import strtobytes, bytestostr, load_binary_file, LINUX
from xpra.log import Logger

log = Logger("util", "network")

ctypedef uint32_t __u32
ctypedef uint16_t __u16
ctypedef uint8_t __u8

DEF ETHTOOL_GDRVINFO = 0x00000003
DEF ETHTOOL_BUSINFO_LEN = 32


cdef extern from "linux/ethtool.h":
    int ETHTOOL_GSET
    int ETHTOOL_BUSINFO_LEN
    cdef struct ethtool_cmd:
        __u32   cmd
        __u32   supported
        __u32   advertising
        __u16   speed
        __u8    duplex
        __u8    port
        __u8    phy_address
        __u8    transceiver
        __u8    autoneg
        __u8    mdio_support
        __u32   maxtxpkt
        __u32   maxrxpkt
        __u16   speed_hi
        __u8    eth_tp_mdix
        __u8    eth_tp_mdix_ctrl
        __u32   lp_advertising
        __u32   reserved[2]

    cdef struct ethtool_drvinfo:
        uint32_t    cmd
        char    driver[32]     # driver short name, "tulip", "eepro100"
        char    version[32]     # driver version string
        char    fw_version[32]     # firmware version string, if applicable
        char    bus_info[ETHTOOL_BUSINFO_LEN]     # Bus info for this IF.
                    # For PCI devices, use pci_dev->slot_name.
        char    reserved1[32]
        char    reserved2[16]
        uint32_t    n_stats     # number of u64's from ETHTOOL_GSTATS
        uint32_t    testinfo_len
        uint32_t    eedump_len     # Size of data from ETHTOOL_GEEPROM (bytes)
        uint32_t    regdump_len     # Size of data from ETHTOOL_GREGS (bytes)


cdef extern from "linux/sockios.h":
    int SIOCETHTOOL

cdef extern from "net/if.h":
    DEF IFNAMSIZ=16
    cdef struct ifr_ifrn:
        char ifrn_name[IFNAMSIZ]
    cdef struct ifr_ifru:
        int ifru_flags
        int ifru_ivalue
        int ifru_mtu
        void *ifru_data
    cdef struct ifreq:
        ifr_ifrn ifr_ifrn
        ifr_ifru ifr_ifru

cdef extern from "sys/ioctl.h":
    int ioctl(int fd, unsigned long request, ...)

#linux kernel: if_arp.h
ARPHRD = {
    0   : "netrom",
    1   : "ether",
    2   : "eether",
    3   : "ax25",
    4   : "pronet",
    5   : "chaos",
    6   : "ieee802",
    7   : "arcnet",
    8   : "appletlk",
    15  : "dlci",
    19  : "atm",
    23  : "metricom",
    24  : "ieee1394",
    27  : "eui64",
    32  : "infiniband",

    256 : "slip",
    257 : "cslip",
    258 : "slip6",
    259 : "cslip6",
    260 : "rsrvd",
    264 : "adapt",
    270 : "rose",
    271 : "x25",
    272 : "hwx25",
    280 : "can",
    512 : "ppp",
    513 : "cisco",
    516 : "lapb",
    517 : "ddcmp",
    518 : "rawhdlc",

    768 : "tunnel",
    769 : "tunner6",
    770 : "frad",
    771 : "skip",
    772 : "loopback",
    773 : "localtlk",
    774 : "fddi",
    775 : "bif",
    776 : "sit",
    777 : "ipddp",
    778 : "ipgre",
    779 : "pimreg",
    780 : "hippi",
    781 : "ash",
    782 : "econet",
    783 : "irda",

    784 : "fcpp",
    785 : "fcal",
    786 : "fcpl",
    787 : "fcfabric",
    800 : "ieee802_tr",
    801 : "ieee80211",
    802 : "ieee80211_prism",
    803 : "ieee80211_radiotap",
    804 : "ieee802154",

    820 : "phonet",
    821 : "phonet_pipe",
    822 : "caif",
    }

def get_interface_info(int sockfd, ifname):
    if sockfd==0:
        return {}
    info = {}
    adapter_type = None
    sysnetfs = "/sys/class/net/%s" % ifname
    if os.path.exists(sysnetfs) and os.path.isdir(sysnetfs):
        type_file = os.path.join(sysnetfs, "type")
        if os.path.exists(type_file):
            dev_type = bytestostr(load_binary_file(type_file).rstrip(b"\n\r"))
            if dev_type:
                try:
                    idev_type = int(dev_type)
                    adapter_type = ARPHRD.get(idev_type)
                except ValueError:
                    pass
    if not adapter_type:
        if ifname.startswith("lo"):
            adapter_type = "loopback"
        elif ifname.startswith("wl"):
            adapter_type = "wireless"
        elif ifname.startswith("eth") or ifname.startswith("en"):
            adapter_type = "ethernet"
        elif ifname.startswith("ww"):
            adapter_type = "wan"
        else:
            wireless_path = "%s/wireless" % sysnetfs
            if os.path.exists(wireless_path):
                adapter_type = "wireless"
    if adapter_type:
        info["adapter-type"] = adapter_type
    if sockfd>0:
        info.update(get_ethtool_info(sockfd, ifname))
    return info

def get_ethtool_info(int sockfd, ifname):
    if len(ifname)>=IFNAMSIZ:
        log.warn("Warning: invalid interface name '%s'", ifname)
        log.warn(" maximum length is %i", IFNAMSIZ)
        return {}
    cdef ifreq ifr
    cdef ethtool_cmd edata
    bifname = strtobytes(ifname)
    cdef char *cifname = bifname
    ifr.ifr_ifrn.ifrn_name = cifname
    ifr.ifr_ifru.ifru_data = <void*> &edata
    edata.cmd = ETHTOOL_GSET
    cdef int r = ioctl(sockfd, SIOCETHTOOL, &ifr)
    info = {}
    if r >= 0:
        info["speed"] = edata.speed*1000*1000
        #info["duplex"] = duplex: DUPLEX_HALF, DUPLEX_FULL DUPLEX_NONE?
    else:
        log("no ethtool interface speed available for %s", ifname)
        return info
    cdef ethtool_drvinfo drvinfo
    drvinfo.cmd = ETHTOOL_GDRVINFO
    ifr.ifr_ifru.ifru_data = <void *> &drvinfo
    r = ioctl(sockfd, SIOCETHTOOL, &ifr)
    if r>=0:
        info["driver"] = bytestostr(drvinfo.driver)
        info["version"] = bytestostr(drvinfo.version)
        info["firmware-version"] = bytestostr(drvinfo.fw_version)
        info["bus-info"] = bytestostr(drvinfo.bus_info)
    else:
        log.info("no driver information for %s", ifname)
    return info


def get_socket_tcp_info(sock):
    if not LINUX:
        #should be added for BSDs
        return {}
    from ctypes import c_uint8, c_uint32, c_uint64
    ALL_FIELDS = (
        ("state",           c_uint8),
        ("ca_state",        c_uint8),
        ("retransmits",     c_uint8),
        ("probes",          c_uint8),
        ("backoff",         c_uint8),
        ("options",         c_uint8),
        ("snd_wscale",      c_uint8, 4),
        ("rcv_wscale",      c_uint8, 4),
        ("rto",             c_uint32),
        ("ato",             c_uint32),
        ("snd_mss",         c_uint32),
        ("rcv_mss",         c_uint32),
        ("unacked",         c_uint32),
        ("sacked",          c_uint32),
        ("lost",            c_uint32),
        ("retrans",         c_uint32),
        ("fackets",         c_uint32),
        ("last_data_sent",  c_uint32),
        ("last_ack_sent",   c_uint32),
        ("last_data_recv",  c_uint32),
        ("last_ack_recv",   c_uint32),
        ("pmtu",            c_uint32),
        ("rcv_ssthresh",    c_uint32),
        ("rtt",             c_uint32),
        ("rttvar",          c_uint32),
        ("snd_ssthresh",    c_uint32),
        ("snd_cwnd",        c_uint32),
        ("advmss",          c_uint32),
        ("reordering",      c_uint32),
        ("rcv_rtt",         c_uint32),
        ("rcv_space",       c_uint32),
        ("total_retrans",   c_uint32),
        ("pacing_rate",     c_uint64),
        ("max_pacing_rate", c_uint64),
        ("bytes_acked",     c_uint64),
        ("bytes_received",  c_uint64),
        ("segs_out",        c_uint32),
        ("segs_in",         c_uint32),
        ("notsent_bytes",   c_uint32),
        ("min_rtt",         c_uint32),
        ("data_segs_in",    c_uint32),
        ("data_segs_out",   c_uint32),
        ("delivery_rate",   c_uint64),
        ("busy_time",       c_uint64),
        ("rwnd_limited",    c_uint64),
        ("sndbuf_limited",  c_uint64),
        ("delivered",       c_uint32),
        ("delivered_ce",    c_uint32),
        ("bytes_sent",      c_uint64),
        ("bytes_retrans",   c_uint64),
        ("dsack_dups",      c_uint32),
        ("reord_seen",      c_uint32),
        ("rcv_ooopack",     c_uint32),
        ("snd_wnd",         c_uint32),
        )
    from xpra.net.socket_util import get_sockopt_tcp_info
    return get_sockopt_tcp_info(sock, socket.TCP_INFO, ALL_FIELDS)

def get_send_buffer_info(sock):
    import fcntl
    import struct
    send_buffer_size = sock.getsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF)
    info = {
        "sndbuf_size"   : send_buffer_size,
        }
    #SIOCINQ = 0x541B
    SIOCOUTQ = 0x5411
    unacked = struct.unpack("I", fcntl.ioctl(sock.fileno(), SIOCOUTQ, b'\0\0\0\0'))[0]
    info["sndbuf_unacked"] = unacked
    SIOCOUTQNSD = 0x894B
    bytes_in_queue = struct.unpack("I", fcntl.ioctl(sock.fileno(), SIOCOUTQ, b'\0\0\0\0'))[0]
    info["sndbuf_bytes"] = bytes_in_queue
    return info

def get_tcp_info(sock):
    tcpi = get_socket_tcp_info(sock)
    bi = get_send_buffer_info(sock)
    log("get_send_buffer_status(%s)=%s", sock, bi)
    tcpi.update(bi)
    return tcpi
