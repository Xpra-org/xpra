# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

_loop_init_done = False
def loop_init():
    global _loop_init_done
    if _loop_init_done:
        return
    from dbus.mainloop.glib import DBusGMainLoop
    DBusGMainLoop(set_as_default=True)
    _loop_init_done = True

_session_bus = None
def init_session_bus():
    global _session_bus
    if _session_bus:
        return _session_bus
    loop_init()
    import dbus
    _session_bus = dbus.SessionBus()
    return _session_bus
