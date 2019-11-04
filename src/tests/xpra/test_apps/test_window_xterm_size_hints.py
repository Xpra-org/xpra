#!/usr/bin/env python

import sys
from xpra.gtk_common.gobject_compat import import_gtk, import_gdk
gtk = import_gtk()
gdk = import_gdk()

width = 400
height = 200

def main():
    PY2 = sys.version_info[0]==2
    if PY2:
        w = gtk.Window(gtk.WINDOW_TOPLEVEL)
        w.set_default_size(499, 316)
        w.set_title("xterm size hints")
        w.connect("delete_event", gtk.main_quit)
        hints = {
            "min_width" : 25,
            "min_height" : 17,
            "base_width" : 19,
            "base_height" : 4,
            "width_inc" : 6,
            "height_inc" : 13,
                }
        w.set_geometry_hints(None, **hints)
    else:
        w = gtk.Window(type=gtk.WindowType.TOPLEVEL)
        w.set_default_size(499, 316)
        w.set_title("xterm size hints")
        w.connect("delete_event", gtk.main_quit)
        geom = gdk.Geometry()
        wh = gdk.WindowHints
        geom.min_width = 25
        geom.min_height = 17
        geom.base_width = 19
        geom.base_height = 4
        geom.width_inc = 6
        geom.height_inc = 13
        mask = wh.MIN_SIZE | wh.BASE_SIZE | wh.RESIZE_INC
        if sys.platform.startswith("linux"):
            geom.max_width = 32767
            geom.max_height = 32764
            mask |= wh.MAX_SIZE
        gdk_hints = gdk.WindowHints(mask)
        w.set_geometry_hints(None, geom, gdk_hints)
    da = gtk.DrawingArea()
    #da.connect("click", show)
    def configure_event(w, event):
        #print("configure_event(%s, %s)" % (w, event))
        print("event geometry:        %s" % ((event.x, event.y, event.width, event.height),))
        if PY2:
            gdkwindow = w.get_window()
            x, y = gdkwindow.get_origin()
        else:
            gdkwindow = da.get_window()
            x, y = gdkwindow.get_origin()[1:]
        w, h = w.get_size()
        print("drawing area geometry: %s" % ((x, y, w, h),))
    w.connect("configure_event", configure_event)
    w.add(da)
    w.show_all()
    gtk.main()


if __name__ == "__main__":
    main()
