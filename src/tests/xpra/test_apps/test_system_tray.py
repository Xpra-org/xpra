#!/usr/bin/env python

import gtk


class StatusIcon:
    def __init__(self):
        self.statusicon = gtk.StatusIcon()
        self.counter = 0
        self.statusicon.set_from_stock(gtk.STOCK_HOME)
        self.statusicon.connect("popup-menu", self.popup_menu)
        self.statusicon.connect("activate", self.activate)
        self.statusicon.set_tooltip("StatusIcon Example")
        #build list of stock icons:
        self.stock = {}
        for x in dir(gtk):
            if x.startswith("STOCK_"):
                self.stock[x[len("STOCK_"):]] = getattr(gtk, x)

    def activate(self, *args):
        self.counter += 1
        name, stock = list(self.stock.items())[self.counter % len(self.stock)]
        print("setting tray icon to: %s" % name)
        self.statusicon.set_from_stock(stock)

    def popup_menu(self, icon, button, time):
        menu = gtk.Menu()
        quit_menu = gtk.MenuItem("Quit")
        quit_menu.connect("activate", gtk.main_quit)
        menu.append(quit_menu)
        menu.show_all()
        menu.popup(None, None, gtk.status_icon_position_menu, button, time, self.statusicon)


def main():
    StatusIcon()
    gtk.main()


if __name__ == "__main__":
    main()
