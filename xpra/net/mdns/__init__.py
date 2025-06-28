# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from xpra.util.env import envbool

XPRA_TCP_MDNS_TYPE = "_xpra._tcp."
XPRA_UDP_MDNS_TYPE = "_xpra._udp."
RFB_MDNS_TYPE = "_rfb._tcp."

# publishes the name of the interface we broadcast from:
SHOW_INTERFACE = envbool("XPRA_MDNS_SHOW_INTERFACE", True)


def get_listener_class() -> type | None:
    from xpra.log import Logger
    log = Logger("mdns")
    log("mdns.get_listener_class()")
    # workaround for macOS Big Sur which broke ctypes,
    # ctypes is used in the ifaddr module which is imported by zeroconf:
    if sys.platform.startswith("darwin"):
        import xpra.platform  # pylint: disable=import-outside-toplevel
        # on macOS, an import side effect is to patch the ctypes loader
        assert xpra.platform
    try:
        from xpra.net.mdns.zeroconf_listener import ZeroconfListener
        log("ZeroconfListener=%s", ZeroconfListener)
        return ZeroconfListener
    except (ImportError, OSError):
        log("failed to import ZeroconfListener", exc_info=True)
    log("mdns.get_listener_class()=None no backend found")
    return None
