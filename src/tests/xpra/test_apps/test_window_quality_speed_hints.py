#!/usr/bin/env python

from xpra.x11.gtk_x11.gdk_display_source import init_gdk_display_source
init_gdk_display_source()

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk   #pylint: disable=wrong-import-position

from xpra.x11.gtk_x11.prop import prop_set
from xpra.gtk_common.error import xsync

def main():
    win = Gtk.Window()
    win.set_size_request(400, 100)
    win.set_title("quality / speed hint")
    vbox = Gtk.VBox()
    win.add(vbox)
    def set_int_prop(prop_name, value):
        with xsync:
            prop_set(win.get_window(), prop_name, "u32", value)
        print("%s=%s" % (prop_name, value))
    win.quality = 100
    win.speed = 100
    def set_quality_hint():
        set_int_prop("_XPRA_QUALITY", win.quality)
    def set_speed_hint():
        set_int_prop("_XPRA_SPEED", win.speed)
    def change_quality(*_args):
        win.quality = (win.quality - 20) % 100
        set_quality_hint()
    def change_speed(*_args):
        win.speed = (win.speed - 20) % 100
        set_speed_hint()
    def add_button(label, cb):
        btn = Gtk.Button(label=label)
        vbox.add(btn)
        btn.connect('button-press-event', cb)
    add_button("change quality", change_quality)
    add_button("change speed", change_speed)
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
    return 0


if __name__ == '__main__':
    main()
