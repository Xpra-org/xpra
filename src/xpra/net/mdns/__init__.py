# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

XPRA_MDNS_TYPE = '_xpra._tcp.'


def get_listener_class():
    try:
        from xpra.net.mdns.avahi_listener import AvahiListener
        return AvahiListener
    except ImportError:
        try:
            from xpra.net.mdns.zeroconf_listener import ZeroconfListener
            return ZeroconfListener
        except ImportError:
            pass
    return None