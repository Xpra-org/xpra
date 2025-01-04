# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket
from typing import Callable, Any
from collections.abc import Sequence

from xpra.os_util import OSX, WIN32
from xpra.util.env import envbool


def import_zeroconf() -> tuple[Any, Callable]:
    from xpra.net.mdns.zeroconf_publisher import ZeroconfPublishers, get_interface_index
    return ZeroconfPublishers, get_interface_index


def import_avahi() -> tuple[Any, Callable]:
    from xpra.net.mdns.avahi_publisher import AvahiPublishers, get_interface_index
    return AvahiPublishers, get_interface_index


MDNS_WARNING = False


def mdns_publish(display_name: str, listen_on, text_dict=None) -> Sequence:
    global MDNS_WARNING
    if MDNS_WARNING is True:
        return ()
    from xpra.log import Logger
    log = Logger("mdns")
    log("mdns_publish%s", (display_name, listen_on, text_dict))
    try:
        from xpra.net import mdns
        assert mdns
        from xpra.net.mdns import XPRA_TCP_MDNS_TYPE, XPRA_UDP_MDNS_TYPE, RFB_MDNS_TYPE
    except ImportError as e:
        log(f"mdns support is not installed: {e}")
        return ()
    PREFER_ZEROCONF = envbool("XPRA_PREFER_ZEROCONF", True)
    imports = (import_zeroconf, import_avahi)
    if not PREFER_ZEROCONF:
        imports = (import_avahi, import_zeroconf)
    MDNSPublishers = get_interface_index = None
    exceptions = []
    for i in imports:
        try:
            MDNSPublishers, get_interface_index = i()
            break
        except ImportError as e:
            log("mdns import failure", exc_info=True)
            exceptions.append(e)
    if not MDNSPublishers or not get_interface_index:
        MDNS_WARNING = True
        log.warn("Warning: failed to load the mdns publishers")
        for exc in exceptions:
            log.warn(" %s", str(exc) or type(exc))
        log.warn(" install 'python-avahi', 'python-zeroconf'")
        log.warn(" or use the 'mdns=no' option")
        return ()
    d = dict(text_dict or {})
    # ensure we don't have duplicate interfaces:
    f_listen_on = {}
    for host, port in listen_on:
        f_listen_on[(get_interface_index(host), port)] = (host, port)
    try:
        name = socket.gethostname()
    except OSError:
        name = "Xpra"
    if display_name and not (OSX or WIN32):
        name += f" {display_name}"
    mode = d.get("mode", "tcp")
    service_type = {
        "rfb": RFB_MDNS_TYPE,
        "quic": XPRA_UDP_MDNS_TYPE,
        "webtransport": XPRA_UDP_MDNS_TYPE,
    }.get(mode, XPRA_TCP_MDNS_TYPE)
    index = 0
    aps = []
    for host, port in listen_on:
        sn = name
        mode_str = mode
        if index > 0:
            mode_str = f"{mode}-{index + 1}"
        if mode not in ("tcp", "rfb"):
            sn += f" ({mode_str})"
        listen = ((host, port),)
        index += 1
        aps.append(MDNSPublishers(listen, sn, service_type=service_type, text_dict=d))
    return aps
