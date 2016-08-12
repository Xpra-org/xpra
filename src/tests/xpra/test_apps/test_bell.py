#!/usr/bin/env python

import gtk

def main():
    window = gtk.Window(gtk.WINDOW_TOPLEVEL)
    window.set_size_request(100, 200)
    window.connect("delete_event", gtk.mainquit)
    vbox = gtk.VBox()
    window.add(vbox)

    from xpra.x11.gtk2 import gdk_display_source
    assert gdk_display_source
    from xpra.platform.xposix.gui import system_bell

    def default_bell(*args):
        system_bell(window.get_window(), 0, 100, 2000, 1000, 0, 0, "test")

    btn = gtk.Button("default bell")
    btn.connect('clicked', default_bell)
    vbox.add(btn)

    window.show_all()
    gtk.main()
    return 0


if __name__ == "__main__":
    main()
