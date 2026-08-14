# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

_loop: object | None = None


def loop_init():
    global _loop
    if not _loop:
        from dbus.mainloop.glib import DBusGMainLoop, threads_init
        threads_init()
        _loop = DBusGMainLoop(set_as_default=True)
    return _loop


_session_bus: object | None = None
_session_bus_address: str = ""


def get_session_bus_address() -> str:
    """
    the address of the session bus we are actually connected to,
    which is not necessarily `DBUS_SESSION_BUS_ADDRESS`:
    servers start their own dbus instance and update the environment,
    but connections made before that point are still connected to the previous bus
    """
    return _session_bus_address


def init_session_bus(private=False):
    global _session_bus, _session_bus_address
    address = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    if _session_bus and not private and address == _session_bus_address:
        return _session_bus
    loop_init()
    import dbus
    if address:
        # connect to this address explicitly:
        # `dbus.SessionBus()` returns a connection to the bus we connected to first,
        # even if `DBUS_SESSION_BUS_ADDRESS` has changed since,
        # and even when asking for a `private` connection,
        # because libdbus caches the session bus address globally
        bus = dbus.bus.BusConnection(address)
    else:
        bus = dbus.SessionBus(private=private)
    if not private:
        _session_bus = bus
        _session_bus_address = address
    return bus


_system_bus: object | None = None


def init_system_bus():
    global _system_bus
    if _system_bus:
        return _system_bus
    loop_init()
    import dbus
    _system_bus = dbus.SystemBus()
    return _system_bus
