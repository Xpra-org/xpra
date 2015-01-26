#!/usr/bin/env python

#code found here:
#http://stackoverflow.com/a/3859540/428751
import gtk

class PyGtkWidgetDockExample:
    def __init__(self):
        self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
        self.window.set_default_size(100, gtk.gdk.screen_height())
        self.window.move(gtk.gdk.screen_width()-100, 0)
        self.window.set_type_hint(gtk.gdk.WINDOW_TYPE_HINT_DOCK)        
        self.window.show()          
        self.window.window.property_change("_NET_WM_STRUT", "CARDINAL", 32, 
            gtk.gdk.PROP_MODE_REPLACE, [0, 100, 0, 0])               

def main():
    PyGtkWidgetDockExample()
    gtk.main()


if __name__ == "__main__":
    main()
