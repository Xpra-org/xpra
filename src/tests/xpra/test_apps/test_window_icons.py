#!/usr/bin/env python

import sys
import gtk.gdk

class TestWindow(gtk.Window):

    def __init__(self, icon):
        gtk.Window.__init__(self, gtk.WINDOW_TOPLEVEL)
        self.set_icon(icon)
        self.set_size_request(128, 128)
        self.connect("delete_event", self.quit_cb)
        self.realize()
        self.leader = gtk.gdk.Window(None, 1, 1, gtk.gdk.WINDOW_TOPLEVEL, event_mask=0, wclass=gtk.gdk.INPUT_ONLY)
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
    icons = [gtk.gdk.pixbuf_new_from_file(x) for x in sys.argv[1:]]
    for icon in icons:
        TestWindow(icon)
    gtk.main()


if __name__ == "__main__":
    main()
