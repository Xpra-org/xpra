#!/usr/bin/env python

import sys
import gtk


class StatusIcon:
    def __init__(self, name="test", tooltip="StatusIcon Example"):
        self.name = name
        self.statusicon = gtk.StatusIcon()
        self.counter = 0
        self.statusicon.set_name(name)
        self.statusicon.set_from_stock(gtk.STOCK_HOME)
        self.statusicon.connect("popup-menu", self.popup_menu)
        self.statusicon.connect("activate", self.activate)
        self.statusicon.set_tooltip(tooltip)
        #build list of stock icons:
        self.stock = {}
        for x in dir(gtk):
            if x.startswith("STOCK_"):
                self.stock[x[len("STOCK_"):]] = getattr(gtk, x)

    def activate(self, *_args):
        self.counter += 1
        name, stock = list(self.stock.items())[self.counter % len(self.stock)]
        print("setting tray icon to: %s" % name)
        self.statusicon.set_from_stock(stock)

    def popup_menu(self, icon, button, time):
        menu = gtk.Menu()
        quit_menu = gtk.MenuItem("Quit")
        quit_menu.connect("activate", gtk.main_quit)
        menu.append(quit_menu)
        notify_menu = gtk.MenuItem("Send Notification")
        notify_menu.connect("activate", self.notify)
        menu.append(notify_menu)
        menu.show_all()
        menu.popup(None, None, gtk.status_icon_position_menu, button, time, self.statusicon)

    def notify(self, *_args):
        try:
            import pynotify
            pynotify.init(self.name or "Xpra")
            n = pynotify.Notification("Test Notification", "The message goes here", "close")
            n.set_urgency(pynotify.URGENCY_LOW)
            n.set_timeout(60*1000)
            def foo_action(*_args):
                pass
            n.add_action("foo", "Foo!", foo_action)
            n.show()
        except ImportError:
            from xpra.client.notifications.dbus_notifier import DBUS_Notifier
            n = DBUS_Notifier()
            n.app_name_format = "%s"
            actions = ["0", "Hello", "1", "Goodbye"]
            hints = {}
            n.show_notify("dbus-id", None, 0, self.name, 0, "", "Notification Summary", "Notification Body", actions, hints, 60*1000, "")


def main():
    name = "test"
    if len(sys.argv)>=2:
        name = sys.argv[1]
    tooltip = "StatusIcon Example"
    if len(sys.argv)>=3:
        tooltip = sys.argv[2]
    from xpra.platform import program_context
    with program_context(name, name):
        StatusIcon(name, tooltip)
        gtk.main()


if __name__ == "__main__":
    main()
