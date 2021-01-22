#!/usr/bin/env python

import gi
gi.require_version('Gdk', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk #pylint: disable=wrong-import-position

width = 400
height = 200

def main():
    w = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
    w.set_default_size(-1, -1)
    w.set_title("eclipse size hints")
    w.connect("delete_event", Gtk.main_quit)
    da = Gtk.DrawingArea()
    w.add(da)
    geom = Gdk.Geometry()
    wh = Gdk.WindowHints
    geom.min_width = 862
    geom.min_height = 385
    geom.max_width = 862
    geom.max_height = 385
    mask = wh.MIN_SIZE | wh.MAX_SIZE
    gdk_hints = Gdk.WindowHints(mask)
    w.set_geometry_hints(da, geom, gdk_hints)
    #da.connect("click", show)
    def configure_event(w, event):
        #print("configure_event(%s, %s)" % (w, event))
        print("event geometry:        %s" % ((event.x, event.y, event.width, event.height),))
        gdkwindow = da.get_window()
        x, y = gdkwindow.get_origin()[1:]
        w, h = w.get_size()
        print("drawing area geometry: %s" % ((x, y, w, h),))
    w.show_all()
    w.connect("configure_event", configure_event)
    Gtk.main()


if __name__ == "__main__":
    main()
