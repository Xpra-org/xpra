# This file is part of Xpra.
# Copyright (C) 2016-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from xpra.util import envbool

XPRA_MDNS_TYPE = "_xpra._tcp."
RFB_MDNS_TYPE = "_rfb._tcp."

AVAHI = envbool("XPRA_AVAHI", True)
ZEROCONF = envbool("XPRA_ZEROCONF", True)
#publishes the name of the interface we broadcast from:
SHOW_INTERFACE = envbool("XPRA_MDNS_SHOW_INTERFACE", True)


def get_listener_class():
    from xpra.os_util import get_util_logger
    log = get_util_logger()
    log("mdns.get_listener_class() AVAHI=%s, ZEROCONF=%s", AVAHI, ZEROCONF)
    if AVAHI:
        try:
            from xpra.net.mdns.avahi_listener import AvahiListener
            log("AvahiListener=%s", AvahiListener)
            return AvahiListener
        except ImportError:
            log("failed to import AvahiListener", exc_info=True)
    if ZEROCONF:
        #workaround for MacOS Big Sur which broke ctypes,
        #ctypes is used in the ifaddr module which is imported by zeroconf:
        if sys.platform.startswith("darwin"):
            import xpra.platform    #pylint: disable=import-outside-toplevel
            #on MacOS, an import side-effect is to patch the ctypes loader
            assert xpra.platform
        try:
            from xpra.net.mdns.zeroconf_listener import ZeroconfListener
            log("ZeroconfListener=%s", ZeroconfListener)
            return ZeroconfListener
        except (ImportError, OSError):
            log("failed to import ZeroconfListener", exc_info=True)
    return None
