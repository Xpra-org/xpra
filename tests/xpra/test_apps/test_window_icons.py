#!/usr/bin/env python

import sys
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk    #pylint: disable=wrong-import-position

class TestWindow(Gtk.Window):

    def __init__(self, icon):
        Gtk.Window.__init__(self, Gtk.WindowType.TOPLEVEL)
        self.set_icon(icon)
        self.set_size_request(128, 128)
        self.connect("delete_event", self.quit_cb)
        self.realize()
        self.leader = Gdk.Window(None, 1, 1, gdk.WINDOW_TOPLEVEL, event_mask=0, wclass=gdk.INPUT_ONLY)
        self.leader.set_icon_list([icon])
        #self.leader.realize()
        self.get_window().set_group(self.leader)
        self.show_all()

    def quit_cb(self, *args):
        gtk.main_quit()


def main():
    if len(sys.argv)<2:
        print("usage: %s ICONFILE1 [ICONFILE2] [..]" % sys.argv[0])
        sys.exit(1)
    icons = [gdk.pixbuf_new_from_file(x) for x in sys.argv[1:]]
    for icon in icons:
        TestWindow(icon)
    Gtk.main()


if __name__ == "__main__":
    main()
