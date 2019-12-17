#!/usr/bin/env python

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk   #pylint: disable=wrong-import-position

opacity = 50

def main():
    win = Gtk.Window()

    win.set_title('Alpha Demo')
    win.connect('delete-event', Gtk.main_quit)

    btn = Gtk.Button(label="Change Opacity")
    def change_opacity(*_args):
        global opacity
        opacity = (opacity + 5) % 100
        btn.set_label("Change Opacity: %i%%" % opacity)
        win.set_opacity(opacity/100.0)
    btn.connect('clicked', change_opacity)
    win.add(btn)
    change_opacity()

    win.show_all()
    Gtk.main()
    return 0


if __name__ == '__main__':
    main()
