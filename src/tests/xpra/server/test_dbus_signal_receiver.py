#!/usr/bin/env python

import dbus.glib
assert dbus.glib
import gobject

BUS_NAME = "org.xpra.Server"
INTERFACE = "org.xpra.Server"
PATH = "/org/xpra/Server"

def event_handler(*args):
    print("event_handler%s" % (args, ))

print("listening for 'Event' signal on '%s'" % INTERFACE)

loop = gobject.MainLoop()
bus = dbus.SessionBus()
bus.add_signal_receiver(event_handler,
                        dbus_interface=INTERFACE,
                        signal_name='Event')
loop.run()
