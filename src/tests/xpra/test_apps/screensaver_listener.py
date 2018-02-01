# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


try:
    #new recommended way of using the glib main loop:
    from dbus.mainloop.glib import DBusGMainLoop
    DBusGMainLoop(set_as_default=True)
except:
    #beware: this import has side-effects:
    import dbus.glib
    assert dbus.glib
import dbus #@Reimport


#NAME = "org.freedesktop.ScreenSaver"
#PATH = "/org/freedesktop/ScreenSaver"
NAME = "org.gnome.ScreenSaver"
PATH = "/org/gnome/ScreenSaver"

def main():
    from xpra.platform import program_context
    with program_context("ScreenSaver-Listener", "ScreenSaver Listener"):
        dbus_session = dbus.SessionBus()
        def active_changed(active):
            print("screensaver active status changed: %s" % (active, ))
        dbus_session.add_signal_receiver(active_changed, "ActiveChanged", NAME, path=PATH)
        from xpra.gtk_common.gobject_compat import import_glib
        glib = import_glib()
        loop = glib.MainLoop()
        loop.run()


if __name__ == "__main__":
    main()
